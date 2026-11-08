# Reservation Expiry Automation and Monitoring Audit

**Scope:** IMPLEMENTATION 04B-2 only.

## Deployment assessment

No Celery, Redis, Docker Compose, background worker, scheduler service, or deployment scheduler configuration exists in this repository. `config/settings.py` uses SQLite by default and PostgreSQL only when the `POSTGRES_DB` environment variable is configured. The implementation therefore retains a dependency-free Django management command and documents external scheduling appropriate to the target environment.

## Execution trace

```text
External scheduler
  -> manage.py expire_reservations
  -> expired ACTIVE reservation discovery
  -> MasterOrder / Payment locks
  -> SupplierOrder / InventoryReservation / Inventory locks
  -> release_reservations
  -> one RESERVATION_RELEASE movement per released reservation
  -> order CANCELLED / payment status EXPIRED
  -> structured log events and JSON execution summary
```

The lock hierarchy is `MasterOrder -> Payment -> SupplierOrder -> InventoryReservation -> Inventory`. A successful payment confirmation obtains the same order-first hierarchy. Whichever transaction obtains the master-order lock first determines the safe outcome: payment fulfillment, normal expiry, or later payment reconciliation.

## Implemented command behavior

- Discovers only `ACTIVE` reservations whose expiry time has passed.
- Processes each master order in an independent transaction.
- Is repeatable: released reservations become `EXPIRED`, so later runs do not release inventory or create movements again.
- Skips paid/non-pending orders and open/investigating reconciliation cases.
- Preserves late-payment reconciliation: the command does not refund, reallocate, or force a reconciled order through normal expiry.
- Supports `--dry-run`, which performs no writes and never calls the release service.
- Emits JSON counts for discovered reservations, candidate orders, releases, skips, reconciliation cases, errors, and duration.
- Emits `reservation_expiry_*` logger events without payment credentials or customer secrets.
- Finishes with a non-zero exit code after recoverable per-order failures, while continuing other orders and preserving each failed order for retry.

## Tests added

`apps/orders/tests.py` now verifies:

1. Normal expiry and safe repeated execution.
2. Multiple reservations and one release movement per inventory record.
3. Dry-run state preservation.
4. Skipping paid orders and open-reconciliation orders.
5. Per-order rollback and continued processing after a simulated individual-order failure.

Payment tests continue to verify that an expired order receiving a later valid paid webhook is recorded for reconciliation rather than silently fulfilled.

## Verification results

| Command | Result |
| --- | --- |
| `manage.py check` | Passed |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `manage.py test apps.orders` | 16 passed |
| `manage.py test apps.payments` | 17 passed |

The deliberate simulated per-order failure test logs an error traceback; the test passes because the command must report failure, roll back that order, and safely complete the other order.

## Scheduler and operations guidance

`docs/operations.md` provides command usage, JSON output fields, local Windows Task Scheduler setup, Linux cron, Linux systemd timer units, log monitoring, retry/recovery procedure, and scheduler verification commands. The recommended interval is every five minutes.

## PostgreSQL concurrency result

**Not run.** The active development environment uses SQLite and no PostgreSQL service/configuration was available. SQLite does not provide equivalent row-lock contention behavior, so these tests do not claim PostgreSQL concurrency verification. PostgreSQL-backed parallel confirmation/expiry tests are still required before production deployment.

## Remaining limitations

- Scheduling is intentionally external; it must be configured in the selected deployment environment.
- There is no persistent job-run dashboard or alert delivery integration yet; logs, exit codes, and scheduler monitoring are the current operational interface.
- Production monitoring should alert on non-zero command exits, repeated `reservation_expiry_order_failed` events, and unusually high expired-reservation backlog.

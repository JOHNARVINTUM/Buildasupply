# Late Payment Reconciliation and Concurrency Safety

**Scope:** IMPLEMENTATION 04B-1 only. No payment provider, COD, refund-execution, or operational UI was added.

## Implemented outcome

Verified provider callbacks that arrive after an order's payment reservation expired are now durably recorded and acknowledged as `LATE_PAYMENT_REQUIRES_RECONCILIATION`. They do not consume inventory, set an order to `PROCESSING`, create supplier-wallet earnings, or send a payment-success notification.

The durable records are:

- `payments.WebhookEvent`, with `processing_status=LATE_PAYMENT_REQUIRES_RECONCILIATION` and `processed_at`.
- `payments.PaymentEvent`, retaining the normalized verified provider event.
- `payments.PaymentReconciliation`, retaining payment/order/provider-event identity, the expected payment amount/currency, optional provider-reported amount/currency/event time, state, and resolution metadata.
- `payments.PaymentReconciliationHistory`, retaining the detection and resolution history.
- `audit.AuditLog`, through `LATE_PAYMENT_REQUIRES_RECONCILIATION` and reconciliation-resolution actions.

Repeated delivery of the same provider event returns the existing reconciliation identifier without creating additional inventory movements, ledger entries, or reconciliation records.

## Locking protocol

The documented and implemented payment/order lock hierarchy is:

```text
MasterOrder -> Payment -> SupplierOrder -> InventoryReservation -> Inventory
```

`confirm_payment` acquires the first two locks through `_lock_order`. Inventory consumption and release then lock the order, supplier orders, active reservations, and inventories in that order. The existing expiration command already locks `MasterOrder` before calling `release_reservations`, so both paths now follow the same ordering for shared entities.

This reduces lock-order inversion risk. The SQLite test environment does not implement PostgreSQL row locking semantics, so a production-like PostgreSQL concurrency test remains required before production deployment.

## Reconciliation operations

`apps.payments.services.resolve_payment_reconciliation` is the only added resolution entry point. It enforces an active `SUPERADMIN` at the service boundary.

| Resolution | Result |
| --- | --- |
| `INVESTIGATING` | Keeps the financial exception open and adds a history note. |
| `REFUND_REQUIRED` | Records that a refund must be handled; it does not create or mark a provider refund complete. |
| `REALLOCATE` | Revalidates product/supplier availability, minimum quantity, and current stock; creates one replacement reservation per ordered item; consumes it; then performs the normal paid/fulfillment and wallet transition. |

Terminal `REALLOCATED` and `REFUND_REQUIRED` reconciliations return unchanged when retried, preventing duplicate movements or earnings.

No administrative route or UI was added because this task requested secure service-layer operations only. Any later dashboard/API action must call this service and enforce the same superadmin authorization.

## Verification

Focused tests added in `apps/payments/tests.py` verify:

1. Late paid webhook persistence and deterministic duplicate response.
2. No automatic order processing, stock sale, or wallet posting for a late event.
3. Authorized stock reallocation and exactly one sale movement.
4. Safe failure when stock is no longer available.
5. Refund-required recording without creating a fake refund.
6. Superadmin-only resolution and repeated terminal resolution safety.

Commands executed successfully:

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test apps.payments
python manage.py test
```

Results: system check clean; no unapplied model changes detected; 17 focused payment tests passed; 82 total tests passed.

## Remaining explicit limits

- Demo webhooks do not provide provider-verified amount, currency, or event timestamp. The reconciliation model stores those values when a future adapter supplies them; it does not invent them.
- Production provider amount/currency validation, provider refund execution, COD, a reconciliation dashboard/API, scheduler monitoring, and PostgreSQL concurrency stress tests remain out of scope.
- Apply the included migration during deployment before using the new reconciliation records:

```text
& .\.venv\Scripts\python.exe manage.py migrate
```

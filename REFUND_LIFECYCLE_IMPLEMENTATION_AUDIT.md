# Refund Lifecycle Implementation Audit

**Scope:** IMPLEMENTATION 04B-3. No COD, customer/supplier refund UI, order cancellation, inventory restoration, or production payment-provider integration was added.

## State machine

```text
REQUESTED -> APPROVED -> PROCESSING -> COMPLETED
     |           |             \-> FAILED
     \-> REJECTED
```

Only an active `SUPERADMIN` can create, approve/reject, or initiate a refund at the service boundary. A request is not a completed refund. Provider initiation produces `PROCESSING`; only a verified completion event increments `Payment.refunded_minor`, updates the payment to `PARTIALLY_REFUNDED` or `REFUNDED`, and evaluates supplier-wallet reversal.

## Trace

```text
Superadmin authorization
  -> create_refund allocation validation
  -> approve_refund
  -> initiate_refund through provider adapter
  -> verified provider refund event
  -> complete_refund payment total/status update
  -> reverse_refund completed-only ledger evaluation
  -> audit events
```

## Models and migration

`apps/payments/migrations/0003_refund_lifecycle.py` adds provider metadata and timestamps to `Refund`, approval/rejection actors, `RefundEvent`, and allocation-level `RefundWalletReversal` records. Existing refunds remain compatible: new provider and approval fields are nullable/blank or have defaults; pre-existing refund status values remain valid.

## Allocation and financial controls

- Locks `MasterOrder` then `Payment`, then supplier orders before request validation.
- Requires a paid/partially-refunded payment, a superadmin actor, an idempotency key, at least one allocation, matching currency, valid supplier-order ownership, and valid item ownership.
- Reserves the payment amount against requests in `REQUESTED`, `APPROVED`, `PROCESSING`, and `COMPLETED` states so concurrent requests cannot exceed paid funds under the payment lock.
- Caps cumulative supplier-order amount, item amount, and item quantity against the original snapshots.
- `RefundEvent` has a unique provider event key. Replayed completion events do not update payment totals or wallet entries twice.
- Failed/pending provider events do not change `Payment.refunded_minor` or payment refund status.

## Provider boundary

`DemoAdapter.create_refund` creates only a development/test pending refund intent. It never claims money was returned. `DemoAdapter.verify_refund_webhook` verifies the signed demo callback and returns normalized `COMPLETED`, `FAILED`, or pending status. `process_refund_webhook` validates provider reference, amount, and currency before calling `complete_refund`.

## Wallet behavior

`reverse_refund` now refuses non-completed refunds. It creates one allocation-level `RefundWalletReversal` record and one immutable wallet ledger entry at most. It selects `PENDING` or `AVAILABLE` based on settlement status. If no settlement exists or the relevant balance is insufficient (including funds already withdrawn), it records `HELD` instead of creating a negative wallet balance or an unapproved supplier debt. This remains visible for later approved financial handling.

Refunds do not change order, delivery, reservation, or inventory state.

## Verification

| Command | Result |
| --- | --- |
| `manage.py check` | Passed |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `manage.py test apps.payments apps.wallets` | 29 passed |

Focused tests cover partial and full completion, failure without financial effects, demo webhook completion, duplicate completion, admin authorization, excessive item quantity, request idempotency, pending-wallet reversal, and released-wallet reversal.

## PostgreSQL and remaining decisions

PostgreSQL concurrency tests were **not run**: the available environment uses SQLite and no PostgreSQL service is configured. SQLite validates transactional state paths but not PostgreSQL row-lock contention. Production validation must run concurrent allocation, completion/settlement, and payout/refund tests against PostgreSQL.

The unresolved business decision is supplier debt collection when a completed customer refund exceeds the supplier's current available/pending balance. This implementation deliberately holds that reversal rather than creating a negative balance. A production provider adapter must also define secure event replay, amount/currency verification, key rotation, and refund retry semantics.

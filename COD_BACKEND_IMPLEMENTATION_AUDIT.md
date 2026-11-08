# COD Backend and Financial State Machine

## Architecture

COD uses explicit payment-domain records instead of treating `Payment.method_category` as proof of collection:

- `CODCommitment`: customer-selected active COD commitment for a master order.
- `CODCollection`: immutable full cash collection event per supplier order.
- `CODReceiptConfirmation`: independent customer receipt event per supplier order.
- `CODException`: failed-delivery/dispute/verified-return record.

## State flow

```text
PENDING_PAYMENT
  -> COD_COMMITTED / COD_PENDING
  -> supplier PENDING_SUPPLIER
  -> CONFIRMED -> PREPARING -> READY_FOR_DELIVERY -> SHIPPED -> DELIVERED
  -> cash collected + customer receipt confirmed
  -> COMPLETED -> pending supplier settlement -> existing settlement release
```

Payment selection, delivery, cash collection, receipt confirmation, and settlement remain distinct events. COD never calls online `confirm_payment` or payment-provider webhooks.

## Service inventory and permissions

| Service | Authorization | Result |
| --- | --- | --- |
| `select_cod` | Owning customer | Creates/reuses commitment, protects reservations, never marks PAID. |
| `accept_cod_supplier_order` | Active fulfillment staff or superadmin | Accepts only that supplier's committed suborder. |
| `record_cod_collection` | Active fulfillment staff or superadmin | Records exactly one full delivered-order collection. |
| `confirm_cod_receipt` | Owning customer | Records receipt independently and idempotently. |
| `cancel_cod_before_acceptance` | Owning customer | Releases active stock exactly once before acceptance. |
| `report_cod_delivery_exception` | Active fulfillment staff or superadmin | Records failed delivery/dispute; no stock movement. |
| `verify_cod_return` | Superadmin | Releases that supplier order's active reservations after verified return. |

## Reservation and ledger integration

- The expiry command now skips an active `COD_COMMITTED` / `COD_PENDING` order.
- Cancellation before supplier acceptance releases active COD reservations through the established release service.
- Failed delivery alone does not restore stock. A superadmin verified-return event is required.
- COD earnings are not posted at selection, acceptance, dispatch, or collection alone.
- Once collection and customer receipt are both recorded, the supplier order becomes `COMPLETED` and `post_supplier_order_earnings` creates the existing pending settlement/ledger records exactly once.
- When all supplier orders are completed, active checkout reservations are consumed once and master payment status becomes `COD_COLLECTED`.

## Migration

`apps/payments/migrations/0005_cod_backend.py` adds COD records and preserves all existing online-payment records. It is not applied automatically.

## Verification

`manage.py check`, `manage.py makemigrations --check --dry-run`, and focused COD/wallet tests passed. SQLite validates service transitions and idempotency only; PostgreSQL lock-contention testing remains outstanding.

## Interfaces still pending

No customer or supplier COD browser/API interface was added, by design. The next interface phase should call these services and retain their server-side authorization checks.

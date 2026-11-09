# Notification System Implementation Audit

## A. Existing architecture

BUILTASUPPLY uses durable database records rather than a separate queue:

`business service → DomainEvent → transaction.on_commit(process) → Notification → NotificationDelivery(IN_APP)`.

`Notification` is unique per `(recipient, event)`. Delivery is in-app only. Events are processed synchronously after the surrounding transaction commits; a failed processor records `FAILED`, retry count, and an error on `DomainEvent`.

## B. Registered event types

The registry in `apps/notifications/services.py` now covers payment, order, COD, supplier, refund, finance, and operations events, including:

- `order.created`, `supplier.order_assigned`
- `payment.succeeded`, `payment.failed`, `payment.reconciliation_required`
- `cod.selected`, `cod.supplier_accepted`, `cod.collection_recorded`, `cod.receipt_confirmed`, `cod.cancelled`
- `order.preparing`, `order.ready`, `order.dispatched`, `order.delivered`
- `cod.failed_delivery`, `cod.collection_disputed`
- `refund.approved`, `refund.processing`, `refund.completed`, `refund.failed`, `refund.reversal_held`
- `settlement.released`

## C. Recipient mapping

| Event group | Recipients | Destination |
| --- | --- | --- |
| Checkout/payment/refund/COD tracking | Owning customer only | Customer order or payment page |
| New supplier order, COD collection/receipt/cancellation, settlement/reversal | Active staff of the exact supplier only | Supplier COD inbox or wallet |
| Late-payment reconciliation, failed delivery, collection dispute, held reversal | Active superadmins only | Operations queue/detail |

Supplier recipients are resolved from active memberships. Administrative recipients are active `SUPERADMIN` accounts. No customer or supplier receives raw webhook data, evidence metadata, collection references, wallet balances, or operations notes.

## D. Transaction and duplicate behavior

- Events are created from successful transactional service operations and processed through `transaction.on_commit()`.
- Existing service idempotency prevents emissions on duplicate COD acceptance/collection/receipt, settlement release, payment event, and refund completion paths.
- Notification uniqueness prevents duplicate delivery for the same domain event and recipient.
- User preferences are now respected for in-app category delivery when a preference explicitly disables it.

## E. UI and API

- Global authenticated navigation links to `/notifications/` and shows a server-rendered unread count.
- Existing notification center and API retain private recipient scoping, read/read-all operations, and preferences.

## F. Test evidence

- Notification tests cover private read access, preference suppression, idempotent event processing, and active supplier/superadmin recipient resolution.
- Related order/payment/wallet tests exercise the emitting transactions and financial idempotency paths.
- `manage.py check` passed during implementation.

## G. Remaining limitations

- Only in-app delivery exists. Email, SMS, push, and external messaging are unsupported.
- Failed `DomainEvent` processing is durable but has no scheduled retry command/UI in this phase; operations must replay it through a future approved maintenance workflow.
- PostgreSQL concurrency behavior remains unverified in this SQLite environment.

## Final status

**COMPLETE** for in-app domain event notifications. Delivery-channel expansion and automated failed-event retries require a separate operations scope.

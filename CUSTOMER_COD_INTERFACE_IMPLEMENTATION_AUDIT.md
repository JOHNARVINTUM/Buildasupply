# Customer COD Interface Implementation Audit

## Browser workflow

`Checkout → Order confirmation → Choose cash on delivery → Order details / history → Supplier-order tracking → Confirm receipt`

Checkout remains unchanged: it creates a reservation-backed order before payment method selection. The order-confirmation page now offers COD only while the existing `select_cod` service considers the order eligible. Online payment remains available through its original route.

## Routes

| Route | Purpose | Authority |
| --- | --- | --- |
| `POST /shop/orders/<order_id>/cash-on-delivery/` | Select COD using `payments.services.select_cod`. | Owning active customer and COD service checks. |
| `POST /shop/orders/<order_id>/supplier-orders/<supplier_order_id>/confirm-receipt/` | Confirm one delivered supplier order using `payments.services.confirm_cod_receipt`. | Owning active customer and existing delivered-state check. |
| `POST /shop/orders/<order_id>/cancel-cod/` | Cancel a COD order before supplier acceptance using `payments.services.cancel_cod_before_acceptance`. | Owning customer and existing all-supplier pending-state policy. |

All customer order GET routes remain scoped through `MasterOrder.customer`. No browser value supplies an amount, currency, or financial status.

## Traced behavior

- **COD selection:** creates/reuses only the existing `CODCommitment`; it does not create an online payment, call a webhook, or mark the order paid.
- **Order confirmation:** explains that collection occurs upon delivery, displays the master order, delivery snapshot, total, and independently listed supplier orders.
- **Tracking:** details and history label COD separately from online payment. Each supplier order displays its own fulfillment state, collection state, receipt state, products, and delivery tracking.
- **Collection visibility:** only record-derived collection status and amount are displayed. Collection evidence, reference, actor, and wallet data are not exposed.
- **Receipt confirmation:** is shown only for a delivered, unconfirmed supplier order. The service preserves customer ownership, idempotency, audit data, inventory consumption, and deferred settlement logic.
- **Cancellation:** is offered only while every supplier order remains `PENDING_SUPPLIER`; the existing service releases active reservations and rejects any progressed fulfillment state.
- **Exceptions:** delivery failure/dispute status is visible without exposing supplier evidence or administrative resolution data.

## Notifications

The current notification template registry has no COD lifecycle event templates. No notification was emitted merely from page rendering, and no duplicate notification implementation was introduced.

## Verification

- Customer interface tests cover COD selection, repeat selection, ownership isolation, unavailable/online-payment exclusions, collection privacy, receipt eligibility, and multi-supplier receipt independence.
- Existing COD backend, supplier fulfillment, online payment, wallet, inventory, and checkout suites remain part of the full regression run.

## Deliberately unchanged

- COD financial policies, supplier settlement release rules, wallet behavior, and inventory services.
- Superadmin COD operations.
- Production carrier integration and COD-specific notifications, which require approved event templates/policy before implementation.

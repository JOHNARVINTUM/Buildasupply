# PAYMENT AND COD WORKFLOW PLAN

**Scope:** Read-only discovery of the existing payment, inventory, order, wallet, payout, and notification architecture.  
**Status key:** **VERIFIED** = traced in code; **PARTIAL** = implemented foundation but incomplete workflow; **MISSING** = no implementation found; **UNVERIFIED** = requires runtime/operational evidence or policy approval.

No source, configuration, migration, or database changes were made for this report.

## A. Current payment architecture

The system is a Django modular monolith with an online-payment core centered on `apps/payments`:

- Checkout creates a `MasterOrder`, one `SupplierOrder` per supplier, and active `InventoryReservation` records in `apps/orders/services.py:checkout`.
- `apps/payments/services.py:initiate_payment` creates/reuses a pending `Payment`, then delegates creation of a provider attempt to an adapter.
- Only `DemoAdapter` exists (`apps/payments/adapters.py`). It returns a local instruction URL and verifies HMAC-signed demo webhooks only in DEBUG/test mode.
- `apps/payments/services.py:process_webhook` verifies the provider payload, persists/deduplicates the webhook event, and invokes `confirm_payment`.
- Paid confirmation consumes inventory reservations, sets the master order to `PROCESSING`, supplier orders to `PENDING_SUPPLIER`, creates pending supplier earnings, and emits a customer in-app notification.
- Failed confirmation releases reservations, marks the payment failed, and cancels the master/supplier orders.

The customer checkout implementation creates an order only. It correctly displays payment as pending and does not create a `Payment` or initiate a method (`apps/orders/views.py`, `templates/orders/confirmation.html`). The earlier `templates/carts/payment_status.html` can render a known payment status, but there is no browser payment selection/initiation route.

## B. Existing service and model inventory

| Domain | Verified models/services | Status and boundary |
|---|---|---|
| Payment | `Payment`, `PaymentAttempt`, `WebhookEvent`, `PaymentEvent`, `Refund`, `RefundAllocation` in `apps/payments/models.py` | **PARTIAL**: online payment records and refund allocations exist; no production provider, COD data, or refund execution. |
| Payment initiation | `initiate_payment(customer, order, provider_code, method_category, idempotency_key)` | **VERIFIED** service/API foundation; API-only at `POST /api/v1/orders/<id>/payment/`. |
| Webhooks | `process_webhook`, `confirm_payment`; `PaymentWebhookView` | **VERIFIED** for the demo adapter; provider-specific production verification is **MISSING**. |
| Order / delivery | `MasterOrder`, `SupplierOrder`, `OrderItem`, `OrderFinancialLine`, `Delivery`, `CheckoutIdempotency` | **VERIFIED** checkout snapshots and multi-supplier order structure; delivery lifecycle actions are **MISSING**. |
| Inventory | `Inventory`, `InventoryReservation`, `InventoryMovement`; `consume_reservations`, `release_reservations` | **VERIFIED** reservation and payment consumption/release flows. |
| Wallet | `Wallet`, `WalletLedgerEntry`, `SettlementRecord`; `post_payment_earnings`, `release_settlement`, `reverse_refund` | **PARTIAL**: pending/available accounting works; automatic eligibility scheduling and COD policy are **MISSING**. |
| Payout | `PayoutMethod`, `PayoutRequest`, `PayoutTransaction`; `request_payout`, `approve_payout`, `complete_payout` | **PARTIAL**: internal lifecycle exists; no actual payout-provider adapter/execution path. |
| Notifications | `DomainEvent`, `Notification`, `NotificationDelivery`; `emit`, `process` | **PARTIAL**: `payment.succeeded` exists; payment-pending, failure, COD, delivery, settlement notifications are **MISSING**. |

## C. Current online payment sequence diagram

```text
Customer checkout (orders.services.checkout)
  -> MasterOrder PENDING_PAYMENT + SupplierOrders PENDING_PAYMENT
  -> active inventory reservations (30 minutes)

Customer/API: POST /api/v1/orders/<order>/payment/ + Idempotency-Key
  -> payments.services.initiate_payment
  -> Payment PENDING + PaymentAttempt PENDING
  -> provider adapter create_payment (only DemoAdapter today)
  -> instruction_url returned

Provider: POST /api/v1/payments/webhooks/<provider>/
  -> adapter.verify_webhook HMAC / normalize status
  -> WebhookEvent unique(provider_code, provider_event_id)
  -> PaymentEvent unique(payment, provider_event_id)
  -> confirm_payment
       PAID: consume reservations -> payment PAID -> order PROCESSING
             -> supplier orders PENDING_SUPPLIER
             -> pending wallet earnings -> payment.succeeded notification
       FAILED: release reservations -> payment FAILED -> order/SupplierOrders CANCELLED
```

## D. Proposed COD sequence diagram — subject to approval

```text
Customer selects COD after checkout
  -> create a COD payment/collection record in an explicit pending-collection state
  -> supplier accepts its own SupplierOrder
  -> preparation -> dispatch with delivery evidence
  -> delivery/collection recorded by approved actor with reference/evidence
  -> customer receipt confirmation OR approved timeout/admin resolution
  -> supplier-order-specific settlement becomes eligible
  -> pending supplier wallet amount moves to available

Cancellation/failed delivery before collection
  -> supplier-order-specific cancellation/failure evidence
  -> release or reverse the correct reservations/sale/earnings exactly once
```

The diagram is a proposed shape, not an approved implementation policy. Existing models only partially represent this sequence.

## E. Payment state-transition matrix

| Current state | Event | Current code result | Status |
|---|---|---|---|
| No payment | Initiate valid online payment | `Payment(PENDING)` and `PaymentAttempt(PENDING)` | **VERIFIED** |
| PENDING/AUTHORIZED | Same payment idempotency key | Existing attempt returned | **VERIFIED** |
| PENDING | Signed `PAID` webhook | `Payment.PAID`, paid amount/date set | **VERIFIED** |
| PENDING | Signed `FAILED`/`EXPIRED` demo webhook | `Payment.FAILED` | **VERIFIED** for demo mapping |
| PAID | Duplicate provider event | Ignored through event uniqueness | **VERIFIED** |
| PAID/PARTIALLY_REFUNDED | Create refund allocation | `Refund.REQUESTED` + allocations | **PARTIAL** |
| Refund requested | Provider execution/completion/failure | No service/adapter/state transition found | **MISSING** |
| Any | COD selection/collection | No state transition found | **MISSING** |

`Payment.method_category` is a free text field and can store `COD`, but doing so would not create collection, delivery, inventory, or settlement behavior.

## F. Order state-transition matrix

| State | Current transition | Trigger | Status |
|---|---|---|---|
| `PENDING_PAYMENT` | `PROCESSING` / supplier `PENDING_SUPPLIER` | online `PAID` confirmation | **VERIFIED** |
| `PENDING_PAYMENT` | `CANCELLED` | payment failure or `expire_reservations` command | **VERIFIED** |
| Supplier `PENDING_SUPPLIER` | `CONFIRMED` -> `PREPARING` -> `READY_FOR_DELIVERY` -> `SHIPPED` -> `DELIVERED` -> `COMPLETED` | `orders.services.transition_supplier_order` | **PARTIAL**: transition service exists, but no discovered supplier UI/API invokes it. |
| Any relevant supplier state | cancellation, failed delivery, dispute, partial fulfilment | No complete workflow found | **MISSING** |
| COD checkout | supplier processing eligibility | No implementation found | **MISSING** |

## G. COD business rules requiring approval

The following cannot be safely inferred from existing code:

1. At what event COD becomes supplier-processable: checkout, supplier acceptance, or an operations approval.
2. Whether `InventoryReservation` is consumed on supplier acceptance, dispatch, delivery, or verified collection.
3. Who may record collection: supplier staff, delivery personnel, operations staff, customer, or a constrained combination.
4. Required collection reference/evidence and who may correct it.
5. Whether customer receipt confirmation is required before availability of supplier earnings, its timeout, dispute path, and override authority.
6. Whether each `SupplierOrder` independently collects/settles. This is strongly suggested by the existing supplier-order delivery and wallet structure, but still needs policy approval.
7. Failed-delivery/refusal/no-contact behaviour: stock, delivery costs, payment record, supplier earnings, and notification outcome.
8. Partial delivery/partial collection semantics, including item-level delivery and amounts.
9. Cancellation eligibility by fulfilment state, reasons, authorization, and the associated stock/financial reversal.
10. Administrator dispute holds, evidence, resolution, and final ledger effects.

Recorded earlier project direction identifies COD as launch payment and customer receipt confirmation before earnings release. Current code instead makes `SupplierOrder.COMPLETED` the only settlement gate in `wallets.services.release_settlement`; it does not implement customer confirmation. This must be reconciled explicitly before COD work.

## H. Financial integrity risks

| Risk | Evidence | Required mitigation before launch |
|---|---|---|
| Reservation expires before delayed online confirmation | Reservations expire after 30 minutes; payment may later receive a paid webhook. | Define late-payment reconciliation/reversal/refund path; current `consume_reservations` raises if none active. |
| Incomplete refund lifecycle | `create_refund` creates records but does not call a provider, complete it, or update `Payment.refunded_minor/status`. | Add provider refund attempts/events and idempotent completion/reversal transitions. |
| Refund allocation quantity not validated against item quantity | `RefundAllocation.quantity` is stored; `create_refund` validates monetary total and ownership, not aggregate per-item quantity. | Define and validate item/quantity allocation rules. |
| Earnings posted before delivery completion | `post_payment_earnings` runs immediately after online payment, though bucket is pending. | Keep pending only; implement policy-backed eligibility worker and reversals. |
| Settlement release is manually callable | `release_settlement` only checks supplier-order `COMPLETED`; no customer confirmation, hold, or policy-time check. | Enforce approved eligibility event/policy in service. |
| Payment attempt/provider relationship | A pending `Payment` cannot switch provider (`PAYMENT_PROVIDER_MISMATCH`). | Decide whether retry requires new payment or provider-specific attempt model; do not loosen without audit design. |
| Concurrent idempotency creation | Payment attempt uniqueness is DB-enforced but `initiate_payment` does not catch uniqueness races. | Add conflict/re-fetch behavior and concurrency tests when exposing UI. |
| Reservation expiration operation | `orders.management.commands.expire_reservations` exists; scheduler evidence was not found. | Schedule, monitor, and test command operation before real payments. |
| COD revenue source | Wallet earnings currently require `confirm_payment(... PAID)`. | Define separate verified-collection event; never credit wallet from a UI toggle. |

## I. Required database changes

### Mandatory for a robust COD and payment lifecycle

- A payment/collection representation that distinguishes online provider payment from COD commitment, collection, verification, and failure/refusal. Existing `Payment` fields are insufficient for collection evidence and actor attribution.
- Immutable COD collection/evidence records scoped to `SupplierOrder`, including amount/currency, actor/role, timestamp, reference/evidence metadata, and idempotency key.
- Delivery outcome/evidence and failure/return reason records scoped to `SupplierOrder`; `Delivery` currently has only broad status, carrier/tracking/notes/timestamps.
- Explicit settlement eligibility/hold/release reason/event records (or equivalent policy snapshots) supporting customer confirmation and dispute holds.
- Payment/refund execution attempt/event tracking for provider refund lifecycle; current `Refund` lacks provider reference, processed timestamps, and outcome events.

### Improvements that may reuse existing models after policy approval

- `PaymentAttempt` can support online retry display if given approved status transitions and provider metadata.
- `PaymentEvent`/`WebhookEvent` can remain the immutable online provider audit trail.
- `RefundAllocation` already supports supplier-order/item allocations but needs quantity/amount policy validation.
- `OrderFinancialLine` can record COD fees/adjustments once rules are approved.

## J. Security findings

- **VERIFIED:** `DemoAdapter.verify_webhook` uses constant-time HMAC comparison and refuses demo verification outside DEBUG/test; the secret comes from environment, not the report/code default.
- **VERIFIED:** `process_webhook` requires adapter verification before event creation; webhook/provider-event uniqueness guards repeat processing.
- **VERIFIED:** payment initiation verifies `MasterOrder.customer_id`; payment detail filters by customer ownership.
- **VERIFIED:** supplier wallet/payout APIs require active supplier membership plus `can_view_finance`; payout approval requires `SUPERADMIN` in `approve_payout`.
- **PARTIAL:** DRF uses session authentication globally, but payment method initiation UI is absent. Browser forms must use CSRF and never expose provider secrets.
- **PARTIAL:** `PaymentWebhookView` intentionally has no session auth. Its security wholly depends on each production adapter's correct signature/replay/timestamp verification.
- **MISSING:** production key rotation, webhook replay-window policy, provider IP policy (if desired), secure credential provisioning, and COD evidence access controls.
- **MISSING:** a customer/supplier/admin refund authorization interface. `create_refund` accepts an actor but does not enforce the appropriate business role itself.

## K. Required interfaces

| Actor | Required interface, not currently complete |
|---|---|
| Customer | Payment method selection, provider redirect/instructions, pending/failed/retry status, verified success notification, COD terms/status, delivery receipt confirmation, refund/cancellation status. |
| Supplier staff | Supplier-order acceptance, fulfilment/delivery status, COD dispatch/collection evidence submission, failed-delivery reporting; role-scoped access. |
| Delivery/carrier | Future controlled delivery-status/evidence integration boundary; no carrier integration exists. |
| Superadmin | Payment/webhook exception review, manual resolution with audit, COD collection/dispute review, settlement hold/release, refund execution oversight, payout review. |

## L. Recommended implementation phases

1. **Approve policies:** resolve every item in section G and define online retry/late-payment/refund policy.
2. **Online customer payment UI:** method catalog, initiation form, idempotency handling, instructions/redirect return, status/retry UI; continue using `initiate_payment` and provider boundary.
3. **Provider adapter hardening:** approved provider only, signed webhooks, normalized events, retry/reconciliation procedures, secrets operationalization.
4. **Refund completion lifecycle:** provider refund attempts/events, exact allocation validation, wallet/order/inventory reconciliation policy.
5. **COD schema and services:** add only approved collection/delivery/evidence/settlement data and supplier-order state transitions.
6. **COD interfaces:** customer selection/status/receipt confirmation; supplier fulfilment and evidence; operations dispute/override tools.
7. **Financial operations:** scheduled expiry/eligibility/reconciliation, alerts, audit reports, and payout integration.

## M. Acceptance criteria and test scenarios

### Online payment

- Customer-owned unpaid order can initiate an approved method with a stable idempotency key and sees pending instructions.
- Duplicate initiation and duplicate webhooks produce one payment effect, one inventory consumption, and one wallet posting.
- Valid paid callback moves only the owned order to the approved processing state, consumes each active reservation once, and creates correct pending ledger records.
- Failed/expired callback restores stock once and produces no supplier earnings.
- Late callback, amount/currency mismatch, invalid signature, unknown payment, provider outage, retry, and concurrency paths are deterministic and auditable.
- Refund tests cover supplier-order/item allocations, partial/full totals, duplicate provider event, wallet reversal, and provider failure.

### COD

- Every collection/delivery/receipt/dispute action is supplier-order scoped, actor-authorized, auditable, idempotent, and transactionally safe.
- Multi-supplier checkout proves independent supplier acceptance, delivery, collection, failure, and settlement outcomes.
- Cancellation/refusal/return restores or reverses inventory and financial records exactly once according to approved policy.
- Customer receipt confirmation/timeout/dispute policies prevent premature available-wallet settlement.
- Superadmin holds/resolutions are fully audited and cannot create duplicate ledger movements.

### Existing regression coverage inspected

- `apps/payments/tests.py`: webhook consumption/replay, invalid signature, initiation idempotency, refund allocation/over-refund cap.
- `apps/wallets/tests.py`: pending-to-available settlement and failed payout compensation.
- `apps/orders/tests.py`: checkout snapshots, reservation behaviour, price rollback, checkout idempotency.
- `apps/notifications/tests.py`: private in-app event delivery.

Missing test coverage includes production providers, browser payment flow, reservation scheduler execution, refund completion, COD, delivery evidence, customer receipt confirmation, disputes, late callbacks, and multi-supplier financial failure paths.

## Existing documentation inspected

- `docs/api/idempotency.md`, `docs/api/webhooks.md`, and `docs/api/errors.md` describe API conventions.
- `docs/operations.md` identifies reservation expiry operational work.
- `docs/integrations/overview.md` describes integration boundaries.

No implementation should begin until the COD and financial-policy approvals above are supplied.

# PAYMENT RELIABILITY AND RECONCILIATION AUDIT

**Scope:** Read-only analysis of the current payment, checkout, reservation, inventory, wallet, and browser payment interface.  
**Status key:** **VERIFIED** means traced in the code; **RISK** is a consequence inferred from the traced control flow/concurrency model; **UNVERIFIED** requires production/runtime evidence.

No code, migrations, configuration, tests, or database records were changed for this audit.

## A. Existing payment state machine

| State / event | Verified transition | Source | Priority |
|---|---|---|---|
| Checkout | `MasterOrder.PENDING_PAYMENT`, payment status `PENDING`, active inventory reservations | `apps/orders/services.py:checkout` | Normal |
| Initiate | Creates/reuses `Payment(PENDING)` and a `PaymentAttempt(PENDING)` | `apps/payments/services.py:initiate_payment` | Normal |
| PAID event | Payment `PAID`; master `PROCESSING`; supplier orders `PENDING_SUPPLIER`; reservations consumed; pending earnings posted | `confirm_payment` | Critical |
| FAILED event | Payment `FAILED`; master/supplier orders cancelled; active reservations released as `EXPIRED` | `confirm_payment` | Critical |
| Expiry command | Master cancelled/payment `EXPIRED`; supplier orders cancelled; active reservations released as `EXPIRED` | `apps/orders/management/commands/expire_reservations.py:Command.handle` | Critical |
| Refund request | `Refund.REQUESTED` with supplier-order/item allocations | `create_refund` | High |
| Settlement | Pending wallet entries move to available only when supplier order is `COMPLETED` | `apps/wallets/services.py:release_settlement` | High |

The browser payment interface in `apps/payments/views.py` is **VERIFIED** to call `initiate_payment` only. It does not alter order/payment status, reservations, or wallets.

## B. Late webhook scenario analysis

### Exact current behavior — **VERIFIED**

Scenario: checkout reserves stock; `expire_reservations` runs; later a valid signed PAID webhook arrives.

1. `expire_reservations.Command.handle` selects active expired reservations, locks the master order, calls `release_reservations(..., expired=True)`, restores `Inventory.available_quantity`, reduces `reserved_quantity`, marks reservations `EXPIRED`, creates `RESERVATION_RELEASE` inventory movements, and sets master order `CANCELLED` / payment status `EXPIRED`; supplier orders become `CANCELLED`.
2. `process_webhook` successfully verifies the signature and calls `confirm_payment` inside `@transaction.atomic`.
3. `confirm_payment` records a `PaymentEvent` in its transaction, verifies `payment.amount_minor == master_order.total_minor`, then calls `consume_reservations`.
4. `consume_reservations` filters for `InventoryReservation(status="ACTIVE")`. After expiry there are none, so it raises `PaymentFailure({"code": "NO_ACTIVE_RESERVATIONS"})`.
5. The exception escapes `confirm_payment` and `process_webhook`; both atomic transactions roll back. The newly created `PaymentEvent` and `WebhookEvent` do **not** persist.
6. The payment does **not** become `PAID`; the master order does **not** become `PROCESSING`; no supplier earnings, wallet records, or success notification are created; inventory is not sold.
7. `PaymentWebhookView` catches `PaymentFailure` and returns HTTP 400. `WebhookEvent.processing_status` is not persisted as processed.
8. A repeated delivery of the same provider event repeats the verification and fails in the same manner, because the unique `WebhookEvent` record was rolled back.

This avoids silently processing a paid order without allocated inventory, which is correct. It does not, however, reconcile the real-world paid customer/provider outcome.

### Finding: late paid callback has no reconciliation workflow

- **Priority:** Critical
- **Files/functions:** `apps/payments/services.py:process_webhook`, `confirm_payment`, `consume_reservations`; `apps/orders/management/commands/expire_reservations.py:Command.handle`
- **Impact:** A customer can be charged while their order remains cancelled/expired. Automatic callback retry will keep returning 400. Operations has no persistent exception record to investigate.
- **Recommended correction:** Introduce a durable, idempotent payment-exception/reconciliation workflow. Persist the verified callback (including an explicit `LATE_PAYMENT_REQUIRES_RECONCILIATION` outcome) outside or independently from the failing fulfillment transition. The approved policy must then select one of: reserve/reallocate stock under an explicit exception; cancel/refund through a provider; or operations-led resolution. Never set order processing/earnings until stock allocation is valid and explicitly approved.

## C. Idempotency and concurrency findings

| Finding | Priority | Actual implementation | Verified behaviour / impact | Recommendation |
|---|---|---|---|---|
| Same payment attempt key | High | `PaymentAttempt` unique `(payment, idempotency_key)`; `initiate_payment` queries existing attempt | Same sequential key returns prior attempt. Browser stores a stable per-order session key. | Keep; add database-conflict catch/re-fetch for concurrent requests. |
| Different simultaneous initiation keys | High | `initiate_payment` locks `MasterOrder` with `select_for_update` then queries pending payment | On a database honoring row locks, order lock serializes requests, but distinct keys can each create separate provider attempts against the same pending payment. Browser GET redirects existing pending payment, but API remains able to request another attempt. | Define approved retry semantics; enforce at most one active provider attempt or record attempt supersession. |
| Payment creation uniqueness | High | No unique constraint for a single pending payment per master order | The master-order lock is the practical protection, not schema enforcement. | Add concurrency tests; consider a conditional unique constraint/explicit active-attempt invariant after retry policy approval. |
| Same webhook event | High | `WebhookEvent` unique `(provider_code, provider_event_id)`; `PaymentEvent` unique `(payment, provider_event_id)` | Sequential duplicate after success returns `{duplicate: True}`. Existing test verifies no second inventory sale. | Keep; catch integrity races from `get_or_create` and re-fetch duplicate result. |
| Concurrent confirmations | High | `confirm_payment` locks payment row, then checks/creates `PaymentEvent` | Same/different callbacks serialize on payment lock. Once paid, later event records may be created but no second consume/ledger posting occurs. | Add database-specific concurrency tests. |
| Provider amount/currency authenticity | Critical | `confirm_payment` only compares internal `payment.amount_minor` to order total; `DemoAdapter.verify_webhook` returns no provider amount/currency | A production adapter must verify the provider-reported amount/currency before normalized PAID reaches this service. | Make normalized webhook contract include verified amount/currency and compare them to payment/order. |
| Browser retry | Normal | `apps/payments/views.py:_payment_key` stores session key | Sequential repeat with the same form creates one attempt; tests cover it. | Session loss/new device behavior needs approved retry UX. |

## D. Reservation expiration analysis

### Verified behaviour

- The command uses only `InventoryReservation(status="ACTIVE", expires_at <= now)` to find candidate master orders.
- Per master order it opens an atomic block, locks the master order, skips if the master status is no longer `PENDING_PAYMENT`, then invokes `release_reservations(expired=True)`.
- `release_reservations` locks active reservations/inventory, restores available quantity, lowers reserved quantity, marks each reservation `EXPIRED`, and creates an inventory movement.
- It sets master order `CANCELLED`, payment status `EXPIRED`, and supplier orders `CANCELLED`.
- A later command execution sees no active reservations; it is effectively repeatable for completed expiry sets.

### Findings

| Finding | Priority | File/function | Impact | Recommended correction |
|---|---|---|---|---|
| Scheduler is not implemented/verified | Critical | `apps/orders/management/commands/expire_reservations.py` | Reservations may remain held indefinitely without an external scheduler. | Run under a monitored scheduler; emit metrics/alerts for backlog, failures, expired counts, and command duration. |
| Lock-order inversion risk | Critical | expiry locks master then reservations; `confirm_payment` locks payment then reservations then updates master | PostgreSQL can encounter contention/deadlock or a race between payment confirmation and expiry. Exact outcome is database/timing dependent. | Establish one global lock order (for example master -> payment -> reservations/inventory) and test concurrent expiry/paid callback paths. |
| No expiry audit event | Medium | `expire_reservations.Command.handle` | Inventory movements exist, but no `log_action` / notification / operational exception record is written for order expiry. | Add auditable order-expiry action and operational visibility. |
| Existing pending payment after expiry | High | `Payment` remains PENDING while master order becomes `CANCELLED`/`EXPIRED` | UI/service blocks new initiation through order eligibility; provider may still settle a prior attempt. | Explicitly cancel/expire provider attempts where provider supports it, and reconcile late settlement. |

## E. Refund lifecycle analysis

### Verified current behaviour

- `create_refund(payment, actor, allocations, idempotency_key, reason)` accepts only `PAID` or `PARTIALLY_REFUNDED` payment status.
- It locks payment, returns the same `Refund` for duplicate `(payment, idempotency_key)`, aggregates non-cancelled refund amounts, and rejects over-refunds versus `payment.paid_minor`.
- It persists `Refund.REQUESTED` and `RefundAllocation` records validated to belong to the master order/supplier order.
- It records an audit action `REFUND_CREATED`.
- It does **not** call a provider, create a refund attempt/event, change `Refund.status`, increment `Payment.refunded_minor`, or transition payment to `PARTIALLY_REFUNDED`/`REFUNDED`.
- It does **not** update order, delivery, inventory, or supplier order state.
- `wallets.services.reverse_refund(refund)` can post negative wallet entries, but is not called by `create_refund`, does not require `Refund.COMPLETED`, and assumes a settlement exists.

### Findings

| Finding | Priority | Function/model | Impact | Recommended correction |
|---|---|---|---|---|
| Refund is only a request record | Critical | `create_refund`, `Refund` | Requested/full/partial refunds never reach provider/customer/ledger completion. | Add provider refund initiation, verified completion/failure events, state transitions, and reconciliation. |
| Payment refund totals/status never update | Critical | `Payment.refunded_minor`, `Payment.status` unused by current service | Future refunds can be inconsistently represented even though allocation cap uses committed request amounts. | On verified completion, atomically update refunded amount/status from completed refunds only. |
| Wallet reversal can precede refund completion | Critical | `wallets.services.reverse_refund` | Pending/available supplier balance could be reduced for a refund that fails or is cancelled. | Gate reversal on completed/refund-approved policy and make reversal idempotent by provider completion event. |
| Allocation quantity not capped | High | `RefundAllocation.quantity` | Amount cap exists but repeated item quantities can exceed ordered quantity. | Validate cumulative per-item quantity and allocation amount under approved refund policy. |
| Actor authorization missing at service boundary | High | `create_refund` accepts arbitrary actor | A future endpoint could call it without an authorization rule. | Enforce or centrally authorize customer/supplier/superadmin roles before service call. |

## F. Wallet and ledger integrity

| Control | Status | Evidence / finding |
|---|---|---|
| Earnings exactly once per supplier order | **VERIFIED** | `post_payment_earnings` uses `SettlementRecord.get_or_create(supplier_order=...)`; payment confirmation executes it only on first PAID transition. |
| Pending/available separation | **VERIFIED** | `WalletLedgerEntry.bucket` and `release_settlement` post offsetting PENDING/AVAILABLE settlement entries. |
| Settlement release idempotency | **VERIFIED** | `release_settlement` returns when already released; test expects exactly two settlement entries. |
| Refund ledger integrity | **PARTIAL / Critical** | `reverse_refund` deduplicates by reference but has no refund-completed guard and may fail if no settlement exists. |
| Payout reservation/failed compensation | **VERIFIED** | `approve_payout` creates RESERVED debit; `complete_payout(failed=True)` posts reversal; wallet balance tests cover it. |
| Payout provider execution | **MISSING** | `PayoutTransaction` model exists but `complete_payout` has no provider adapter/callback. |
| Audit persistence | **PARTIAL** | Payment confirmed/failed and refund-created events call `log_action`; expiry, settlement release, refund reversal, and payout completion do not all log actions. |

## G. Security findings

- **VERIFIED:** `DemoAdapter.verify_webhook` uses HMAC SHA-256 and `hmac.compare_digest`; demo verification is disabled outside DEBUG/test and secret is environment-sourced.
- **VERIFIED:** `PaymentWebhookView` has no session authentication intentionally; security rests on provider-adapter verification.
- **VERIFIED:** Payment initiation locks and verifies customer ownership; browser payment views scope orders/payments to the customer.
- **VERIFIED:** Browser confirmation cannot mark a payment paid; only `process_webhook` calls `confirm_payment`.
- **RISK:** Production adapters must validate provider event authenticity, amount, currency, provider reference, event freshness/replay semantics, and key rotation. The current normalized adapter contract does not enforce amount/currency fields.
- **RISK:** Raw webhook bodies are stored in `WebhookEvent.raw_body`; retention/redaction/access-control policy is **UNVERIFIED**.

## H. Required code changes

| Priority | Required correction | Primary locations |
|---|---|---|
| Critical | Durable late-payment exception/reconciliation state; never silently process without allocation | `payments.services.process_webhook`, `confirm_payment`; order/payment models |
| Critical | Establish a consistent transaction lock order between expiry and confirmation | `payments.services`, expiry command, inventory services |
| Critical | Complete provider refund lifecycle and only reverse wallet after verified completion | payments/refund services, wallets services |
| Critical | Require verified provider amount/currency in production webhook adapter contract | adapters and `confirm_payment` |
| High | Define/implement one-active-attempt retry semantics and concurrency conflict handling | `initiate_payment`, `PaymentAttempt` |
| High | Add operational scheduler/monitoring/audit for reservation expiry | expiry command and operations/notifications |
| High | Add service-boundary refund authorization and item quantity validation | `create_refund` and future endpoints |

## I. Proposed database changes

No migration is created by this audit. Likely requirements, subject to approved policy:

- Persistent payment reconciliation/exception record with provider event identity, reason, review actor/status, resolution, and financial links.
- Provider refund execution attempt/event records: provider reference, idempotency, response/result, timestamps, normalized status, and verified amount/currency.
- Optional conditional active-payment/attempt constraint after retry policy is approved.
- Refund completion timestamps/provider references and a ledger linkage to prevent premature or duplicate wallet reversal.
- Operational job execution/run record or durable metrics/audit for reservation expiry and reconciliation jobs.

## J. Required automated tests

1. Paid webhook after expired reservation: callback is durably recorded as reconciliation-required; no sale/wallet/processing transition occurs.
2. Repeated late webhook: one exception record, deterministic provider response, no duplicate inventory effect.
3. Concurrent expiry and PAID confirmation: no deadlock or partial order/inventory/payment state.
4. Concurrent same/different payment initiation keys: approved number of attempts, no duplicate charge intent.
5. Concurrent same/different provider events: one sale, one wallet posting, auditable event outcomes.
6. Provider amount/currency mismatch rejection.
7. Expiry command rerun/partial failure/restart and monitoring output.
8. Partial/full refund request, provider success/failure/retry/replay, cumulative item quantity, payment refund totals/status, and wallet reversal timing.
9. Settlement/refund race and payout/refund race.

## K. Recommended implementation sequence

1. Approve late-payment, retry, refund, and reconciliation policies.
2. Define lock ordering and add concurrency tests before adding more provider functionality.
3. Implement durable late-event reconciliation and reservation-expiry operational monitoring.
4. Extend provider webhook contract for verified amount/currency and production event properties.
5. Implement refund execution/completion workflow and ledger-safe wallet reversal.
6. Implement approved payment retry/attempt model and customer/operations UX.
7. Add scheduled reconciliation and exception dashboards with audit trails.

## Existing test coverage inspected

- `apps/payments/tests.py` verifies demo webhook consumption once, sequential webhook duplication, invalid signature, payment initiation idempotency, and refund request over-refund cap.
- `apps/orders/tests.py` verifies checkout reservation creation, rollback on price change, and checkout idempotency.
- `apps/wallets/tests.py` verifies settlement release once and failed payout balance restoration.

The late-webhook, expiry/concurrency, scheduler, refund completion, provider amount/currency, and refund-wallet timing cases are **MISSING**.

# Payment Concurrency and Provider Verification Hardening

**Scope:** IMPLEMENTATION 04B-4. No COD or production provider integration was added.

## Payment-attempt policy

1. The same payment and idempotency key always returns its original attempt.
2. At most one `PENDING` provider attempt exists for a payment.
3. A request with a different key while an attempt is pending returns that pending attempt and does not call the provider again.
4. A failed attempt can be retried with a new idempotency key only while the order remains otherwise payment-eligible.
5. A confirmed provider failure cancels the existing order/reservations under the current business flow; it therefore requires a new checkout rather than a second attempt.
6. Provider-code mismatches remain rejected.

`PaymentAttempt` has a conditional database uniqueness constraint for one `PENDING` attempt per payment. The master-order lock in `initiate_payment` serializes normal initiation; the conditional constraint protects the invariant at the database level.

## Provider verification path

```text
Customer submission
  -> MasterOrder lock / payment attempt policy
  -> provider payment request
  -> HMAC-verified DemoAdapter webhook
  -> event ID + provider reference + merchant reference + amount + currency verification
  -> confirm_payment
  -> reservation consumption / payment status / supplier earnings
```

For a normalized `PAID` demo event, `DemoAdapter` now requires and verifies:

- provider event identity;
- provider payment reference;
- merchant reference, matched to the internal payment reference;
- positive integer amount in minor units, matched to the payment amount;
- three-letter currency, matched to the payment currency; and
- a constant-time HMAC signature.

Malformed, missing, or mismatched values cannot reach `confirm_payment` through `process_webhook`. Browser-provided values are never used for confirmation.

## Locking and duplicate effects

The established lock order remains `MasterOrder -> Payment -> SupplierOrder -> InventoryReservation -> Inventory`. Payment confirmation marks pending attempts completed and failed confirmation marks them failed. Existing payment-event uniqueness and payment locking continue to prevent duplicate inventory consumption and wallet earnings. Late verified payment reconciliation and refund services are unchanged.

## Migration

`apps/payments/migrations/0004_paymentattempt_one_pending_attempt_per_payment.py` adds the conditional one-pending-attempt constraint. Apply this migration before enabling the new invariant in an environment with existing payment attempts.

## Verification

| Command | Result |
| --- | --- |
| `manage.py check` | Passed |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `manage.py test apps.payments` | 33 passed |
| `manage.py test` | 103 passed |

Focused coverage includes same/different idempotency keys, one pending attempt, retry after a failed attempt, invalid signature, missing/incorrect payment amount and currency, merchant-reference mismatch, duplicate callbacks, late-payment reconciliation, and refund regression paths.

## Production-provider boundary

A selected production provider must still implement independently verified signatures, timestamp/freshness and replay protection, key rotation, provider reconciliation, explicit cancellation/expiration semantics, refund idempotency, availability/retry rules, and audited provider-error handling. PostgreSQL concurrent-request testing is also required before production; SQLite does not validate row-lock behavior.

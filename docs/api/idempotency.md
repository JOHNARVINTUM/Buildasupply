# Idempotency

`Idempotency-Key` is required for checkout and payment initiation and is persisted per customer/action. Repeating a completed key returns the original effective result. Keys must be high-entropy and unique per action; changing the request behind a reused key is rejected where a request fingerprint exists.

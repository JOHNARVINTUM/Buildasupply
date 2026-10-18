# Error contract

Current endpoints return Django REST Framework error payloads; integrations should treat HTTP status as authoritative. The next compatible API revision standardizes `{ "error": { "code", "message", "details", "request_id" } }`. Existing domain codes include `PRICE_CHANGED`, `INSUFFICIENT_STOCK`, `IDEMPOTENCY_REQUIRED`, `INVALID_WEBHOOK`, and `ORDER_ACCESS_DENIED`.

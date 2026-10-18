# Webhooks

Inbound payment webhooks currently use the provider adapter boundary and persistent provider event IDs for deduplication. The demo adapter signs raw request bytes with HMAC-SHA256 in `X-Builtasupply-Signature`. Production providers must define their own verified adapter contract. Outbound webhook persistence is prepared through `WebhookSubscription` and `WebhookDelivery`; no outbound delivery worker is enabled yet.

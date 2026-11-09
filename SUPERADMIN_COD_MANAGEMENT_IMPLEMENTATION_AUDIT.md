# Superadmin COD Management and Financial Oversight Audit

## Implemented operations routes

- `GET /operations/cod/orders/` — filtered, paginated COD supplier-order register.
- `GET /operations/cod/orders/<uuid>/` — supplier-order investigation detail and audit timeline.
- `GET /operations/cod/failed-deliveries/` — failed delivery and verified-return review queue.
- `POST /operations/cod/returns/<int>/verify/` — existing `verify_cod_return` service, requiring an operations explanation.
- `GET /operations/cod/disputes/` — collection-dispute investigation queue.
- `GET /operations/cod/settlements/` and `POST .../<uuid>/release/` — COD settlement monitoring and existing `release_settlement` service.
- `GET /operations/cod/held-reversals/` — held refund wallet-reversal review queue.
- `GET /operations/cod/reconciliations/` and `POST .../<uuid>/resolve/` — existing reconciliation visibility and resolution service.

All routes require an active authenticated superadmin. State-changing routes are POST-only and CSRF protected.

## Financial and inventory safeguards

- No view updates wallet balances, inventory quantities, collection evidence, or settlement status directly.
- Verified returns call only `payments.services.verify_cod_return`; repeat requests cannot create a second reservation-release movement.
- Settlement release calls only `wallets.services.release_settlement`, retaining its completed-order, collection, receipt-confirmation, and exception-hold checks.
- Reconciliation actions call only `payments.services.resolve_payment_reconciliation` with one of its approved paths.
- Held refund reversals are intentionally read-only: no debt recovery or future-earnings deduction policy exists.

## Audit coverage

Existing service audit events remain authoritative. The operations return workflow adds an administrative `COD_RETURN_VERIFICATION_NOTES` event with the administrator and required explanation; settlement-release requests are also logged after the validated service succeeds.

## Deliberately unavailable actions

There is no existing approved service to resolve a COD collection dispute or rewrite immutable collection evidence. The interface provides investigation visibility only. It also does not implement supplier debt recovery, production provider operations, or manual financial overrides.

## Verification

- `python manage.py check` — passed.
- `python manage.py makemigrations --check --dry-run` — no changes detected.
- Operations COD tests — passed, including access control, independent multi-supplier rows, verified-return idempotency, settlement release, and reconciliation review.
- Full Django test suite — passed.

## Production verification outstanding

The environment uses SQLite for automated tests. PostgreSQL lock-contention verification remains required for concurrent collection, return verification, settlement release, and reconciliation resolution.

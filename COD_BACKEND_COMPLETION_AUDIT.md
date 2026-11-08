# COD Backend Completion and Financial Verification

## Multi-supplier behavior

COD fulfillment is supplier-order scoped. In the tested two-supplier flow, Supplier A can accept, deliver, collect cash, receive customer confirmation, complete, post pending earnings, and release its own settlement while Supplier B remains `CONFIRMED` with its inventory reservation intact.

Supplier staff permissions are evaluated against the exact supplier on the supplier order. Staff from Supplier A cannot accept or collect Supplier B's order.

## Inventory behavior

The original master-order-wide consumption was replaced with `_consume_cod_supplier_reservations`. It locks the master order, then the relevant supplier order, reservations, and inventory records, and creates sale movements only for that completed supplier order. Other supplier orders remain reserved until their own collection and receipt confirmation are complete.

Failed delivery/dispute creates no inventory movement. A return must be verified by a superadmin before the affected supplier order's active reservations are released.

## Settlement eligibility

`release_settlement` now recognizes an active COD commitment and requires, at the service boundary:

- completed supplier order;
- COD collection;
- customer receipt confirmation; and
- no unresolved `FAILED_DELIVERY` or `DISPUTED` exception.

The existing online-payment settlement path is unchanged. Existing settlement idempotency remains: repeated release returns the released settlement without duplicate entries.

## Verification

- `manage.py check` — passed.
- `manage.py makemigrations --check --dry-run` — no changes detected.
- `manage.py test apps.payments.tests_cod apps.wallets apps.orders` — 26 passed.

SQLite confirms state transitions, permissions, and idempotency. PostgreSQL lock-contention testing was not available and remains required before production.

## Remaining limitations

- No customer/supplier interface endpoints were added.
- Failed-delivery/dispute and return verification services are backend-only.
- Production PostgreSQL concurrency testing, including settlement/collection races, remains outstanding.

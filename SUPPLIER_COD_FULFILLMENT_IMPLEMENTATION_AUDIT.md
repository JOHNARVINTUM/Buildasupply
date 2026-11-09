# Supplier COD Fulfillment Interface Audit

## Implemented browser path

`/supplier/` dashboard → **COD orders** → `/supplier/orders/` → supplier-order detail → POST-only fulfillment action.

The new inbox is scoped to active memberships of approved suppliers and only includes orders with a COD commitment. It supports status filtering and 20-row pagination.

## Route and action trace

| Browser action | Route | View/service boundary | Authorization and result |
| --- | --- | --- | --- |
| View COD inbox | `GET /supplier/orders/` | `orders.supplier_views.cod_order_dashboard` | Active approved supplier membership; queryset is scoped by supplier. |
| View order | `GET /supplier/orders/<uuid>/` | `cod_order_detail` | Supplier ownership in queryset; historical `OrderItem` and `Delivery.address_snapshot` data displayed. |
| Accept | `POST .../accept/` | `accept_cod_supplier_order` | `can_manage_fulfillment`; existing COD transition and audit event. |
| Prepare / ready | `POST .../prepare/`, `.../ready/` | `transition_supplier_order` | Fixed state graph and fulfillment permission. |
| Dispatch / delivered | `POST .../dispatch/`, `.../deliver/` | `transition_supplier_order` | Dispatch requires carrier/delivery method and reference; updates existing `Delivery`. |
| Collect cash | `POST .../collect/` | `record_cod_collection` | Existing exact server-side amount/currency, delivered-status, ownership, and idempotency checks. |
| Report exception | `POST .../exception/` | `report_cod_delivery_exception` | Existing failure/dispute service; no stock or settlement change. |

All state-changing endpoints reject non-POST requests and use Django CSRF tokens. Buttons are hidden when an action is not valid, but the service layer remains the authorization authority.

## Financial and customer-confirmation boundaries

- The collection form supplies the expected amount as a convenience only. `record_cod_collection` compares it to the persisted supplier-order total and currency.
- A supplier cannot create a receipt confirmation. The detail page only exposes receipt status.
- Collection does not release earnings. Existing COD services complete and post pending earnings only after independent customer receipt confirmation.
- Failed delivery/dispute reporting does not restore inventory or release settlements. Return verification remains superadmin-only.

## Verification

- `python manage.py check` — passed.
- `python manage.py makemigrations --check --dry-run` — no changes detected.
- `python manage.py test apps.orders.tests_supplier_cod` — passed (browser scope, filtering/pagination, fulfillment authorization, accept/prepare/dispatch/deliver, collection validation/idempotency, receipt visibility, and exception reporting).
- `python manage.py test` — passed (exit code 0).

## Remaining production consideration

No carrier integration was added. Dispatch records the supplier-managed carrier/delivery method, reference, notes, and timestamps in the existing `Delivery` record, preserving the future carrier boundary.

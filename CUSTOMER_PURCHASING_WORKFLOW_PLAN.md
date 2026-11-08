# CUSTOMER PURCHASING WORKFLOW — DISCOVERY REPORT

**Scope:** Read-only architecture discovery of the existing BUILTASUPPLY codebase.  
**Inspection date:** 2026-11-07  
**Status key:** **VERIFIED** = traced in code; **PARTIAL** = implemented but not connected through the complete customer journey; **MISSING** = no implementation found; **UNVERIFIED** = cannot be established from static inspection alone.

No source files, migrations, database records, or configuration were changed while preparing this report. Tests were inspected but not executed as part of this read-only discovery.

## A. Existing architecture and purchasing workflow

BUILTASUPPLY is a Django modular monolith using server-rendered pages alongside Django REST Framework API endpoints. The customer purchase domain is distributed across these apps:

- `accounts`: account registration, session login/logout, password reset, account status, and global role checks.
- `customers`: `CustomerProfile` and persisted delivery addresses.
- `catalog`: products, prices, public catalog selector, and product availability rules.
- `inventory`: per-product/supplier inventory, movements, and time-bounded reservations.
- `carts`: persistent carts and items; public browsing templates; cart validation and REST endpoints.
- `orders`: transactional checkout, master/supplier order construction, price/address snapshots, and reservation creation.
- `payments`: provider adapter boundary, payment attempts, webhook processing, reservation consumption/release, and refund allocation foundation.
- `wallets` / `payouts`: supplier pending/available ledger, settlement records, and payout workflow.
- `notifications`: domain-event-backed in-app notifications.

The domain supports a master order with one `SupplierOrder` per supplier. The checkout service already locks cart/inventory rows and reserves stock before payment. Payment confirmation consumes reservations, changes order state, creates pending supplier earnings, and emits an in-app notification.

The complete *backend* path exists in substantial form. The complete *customer-facing workflow* does not: the HTML templates provide browsing and read-only cart/order pages, but do not submit add-to-cart, quantity change, address, checkout, or payment actions.

## B. File and function inventory

| Area | Verified files and principal classes/functions | Finding |
|---|---|---|
| Authentication | `apps/accounts/models.py: User`; `apps/accounts/views.py: login_view, customer_register, logout_view, password_reset`; `apps/accounts/services.py: register_customer`; `apps/accounts/permissions.py: IsActiveAccount, IsCustomer` | Session customer accounts and profile creation are implemented. |
| Customer data | `apps/customers/models.py: CustomerProfile, CustomerAddress` | Address persistence exists; no customer forms, views, URLs, or API endpoints were found. |
| Public catalog | `apps/catalog/selectors.py: customer_catalog_queryset`; `apps/catalog/services.py: is_product_purchasable, current_price_for`; `apps/carts/views.py: browse, product_detail`; `apps/carts/api_views.py: CatalogProductsView, CatalogProductDetailView` | Public catalog is correctly filtered and has both templates and API access. |
| Cart | `apps/carts/models.py: Cart, CartItem`; `apps/carts/services.py: get_active_cart, add_item, update_quantity, validate_cart`; `apps/carts/api_views.py: CartView, CartItemsView, CartItemDetailView, CartValidationView`; `apps/carts/views.py: cart_page` | Services and API CRUD exist; HTML page is display-only. |
| Checkout/orders | `apps/orders/models.py: MasterOrder, SupplierOrder, OrderItem, OrderFinancialLine, Delivery, CheckoutIdempotency`; `apps/orders/services.py: checkout, release_reservation, transition_supplier_order`; `apps/orders/api_views.py: CheckoutView, CustomerOrdersView, CustomerOrderDetailView` | Transactional checkout is implemented as an API-only operation. |
| Reservation expiry | `apps/orders/management/commands/expire_reservations.py: Command.handle` | Expiry/release command exists; scheduler integration and tests were not found. |
| Payments | `apps/payments/models.py`; `apps/payments/services.py: initiate_payment, confirm_payment, consume_reservations, release_reservations, process_webhook, create_refund`; `apps/payments/api_views.py`; `apps/payments/adapters.py: DemoAdapter, get_adapter` | Provider abstraction and demo payment flow exist; no customer payment selection/submission UI exists. |
| Supplier financials | `apps/wallets/services.py: post_payment_earnings, release_settlement, reverse_refund`; `apps/payouts/services.py: request_payout, approve_payout, complete_payout` | Supplier financial services and API are present, not customer-facing. |
| Notifications | `apps/notifications/services.py: emit, process`; `apps/notifications/models.py`; `apps/notifications/api_views.py` | In-app event delivery is present; only payment success is connected to the discovered customer flow. |

Routes are assembled in `config/urls.py`: `/shop/` includes template routes from `apps/carts/urls.py`; `/api/v1/` includes carts, orders, payments, notifications, wallets, and payouts APIs.

## C. Current workflow diagram

```text
Customer
  │
  ├─ Register / login (HTML session) ──> accounts.views / CustomerProfile
  │
  ├─ Browse /shop/ or /shop/browse/ ──> carts.views.browse
  │       └─ catalog.selectors.customer_catalog_queryset() [public approved/in-stock items]
  │
  ├─ View /shop/products/<id>/ ──> carts.views.product_detail
  │       └─ product detail page only; no add-to-cart submission
  │
  ├─ API-only cart actions ──> /api/v1/cart/items/, /api/v1/cart/items/<id>/
  │       └─ carts.services.add_item / update_quantity / validate_cart
  │
  ├─ API-only checkout ──> POST /api/v1/checkout/ [Idempotency-Key]
  │       └─ orders.services.checkout() [atomic]
  │             ├─ locks cart + inventory
  │             ├─ creates MasterOrder + SupplierOrder(s) + OrderItem snapshots
  │             ├─ creates Delivery address snapshot(s)
  │             └─ reserves inventory and marks cart CHECKED_OUT
  │
  ├─ API-only payment initiation ──> POST /api/v1/orders/<id>/payment/
  │       └─ payments.services.initiate_payment() ──> provider adapter
  │
  └─ provider webhook ──> POST /api/v1/payments/webhooks/<provider>/
          └─ payments.services.confirm_payment()
                ├─ consume reservations
                ├─ order PROCESSING / supplier orders PENDING_SUPPLIER
                ├─ wallets.post_payment_earnings()
                └─ notifications.emit("payment.succeeded")
```

The existing `/shop/cart/`, `/shop/checkout/`, `/shop/orders/`, and `/shop/payments/<id>/` templates are read-oriented pages. They do not invoke the API path shown above.

## D. Feature completeness matrix

| Customer stage | Status | Existing implementation and entry point | Missing or limitation |
|---|---|---|---|
| 1. Authentication | **VERIFIED** | `/login/`, `/register/`; `accounts.views.login_view`, `register_customer`; root redirects customers to `/shop/`. | None required for basic session access. |
| 2. Product browsing | **VERIFIED** | `/shop/`, `/shop/browse/`; `carts.views.browse`; catalog API. | HTML has no search/filter/pagination despite API support. |
| 3. Product details | **VERIFIED** | `/shop/products/<uuid>/`; `carts.views.product_detail`. | Image placeholder rather than rendering images; no purchase action. |
| 4. Add product to cart | **PARTIAL** | `POST /api/v1/cart/items/`; `carts.services.add_item`. | No HTML form/button or JavaScript/API client connects the product page to it. |
| 5. View cart | **PARTIAL** | `/shop/cart/`; `carts.views.cart_page`; `GET /api/v1/cart/`. | Template does not show a computed total or cart item controls. |
| 6. Update quantity | **PARTIAL** | `PATCH /api/v1/cart/items/<id>/`; `update_quantity`. | No UI control; update validation has a stale-instance risk noted below. |
| 7. Remove cart item | **PARTIAL** | `DELETE /api/v1/cart/items/<id>/`. | No remove button or HTML action. |
| 8. Inventory validation | **VERIFIED** at service/API level | `validate_cart`, `checkout`, inventory locking/reservations. | Cart template only warns generically and cannot resolve changed items. |
| 9. Manage delivery addresses | **MISSING** | `CustomerAddress` model exists. | No address CRUD views, forms, serializers, URLs, or selection UI/API. |
| 10. Select delivery address | **PARTIAL** | `_address_snapshot` chooses default address, otherwise first address. | Customer cannot select a specific address at checkout; checkout payload does not accept one. |
| 11. Review order summary | **PARTIAL** | `/shop/checkout/` lists items; backend generates `OrderFinancialLine`. | No authoritative server-calculated review/order total prior to submission; template is placeholder. |
| 12. Checkout submission | **PARTIAL** | `POST /api/v1/checkout/`, `CheckoutView`, `checkout`. | No checkout form/action or client-issued idempotency key. |
| 13. Order creation | **VERIFIED** | `orders.services.checkout`. | No HTML confirmation route/page linked from checkout. |
| 14. Inventory reservation | **VERIFIED** | Atomic checkout creates `InventoryReservation`; expiry command exists. | Command scheduling/operational execution is **UNVERIFIED**. |
| 15. Payment processing | **PARTIAL** | Payment initiation API, demo adapter, webhook processing. | No production adapter, payment-method selection, redirect/instruction UI, or COD flow. |
| 16. Order confirmation | **PARTIAL** | Payment success makes master `PROCESSING`, supplier orders `PENDING_SUPPLIER`; payment status page exists. | No customer confirmation page after checkout/payment initiation; supplier progression is not surfaced to customer HTML. |
| 17. Customer order history | **PARTIAL** | `/shop/orders/`, `carts.views.order_history`; customer order APIs. | List has no detail links; no customer order detail HTML/status timeline. |

## E. Missing UI and backend connections

1. `templates/carts/product_detail.html` only links to `Manage cart`; it has no quantity input or POST to `CartItemsView`. The API can add an item, but a normal customer cannot do it through the supplied HTML.
2. `templates/carts/cart.html` renders item text and a checkout link only. It has no update/remove controls wired to `CartItemDetailView` and does not render calculated totals.
3. `templates/carts/checkout.html` contains the literal disabled control `Continue to payment — coming in Phase 8`. It does not call `CheckoutView`, generate an `Idempotency-Key`, or initiate payment after order creation.
4. There is no address management UI, form, serializer, API view, URL, default-address operation, or checkout address selector despite `CustomerAddress` and `_address_snapshot`.
5. `CheckoutView` is API-only and accepts no request body address selection. The service silently selects default then first address.
6. `templates/carts/orders.html` has no link to `CustomerOrderDetailView`, while that detail view is API-only.
7. `templates/carts/payment_status.html` displays a payment already known by ID but cannot initiate a payment or select a method.
8. No discovered customer HTML is connected to `notifications` for an order-confirmation experience beyond the notification center route.

## F. Existing services that should be reused

No architecture replacement is indicated. The following services are the intended reuse points:

- `apps.catalog.selectors.customer_catalog_queryset()` for every public browse/detail lookup, so only approved products from active suppliers with active inventory and current prices are exposed.
- `apps.catalog.services.is_product_purchasable()` and `current_price_for()` for availability/pricing checks; do not reimplement them in templates, serializers, or views.
- `apps.carts.services.add_item()`, `update_quantity()`, `get_active_cart()`, and `validate_cart()` for cart operations. UI/API adapters should call these services.
- `apps.orders.services.checkout()` for the checkout transaction. It already owns idempotency, final validation, snapshot creation, multi-supplier grouping, and reservation creation.
- `apps.payments.services.initiate_payment()`, `process_webhook()`, `confirm_payment()`, `consume_reservations()`, and `release_reservations()` for online payment lifecycle handling.
- `apps.orders.management.commands.expire_reservations.Command` for releasing abandoned unpaid reservations once an operational scheduler is established.
- `apps.wallets.services.post_payment_earnings()`, `release_settlement()`, and `reverse_refund()` for supplier financial effects rather than adding direct wallet writes elsewhere.
- `apps.notifications.services.emit()` for customer-facing domain notifications after the relevant state transition is determined.

## G. Business rules already established in code

### Cart and availability

- One active PHP cart per customer is enforced by `Cart` constraint `one_active_cart_per_currency`; one line per product is enforced by `unique_cart_product` (`apps/carts/models.py`).
- `add_item()` replaces the quantity of an existing product line rather than incrementing it (`apps/carts/services.py:add_item`).
- Product quantity must be positive, meet product MOQ, and not exceed *currently available* supplier inventory. Adding to cart does not reserve stock.
- Public catalog eligibility requires: supplier approved and operationally active; product approved and public; inventory active and >0; and a current active price (`apps/catalog/selectors.py:customer_catalog_queryset`).
- Cart validation detects archived/unavailable supplier/product, price/currency changes, MOQ breaches, and stock insufficiency.

### Checkout and orders

- Checkout requires an `Idempotency-Key`. A completed matching key returns the existing order; reusing an in-progress key with different cart fingerprint is rejected (`apps/orders/services.py:checkout`).
- Checkout locks the active cart and relevant inventory rows inside `@transaction.atomic`, then validates inventory, supplier/product availability, price/currency, MOQ, and quantity again.
- Checkout requires a delivery address. The established selection rule is default address, otherwise first address; it has no explicit address-ID choice.
- A master order is split into one `SupplierOrder` per supplier. Order item, supplier identity, delivery address, and financial line data are snapshotted.
- Checkout reduces `available_quantity`, increases `reserved_quantity`, creates an `InventoryReservation` expiring after 30 minutes, and records `RESERVATION` movements.
- On success the cart becomes `CHECKED_OUT`. On validation failure, the atomic transaction is intended to leave no order/reservation records; the price-change test verifies that path.
- Monetary fields are stored as `*_minor`; template presentation currently applies `floatformat:-2`, which is not a reliable minor-unit currency formatter.

### Payment, refunds, and financials

- Payment initiation is customer-order scoped and idempotent per payment/idempotency key. It only permits the same provider for an outstanding payment.
- A verified paid webhook consumes active reservations, marks payment/order paid/processing, moves supplier orders to `PENDING_SUPPLIER`, records pending supplier earnings, and emits `payment.succeeded`.
- A failed payment before payment success releases active reservations, marks the master order cancelled/failed, and cancels supplier orders.
- Payment webhook events and payment events have uniqueness constraints to prevent repeated processing.
- Refunds already support one or more `RefundAllocation` rows against a `SupplierOrder` and optionally an `OrderItem`; refunds are capped against paid amount and are idempotent per payment key. The code creates refund records but does not initiate provider refund execution or change order/inventory state.
- Supplier revenue is posted to the `PENDING` wallet bucket after payment. `release_settlement()` currently requires the supplier order to be `COMPLETED`; it does not itself require a customer receipt confirmation.

## H. COD requirement: current behavior, recorded context, and unresolved decisions

### Existing behavior — **VERIFIED**

- `Payment.method_category` is an unconstrained string, so it can store a value such as `COD`, but this alone does not implement cash-on-delivery.
- `initiate_payment()` always requests an adapter payment creation and `get_adapter()` currently supports only the development/test `demo` adapter (`apps/payments/adapters.py`).
- `confirm_payment()` treats a verified `PAID` event as the trigger for inventory consumption, order processing, pending earnings, and the customer payment-success notification.
- No COD-specific model, service, endpoint, template, staff action, delivery evidence, collection event, or automated test was found.

### Recorded project context — not new decisions

Prior project direction identifies COD as an intended launch payment method and indicates customer confirmation before supplier earnings release. These requirements are not reflected end-to-end in the inspected implementation. This report does not redefine them.

### Decisions that remain unresolved before COD implementation

1. Which COD event changes an order from `PENDING_PAYMENT` to confirmed/processable: customer checkout submission, supplier acceptance, dispatch, or another explicit event?
2. When should stock move from reservation to sold for COD: acceptance, delivery, or verified collection? The current online-payment behavior consumes it at payment confirmation.
3. Who records cash collection (supplier staff, customer, operations staff, or carrier), and what evidence/reference is required?
4. Does a customer receipt confirmation control supplier settlement in all cases? If so, what is the timeout, reminder, dispute, or administrative override process?
5. For multi-supplier orders, are collection, delivery, cancellation, and settlement independent per `SupplierOrder`? The model supports this, but the policy must be explicit.
6. How do failed delivery, refusal, partial delivery, return-to-supplier, and cancellation affect reservation restoration, sale movements, payment state, refunds, and settlement reversal?
7. Whether COD has a maximum order value, geography/serviceability restrictions, supplier eligibility, delivery fee treatment, or customer eligibility requirements.

## I. Database or migration requirements

### Current UI completion without new business rules

The existing schema is sufficient for basic address CRUD, choosing an existing address, cart operations, checkout, order history/detail rendering, and online demo-payment connection. Those additions should be assessed against the current models before deciding whether a migration is needed.

### Conditional future requirements

No migration should be designed until the COD decisions in section H are approved. Depending on those decisions, COD may require persisted collection/delivery-proof events, COD-specific payment state/data, settlement eligibility evidence, and cancellation/failure reason records. The exact model boundary is **UNVERIFIED** until the operational policy is set.

`OrderFinancialLine` already carries `line_type`, `source`, `description`, `amount_minor`, `currency`, `calculation_basis`, and `rule_version`; no redesign is indicated merely to explain totals. Current checkout creates only subtotal and total lines because tax, platform fee, discount, and delivery fee are zero.

## J. Implementation risks

| Risk | Evidence | Impact / planning implication |
|---|---|---|
| Customer workflow is API-only after browsing | Templates do not call cart/checkout/payment APIs. | Build thin views/forms or deliberate client integration over existing services; do not duplicate service logic. |
| Address choice is implicit | `_address_snapshot()` chooses default or first address. | A customer could place an order to an unintended valid stored address unless explicit selection is introduced. |
| Reservation expiry is operationally dependent | `expire_reservations` exists but no scheduler integration/test was found. | Unpaid orders can hold stock beyond 30 minutes unless command execution is scheduled and monitored. |
| Stale inventory object during cart quantity update | `update_quantity()` validates `item.product` without re-fetching/locking inventory, unlike `add_item()` and checkout. | UI will need final validation before checkout (already present); consider race behavior during implementation review rather than trusting cart state. |
| Price display can be misleading | Templates use `floatformat:-2` on minor units. | PHP price display should be standardized before customer checkout is exposed. |
| Checkout idempotency race semantics need test coverage | Existing service checks then creates `CheckoutIdempotency`; DB uniqueness protects duplicate keys, but conflict handling is not explicit. | Concurrent duplicate submissions may surface an integrity error instead of an idempotent response. Add focused concurrency/error-path tests when implementing UI. |
| Supplier fulfillment transition is not an exposed customer journey | `transition_supplier_order()` exists but no route/view invokes it was found. | Customer order history cannot show meaningful progression until supplier operational flow is connected. |
| Financial release differs from stated intended customer confirmation | `release_settlement()` only checks `SupplierOrder.status == COMPLETED`. | Do not connect COD settlement until completion/receipt policy is reconciled. |
| Refund foundation is not a complete lifecycle | `create_refund()` records allocations; no provider execution/order state/cancellation UI found. | Do not expose customer refunds as working solely because allocation records exist. |

## K. Recommended implementation sequence

The sequence preserves existing boundaries and makes each visible customer feature use the existing domain services.

1. **Confirm operational decisions first:** approve COD lifecycle, address-selection behavior, payment confirmation definition, supplier-order cancellation/failed-delivery outcomes, and settlement release policy. No schema work before this.
2. **Finish customer account/address capability:** add protected customer address management and default-address behavior, with tests for ownership and selection. Reuse `CustomerProfile` and `CustomerAddress`.
3. **Connect the cart UI:** add product quantity/add action, cart quantity/update/remove actions, error display, and server-side ownership checks. Delegate to `carts.services`.
4. **Add a server-calculated checkout review:** validate cart and selected address; clearly show supplier grouping and financial snapshot values. Maintain the checkout service as the authority.
5. **Connect checkout submission:** issue a per-submission idempotency key and route through `orders.services.checkout()` once only; display the generated master order and next payment action.
6. **Connect approved payment methods:** expose payment initiation/status UI against the provider-agnostic API/service layer. Add a production provider only after provider selection/configuration is approved.
7. **Implement COD only after step 1:** add the minimal state/events and explicit operational controls supported by approved policy; keep it isolated behind the payments/order service boundary.
8. **Complete customer after-purchase experience:** add order detail/status timeline, payment status link, notifications, and policy-approved cancellation/customer receipt actions.
9. **Operational hardening:** schedule and monitor reservation expiry; add focused tests for duplicate requests, provider failures, partial multi-supplier outcomes, refunds, and ledger effects.

## L. Acceptance criteria for the completed customer purchasing workflow

- A customer can register/login and access only their customer purchase data.
- Public browsing exposes only purchasable products from approved, active suppliers with active stock and current pricing.
- A customer can add an eligible product at a valid MOQ, change quantity, and remove it using visible UI controls; server-side validation remains authoritative.
- Cart ownership cannot be bypassed by changing item/order identifiers.
- A customer can create, edit, delete, and explicitly select an owned delivery address; checkout snapshots the selected address.
- The checkout review displays server-derived, PHP minor-unit-safe totals and supplier grouping, and identifies cart validation failures clearly.
- Checkout requires and honors an idempotency key; retrying the same submission returns the original order without duplicate orders or reservations.
- Checkout creates exactly one master order, one supplier suborder per supplier, immutable product/price/supplier/address snapshots, inventory reservations, and auditable movements within the defined transaction.
- Failed or expired unpaid checkout releases reservations and restores available inventory exactly once.
- The customer can select an approved payment method, see its status, and receive confirmation only after the defined payment/collection event.
- COD behavior meets the approved lifecycle decisions for confirmation, collection, delivery, failed delivery/cancellation, stock, and settlement; it is not merely a free-text method category.
- Payment success/failure, refund allocation, wallet pending/available movement, and payout eligibility use the existing financial services and remain auditable.
- Customer order history and order detail show only that customer’s orders and current supplier-order status.
- Automated tests cover normal flow and failure paths: cross-customer access denial, stock/price changes, multi-supplier cart, address selection, checkout idempotency/duplicate submission, reservation expiry, payment webhook replay/failure, and the approved COD scenarios.

## Existing automated-test coverage inspected

- `apps/accounts/tests.py`: registration, session/root routing, account status, password reset, supplier scope.
- `apps/catalog/tests.py`: product/supplier approval prerequisites and inventory movements.
- `apps/carts/tests.py`: public catalog filtering, MOQ/stock validation, price-change validation, customer cart isolation.
- `apps/orders/tests.py`: checkout snapshots/reservations, price-change rollback, idempotent service retries.
- `apps/payments/tests.py`: demo-webhook consumption/replay, invalid signature, payment initiation idempotency, refund allocations/over-refund protection.
- `apps/wallets/tests.py`: pending-to-available settlement and payout reserve/failure release.
- `apps/notifications/tests.py`: recipient-private in-app notification delivery.

Coverage absent or not found includes customer address CRUD/selection, HTML cart/checkout actions, scheduled reservation expiry, full supplier fulfillment transitions, production provider behavior, COD, customer receipt confirmation, failed delivery, and cancellation policy workflows.

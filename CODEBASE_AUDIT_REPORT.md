# CODEBASE AUDIT REPORT

Audit date: 7 November 2026 (Asia/Manila)  
Scope: static source inspection and non-mutating Django checks only. No migrations, database writes, tests, or source fixes were performed for this audit.

## A. Executive Summary

BUILTASUPPLY is a modular Django marketplace prototype with good initial domain separation and meaningful transaction safeguards in checkout, inventory, payments, wallets, and payouts. It has working account registration, role routing, supplier catalog draft creation/editing/submission, custom superadmin user/supplier/item moderation screens, and a DRF API surface.

It is not yet a complete browser-operable marketplace. The most significant gap is the customer purchase flow: product pages have no add-to-cart control, cart and checkout templates do not submit any operations, there is no browser address-management workflow, and checkout explicitly renders a disabled phase-placeholder button. Supplier fulfillment, customer cancellation/receipt confirmation, COD completion, and payout execution are likewise not exposed as usable UI workflows. The deployment configuration is local-development only.

No P0 exploit was proven by static inspection. Several P1/P2 issues prevent the intended marketplace workflow from being completed by real users.

## B. Technology Stack and Architecture

| Area | Evidence |
|---|---|
| Runtime | Django constrained to `>=5.1,<5.3`; observed error pages report Django 5.2.17. Python 3.12.14 was observed in the current virtual environment. |
| API | Django REST Framework `>=3.15,<3.17`; session authentication is the configured default. |
| Database | SQLite by default; PostgreSQL if `POSTGRES_DB` is set (`config/settings.py:21`). |
| Apps | `accounts`, `customers`, `suppliers`, `memberships`, `catalog`, `inventory`, `carts`, `orders`, `payments`, `wallets`, `payouts`, `notifications`, `audit`, `operations`, `integrations`, and `core` (`config/settings.py:13-16`). |
| UI | Server-rendered Django templates, one global inline stylesheet in `templates/base.html`; no organized static JS/CSS directories were found. |
| External boundary | Provider adapter interface in `apps/payments/adapters.py`; integration metadata models in `apps/integrations/models.py`; neither is a completed external integration product. |

The normal flow is intended to be: accounts create customer/supplier identities; suppliers own products and inventory; customers assemble carts; checkout creates master and supplier suborders plus reservation records; payments settle reservations; wallets/payouts track supplier funds; operations moderates users, suppliers, and products. That architecture is present, but the browser UI does not yet connect the whole sequence.

## C. Application and Feature Inventory

| App | Major responsibility | Audit result |
|---|---|---|
| accounts | Custom email user, registration, login/reset, global roles, supplier memberships, account status | Mostly implemented; no browser password-change route and minimal role navigation. |
| customers | Customer profiles and delivery addresses | Models exist; no customer address views, forms, URLs, or templates. |
| suppliers | Supplier organization, staff membership, verification-document metadata | Registration exists; verification upload/review UI absent. |
| catalog | Categories, products, prices, product images, supplier product screens | Supplier create/edit/submit exists; image handling and supplier archiving/detail are absent from UI. |
| inventory | Stock, journaled movements, reservations | Services/API exist; supplier browser stock history/adjustment UI absent. |
| carts | Cart/items and validation | Services/API exist; browser add/update/remove controls absent. |
| orders | Checkout, master/supplier orders, financial snapshots, delivery records | Checkout service exists; browser checkout/order detail/cancel/fulfillment flows absent. |
| payments | Provider abstraction, attempts, webhooks, refunds | Demo flow only; no COD implementation or browser payment flow. |
| wallets/payouts | Ledger, settlement, payout records | Services/API exist; supplier wallet page has no role enforcement at its view layer and no browser payout workflow. |
| notifications | Event/notification records, in-app center, preferences API | In-app center exists; external delivery processing/scheduler is not evident. |
| operations | Superadmin dashboard, users, suppliers, product moderation, audit | Basic custom screens exist; orders/payments/transaction detail workflows absent. |
| integrations | Credentials, mappings, webhooks models | Data boundary only; no request authentication, scope enforcement, or delivery worker. |
| memberships | Tier/benefit/assignment model | Standard assignment occurs at registration; no customer membership management UI. |

## D. Feature Completeness Matrix

| Module | List | Create | View | Edit | Delete/Deactivate | Navigation | Status |
|---|---|---|---|---|---|---|---|
| Accounts | Partial | Complete | Partial profile | Missing password change | Status via admin UI | Partial | PARTIAL |
| Customer addresses | Missing | Missing | Missing | Missing | Missing | Missing | MISSING |
| Suppliers | Complete for admin | Registration complete | Partial | Missing supplier profile edit UI | Approve/reject/suspend partial | Operations dashboard button | PARTIAL |
| Supplier products | Complete | Complete draft form | List only; no own detail view | Complete | Archive API only | Supplier catalog/dashboard | PARTIAL |
| Product moderation | Per-supplier list | N/A | List only | Approve/reject | N/A | Operations → Manage suppliers → Manage items | PARTIAL |
| Product images | Missing UI | Missing UI | Placeholder only | Missing | Missing | Missing | MISSING |
| Inventory | API lists/movements | API adjustment | API only | API adjustment | N/A | No browser entry point | PARTIAL |
| Cart | API list | API add | Browser read-only | API update | API delete | Product page lacks entry | PARTIAL |
| Checkout | Service/API | Checkout API | Browser placeholder only | N/A | Service only | Cart links to disabled checkout | BROKEN |
| Orders/customer tracking | API list/detail; basic list template | Checkout service | API detail only | N/A | Missing cancellation | Partial | PARTIAL |
| Supplier fulfillment | API list only | N/A | No detail UI | Transition service only | Cancellation missing | Missing | MISSING |
| Payments/refunds | Service/API/webhook | API initiation | Browser status only | Provider dependent | Refund creation service only | Missing browser entry | PARTIAL |
| Wallet/payout | API, supplier wallet summary | Payout API request | API and ledger summary | Admin approval service | Failure compensation service | Wallet lacks dashboard link | PARTIAL |
| Notifications | In-app list | Event-driven | In-app list | Preferences API | Read/read-all | No global nav link | PARTIAL |
| Operations users | Complete list/search | N/A | List only | Status change | Deactivate via status | Dashboard button | PARTIAL |
| Operations orders/payments | Dashboard counts/API collection only | N/A | No usable details | Missing | Missing | Missing | MISSING |

## E. Navigation and UI Connectivity

| User Role | Feature | Expected Entry Point | Actual Entry Point | Status |
|---|---|---|---|---|
| Visitor | Landing/register/login | Root page | Root and account URLs | Connected |
| Customer | Browse catalog | Home/shop navigation | `/shop/` and product links | Connected |
| Customer | Add to cart | Product detail | No add-to-cart control in `templates/carts/product_detail.html:1` | Disconnected |
| Customer | Address book | Checkout/account | No URL/template/view found | Missing |
| Customer | Checkout | Cart | `/shop/checkout/`, but disabled button in `templates/carts/checkout.html:1` | Broken |
| Customer | Order detail | Order history | No template link or server view; API only | Disconnected |
| Supplier | Dashboard/catalog | Root role redirect/dashboard | Dashboard → Review catalog | Connected |
| Supplier | Add/edit/submit item | Product list | Add, Edit, Submit buttons in `templates/catalog/product_list.html` | Connected |
| Supplier | Inventory management | Catalog/dashboard | No browser link to inventory API | Disconnected |
| Supplier | Orders/fulfillment | Dashboard | No browser route or button | Missing |
| Supplier | Wallet/payout | Dashboard | Wallet route exists but no dashboard link; payout UI absent | Disconnected |
| Superadmin | Users/suppliers/items | Operations dashboard | Manage users/suppliers → Manage items | Connected |
| Superadmin | Product moderation | Supplier item list | Available for pending items | Connected |
| Superadmin | Orders/payments/audit transactions | Operations dashboard | Audit link exists; no orders/payment detail navigation | Partial |
| All roles | Notifications | Expected header/navigation | Route exists (`/notifications/`), but `templates/base.html` has no link | Orphaned UI |

Additional navigation finding: the base header only displays the brand and sign-out action (`templates/base.html:1`). It supplies no role-aware navigation. Most pages are therefore reachable only through dashboard-specific buttons or manual URLs.

## F. Authentication and Authorization

### Verified controls

- Custom `accounts.User` is the configured `AUTH_USER_MODEL` (`config/settings.py:22`) with CUSTOMER, SUPPLIER, and SUPERADMIN global roles.
- Supplier-scoped roles are represented by `SupplierStaffMembership`; helpers separate catalog, inventory, fulfillment, and finance capabilities (`apps/accounts/permissions.py:14-20`).
- `AccountStatusMiddleware` logs out suspended/deactivated authenticated sessions (`apps/accounts/middleware.py:4-12`).
- Browser POST forms shown in scope include CSRF tokens.
- Supplier product edit/submit queries are scoped by both product ID and supplier (`apps/catalog/views.py:49-50`, `70`), which prevents direct-ID editing of another supplier’s product.
- Operations HTML views use `admin_required` based on authenticated SUPERADMIN role (`apps/operations/views.py:15`).

### Findings

- Supplier dashboard, product-list, and wallet template views require a membership but do not consistently enforce specific staff capability at the view level (`apps/catalog/views.py:13-25`, `77-83`). Product create/edit/submit add `can_manage_catalog`, but wallet page has no `can_view_finance` check. The APIs were tightened, but the server-rendered wallet view is not. **Verified permission inconsistency.**
- `admin_required` uses `user_passes_test`, which redirects unauthenticated/unauthorized browser users to login rather than returning a deliberate 403. This is acceptable Django behavior but should be confirmed against product requirements. **Unverified policy concern.**
- No password-change route/template exists in account URLs (`apps/accounts/urls.py:4`). **Verified missing account-management function.**
- Public registration allows separate customer and supplier flows and does not expose superadmin registration. **Verified.**

## G. Backend and Database Findings

### Strengths

- Checkout locks cart and inventory rows in a deterministic order (`apps/orders/services.py:20-69`), and inventory/wallet/payout services use `transaction.atomic()` plus row locking.
- Constraints cover inventory non-negativity, positive reservations, supplier/product ownership uniqueness, active membership uniqueness, idempotency keys, and webhook/payment uniqueness.
- Checkout snapshots product/supplier/financial data and reserves stock rather than immediately selling it.

### Findings

1. **No COD workflow despite stated launch policy.** Payment initiation defaults to provider `demo` and method `EWALLET` (`apps/payments/api_views.py:13`); order/payment services transition to PAID only after a webhook (`apps/payments/services.py:47-67`). There is no COD payment-state model, customer receipt confirmation, or supplier settlement trigger for COD. This blocks the agreed launch payment flow.
2. **Checkout cannot be completed from the browser.** The service requires an address snapshot (`apps/orders/services.py:14-18`), while customer addresses have no UI. The checkout template does not post to checkout and has a disabled button. This makes the service unreachable through intended customer UI.
3. **Supplier fulfillment state machine is unexposed and incomplete.** `transition_supplier_order()` exists (`apps/orders/services.py:75-79`) but has no URL/UI caller. It updates only `SupplierOrder.status`; it does not synchronize `MasterOrder.status` or `Delivery` records. The transition map does not implement cancellation. 
4. **Reservation expiry command exists but is operationally unverified.** `apps/orders/management/commands/expire_reservations.py` correctly targets expired active reservations for PENDING_PAYMENT orders, but it has no test and no runtime scheduler configuration. `docs/operations.md` describes a five-minute scheduler, but deployment automation is absent.
5. **Potential partial-write defect in supplier item creation/editing.** `product_create` calls product creation then stock movement without wrapping both calls in one outer transaction (`apps/catalog/views.py:37-39`). `product_edit` separately updates fields, price, then inventory (`apps/catalog/views.py:56-59`). Each called service is individually atomic, but a later failure can leave earlier changes committed. **Verified transaction-boundary concern; runtime reproduction not performed.**
6. **Automatic shared-category side effect.** Missing category selection creates a global `General Supplies` category inside a supplier create view (`apps/catalog/views.py:33-35`). This is functional but crosses catalog taxonomy governance into a supplier action without admin review or audit intent.
7. **Price history flow is incomplete.** Supplier edits create a new active price and deactivate the previous one (`apps/catalog/services.py:48-57`), but no UI lists historical prices/effective dates. This is a feature gap, not a corruption finding.
8. **Integration credentials are data models only.** `ExternalSystem`, credentials, references, and webhook subscription models exist, but no authentication middleware, scope checks, outbound delivery worker, or management UI was found. These should not be treated as a launch-ready integration system.

## H. Frontend and Template Findings

- `templates/carts/product_detail.html:1` has no quantity input or add-to-cart form; “Manage cart” does not add the viewed item.
- `templates/carts/cart.html:1` displays cart lines but exposes no quantity update/remove controls, although the API supports them.
- `templates/carts/checkout.html:1` explicitly says payment is a later phase and renders a disabled button. This is a confirmed non-functional checkout UI.
- Currency presentation is inconsistent. `apps/core/templatetags/currency.py` provides `php`, but cart/order/payment/operations templates still use raw `amount_minor|floatformat:-2` in multiple places (for example `templates/carts/orders.html:1`, `payment_status.html:1`, `operations/dashboard.html`). Integer centavo values can therefore appear 100x too large. **Verified.**
- The product image model exists but product detail only renders “Product image”/“Image unavailable”; it never emits an image URL (`templates/carts/product_detail.html:1`).
- The custom admin operations templates provide basic list/search/status actions, but no user/supplier/order details, confirmation dialog for status mutations, filtering by role/status, or pagination on supplier/item screens.
- Most templates are single-line HTML with large inline styles and inline page styling. This is maintainable only at very small scale; it makes accessibility, responsive QA, and reuse difficult. **Maintainability concern.**
- Dashboard page uses raw `<table>` styling but base CSS does not establish table, select, textarea, or focus-state rules consistently.

## I. Testing Coverage

### Inspected tests

Test modules cover accounts, catalog/inventory, carts, orders, payments, wallets/payouts, notifications, operations, and the PHP formatter. The inspected suite includes registration, supplier scoping, catalog draft/edit/submit, cart validation, checkout idempotency, payment webhook idempotency, refund limits, wallet release/payout failure, and operations status/moderation checks.

### Gaps

- No automated browser tests were found.
- No customer address UI/form tests because no such UI exists.
- No browser cart mutation/checkout test because those controls are absent.
- No tests for reservation-expiry command, failed-payment cancellation/release, payment retry after failure, late payment callback, COD, supplier order fulfillment, delivery synchronization, customer cancellation, customer receipt confirmation, or multi-supplier end-to-end fulfillment.
- No tests for server-rendered wallet capability authorization, product image upload/validation, pagination/search behavior, or operations item approval/rejection form validation.
- No PostgreSQL concurrency suite; existing transactional tests run against Django’s configured test backend and are not evidence of PostgreSQL locking behavior.

### Executed checks

| Command | Result |
|---|---|
| `manage.py check --deploy` | Completed with 6 security warnings (below). |
| `manage.py makemigrations --check --dry-run` | `No changes detected`. |

Tests were deliberately not executed in this audit because the scope requested no database-modifying commands and Django tests create a test database.

## J. Critical Issues

| ID | Priority | Module | Issue | Evidence (File/Line) | Impact | Recommended Fix |
|---|---|---|---|---|---|---|
| AUD-01 | P1 | Customer checkout | Browser purchase flow is non-functional. | `templates/carts/product_detail.html:1`, `cart.html:1`, `checkout.html:1`; `apps/orders/services.py:14-18` | Customers cannot add an item, manage quantities, provide an address, or submit checkout. | Build customer address CRUD and connect product/cart/checkout forms to existing services with idempotency. |
| AUD-02 | P1 | Payments/COD | Stated COD launch policy is not implemented. | `apps/payments/api_views.py:13`; `apps/payments/services.py:47-67` | No usable payment completion or settlement sequence for launch policy. | Define COD states, collection/receipt confirmation, supplier earnings timing, and cancellation/late-event behavior. |
| AUD-03 | P1 | Fulfillment | Supplier order state machine has no UI/API transition endpoint and no parent/delivery synchronization. | `apps/orders/services.py:75-79`; `apps/orders/api_views.py:24`; no supplier order template/URL | Suppliers cannot fulfill orders; customers cannot receive accurate delivery progress. | Expose staff-authorized transitions; synchronize master/delivery state; test multi-supplier outcomes. |
| AUD-04 | P1 | Currency | Most templates show minor units as pesos. | `templates/carts/orders.html:1`, `payment_status.html:1`, `operations/dashboard.html:1`; formatter exists in `apps/core/templatetags/currency.py` | Users/admins can see amounts 100x too high. | Apply one minor-unit formatter to every financial template and test rendered output. |
| AUD-05 | P1 | Production security | Current active defaults are development-only. | `config/settings.py:6, 30`; `manage.py check --deploy` warnings W004/W008/W009/W012/W016/W018 | Unsafe for deployment: DEBUG/default secret/no enforced HTTPS or secure cookies/local-memory email. | Require production environment configuration and rerun `check --deploy` until clean. |
| AUD-06 | P2 | Authorization | Supplier wallet template view does not enforce finance role. | `apps/catalog/views.py:77-83`; finance helper at `apps/accounts/permissions.py:20` | A non-finance active supplier staff member may reach wallet data through the browser route. | Apply `can_view_finance` to the HTML wallet view and test it. |
| AUD-07 | P2 | Order expiry | Reservation expiry is not covered by tests or deployment scheduler. | `apps/orders/management/commands/expire_reservations.py`; `docs/operations.md` | Abandoned reservations can remain active if scheduler is not configured. | Add unit/integration tests and provision a real scheduler/monitor. |
| AUD-08 | P2 | Operations | No usable order/payment transaction oversight. | `apps/operations/views.py:17-21`, `api_views.py:26-30` | Admins see counts/audit lines but cannot inspect and resolve transactions in custom UI. | Add paginated order/payment lists and scoped detail views backed by services. |
| AUD-09 | P2 | Supplier catalog | Product image upload/display is absent. | `apps/catalog/models.py:43`; `templates/carts/product_detail.html:1` | Supplier cannot showcase items visually; customers cannot see uploaded images. | Add protected upload validation, product-scoped UI, and rendered primary image. |
| AUD-10 | P2 | Customer accounts | No browser address management or password change. | `apps/customers/models.py:9`; `apps/accounts/urls.py:4` | Checkout prerequisites and routine account self-service are unavailable. | Implement customer address CRUD and authenticated password-change workflow. |
| AUD-11 | P2 | Data consistency | Product create/edit spans multiple independently atomic calls. | `apps/catalog/views.py:37-39`, `56-59` | A stock/price failure can leave a newly created or partially edited product state. | Move composite catalog edits into an outer transactional service. |
| AUD-12 | P3 | Navigation | Global role-aware navigation is absent; notifications and several views are orphaned. | `templates/base.html:1`; `apps/notifications/urls.py:3` | Features require manual URLs or local dashboard knowledge. | Add minimal role-based header/navigation and route tests. |
| AUD-13 | P3 | Maintainability | Dense one-line templates/views and broad `except Exception` handlers. | `apps/operations/views.py:62,81`; many `templates/*.html` | Difficult review/debugging; internal exceptions become user messages. | Format source, handle expected validation exceptions, log unexpected failures. |

## K. Recommended Implementation Roadmap

1. **Critical fixes**
   - Complete the browser cart/address/checkout path.
   - Implement and test COD state/collection/receipt/settlement behavior.
   - Fix all financial minor-unit display paths.
   - Create a deployment settings profile; do not deploy while `check --deploy` warns.

2. **Missing feature completion**
   - Supplier order inbox/detail/transition and delivery tracking.
   - Customer cancellation before supplier acceptance and customer receipt confirmation.
   - Customer address CRUD, order details, and order tracking.
   - Supplier inventory, image, and price-history management.
   - Operations order/payment/refund/payout detail pages.

3. **Navigation and UI improvements**
   - Add role-aware top navigation.
   - Add all expected action buttons and empty/error states.
   - Replace disabled phase wording with either working action or hidden unreleased feature.

4. **Backend consistency improvements**
   - Make multi-step product mutations transactional.
   - Apply finance capability checks to all HTML/API wallet/payout access paths.
   - Standardize error handling and audit-safe structured logging.

5. **Testing and quality improvements**
   - Add end-to-end browser tests for customer, supplier, and superadmin workflows.
   - Cover expiry, failure/retry, late callback, cancellation, fulfillment, and COD paths.
   - Run concurrency tests on PostgreSQL.

6. **Long-term architecture improvements**
   - Use shared cache/background workers for rate limiting, event delivery, and scheduled jobs.
   - Implement integration credential validation/scopes only when exposing third-party APIs.
   - Extract shared template components/styles from one-line templates.

## L. Unverified Items

- Browser behavior, mobile responsiveness, actual link-click journeys, and CSRF behavior were not runtime-tested.
- The active SQLite data, migration application state, and data integrity were not inspected or modified.
- PostgreSQL query behavior, locking, query plans, and concurrent checkout safety were not verified.
- Email, storage, payment providers, outbound notifications, carrier APIs, and backup/restore behavior were not externally tested.
- Actual deployed environment variables, proxy/TLS setup, logging, scheduler, media storage, and secret management were not available for inspection.
- The most recent full test-suite result was not rerun as part of this audit.

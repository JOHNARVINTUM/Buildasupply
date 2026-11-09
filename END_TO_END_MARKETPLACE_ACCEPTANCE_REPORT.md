# End-to-End Marketplace Acceptance Audit

**Audit date:** 9 November 2026 (Asia/Manila)  
**Scope:** read-only source, route, template, and automated-test audit. No business logic, schemas, configuration, or persistent application data were changed.

## A. Executive summary

**Overall assessment: VERIFIED PARTIAL — suitable for controlled acceptance testing, not yet production-ready.**

The primary marketplace journeys are connected and covered by Django tests: customer checkout with online payment and COD, supplier COD fulfillment, independent multi-supplier outcomes, superadmin COD oversight, refunds, wallet settlement, payout behavior, reservation expiry, and core account/address/catalog/cart behavior. Financial mutations are primarily routed through service-layer functions and exercised with idempotency tests.

The important remaining blockers are environmental/operational rather than an identified SQLite test failure: no PostgreSQL concurrency verification, no production payment provider, no approved COD dispute-resolution or debt-recovery policy, and incomplete COD notification templates.

## B. Application and module inventory

| Module | Acceptance status | Evidence |
| --- | --- | --- |
| accounts | VERIFIED COMPLETE | Registration, login/suspension, reset, root routing, and supplier isolation tests in `apps/accounts/tests.py`. |
| customers | VERIFIED COMPLETE | Address ownership/default/snapshot-safe lifecycle tests in `apps/customers/tests.py`. |
| suppliers | VERIFIED PARTIAL | Supplier registration, approval, scoped memberships, and catalog/COD browser flows are tested; staff invitation lifecycle UI is not present. |
| memberships | UNVERIFIED | Used by checkout snapshots; no dedicated browser acceptance tests found. |
| catalog / inventory | VERIFIED COMPLETE | Product moderation, supplier isolation, purchasability, stock journal, and checkout reservation tests. |
| carts | VERIFIED COMPLETE | Browser browse/detail/add/update/remove/multi-supplier/ownership tests in `apps/carts/tests.py`. |
| orders | VERIFIED COMPLETE | Transactional checkout, snapshots, idempotency, expiry command, customer COD, and supplier COD UI tests. |
| payments | VERIFIED COMPLETE on SQLite | Demo payment initiation, signed webhook verification, mismatch/replay handling, reconciliation, refund lifecycle, and COD backend tests. |
| wallets / payouts | VERIFIED COMPLETE on SQLite | Pending/available movement, settlement idempotency, payout reserve/failure tests. |
| notifications | VERIFIED PARTIAL | Private in-app notification test exists; COD lifecycle template/event coverage is absent. |
| audit | VERIFIED PARTIAL | Audit records are created by exercised service workflows; no standalone audit app test module exists. |
| operations | VERIFIED COMPLETE on SQLite | Superadmin user/supplier plus COD visibility, verified return, settlement, and reconciliation tests. |
| integrations / core | VERIFIED PARTIAL | Integration boundary exists; no provider integration beyond DemoAdapter. Core PHP formatting test exists. |

## C. Customer workflow results

| Journey | Status | Evidence |
| --- | --- | --- |
| Registration, login, browsing, product details, cart changes | VERIFIED COMPLETE | `accounts`, `carts`, and `catalog` test suites. |
| Address ownership and checkout address snapshot | VERIFIED COMPLETE | `CustomerAddressViewsTests`, `CheckoutBrowserWorkflowTests`. |
| Checkout price/stock validation and idempotency | VERIFIED COMPLETE | `CheckoutTests` and browser workflow tests. |
| Demo online payment initiation/status | VERIFIED COMPLETE | `PaymentBrowserWorkflowTests`; payment remains pending until verified webhook. |
| COD selection and repeat selection | VERIFIED COMPLETE | `CustomerCODBrowserTests`. |
| COD per-supplier tracking, collection privacy, receipt confirmation, cancellation | VERIFIED COMPLETE | `tests_customer_cod.py`, including multi-supplier confirmation independence. |
| Customer COD notifications | MISSING | `notifications.services.TEMPLATES` has no COD lifecycle event templates. |

## D. Supplier workflow results

| Journey | Status | Evidence |
| --- | --- | --- |
| Dashboard, catalog draft/edit/submit | VERIFIED COMPLETE | Catalog browser tests and supplier dashboard route/template inspection. |
| COD inbox/detail and supplier scoping | VERIFIED COMPLETE | `SupplierCODBrowserTests`. |
| Accept → prepare → ready → dispatch → delivered | VERIFIED COMPLETE | Browser test validates fixed transitions and delivery reference requirement. |
| Cash collection and receipt visibility | VERIFIED COMPLETE | Exact amount/currency/reference and duplicate protection tests. |
| Cross-supplier denial / fulfillment-role enforcement | VERIFIED COMPLETE | Supplier browser and backend COD multi-supplier tests. |
| Supplier A/B independent inventory and settlement | VERIFIED COMPLETE on SQLite | `MultiSupplierCODTests`. |

## E. Superadmin workflow results

| Journey | Status | Evidence |
| --- | --- | --- |
| Operations access protection | VERIFIED COMPLETE | Browser/API operations tests and `admin_required` / `IsSuperadmin` inspection. |
| COD list, investigation detail, failed-delivery review | VERIFIED COMPLETE | `tests_cod_operations.py` and route/template inspection. |
| Verified return | VERIFIED COMPLETE on SQLite | Existing `verify_cod_return` service invoked through POST-only UI; repeated verification does not duplicate release movement. |
| Settlement monitoring/release | VERIFIED COMPLETE on SQLite | Existing `release_settlement` path tested for eligibility and idempotency. |
| Reconciliation review/resolution | VERIFIED COMPLETE on SQLite | Existing resolution paths exposed and tested. |
| Held refund reversal review | VERIFIED PARTIAL | Read-only queue is implemented; no approved recovery action exists by policy. |
| Collection dispute resolution | MISSING BY APPROVED POLICY | Investigation queue exists; there is no approved backend dispute-resolution service or historical-evidence rewrite. |

## F. Multi-supplier and financial integrity results

- **VERIFIED COMPLETE on SQLite:** checkout creates separate supplier orders and reservations; COD completion consumes only the completed supplier order’s reservations; Supplier A settlement does not affect Supplier B.
- **VERIFIED COMPLETE on SQLite:** verified webhooks enforce amount/currency and provider event uniqueness; duplicate callbacks and reservation consumption are tested.
- **VERIFIED COMPLETE on SQLite:** late paid callbacks create durable reconciliation rather than silently fulfilling expired stock.
- **VERIFIED COMPLETE on SQLite:** partial/full refund allocation limits, refund completion idempotency, held reversal behavior, and no-negative-balance safeguards are tested.
- **VERIFIED COMPLETE on SQLite:** reservation expiry is repeatable, supports dry-run, and skips active COD commitments/reconciliation cases as implemented.

## G. Role and authorization matrix

| Capability | Customer | Supplier fulfillment staff | Superadmin | Evidence |
| --- | --- | --- | --- | --- |
| Browse public catalog | Yes | Yes | Yes | Public selectors/views. |
| Cart, checkout, addresses, own orders | Own records only | No | No | Customer ownership helpers/tests. |
| Start online payment / select COD | Own order only | No | No | Payment/COD views plus service ownership checks. |
| Confirm COD receipt / cancel eligible COD | Own supplier order/master order only | No | No | Customer routes and COD service checks. |
| Product/catalog changes | No | Role-scoped | Yes | `can_manage_catalog`. |
| COD fulfillment/collection/exception | No | Exact supplier + fulfillment role | Yes | `can_manage_fulfillment` and COD services. |
| Wallet/payout visibility | No | Finance-role scoped | Yes | Wallet/payout APIs/services. |
| Operations/COD resolutions | No | No | Active superadmin only | Operations decorator, service checks, tests. |

## H. Navigation and UI connectivity findings

**VERIFIED COMPLETE:**

- Root redirects authenticated users by server-side role.
- Customer flow is connected from public browse through cart, checkout, confirmation, payment/COD selection, history, and details.
- Supplier dashboard links catalog and COD orders; COD detail actions are state-gated and POST-backed.
- Operations dashboard links COD orders, failed deliveries/returns, disputes, settlement monitoring, held reversals, and reconciliation.

**VERIFIED PARTIAL / cleanup findings:**

1. `apps.carts.views.checkout_page`, `order_history`, and `payment_status` plus `templates/carts/checkout.html`, `orders.html`, and `payment_status.html` are legacy, unmounted paths. Active routes use `apps.orders` and `apps.payments` equivalents. They are not customer-facing dead links, but should be removed or consolidated in a separately approved cleanup.
2. The supplier wallet page has a route (`/supplier/wallet/`) but no visible supplier-dashboard navigation link was found. Its API and page remain direct-route accessible to authorized users.
3. The notification center has a route but no global navigation link in `templates/base.html`; it is reachable directly and through application links only where provided.

## I. PostgreSQL compatibility

`config/settings.py` selects PostgreSQL only when `POSTGRES_DB` is supplied; otherwise it uses SQLite. No PostgreSQL connection/configuration was available in this audit environment.

**UNVERIFIED on PostgreSQL:** concurrent checkout, expiry versus payment callback, payment initiation, webhook replay races, refund-versus-settlement races, and simultaneous COD collection/receipt completion. SQLite tests validate state transitions and service idempotency but do **not** establish PostgreSQL row-lock correctness.

## J. Regression test execution

Commands executed:

```powershell
& .\.venv\Scripts\python.exe manage.py check
& .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
& .\.venv\Scripts\python.exe manage.py test
```

- `check`: **passed**.
- `makemigrations --check --dry-run`: **No changes detected**.
- Full Django test suite: **passed**; the source includes 106 explicit `test_` methods, with inherited tests increasing executed coverage. No real failures were observed. The reservation-expiry suite deliberately simulates an individual order failure to verify per-order rollback/recovery; that is expected test behavior, not an acceptance failure.
- No tests were skipped by the executed Django suite. PostgreSQL-specific concurrency tests were not executed because PostgreSQL was unavailable.

## K. Critical issues and priorities

| Priority | Finding | Status | Recommended disposition |
| --- | --- | --- | --- |
| P0 before production | PostgreSQL concurrency validation absent. | UNVERIFIED | Provision isolated PostgreSQL and run targeted race tests. |
| P0 before production | DemoAdapter is not a production payment provider. | UNVERIFIED | Select/integrate provider under a separately approved payment rollout. |
| P1 | COD lifecycle notifications absent. | MISSING | Approve event/template policy, then add idempotent operational events. |
| P1 | COD collection disputes cannot be resolved in-app. | MISSING BY POLICY | Approve a resolution state machine; do not add manual corrections. |
| P2 | Legacy unmounted cart views/templates remain. | VERIFIED PARTIAL | Remove or consolidate in a scoped cleanup after regression coverage. |
| P2 | Supplier wallet/notification center lack prominent navigation. | VERIFIED PARTIAL | Add navigation only as a separate UX scope. |

## L. Production-readiness roadmap

1. Provision PostgreSQL staging and execute concurrency/lock-contention acceptance tests.
2. Configure production secrets, HTTPS, allowed hosts, database backup/restore, structured logs, and reservation-expiry scheduler monitoring.
3. Select a Philippine payment provider and implement its verified adapter/webhook contract.
4. Approve COD dispute, exception, and notification policies before implementing new financial actions.
5. Resolve the UI cleanup/navigation findings and conduct a human UAT pass with separate customer, supplier, and superadmin accounts.

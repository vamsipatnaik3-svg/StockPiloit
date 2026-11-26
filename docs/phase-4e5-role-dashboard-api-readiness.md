# Phase 4E.5 — Role-Based Dashboard API Readiness Audit

## Scope and evidence

This is a read-only audit of the repository implementation. No role, endpoint, frontend, database, or migration changes were made. Endpoint paths below include the `/api/v1` prefix registered in `app/main.py`.

The permission findings are based on `app/api/dependencies.py`, the route handlers and their service queries, the membership/branch models, and existing authorization/API tests. A role name is not treated as a permission unless code enforces it.

## Current role and access-control implementation

- `CompanyMembership` links a user to a company and stores one of `OWNER`, `MANAGER`, `STAFF`, or `ANALYST`. A unique company/user pair is enforced. There is no separate permission or analyst-grant model or owner-managed grant endpoint.
- `BranchMembership` assigns a company membership to a branch. Its uniqueness constraint prevents duplicate assignments. The database model itself does not express role policy; route/service code decides when assignments are checked.
- Authentication resolves the session to a `User`. Business routes then resolve a company membership using optional `X-Company-ID`. A user with multiple company memberships must select one; a user without membership is denied. Normal business endpoints also reject users who must change their temporary password.
- `require_roles(...)` is a fixed role allowlist check. It does not automatically apply branch assignments. Each route/service that accepts a branch identifier must enforce branch scope independently.
- `Branch` carries `company_id`, `is_active`, and `timezone`. Branch/company scoping is generally enforced in service queries and composite foreign keys; branch assignment is separately enforced where needed.
- Branch list behavior is role-dependent: OWNER sees company branches (including inactive branches); other roles see only assigned active branches. Branch member details are limited to OWNER or a user assigned to that branch. Only OWNER can create branches, assign/remove members, and create employees.
- Employee creation supports MANAGER, STAFF, and ANALYST, assigns one or more active company branches, sets a temporary password, and requires a first-login password change. There is no team listing, role update, deactivation, or analyst grant API in the inspected team route.
- Existing tests establish that all four roles are recognized; STAFF is rejected on owner-only actions; ANALYST is rejected on operational writes; company membership selection and cross-company denial work; and managers are constrained to assigned branches on branch, upload, and movement operations.

### Important scope distinction

Some APIs enforce company scope only. Others enforce both company and assigned branch, but only for MANAGER. This is endpoint-specific, not a global property of the role. In particular, analytics is currently OWNER-only, so its company-only `validate_branch` check is not presently an access bypass. It would be insufficient if a later change simply allowed MANAGER or ANALYST through the analytics role gate.

## Endpoint inventory

`GET` endpoints below are read-only. Upload processing, stock movement voiding, and import retry are state-changing operations even when they expose status/report information.

| Method and path | Current allowed roles | Scope and branch enforcement | Filters / pagination | Dashboard readiness and gaps |
|---|---|---|---|---|
| `GET /api/v1/analytics/overview` | OWNER | Company; optional branch must belong to company. No branch-assignment check (OWNER sees all). | start/end dates, branch | Ready for Owner. Includes sales KPIs, coverage/freshness dates and supported waste summary; no manager/analyst access. |
| `GET /api/v1/analytics/sales/trends` | OWNER | Company or selected company branch | start/end dates, branch; no pagination | Owner sales trend. |
| `GET /api/v1/analytics/branches/performance` | OWNER | Company; optional company branch | start/end dates, branch; no pagination | Owner branch comparisons. With a branch filter it is scoped; company-wide result is Owner-only. |
| `GET /api/v1/analytics/products/performance` | OWNER | Company or selected company branch | start/end dates, branch; no pagination | Owner product ranking. |
| `GET /api/v1/analytics/inventory/overview` | OWNER | Company or selected company branch | as-of date, branch; no pagination | Owner inventory overview; no manager/staff endpoint. |
| `GET /api/v1/analytics/inventory/expiry` | OWNER | Same as inventory overview | as-of date, branch; no pagination | Shares inventory calculation and currently returns an empty `products` list in the route; expiry drill-down is not implemented there. |
| `GET /api/v1/analytics/waste/overview` | OWNER | Company or selected company branch | start/end dates, branch; no pagination | Owner waste/damage view; no staff recording action. |
| `GET /api/v1/analytics/purchases/overview` | OWNER | Company or selected company branch | start/end dates, branch; no pagination | Owner purchase analytics; no supplier/receipt CRUD or delivery confirmation API. |
| `GET /api/v1/analytics/alerts` | OWNER | Company or selected company branch | start/end dates, branch; no pagination | Owner alerts only. |
| `GET /api/v1/analytics/ingredient-consumption/theoretical` | OWNER | Company or selected company branch | start/end dates, branch, ingredient | Owner-only theoretical consumption; current completed upload versions feed sales data. |
| `GET /api/v1/analytics/ingredient-consumption/actual` | OWNER | Company or selected company branch | start/end dates, branch, ingredient | Owner-only actual stock depletion/consumption; uses stock evidence and coverage status. |
| `GET /api/v1/analytics/variance/intelligence` | OWNER | Company or selected company branch | start/end, branch, ingredient, finding type, severity, status; offset/limit | Owner-only, read-only, paginated; no analyst access grant. |
| `POST /api/v1/products` | OWNER | Writes into membership company | — | Catalogue administration. |
| `GET /api/v1/products` | Any current company member | Company-wide; no branch filter | search, category, active flag, product kind; no pagination | Readable to STAFF and ANALYST across company, not only assigned branches. Verify whether this catalogue breadth is intended for each dashboard. |
| `GET /api/v1/products/categories` | Any current company member | Company-wide | none | Readable to all roles. |
| `POST /api/v1/products/categories` | OWNER | Membership company | — | Owner catalogue administration. |
| `GET /api/v1/products/{product_id}` | Any current company member | Product constrained to membership company | none | Company-scoped read. |
| `PATCH /api/v1/products/{product_id}` | OWNER | Membership company | — | Product updates/classification management. |
| `GET /api/v1/recipes` | Any current company member | Company-wide service query | none | STAFF and ANALYST can read recipes across the company; there is no branch scope. |
| `GET /api/v1/recipes/menu-items/{id}` | Any current company member | Membership company | none | Recipe detail read. |
| `GET /api/v1/recipes/menu-items/{id}/version-for-date` | Any current company member | Membership company | business date | Historical recipe version lookup. |
| `GET /api/v1/recipes/menu-items/{id}/modifier-groups` | Any current company member | Membership company | none | Modifier catalogue read. |
| `POST /api/v1/recipes/menu-items/{id}/versions` | OWNER | Membership company | — | Recipe authoring. |
| `POST /api/v1/recipes/menu-items/{id}/modifier-groups` | OWNER | Membership company | — | Modifier authoring. |
| `POST /api/v1/recipes/modifier-groups/{id}/options` | OWNER | Membership company | — | Modifier option authoring. |
| `POST /api/v1/stock-movements` | OWNER, MANAGER | Company; MANAGER must be assigned to active target branch | — | Authorized manual stock event entry. STAFF and ANALYST denied. |
| `GET /api/v1/stock-movements` | OWNER, MANAGER | Company; MANAGER scoped to assigned branch(es), selected branch checked | type, date, batch, state; limit/offset | Operational history; Owner company-wide, Manager assigned branches. |
| `GET /api/v1/stock-movements/{id}` | OWNER, MANAGER | Company and, for MANAGER, assigned branch | — | Detail read. |
| `POST /api/v1/stock-movements/{id}/void` | OWNER, MANAGER | Same branch checks; only manual movements are voidable | reason in request | Operational correction with actor/time audit. Upload-originated, linked purchase, and transfer movements are rejected. |
| `POST /api/v1/uploads` | OWNER, MANAGER | Company; MANAGER assigned to active branch | branch and business date in form | Upload/import operations. STAFF and ANALYST cannot upload. |
| `GET /api/v1/uploads` | OWNER, MANAGER | Company; list is filtered to MANAGER assigned branches | none; no pagination | Upload health and history. |
| `POST /api/v1/uploads/{id}/process` | OWNER, MANAGER | Upload company plus branch authorization | — | State-changing processing/correction operation. |
| `GET /api/v1/uploads/{id}/processing-status` | OWNER, MANAGER | Upload company plus branch authorization | — | Upload data quality/progress status. |
| `GET /api/v1/uploads/{id}/validation-report` | OWNER, MANAGER | Upload company plus branch authorization | — | Validation details. |
| `POST /api/v1/historical-imports` | OWNER, MANAGER | Every referenced upload is company- and branch-authorized | upload IDs | Historical import is a write/process action, assigned-branch constrained for MANAGER. |
| `GET /api/v1/historical-imports` | OWNER, MANAGER | Company query, then each job is shown only if all its uploads are authorized | no pagination | Manager sees only jobs whose full upload set is within their assignments. |
| `GET /api/v1/historical-imports/{id}` | OWNER, MANAGER | Job company, then each upload authorization checked | — | Job detail; same all-uploads rule. |
| `POST /api/v1/historical-imports/{id}/retry` | OWNER, MANAGER | Same job and upload checks | — | State-changing retry. |
| `GET /api/v1/branches` | Any current company member | OWNER: all company branches. Other roles: assigned active branches. | none | Provides allowed branch list for non-owner UI, but no generic access-control dependency is applied to other APIs. |
| `GET /api/v1/branches/{id}/members` | Any current company member | OWNER: company branch. Others: must be assigned to that branch | — | Exposes branch member names, emails, and roles to OWNER or assigned member; decide if STAFF/ANALYST need this visibility. |
| `GET /api/v1/branches/members/eligible` | OWNER | Company members | — | Owner branch administration. |
| `POST /api/v1/branches` | OWNER | Membership company | — | Branch administration. |
| `POST /api/v1/branches/{id}/members` | OWNER | Branch and target membership must belong to same company | — | Assignment administration. |
| `DELETE /api/v1/branches/{id}/members/{membership_id}` | OWNER | Company branch/member | — | Assignment administration. |
| `POST /api/v1/team/employees` | OWNER | Employee and branch assignments created within company | branch IDs | Owner can create MANAGER/STAFF/ANALYST; no employee directory/update/deactivation endpoint. |

### API capability notes

- There is no independent purchase-line/receipt API. Purchase records are ingested through workbook uploads and summarized by analytics.
- There is no staff stock-count, waste/damage entry, receipt confirmation, or delivery confirmation API. Staff can read products/recipes/branches (under the scopes above), but cannot create operational records.
- `StockTransfer` is represented in the data model and movement ledger, but no transfer creation endpoint is registered. Paired transfer initiation is therefore not dashboard-ready through an API.
- Coverage declarations are imported through workbook processing and consumed by actual-consumption logic. There is no standalone API for daily coverage declarations or explicitly closed/non-operating days.
- There are no API export/report endpoints identified in the inspected routes.
- Inventory expiry currently has no expiry product rows in its route response. A dashboard can consume the current contract, but cannot rely on that route for expiry drill-down.

## Owner dashboard capability matrix

| Capability | Classification | Evidence / limitation |
|---|---|---|
| Company-wide sales and performance | Available now | Owner-only overview, sales trends, branch and product performance, with date filters and company/branch selection. |
| Branch comparisons | Available now | Owner branch performance; data comes from company-scoped analytics. |
| Inventory and stock health | Available now, partial | Inventory overview and actual consumption exist; no configured low-stock thresholds are reported as unsupported by overview, and expiry route currently returns no products. |
| Waste and damage | Available now | Waste overview includes snapshot/ledger reconciliation status and current movement data. |
| Ingredient consumption and variance | Available now | Theoretical, actual and variance APIs, all Owner-only. Coverage/incomplete statuses are represented. |
| Upload and data-quality health | Available now | Upload list/status/validation plus analytics coverage/freshness. Owner has company scope. |
| Product and recipe performance | Available now, partial | Product performance analytics and catalogue/recipe APIs. Recipe performance may not expose all sales/modifier dimensions required by a richer menu analytics UI. |
| Employee and branch administration | Available now, partial | Branch create/list/assign/remove and employee creation. No employee directory, edit, deactivate, or history API. |

## Manager dashboard capability matrix

| Capability | Classification | Evidence / limitation |
|---|---|---|
| Assigned-branch sales and performance | Requires permission or scope change | Analytics endpoints are all OWNER-only. Current branch validator confirms company ownership only; manager assignment filtering must be added before granting access. |
| Assigned-branch inventory | Requires permission or scope change | Inventory analytics are OWNER-only. |
| Waste and damage | Requires permission or scope change | Waste analytics are OWNER-only. |
| Ingredient consumption and variance | Requires permission or scope change | All three endpoints are OWNER-only; branch assignment needs enforcement in data query and request validation. |
| Stock movements | Available now | Manager can create/list/detail/void manual events in assigned branches; page supports date/type/batch/state and pagination. |
| Purchases and receipts | Available with frontend-only change for current analytics; operational actions not supported | Owner-only purchase overview cannot be called by managers; there is no receipt confirmation API. Workbook upload is available to assigned-branch managers. |
| Upload and data-quality health | Available now | Upload list and per-upload validation/status; branch assignment enforced. Historical import is allowed on assigned uploads. |
| Staff activity and operational actions | Not yet supported | No staff activity feed/audit endpoint or manager endpoint for routine stock counts/receipt confirmation. Employee administration remains Owner-only. |

## Staff dashboard capability matrix

| Capability | Classification | Evidence / limitation |
|---|---|---|
| Assigned-branch operational information | Available with frontend-only change, limited | Branch list returns assigned active branches; product and recipe read APIs are currently company-wide. No assigned-branch operational summary endpoint exists. |
| Stock counts | Not yet supported | No stock-count write endpoint; inventory snapshots arrive through uploads performed by OWNER/MANAGER. |
| Waste and damage recording | Not yet supported | No staff write endpoint; analytics are OWNER-only and stock movement API denies STAFF. |
| Receipt/delivery confirmation | Not yet supported | No standalone receipt/delivery endpoint; purchase lines arrive through workbook uploads. |
| Relevant product and ingredient information | Available with frontend-only change, with scope decision | Product API includes company catalogue and product kind; no branch-level catalogue availability/information restriction. |
| Restrictions on financial/company-wide information | Requires permission or scope change | Analytics are blocked by OWNER-only gates, but product/recipe read APIs and branch-member detail API are available company-wide or to assigned branch. No field-level permission model exists. |

## Analyst dashboard capability matrix

| Capability | Classification | Evidence / limitation |
|---|---|---|
| Read-only company analytics | Requires permission or scope change | Analyst is rejected by all analytics route role dependencies. No owner-controlled analytics grant exists. |
| Explicitly authorized branch analytics | Requires permission or scope change | No branch analytics grant representation or dependency exists. Current branch assignment is not an analyst analytics grant. |
| Historical trends and comparisons | Requires permission or scope change | Trend and period comparison APIs exist but are OWNER-only. |
| Sales, inventory, waste, consumption analysis | Requires permission or scope change | APIs exist but are OWNER-only. |
| Variance intelligence and data quality | Requires permission or scope change | API exists, paginated and filtered, but is OWNER-only. |
| Export/reporting | Not yet supported | No export endpoint was found. |
| No operational writes | Available now | Analyst is not permitted to upload, author products/recipes, or create/void stock movements. However, no explicit read-only grant model exists. |
| Catalogue/recipe reads | Available now, scope may be too broad | Analyst can read company-wide products, categories, recipes, and modifiers. This is read-only but broader than a branch-specific analytics grant. |

## Proposed permission matrix (recommendation only)

Use role, company membership, branch assignment, and explicit grant as separate checks. Do not infer analytics permission from a role label alone.

| Role | Company-level permission | Branch scope | Recommended allowed capabilities |
|---|---|---|---|
| OWNER | Full access for their company | All company branches | Company analytics/admin; catalogue and recipe writes; upload lifecycle; stock movement create/void; employee and branch administration. Company boundary remains mandatory. |
| MANAGER | Operational access only | Explicitly assigned active branches | Branch analytics only if approved; uploads/corrections and historical imports only for assigned branches; movement create/void only for assigned branches. No company-wide comparison or employee/recipe/catalogue administration by default. |
| STAFF | Operational access only | Explicitly assigned active branches | After business approval, narrow task APIs such as stock count, waste/damage entry, or receipt confirmation. No analytics, financial aggregates, user/member directory, or cross-branch reads by default. Current implementation has no such writes. |
| ANALYST | Read-only analytics access only when explicitly granted | Company-wide or a specific set of branches per grant | Read only the analytics and data-quality surfaces covered by a current Owner grant; no catalogue/recipe writes, uploads, purchases, movement create/void, or employee administration. Do not assume financial details or employee data are included in “read-only.” |

### Permission design guidance

- Keep membership role checks as a coarse operational policy. Add explicit grant records only if approved; a grant should identify company, subject membership, permitted capability family, scope (company or branch IDs), granting Owner, and audit timestamps/revocation.
- Company scoping must remain applied in every query even when the user has an explicit grant.
- Branch access must be evaluated for every requested branch and also for unfiltered/list queries. A `branch_id` validation alone is not sufficient if omitted branch means all branches.
- Separate analytics permissions from operational-write permissions. A read-only analyst grant should not permit access to product/recipe writes, staff/member details, or stock actions.
- Avoid returning emails and role membership data to staff/analysts unless the dashboard explicitly needs it.

## Missing capabilities and verified audit findings

1. **Manager assigned-branch analytics is absent.** Every analytics endpoint uses `require_roles("OWNER")`. Analytics branch validation checks company ownership, not `BranchMembership`.
2. **Owner-controlled analyst analytics access is absent.** There are no grant models, grant routes, or grant-aware dependencies. ANALYST is a valid membership role and can be created by Owner, but cannot call analytics APIs.
3. **Staff stock count, waste/damage, and receipt actions are absent.** Staff cannot create stock movements and there is no dedicated staff count/waste/receipt route.
4. **Stock transfer creation API is absent.** The model supports `StockTransfer` and paired movement concepts but no route is registered.
5. **Closed-day/non-operating-day declarations are absent.** Workbook coverage declares stock evidence; there is no endpoint or identified explicit business-day calendar/declaration API for a branch with no operation/upload.
6. **Purchase receipt management is absent as a direct operational API.** Purchase lines are workbook-originated, while managers can only upload/process workbooks for assigned branches.
7. **Employee management is incomplete for ongoing administration.** Owner can create employees and assign initial branches; no list/update/deactivate/role change route is present in `team.py`.
8. **Potential read-scope overbreadth exists.** Product and recipe reads are company-wide for every company member. Branch member listing is available to an assigned member and returns member identity/contact data. This is implemented behavior, but whether it is intended for STAFF/ANALYST requires an explicit decision.

## Tenant and branch isolation risks

- **Analytics extension risk:** Current OWNER-only gates prevent managers/analysts from using analytics. If roles are broadened without query-scope changes, `validate_branch()` only checks that a selected branch belongs to the company; it does not check manager assignment or analyst grant. For `branch_id=None`, analytics deliberately aggregates company data.
- **Grant scope risk:** There is no current grant abstraction. An analyst role alone currently grants no analytics access. Using `role == ANALYST` as the new access rule would unintentionally give every analyst company-wide access.
- **Generic reads:** Product, category, recipe, modifier, and recipe-version reads use membership/company filtering but not branch membership. This is tenant-isolated, but not branch-isolated.
- **Branch roster exposure:** Non-owner branch member listing requires assignment to the branch, but it still exposes names, emails, and roles to MANAGER, STAFF, and ANALYST assigned there.
- **Membership selection:** `X-Company-ID` is required when membership is ambiguous. APIs must consistently use the resolved membership, never a company ID supplied only in a query or body as the tenant authority.
- **Current protections that should be retained:** Analytics service queries are company-scoped; product and recipe services query by the membership company; uploads and stock movements check manager branch assignments; historical import detail/retry validates every contained upload for the caller.

## Recommended implementation sequence (future approval required)

1. Decide staff operations and analyst scope/content, especially whether financial analytics and branch roster/contact data are permitted.
2. Define an explicit, minimal analyst analytics grant and revocation model, including company versus branch scope and audit behavior; add tests before enabling analyst routes.
3. Create a reusable branch-scope authorization dependency/query helper that handles both explicit branch filters and unfiltered collections. Apply it before permitting MANAGER analytics.
4. Add manager analytics access endpoint-by-endpoint, with tests for assigned branch, unassigned branch, omitted branch filter, cross-company branch, and multiple assigned branches.
5. Add analyst read-only analytics access only through the explicit grant; keep operational APIs excluded and test revocation immediately denies access.
6. Implement staff operational APIs separately with narrow task permissions and audit provenance (counts, waste/damage, receipt confirmation only after business rules are approved).
7. Add stock transfer APIs and paired-event atomicity tests if transfers are in dashboard scope.
8. Add closed/non-operating day coverage declarations and define their effect on analytics completeness before exposing “no activity” as zero.
9. Add missing employee lifecycle/report/export APIs only if the approved dashboard requires them. Preserve company/branch scoping and pagination on list/detail surfaces.
10. Run authorization isolation, API contract, existing regression, and frontend integration tests before exposing each dashboard role.

## Open business decisions requiring approval

- Should MANAGER access sales revenue, purchase costs, actual consumption, and variance findings for assigned branches, or only operational metrics?
- Should an ANALYST grant default to full-company scope, require branch-by-branch scope, or allow either? Who can grant/revoke and is grant expiry needed?
- Which analytics fields may ANALYST see: revenue/prices/costs, employee data, supplier identity, and movement reasons?
- Should STAFF see any financial values, recipes, company-wide catalogue entries, or branch member information?
- Which staff actions are in scope first: physical stock count, waste, damage, staff consumption, or receipt confirmation? Which require manager approval?
- Should managers see jobs spanning multiple assigned branches only when every branch is assigned (current behavior), or should the response be filtered to their visible uploads?
- What is the authoritative representation of a non-operating day, and should it be distinguished from a missing upload for coverage and trends?
- Should purchase receipt confirmation be a separate user action, or remain an upload-derived fact? What fields/approval/audit are required?
- Are product/menu-item and recipe reads deliberately company-wide for all roles, or should some be branch-limited or hidden from STAFF/ANALYST?
- Does the dashboard require employee listing and lifecycle management beyond Owner-only employee creation?

## Verification

No code or permission changes were made. Relevant existing tests are in `backend/tests/test_authorization.py`, `test_analytics.py`, `test_branches.py`, `test_stock_movements_api.py`, and `test_team.py`. `git diff --check` was run after writing this audit; result: clean.

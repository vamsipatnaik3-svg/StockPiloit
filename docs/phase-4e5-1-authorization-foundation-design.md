# Phase 4E.5.1 — Authorization Foundation Design Audit

## Purpose and status

This report separates verified current behavior from proposed design. It is a read-only design audit; proposed grants and branch-scope behavior below are not implemented. No code, migrations, or database data were changed.

The initial `git status --short` was recorded before inspection. The workspace already contained modified and untracked backend, frontend, migration, test, template, and documentation files. Those were preserved. The only file created for this task is this report.

## 1. Existing authorization architecture (verified)

### Identity, membership, role, and branch

- `User` is the authenticated identity. Session-cookie resolution lives in `app/api/dependencies.py` and `app/services/authentication.py`.
- `CompanyMembership` links one user to one company and contains the role string. Its database check constraint and `VALID_ROLES` both recognize `OWNER`, `MANAGER`, `STAFF`, and `ANALYST`. `(company_id, user_id)` is unique. Role is not currently a Python enum.
- `BranchMembership` links a company membership to a branch, with a unique `(branch_id, company_membership_id)` constraint. It does not itself grant any particular API capability.
- `get_current_membership` resolves membership from the authenticated user and optional `X-Company-ID`. If multiple memberships exist and no company is selected, it returns 409; a foreign company selection returns 403. Normal business routes block users who must change their temporary password.
- `require_roles(...)` checks only the resolved membership's role. It does not enforce branch assignment, access grants, or service-query scope.
- OWNER branch listing includes all company branches. Other roles receive assigned active branches. Branch service methods also check assignment for manager access to branch-member records. Branch assignment is not applied automatically in other routes.
- Owner-only employee creation can create MANAGER, STAFF, or ANALYST memberships and initial branch assignments. No analyst access grant is created by employee creation. There is no employee update or role-change route in `team.py`.

### Current role behavior

| Role | Verified current capabilities |
|---|---|
| OWNER | All company analytics and company branch administration; product/recipe authoring; upload/import; stock movement create/list/detail/void; employee creation. Queries remain company-filtered. |
| MANAGER | Assigned-branch upload and historical-import operations; assigned-branch manual stock movement operations; assigned branch and member reads. All analytics are denied. No product/recipe, employee, branch, or analyst-grant administration. |
| STAFF | Can use membership-protected read APIs such as branch, product, and recipe reads; no analytics, uploads, or movement writes. No count, waste/damage, or receipt operation API exists. |
| ANALYST | A valid membership role, but all analytics routes are denied. Read-only catalogue/recipe APIs are currently accessible company-wide. No owner-controlled grant exists. Operational writes are denied by current role allowlists. |

### Company isolation and branch checks

Company scope is resolved from membership, then repeated in product/recipe/analytics/service queries and in several composite foreign keys. This protects tenant isolation when call sites use the resolved membership's `company_id`.

Branch enforcement is endpoint-specific. Uploads and stock movements explicitly check a MANAGER's `BranchMembership`; branch listing filters non-owners to assigned active branches. Analytics currently permits only OWNER and checks a supplied branch belongs to the company. `validate_branch()` does not check assignment; this is safe under its current OWNER-only caller set, but unsafe as the sole check if a manager or analyst is admitted later.

## 2. Current analytics endpoint inventory (verified route → service/query)

Every endpoint below is registered under `/api/v1/analytics`, currently has `Depends(require_roles("OWNER"))`, and is read-only. Optional `branch_id` is a single UUID; `_filters()` validates company membership for that branch and passes that optional UUID to service code. With no branch ID, these queries aggregate company-wide. No analytics route currently has pagination except variance intelligence.

| Method/path | Date/input filters | Current aggregation/query scope | Cross-branch or history exposure if scope is broadened |
|---|---|---|---|
| `GET /overview` | start/end, branch | Sales KPI, active branch count, waste summary, freshness; company-wide unless branch supplied. Current completed upload filtering in sales/snapshot helpers. | Every source query and active-branch count must use the resolved allowed branch set. Previous-period KPI and freshness must use the same set. |
| `GET /sales/trends` | start/end, branch | Revenue grouped by daily/weekly/monthly buckets; current completed uploads; current and previous revenue comparison. | Both trend points and previous-period comparison must use exactly the authorized branch scope. |
| `GET /branches/performance` | start/end, branch | Groups sales by Branch; prior-period branch totals and transaction counts are also queried. | Explicit peer comparison must be limited to allowed branches. Branch filter currently narrows a single branch; no manager assignment check exists. |
| `GET /products/performance` | start/end, branch | Product sales aggregates; current completed upload sales filters. | Product ranking and previous/current comparisons must never include an ungranted branch. |
| `GET /inventory/overview` | as-of date, branch | Inventory snapshot aggregates; current completed upload filtering. | Company-wide snapshot result must be constrained to branch scope. |
| `GET /inventory/expiry` | as-of date, branch | Calls inventory overview then currently returns an empty `products` list. | Same scope requirement; expiry drill-down is currently incomplete. |
| `GET /waste/overview` | start/end, branch | Snapshot and stock-movement evidence; service reconciles the data and reports ambiguity/completeness. | Snapshot rows, ledger rows, coverage, and company totals must all use the same authorized branch scope. |
| `GET /purchases/overview` | start/end, branch | Purchase summaries from current completed upload versions. | Must constrain purchase lines to the same scope; no direct purchase editing endpoint exists. |
| `GET /alerts` | start/end, branch | Builds stock/sales alerts from analytics data and current evidence. | Each source query and alert grouping must share the scope; aggregate alerts can leak out-of-scope branch labels/counts. |
| `GET /ingredient-consumption/theoretical` | start/end, branch, ingredient | Route calls `load_theoretical_inputs`; loader selects upload scopes and sales under optional single branch and current completed upload IDs, then loads recipe/modifier data. | Current sales, scope completeness, unresolved sales, and every recipe-derived item must use the same authorized branch scope. |
| `GET /ingredient-consumption/actual` | start/end, branch, ingredient | Calls actual loader for branches, products, uploads, snapshots, purchases, movements, transfers, and theoretical inputs. Loader with no branch selects all company branches. | All actual evidence, paired transfer legs, current uploads, and theoretical inputs must follow scope; transfer validation may need both legs internally without exposing or counting the unauthorized counterpart. |
| `GET /variance/intelligence` | start/end, branch, ingredient, type, severity, status; offset/limit | Calls variance service; current period and historical comparison windows use `_period_data`, actual/theoretical loaders; branch peer findings are generated where branch is omitted. | Critical risk: both current and every historical baseline query, comparison-period selection, branch peer set, totals, and paginated findings must use the exact same allowed branch set. A scoped current query with unscoped baseline still leaks. |

### Query-layer finding

Route authorization alone is not sufficient. Analytics services accept a `branch_id: UUID | None` or pass `None`; `None` intentionally means all company branches. The actual and theoretical loaders also accept the optional UUID and interpret `None` as all branches. Variance intelligence repeatedly invokes these loaders for historical windows and can generate peer findings. A future scoped API should pass an immutable, already-resolved scope object into every analytics service and loader, not pass an untrusted optional branch parameter as the only scope control.

Existing analytics filters generally enforce `company_id` and current completed upload state. This is a useful tenant and data-version boundary, but it does not represent authorization to a subset of branches.

## 3. Proposed minimal Analyst grant model (not implemented)

### Grant belongs to company membership

Bind the grant to `CompanyMembership`, not `User`. A user can have memberships in multiple companies; role, company, and assignments belong to each membership. A grant attached to the company membership cannot accidentally carry across companies. At authorization time, require that the membership still has role `ANALYST` and that its grant is active.

### Proposed tables

**`analyst_analytics_grants`** (immutable grant identity except revocation):

| Column | Proposed type | Purpose |
|---|---|---|
| `id` | UUID primary key | Grant record. |
| `company_id` | UUID not null | Tenant scope; also supports composite integrity. |
| `analyst_membership_id` | UUID not null | The membership being granted access. |
| `granted_by_membership_id` | UUID not null | The OWNER membership that created the grant. |
| `scope_type` | short string/check: `COMPANY` or `BRANCHES` | Explicitly distinguishes company-wide and selected-branch access. |
| `created_at` | timezone-aware timestamp, server default | Audit creation time. |
| `revoked_at` | nullable timezone-aware timestamp | Null means active; non-null means revoked. |
| `revoked_by_membership_id` | nullable UUID | Owner who revoked; null iff active. |

**`analyst_analytics_grant_branches`** (normalized branch set):

| Column | Proposed type | Purpose |
|---|---|---|
| `grant_id` | UUID not null | Parent grant. |
| `company_id` | UUID not null | Composite tenant consistency. |
| `branch_id` | UUID not null | Branch covered by a selected-branch grant. |

Use `(grant_id, branch_id)` as the primary/unique key. Grant rows should be historical: revoke, then create a new grant to change scope. Do not edit an old grant's branch set. This makes audit history unambiguous.

### Proposed integrity rules

- Add a unique candidate key on `(company_id, id)` to `company_memberships` if needed for composite foreign keys. Use composite `(company_id, analyst_membership_id)` and `(company_id, granted_by_membership_id)` references to membership. The existing model's membership ID is globally primary, but composite references enforce tenant consistency at the database boundary.
- Add/retain branch candidate key `(company_id, id)` on `branches` (the current Branch model already declares this uniqueness). The branch rows reference `(company_id, branch_id)` on the grant-branch table, making cross-company selected branches impossible.
- Add a composite `(grant_id, company_id)` unique key on grants and reference it from grant branches, or use a direct composite grant FK with equivalent integrity.
- Check `scope_type IN ('COMPANY','BRANCHES')`; check revocation fields are either both null (active) or both non-null (revoked).
- Add partial unique index permitting at most one active grant per analyst membership: unique `analyst_membership_id` where `revoked_at IS NULL` (company ID may be included defensively).
- Enforce analyst target role, owner creator/revoker role, creator company match, and branch-grant shape in the transactional service. SQL FKs do not prove membership role. Require `BRANCHES` to have at least one branch row and `COMPANY` to have none; because a standard check cannot count child rows, enforce transactionally or with a deferred constraint trigger if hard database-level enforcement is required.
- Reject duplicate branch IDs in requests and rely on the child-table primary/unique key as a second guard.
- Creation/revocation endpoints must be OWNER-only and must operate on a target membership within the actor's company. MANAGER must never be authorized by an incidental branch assignment.

No generic permission table or arbitrary capability strings are needed for this policy.

## 4. Proposed reusable branch-scope authorization (not implemented)

### Resolution result

Resolve one trusted `BranchAccessScope` for each request after user, membership, role, and any applicable active grant are loaded. Suggested immutable fields:

- `company_id`
- `principal_membership_id`
- `role`
- `scope_kind`: `COMPANY` or `BRANCH_SET`
- `allowed_branch_ids`: the resolved set for the request
- optional audit source/grant ID

OWNER resolves to every branch in the membership company. MANAGER and STAFF resolve to active `BranchMembership` rows for that membership. ANALYST resolves from exactly one active owner-created grant: COMPANY means all company branches; BRANCHES means exactly the grant's branch children. A missing, revoked, role-inconsistent, or empty grant denies analytics.

Role grants capabilities; company membership identifies tenant; branch memberships or grant identify branch set. These are independent checks. A manager's assignment is not an analyst grant, and an analyst grant is not an operational capability.

### Request resolution rules

| Request shape | Proposed behavior |
|---|---|
| One branch ID | Validate it belongs to `company_id` and is contained in `allowed_branch_ids`. If not, reject the entire request (use a consistent 404/403 policy that does not expose branch existence). Never silently widen or partially serve. |
| No branch filter | Resolve to the caller's entire authorized branch set. For MANAGER this is assigned branches only; for selected-branch ANALYST it is grant branches only. Empty allowed set denies or returns a deliberately empty response, never “all branches.” Prefer explicit 403 for no usable access. |
| Multiple branch IDs | Normalize/reject duplicates, validate every ID against company and allowed set, and reject the whole request if any is invalid/ungranted. Do not intersect silently, because partial success can hide a mistaken request and inconsistent totals. |
| Company-wide aggregation | Only OWNER or active COMPANY-grant ANALYST can receive it. Derive IDs from all branches for the authorized company and explicitly apply them. `branch_id=None` must not be interpreted downstream as proof of company-wide permission. |
| Branch-level aggregation | Apply the same allowed branch set to every source query before grouping. Return labels/rows only for included branches. |
| Cross-branch/peer comparison | Compare only branches in the resolved set. A manager can compare assigned branches only if the dashboard policy explicitly permits peer comparisons within that set. Selected-branch analyst comparisons use only granted branches. |
| Historical baseline | Reuse the exact same immutable scope for current and every prior period. Never resolve a broader scope for baseline or “comparison” queries. |

### Enforce at route and service/query boundaries

1. Route dependency resolves role capability and `BranchAccessScope`; endpoint validates all user-supplied branch parameters against it.
2. Pass the scope object into service functions/loaders. Remove or deprecate the pattern where an optional `branch_id=None` is the only authorization input.
3. Provide one query predicate/helper that requires a branch column and emits `column.in_(scope.allowed_branch_ids)` plus `company_id == scope.company_id`. A company-wide scope still emits both predicates.
4. Apply it to sales, branches, products, inventory snapshots, purchases, stock movements, coverage, sales uploads, theoretical inputs, actual inputs, data-quality issues, and freshness queries.
5. Audit queries that infer totals or peer groups after materializing rows in Python as well as SQL aggregates.
6. Variance intelligence must pass the same scope to current analysis, every baseline window, branch peer metrics, totals, and pagination/count calculation. No query helper should independently turn missing branch ID into an all-company scan.
7. Transfers may require loading the counterpart leg to verify the pair, but unauthorized branch facts must not appear in result rows or be counted as consumption. Company-level netting is available only under full company scope.
8. Apply authorization in service entry points too, or make scoped query APIs require a `BranchAccessScope` that cannot be constructed from an untrusted request. This protects non-route callers and future background jobs.

## 5. Proposed role-wise access matrix

| Capability | OWNER | MANAGER | STAFF | ANALYST |
|---|---|---|---|---|
| Company boundary | Own company | Own company | Own company | Own company membership and active grant |
| Branch scope | All company branches | Assigned active branches | Assigned active branches | Company grant or selected granted branches |
| Sales/inventory/waste/consumption/variance analytics | Yes, company or one branch | Approved metrics, only assigned branch set | No financial/company analytics | Read-only analytics only within active grant; field groups require decision |
| Product/recipe read | Existing broad company read; consider tightening | Existing broad company read; consider tightening | Existing broad company read; confirm decision | Existing broad company read; confirm decision |
| Product/recipe writes | Yes | No | No | No |
| Upload/history correction | Yes, company | Assigned branch only | No | No |
| Stock movement create/void | Yes (existing) | Assigned branch (existing) | No unless separately approved | No |
| Planned stock count, waste/damage, receipt confirmation | Owner can supervise/administer as designed | Operationally manage assigned branches after APIs approved | Narrow assigned-branch actions after APIs approved | No |
| Branch/employee administration | Yes | No | No | No |
| Analyst grant create/revoke | Yes, own company | No | No | No |
| Export | Not presently implemented | Not presently implemented | No | Future explicit read-only grant decision |

The STAFF and MANAGER future capabilities in this table are recommendations from the approved policy in the brief, not current API behavior. Staff manual stock movement creation remains excluded unless separately approved.

## 6. Migration and compatibility assessment

- A new grant table is required; the current schema has no persisted representation of Owner-authorized Analyst access. Role alone is insufficient because the policy allows company-wide or selected-branch access per analyst.
- A grant-branch child table is the smallest normalized representation of a selected set and gives database-enforced company/branch consistency. A comma-separated branch list or JSON field would weaken referential integrity and make revocation/scope queries harder to validate.
- Existing membership and branch-assignment rows need no data migration. Do not auto-grant current analysts. Existing ANALYST users remain without analytics permission until an Owner explicitly grants it.
- Migration should be additive: create grant tables/indexes/constraints and any necessary composite candidate keys only. It should not alter roles, assignments, sessions, uploads, or analytics data.
- Existing API paths and response contracts can remain compatible. New owner grant/revoke routes and grant-aware analytics authorization are additive. Existing OWNER results should remain the same. Manager/Analyst access is a deliberate permission expansion and should be endpoint-scoped with tests before release.
- The migration should not synthesize active grants. No downgrade should delete grant history silently; downgrade safety and retention policy should be documented before implementation.
- Repository script inspection confirms current single Alembic head is `8e010cafe004`, with `7e010cafe003 -> 8e010cafe004`. This is repository metadata from `.venv/bin/alembic heads`; no database connection/current revision was queried and no migration was applied.

## 7. Security risks and mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| Missing branch filter becomes company-wide | Existing services interpret `None` as all company branches. | Resolve omitted filters to authorized IDs and always inject explicit scope predicates. |
| Unassigned IDs accepted via URL/query | Company ownership check alone does not prove caller assignment/grant. | Validate every requested ID against both company and allowed set; reject whole request. |
| Multiple IDs cause partial leak | Filtering to visible subset can hide unauthorized input while returning data. | Validate complete list before querying; reject if any unauthorized. |
| Aggregates leak hidden branches | Sum can include out-of-scope values without returning branch rows. | Apply scope before aggregate/group-by; test totals and row groups. |
| Peer comparison leaks competitor branch | Branch performance and variance can reveal peer results. | Generate peers only from authorized branch set. |
| Variance baseline crosses scope | Historical values can influence explanations/anomaly status and reveal historical activity. | Pass identical scope into every baseline period and peer calculation. |
| Actual consumption transfer validation | Pair integrity may need both branch legs; naively exposing both can cross scope. | Internally validate pair, return only authorized scope, and exclude company-level netting for branch grants. |
| Stale grant survives role change | ANALYST grant could become active again if membership role changes back. | Check role on every request and revoke grants in any future role-change transaction; there is currently no role-change endpoint. |
| Grantor/branch cross-company references | Application-only checks can be bypassed by future code paths. | Composite FKs for membership and branch company pairs; transactional service checks Owner role. |
| Regrant conflicts/history loss | Updating old scope erases auditability or ambiguous active state. | Immutable grant scope, revocation row, new grant for changes, partial unique active grant constraint. |
| Sensitive read-only data | “Read-only” can still expose revenue, supplier, staff, and branch identity data. | Define field families and API allowlist per grant; read-only does not equal unrestricted. |

## 8. Security and regression test matrix

Each case should run through HTTP routes and, for relevant analytics, direct service/query tests so authorization cannot be bypassed below the route layer.

| Test case | Expected result | Risk protected |
|---|---|---|
| OWNER queries all company branches with no filter | Success; company-only data and all company branches | Preserves intended owner company-wide access while preventing cross-tenant reads |
| MANAGER queries one assigned branch | Success; only that branch's rows/totals | Valid manager workflow |
| MANAGER requests unassigned branch ID | 403/404; no data | IDOR across branches |
| MANAGER omits branch filter | Only assigned active branches included; no company-wide values | Unsafe `None` means all behavior |
| MANAGER supplies multiple branches, all assigned | Success only if multi-branch operation is explicitly allowed; aggregate limited to set | Multi-assignment workflow |
| MANAGER supplies multiple branches including one unassigned | Entire request rejected; no partial response | Partial intersection leakage |
| ANALYST with COMPANY grant queries all branches | Read success within company grant; operational writes remain denied | Valid company-wide analyst grant |
| ANALYST with selected-branch grant queries one granted branch | Read success and only granted data | Valid scoped grant |
| ANALYST with selected-branch grant omits branch filter | Aggregate only granted branches; never all company | Grant scope widening |
| ANALYST requests ungranted branch | 403/404 | Branch IDOR |
| ANALYST after grant revocation requests analytics | 403 immediately | Stale authorization/cache issue |
| ANALYST attempts upload, product/recipe write, movement create/void, or grant management | 403 | Read-only boundary |
| STAFF attempts every analytics endpoint | 403 | No analytics/financial access |
| Any role selects another company via `X-Company-ID` | 403; no details | Tenant escape |
| Aggregated totals with hidden-branch high-value records | Totals include only allowed branch rows | Aggregate side-channel/data leak |
| Branch peer comparison with manager assigned to a subset | Peers only from assigned set | Cross-branch competitor leak |
| Variance baseline includes history in an ungranted branch | No influence and no comparison period from that branch | Historical inference leak |
| Actual/theoretical consumption has hidden branch sales, snapshots, movements, transfers | Output and totals restricted; transfer pair validated without leaking opposite branch | Cross-scope inventory leakage |
| Owner creates grant for same-company ANALYST | Success; actor recorded | Correct Owner delegation |
| MANAGER/STAFF/ANALYST attempts grant creation/revocation | 403 | Escalation prevention |
| Grant target is MANAGER/STAFF/OWNER, or belongs to another company | Rejected without creating grant | Invalid principal/tenant binding |
| Selected-branch grant references foreign-company/nonexistent/inactive branch | Rejected atomically | Referential integrity and branch eligibility |
| Selected-branch grant has empty/duplicate branch set | Empty rejected; duplicate rejected or normalized consistently; no partial grant | Ambiguous scope |
| Company-scope grant is supplied branch children or branch-scope grant has no children | Rejected | Scope representation inconsistency |
| Duplicate active grant creation | Conflict/no second active grant | Conflicting access state |
| Revoke twice, revoke foreign grant, or revoke already revoked grant | Deterministic conflict/404; audit unchanged | Audit history tampering and tenant probing |
| Current and previous-period analytics use same scope | Both periods limited identically | Period comparison leakage |
| No branch IDs are assigned/granted | Denied or explicitly empty response; never company-wide | Empty-set widening |

## 9. Recommended implementation sequence (after separate approval)

1. Approve remaining decisions below: analyst data families, branch grant behavior, staff write actions, and member/contact visibility.
2. Add the additive grant schema/model and migration; test constraints, company consistency, revocation history, and absence of automatic grants.
3. Add Owner-only create/list/revoke grant APIs. Check target membership role/company and validate a non-empty, same-company branch set for `BRANCHES` grants.
4. Add focused `BranchAccessScope` resolver and required capability checks for analytics. Keep the existing `require_roles` helper for role-only operations; do not overload it with branch data.
5. Make analytics service/query entry points require the resolved scope. Apply explicit branch predicates to every query and loader, including current and historical variance queries.
6. Add analyst analytics access through active grant only; keep analyst write routes denied. Roll out read-only endpoint allowlist gradually.
7. Add manager analytics one endpoint family at a time with assignment-only resolution, explicit multi-branch policy, and query-layer tests.
8. Implement staff operational APIs separately, with narrow request models, actor/source audit fields, branch checks, and business-approved review/approval rules.
9. Add the branch transfer API and closed-day/coverage mechanism only after their operational and analytics semantics are agreed.
10. Run full authorization, service scope, analytics contract, and existing regression suites before enabling frontend dashboard routes.

## 10. Open questions requiring approval

1. Which analytic field families can an Analyst grant include: sales/revenue/prices, purchase costs/supplier names, stock movement reasons, employee/branch identifiers, actual/theoretical consumption, and variance details?
2. Should a selected-branch Analyst be able to omit branch filters and aggregate all granted branches, or must each request select one branch? Recommendation: allow aggregation over the explicit grant set while keeping branch comparison confined to that set.
3. Should inactive branches remain visible to a grant that includes them? Recommendation: grants target active branches at creation; branch deactivation should remove access from current analytics while preserving grant history.
4. Should grant scope be immutable with revoke-and-regrant (recommended), or may an Owner edit a grant in place?
5. Should one active grant per analyst membership be enforced, or permit multiple grants whose scopes are combined? Recommendation: one active grant with explicit scope; replace by revoke-and-create to avoid ambiguous unions.
6. Should a MANAGER with multiple assignments be allowed a combined assigned-branch dashboard and peer comparison, or only one branch at a time?
7. Which STAFF operations require approval or manager review: stock count, waste, damage, staff consumption, receipt confirmation? Is staff manual adjustment always prohibited?
8. Should STAFF/ANALYST retain company-wide product and recipe reads? Should branch-member identity/contact data be restricted to OWNER/MANAGER?
9. Should manager historical import jobs remain visible only when every item is in assigned branches (current behavior), or be filtered to visible items? Recommendation: keep whole-job visibility rule unless partial-job semantics and counts are explicitly redesigned.
10. Is the existing membership role model expected to gain a dedicated permission for any other function, or should Phase 4E.5 use only this narrow analytics grant?

## Validation and final workspace state

- Repository-only Alembic verification: `.venv/bin/alembic -c alembic.ini heads` reports `8e010cafe004 (head)` and history shows `7e010cafe003 -> 8e010cafe004`. This does not establish a live database revision.
- No migration command that changes a database was run; no database connection or data was touched.
- No application code, frontend code, model, or migration was edited.
- `git diff --check` and a report trailing-whitespace check passed.
- The existing authorization/API test suite was not rerun in this design-only phase; the preceding Phase 4E.5 audit had run the relevant suites (`54 passed`).
- The final `git status --short` should be understood in the context of the preserved pre-existing dirty tree; the only new path from this task is `docs/phase-4e5-1-authorization-foundation-design.md`.

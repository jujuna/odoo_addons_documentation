# Analyze connected apps and business effects

Use for implementation planning and “what else will this affect?” questions. Separate
technical installation requirements from operational dependencies. An app being present
in source does not prove it is installed, licensed, enabled or configured in the database.

## 1. Establish the scope

Identify the target version, available edition/hosting, installed apps and relevant custom
modules when known. Record unknowns. Map the business request to candidate modules by
searching manifests and source with `rg`; inspect both community and available Enterprise
and custom roots. An app is a visible product area; supporting modules may have no app tile.

## 2. Follow installation requirements

Read manifests (`depends`, `auto_install`, `application`, `installable`) and trace relevant
transitive dependencies. Note which are already installed, newly required, or uncertain.
Do not confuse the technical `account` module with installation of every Accounting feature.

Check automatic connecting modules across the available roots and follow additional
connections introduced by new dependencies. `auto_install` may be a boolean or a list;
do not search only for the literal `True`. Verify the target version's loader semantics
for subset/empty-list cases before predicting what installs. Inspect connecting modules
for changes to views, defaults and business methods.

Explain connections in business terms, but qualify them by product setup, settings and
transaction state. “Sales and Inventory connect” does not mean every sales line generates
a delivery regardless of its product or route.

## 3. Trace settings and configuration scope

Read setting fields, their storage/write behavior and the code consuming them:
- `module_...` fields may trigger module installation; also check record-level toggles.
- `group_...` fields may alter implied groups and feature visibility; inspect actual scope.
- Company values, system parameters and record values have different scopes. A visual
  company-dependent marker alone does not prove how the setting is stored.

Check required edition/hosting capabilities where relevant. Explain meaningful installation
and data consequences. Uninstalling can remove data and is not a generic rollback plan.

## 4. Trace operational dependencies

Use [tracing-impact.md](tracing-impact.md). Follow the event through active or proposed
extensions and the rules that decide whether downstream actions run. Include relevant:
- Documents and statuses created or changed; actor and permissions at each step.
- Stock, invoices/bills, accounting entries, payroll, reports and notifications.
- Master data, company context, schedules, dates, currencies and integrations.
- Scheduled processing versus immediate behavior, including runtime conditions.
- Exceptions and effects on already-existing records.

Distinguish capability from enforcement. For example, a matching indicator on a bill does
not establish that payment is blocked. An approval app does not automatically enforce a
purchase order approval chain. Verify the connection and the actual blocking action.

## 5. Explain the impact and verify the proposal

Give the user a compact summary: required apps/setup, normal flow, key rules, connected
areas, data needed first, and unresolved decisions. Show only relevant dependencies, not
the entire technical tree. Keep verified findings separate from proposed setup assumptions.

Build acceptance cases from the user's policy. For an amount-based approval requirement,
check below/at/above the boundary, approver and ordinary-user behavior, self-approval,
currency/company scope, edits after approval, and whether the specified business action
is actually blocked. Add receipt/billing/payment cases only if they are in scope.

# account.analytic.account — Analytic Account Model

> **Module:** `analytic` | **Path:** [`addons/analytic/`](../addons/analytic/)
> Verified against Odoo 20 source on 2026-09-24.

## Overview

An analytic account is a **cost/revenue container that sits outside the general ledger**, allowing users to track financial activity by dimensions other than accounts. Common uses:

- **Project**: accumulate costs/revenues by project code
- **Department**: track spending by cost center or organizational unit
- **Vehicle/Equipment**: accumulate fuel, maintenance, depreciation
- **Job/Task**: group time/materials/expenses to a work order
- **Customer/Contract**: slice revenue or costs by customer or contract

The model is **decoupled from the GL** — a single `account.move.line` can reference one or more analytic accounts via [account.analytic.line](../addons/analytic/models/analytic_line.py) without changing the posting account. Balances (`debit`/`credit`/`balance`) aggregate all lines tied to that account, optionally filtered by date range and company.

The model inherits `mail.thread`, so `name`, `code`, `active` and `partner_id` changes are tracked in the chatter. It also sets `_check_company_auto = True` and `_check_company_domain = models.check_company_domain_parent_of` ([analytic_account.py:16-17](../addons/analytic/models/analytic_account.py#L16)) — company checks accept a **parent** company, which is why balance aggregation pulls in lines from the whole company branch.

---

## Core Fields

### Identity & Organization

| Field | Type | Details | Citation |
|---|---|---|---|
| `name` | Char | Required, user-visible label (`Analytic Account`). Trigram index for fuzzy search. Tracked. Translatable. | [analytic_account.py:20-26](../addons/analytic/models/analytic_account.py#L20) |
| `code` | Char | Optional reference code — often a project/cost-center code (e.g., "CC-2024-001"). BTree indexed for fast lookup. Tracked. Part of display name via `_compute_display_name`. | [analytic_account.py:27-31](../addons/analytic/models/analytic_account.py#L27) |
| `active` | Boolean | Soft-delete flag. Default `True`. Deactivated accounts remain queryable but hidden from dropdowns. Tracked. | [analytic_account.py:32-37](../addons/analytic/models/analytic_account.py#L32) |

### Plan & Hierarchy

| Field | Type | Details | Citation |
|---|---|---|---|
| `plan_id` | Many2one → `account.analytic.plan` | **Required**. Each account belongs to exactly one plan (e.g., "Projects", "Cost Centers", "Vehicles"). The plan defines which column on the analytic line holds this account; see [plan._column_name()](../addons/analytic/models/analytic_plan.py#L118) (e.g., `account_id`, `x_plan2_id`). Indexed. | [analytic_account.py:38-43](../addons/analytic/models/analytic_account.py#L38) |
| `root_plan_id` | Many2one → `account.analytic.plan` | Derived. The root parent of `plan_id` (via [plan.root_id](../addons/analytic/models/analytic_plan.py#L36)). Plans are hierarchical; this field stores the top-level plan for quick filtering. Related and stored. | [analytic_account.py:44-49](../addons/analytic/models/analytic_account.py#L44) |
| `color` | Integer | Related (read-only) to `plan_id.color`. Drives the kanban/tag color, so every account under a plan shares that plan's color. | [analytic_account.py:50-53](../addons/analytic/models/analytic_account.py#L50) |

### Company & Partner

| Field | Type | Details | Citation |
|---|---|---|---|
| `company_id` | Many2one → `res.company` | Defaults to the current user's company. **Not required** — a company-less account is shared. BTree indexed (new in 20.0). A constraint blocks changing the company of an account that already has analytic lines; see [_check_company_consistency](../addons/analytic/models/analytic_account.py#L96). | [analytic_account.py:61-66](../addons/analytic/models/analytic_account.py#L61) |
| `partner_id` | Many2one → `res.partner` | Optional, labelled `Customer`. Often used to link an account to a customer, vendor, or project stakeholder. Indexed `btree_not_null`. Tracked. `check_company=True`. Uses `bypass_search_access=True` to speed up `name_search`. | [analytic_account.py:68-76](../addons/analytic/models/analytic_account.py#L68) |

---

## Balance Computation

### Balance Fields (Computed)

All three are **non-stored** computed Monetary fields on `_compute_debit_credit_balance`.

| Field | Meaning in 20.0 source | Citation |
|---|---|---|
| `debit` | `-1 ×` (sum of analytic lines with `amount < 0`), so it reads as a **positive** number. Costs land here. | [analytic_account.py:82-85](../addons/analytic/models/analytic_account.py#L82) |
| `credit` | Sum of analytic lines with `amount >= 0`. Revenue lands here. | [analytic_account.py:86-89](../addons/analytic/models/analytic_account.py#L86) |
| `balance` | `credit - debit`. The net accumulated flow through the account. | [analytic_account.py:78-81](../addons/analytic/models/analytic_account.py#L78) |
| `currency_id` | Related to `company_id.currency_id` — the reporting currency for balance display. | [analytic_account.py:91-94](../addons/analytic/models/analytic_account.py#L91) |

> **Sign convention:** analytic lines carry costs as **negative** amounts and revenue as **positive** ones (an `account.move.line` materializes as `amount = -balance × pct/100`). So a project that only ran costs shows `debit > 0`, `credit = 0`, `balance < 0`.

### How Balance Is Computed: `_compute_debit_credit_balance`

**Flow** [analytic_account.py:155-195](../addons/analytic/models/analytic_account.py#L155):

1. **Build domain**:
   - Include lines with no company **and** lines of every allowed company: `('company_id', 'in', [False] + self.env.companies.ids)`.
   - If `from_date` in context → add `date >= from_date`.
   - If `to_date` in context → add `date <= to_date`.

2. **Group by plan, then by currency** (`self.grouped('plan_id')`):
   - Accounts with no plan get `debit = credit = balance = 0` and are skipped.
   - For each plan, two `_read_group` calls on `account.analytic.line`:
     - **Credit**: `amount >= 0.0`
     - **Debit**: `amount < 0.0`
   - Both group by the plan's own column (`plan._column_name()`) **and** `currency_id`, aggregating `amount:sum`.

3. **Convert all to company currency**:
   - `convert()` calls `from_currency._convert(from_amount=amount, to_currency=self.env.company.currency_id, company=self.env.company)`.
   - 20.0 **dropped the explicit `date=fields.Date.today()`** argument; `_convert` falls back to `fields.Date.context_today(self)` ([res_currency.py:353](../odoo/addons/base/models/res_currency.py#L353)), so the rate is still "today" but now respects the user's timezone.
   - Accumulated into `data_debit` / `data_credit` dicts keyed by account ID.

4. **Assign per account**:
   ```python
   account.debit = -data_debit.get(account.id, 0.0)   # negate to read positive
   account.credit = data_credit.get(account.id, 0.0)
   account.balance = account.credit - account.debit
   ```

**Example**: a project account with a 100 EUR revenue line and a 50 USD revenue line (= 45 EUR at today's rate):
- `credit = 100 + 45 = 145 EUR`
- `debit = 0`
- `balance = 145 EUR`

---

## Display & Search

### `_compute_display_name`

[analytic_account.py:105-113](../addons/analytic/models/analytic_account.py#L105)

The displayed name includes optional code and the **commercial** partner (if set):

```
[CODE] Name - Partner Name
```

Example: `[CC-2024-001] IT Department - ACME Inc.`

### Multi-Field Search

The model defines [`_rec_names_search = ('name', 'code')`](../addons/analytic/models/analytic_account.py#L18), enabling search on both name and code. `code` carries a BTree index for fast exact lookups.

---

## Multi-Company Behavior

### Consistency Check: `_check_company_consistency`

[analytic_account.py:96-103](../addons/analytic/models/analytic_account.py#L96)

When the **company of an account changes**, Odoo searches (as sudo) for any linked analytic line whose company is **not a child of** the new company. If one exists, the write is rejected:

> "You can't change the company of an analytic account that already has analytic items! It's a recipe for an analytical disaster!"

**Why?** Analytic lines are company-specific; moving an account to a different company without reassigning its lines breaks the company hierarchy assumption.

### Record-Level Security

Record-level security lives in a single [`security/ir.access.csv`](../addons/analytic/security/ir.access.csv), with an `operation` column (`crud`, `r`, …) and an optional `domain`. The multi-company rules:

| Model | Domain |
|---|---|
| `account.analytic.account` | `['|', ('company_id','=',False), ('company_id','parent_of',company_ids)]` |
| `account.analytic.line` | `[('company_id','in',company_ids)]` |
| `account.analytic.applicability` | `['|', ('company_id','=',False), ('company_id','parent_of',company_ids)]` |
| `account.analytic.distribution.model` | `['|', ('company_id','=',False), ('company_id','parent_of',company_ids)]` |

`analytic.group_analytic_accounting` carries `implied_ids = [base.group_user]`, and [`res_groups.py`](../addons/analytic/models/res_groups.py) registers it as a **light group** via `_get_light_group_xmlids()` — it shows up as a simple toggle in the group UI rather than a full access group.

---

## Line Linking & Plan Migration

### One2many Relationship

[analytic_account.py:55-59](../addons/analytic/models/analytic_account.py#L55)

```python
line_ids = fields.One2many(
    'account.analytic.line',
    'auto_account_id',  # magic link to the right column (plan) by using the context in the view
    string="Analytic Lines",
)
```

`auto_account_id` is a **computed, inversable field** on `analytic.plan.fields.mixin` ([analytic_line.py:26-46](../addons/analytic/models/analytic_line.py#L26)) that resolves to the "current" plan's account column. This lets one one2many view work with any plan column (`account_id`, `x_plan2_id`, …) depending on `analytic_plan_id` in the context.

### Plan Migration: `_update_accounts_in_analytic_lines`

[analytic_account.py:197-227](../addons/analytic/models/analytic_account.py#L197), called from [`write()`](../addons/analytic/models/analytic_account.py#L229).

When an account is **moved to a different plan** (`write({'plan_id': new_plan_id})`), the method:

1. **Checks for blocking lines**: if the new plan's column already has a value on any line that also references this account in the old column, raise a `RedirectWarning` ("Whoa there! Making this change would wipe out your current data.") with a **See them** button opening those lines.

2. **Migrates lines** (if no conflict) with raw SQL:
   ```sql
   UPDATE account_analytic_line
      SET <new_fname> = <current_fname>,
          <current_fname> = NULL
    WHERE <current_fname> = ANY(<account_ids>)
   ```

3. **Invalidates the model cache** (`invalidate_model()`).

**Why?** Analytic lines store one column per root plan, so moving an account across plans means moving the FK between columns atomically.

---

## Read Group & Aggregation

### Custom Aggregation: `_read_group_select` / `_read_group_postprocess_aggregate`

[analytic_account.py:121-153](../addons/analytic/models/analytic_account.py#L121)

`balance`, `debit`, `credit` are non-stored, so SQL cannot sum them. Instead:

1. `_read_group_select` rewrites `balance:sum`, `balance:sum_currency`, `debit:*`, `credit:*` into `id:recordset` so the group carries the records themselves.
2. `_read_group_postprocess_aggregate` computes the field in Python and sums per group.
3. For `:sum_currency`, each record's value is converted from **its own** `currency_id` to `env.company.currency_id` before summing.

> **20.0 ORM signature change:** both hooks moved from `(aggregate_spec, query)` to a **`table`-first** signature — `_read_group_select(self, table, aggregate_spec)`. The same rework hit [`analytic_mixin.py`](../addons/analytic/models/analytic_mixin.py): `_read_group_groupby(self, table, groupby_spec)`, `Domain.custom(to_sql=lambda table: ...)`, `table.<field>` in place of `model._field_to_sql(alias, fname, query)`, and `Query` now imported from `odoo.models` instead of `odoo.tools`. Any override of these in `custom_addons/` must be migrated.

---

## Data Lifecycle

### Copying

Duplicating an analytic account keeps the **exact same name** unless you pass one in `default`. Analytic lines are not copied (one2many fields are not copied by default), so the duplicate starts with a zero balance.

### Web Read Context

[analytic_account.py:115-119](../addons/analytic/models/analytic_account.py#L115)

When reading a **single** analytic account via the web client, `web_read` injects `analytic_plan_id = self.plan_id.id` into the context. This is what makes the one2many `line_ids` / `auto_account_id` resolve to the right column in the form view.

---

## Integration Points

### Who References Analytic Accounts?

- **[account.analytic.line](../addons/analytic/models/analytic_line.py)**: every cost/revenue posting; linked via the plan's dynamic column.
- **[account.analytic.plan](../addons/analytic/models/analytic_plan.py)**: parent hierarchy; each account has exactly one plan.
- **[account.analytic.applicability](../addons/analytic/models/analytic_plan.py#L406)**: marks which plans apply to which document types (Invoices, Sales Orders, Expenses…). It lives in `analytic_plan.py`, not a file of its own.
- **[analytic.mixin](../addons/analytic/models/analytic_mixin.py)**: the `analytic_distribution` JSON field, mixed into `account.move.line`, `purchase.order.line`, `hr.expense`, `account.asset` and others.
- **[account.move.line](../addons/account/models/account_move_line.py#L3546)**: materializes analytic lines from its distribution when the move is posted.
- **[budget.analytic / budget.line](../enterprise/account_budget/models/budget_analytic.py)** (enterprise `account_budget`): budgets compare planned amounts against actual analytic balances. Note: there is **no `analytic_budget` module and no `analytic.budget` model** in 20.0 — the models are `budget.analytic` and `budget.line`.

### Analytic Distribution (JSON) — how lines really get created

`analytic_distribution` is a `fields.Json` mapping `"<account_ids>" → percentage`, where the key may be a comma-separated list of account IDs (one per plan) for a multi-plan combination.

Two distinct mechanisms — **neither is a cron**; `analytic` ships no `ir.cron` at all:

1. **On `account.move.line`** — when the move is posted, [`_create_analytic_lines()`](../addons/account/models/account_move_line.py#L3546) walks the distribution and calls [`_prepare_analytic_distribution_line()`](../addons/account/models/account_move_line.py#L3574) to create one `account.analytic.line` per distribution key, with `amount = -balance × pct/100`. Resetting the move to draft unlinks them ([account_move_line.py:2181](../addons/account/models/account_move_line.py#L2181)).

2. **On `account.analytic.line` itself** — the line exposes its own `analytic_distribution` (computed from its plan columns, [analytic_line.py:244](../addons/analytic/models/analytic_line.py#L244)). Writing a multi-key distribution triggers [`_inverse_analytic_distribution()`](../addons/analytic/models/analytic_line.py#L248), which **synchronously** rewrites the first split onto the current line and `create()`s one sibling line per remaining split, then bus-notifies the user ("N analytic lines created").

---

## `account.analytic.line` — 20.0 changes worth knowing

| Change | Impact |
|---|---|
| `name` is optional ([analytic_line.py:170](../addons/analytic/models/analytic_line.py#L170)) | Lines can be created without a description. Custom code that assumed a non-empty `name` (grouping keys, report labels) must handle `False`. |
| `product_uom_id` is now `compute='_compute_product_uom_id', store=True, readonly=False` ([analytic_line.py:188](../addons/analytic/models/analytic_line.py#L188)) | `_compute_product_uom_id()` is an empty hook — it exists so downstream modules (timesheets, MRP) can default the unit. Override the compute, don't onchange it. |
| New `write()` → `_check_can_write(vals)` hook ([analytic_line.py:240](../addons/analytic/models/analytic_line.py#L240), [:287](../addons/analytic/models/analytic_line.py#L287)) | The base returns `True`. It is the sanctioned extension point for write-locking analytic lines (e.g., timesheet validation locks) without overriding `write` in every module. |
| `company_id` gained `index=True` ([analytic_line.py:206](../addons/analytic/models/analytic_line.py#L206)) | Faster company-filtered aggregation — relevant to `_compute_debit_credit_balance`, which always filters on company. |
| `_search_fiscal_date` uses `fields.Date.context_today(self)` instead of `fields.Date.today()` | The "current fiscal year" filter now follows the user's timezone. |

---

## Edge Cases & Gotchas

### 1. Context-Dependent `auto_account_id`

`line_ids` hangs off the computed `auto_account_id`. Without `analytic_plan_id` in the context, the relation resolves against no plan and comes back empty. In custom code, always use `with_context(analytic_plan_id=self.plan_id.id)` before reading `line_ids`.

### 2. Date-Filtered Balance

`debit` / `credit` / `balance` read `from_date` and `to_date` from the **context**. A view or report that forgets to pass them shows the **all-time** balance, not the period balance. Easy to miss, and it silently gives a plausible-looking wrong number.

### 3. Company Change Is Blocked, Never Migrated

Changing `company_id` is rejected outright when lines exist. There is **no automatic migration** of lines to the new company. Rewrite the lines' company first, then change the account.

### 4. Plan Changes Are Expensive and Can Be Blocked

Moving `plan_id` runs raw SQL over `account_analytic_line` and raises a `RedirectWarning` if the target column is already used. In practice accounts get archived, not reparented.

### 5. Duplicating Keeps the Same Name

See **Copying** above — duplicates keep the exact same name unless you pass one via `default`.

### 6. Display Name Shows the Commercial Partner

`_compute_display_name` uses `partner_id.commercial_partner_id.name`. If `partner_id` is a child contact, the display shows the **parent company's** name, not the contact's.

### 7. Accounts Without a Plan Report Zero

`_compute_debit_credit_balance` short-circuits accounts whose `plan_id` is falsy to `0/0/0`. `plan_id` is required, so this only happens on new/unsaved records — but it means a fresh onchange form legitimately shows a zero balance.

---

## Usage Pattern

### Typical Workflow

1. **Create a plan** — Accounting → Configuration → **Analytic Accounting** → Analytic Plans ([account_menuitem.xml:64-67](../addons/account/views/account_menuitem.xml#L64)), e.g. "Projects". The same submenu holds Analytic Accounts and Analytic Distribution Models.
2. **Create accounts** under the plan, e.g. project "Customer ABC - Q3 2026".
3. **Set an analytic distribution** on documents: sales order lines, vendor bills, invoice lines, expenses, timesheets.
4. **Post the document** → `account.move.line._create_analytic_lines()` materializes the analytic lines.
5. **Open the account** → see debit/credit/balance aggregated from those lines.
6. **Filter by date** (context `from_date` / `to_date`) → period-specific balance.
7. **Create a budget** (`budget.analytic`) → compare planned vs achieved.

### Programmatic Access

```python
# Get an account
account = self.env['account.analytic.account'].search([('code', '=', 'CC-2024-001')], limit=1)

# Balance for a specific period (context-driven)
account_period = account.with_context(from_date='2026-01-01', to_date='2026-03-31')
print(f"Q1 2026 balance: {account_period.balance}")

# Read the lines — needs the plan in context, see gotcha #1
lines = account.with_context(analytic_plan_id=account.plan_id.id).line_ids
for line in lines:
    print(f"{line.date}: {line.amount}")

# Create a line manually (rare) — set the plan's own column, not a generic 'account_id'
self.env['account.analytic.line'].create({
    account.plan_id._column_name(): account.id,
    'date': fields.Date.context_today(self),
    'amount': -100.0,          # negative = cost
    'name': 'Manual entry',
    'company_id': account.company_id.id,
})
```

> The old `{'account_id': account.id}` shortcut only works when the account belongs to the **Project** (root) plan, whose column happens to be `account_id`. For any other plan use `plan._column_name()`.

---

## Performance Notes

- **Balance computation is not stored** — every read re-runs two `_read_group` queries per plan on `account.analytic.line`. For high-volume use (thousands of accounts, 100k+ lines) narrow by date or plan.
- **Plan migration** runs raw `UPDATE account_analytic_line` — cheap per row but unbounded; run it off-hours on large datasets.
- **Indexes**: trigram on `name` (fuzzy search), btree on `code` (exact lookup), btree on `plan_id` and `company_id`, `btree_not_null` on `partner_id`. `account.analytic.line` indexes `date`, `user_id` and (new in 20.0) `company_id`.

---

## Related Models

- **[account.analytic.line](../addons/analytic/models/analytic_line.py)** — the transaction records; balances roll up from here.
- **[account.analytic.plan](../addons/analytic/models/analytic_plan.py)** — the dimension; defines hierarchy and the per-plan column name.
- **[account.analytic.applicability](../addons/analytic/models/analytic_plan.py#L406)** — which plans apply to which document types (and whether they are mandatory).
- **[account.analytic.distribution.model](../addons/analytic/models/analytic_distribution_model.py)** — rules that auto-fill `analytic_distribution` on new documents.
- **[budget.analytic / budget.line](../enterprise/account_budget/models/budget_analytic.py)** — enterprise budgets measured against analytic balances.
- Deeper cross-module treatment: [`analytic_accounting.md`](analytic_accounting.md).

# Analytic Accounting

> **Module:** `analytic` (+ `account` for the journal-entry side) | **Path:** [`addons/analytic/`](../addons/analytic/), [`addons/account/`](../addons/account/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

Analytic accounting is a second classification of money, next to the chart of accounts. The general ledger answers "which account, which period"; analytic answers "which project, department or cost center". One journal item can feed several analytic accounts, and the analytic structure never has to mirror the chart of accounts.

The key idea is **plans as dimensions**. A plan is a dimension (Projects, Departments, Cost Centers); an analytic account is one value inside it (Project A, Finance). Each root plan gets its own column, so one analytic item can carry a project and a department at the same time, and reports can group by either. Controllers, project managers and budget owners use it for cost-center reporting, project margins and budget versus actual. The result is a set of analytic items (`account.analytic.line`) you can pivot, filter and compare with budgets.

---

## The Big Picture — How It Works

```
Enable Analytic Accounting (Settings)
        │
Create PLANS (dimensions) ── each root plan adds a column: account_id, x_plan{N}_id ...
        │
Create ANALYTIC ACCOUNTS under each plan (the values)
        │
Set analytic_distribution (percentages) on invoice / bill / SO / PO / expense lines,
   by hand or pre-filled by a Distribution Model
        │
Post the journal entry ── _create_analytic_lines() turns each percentage into an analytic item
        │
Reports and budgets read the analytic items
```

The distribution is a **percentage JSON on the source line**. It becomes real analytic items only when the journal entry is posted: `_post()` calls `_create_analytic_lines()` ([account_move.py:6262](../addons/account/models/account_move.py#L6262)). Each item's amount is `-balance × percentage / 100`, in company currency ([account_move_line.py:3574](../addons/account/models/account_move_line.py#L3574)). Costs are negative, revenues positive.

Sale and purchase order lines carry the distribution to their invoices and create no analytic items themselves; purchase lines also feed budget commitments. Timesheets and manually entered analytic items are analytic items from the start and need no journal entry.

### Key decision points

- **How many dimensions?** Each root plan is one dimension and one extra column. Most companies need one to three.
- **Is a plan mandatory?** A plan's applicability decides whether a line must be 100% distributed on it before posting.
- **Manual or automatic distribution?** Type it on each line, or let Distribution Models fill it from partner, product or account.

---

## Core Concepts

| Concept | Model | What it is |
|---|---|---|
| Plan | `account.analytic.plan` | A dimension. Root plans create columns; sub-plans are hierarchy levels for drill-down |
| Analytic account | `account.analytic.account` | A value inside one plan; shows computed debit, credit and balance |
| Distribution | `analytic_distribution` JSON | On a source line: splits its amount, by percentage, across accounts |
| Analytic item | `account.analytic.line` | The posting: one amount, a date, a company and one account per plan column |
| Distribution Model | `account.analytic.distribution.model` | A rule that pre-fills the distribution |
| Applicability | `account.analytic.applicability` | A rule that makes a plan optional, mandatory or unavailable |

The distribution (percentages, on the source line) and the analytic items (amounts, created at posting) are different records.

---

## When to Use It (and When Not To)

### This module is for:

- Cost and revenue by project, department or cost center, without multiplying GL accounts.
- Project profitability and budget versus actual (with `account_budget`).
- Splitting one cost across dimensions, for example 60% Project A and 40% Project B.

### Use something else when:

- You only need a different GL account per case — use the chart of accounts.
- You need stock valuation by location or lot — that is `stock_account`.
- You need tax or statutory segmentation — use GL accounts, tax tags and fiscal positions.

---

## Real-World Scenarios

### Scenario 1: Cost center on a vendor bill

**Situation:** A controller wants every vendor bill line tagged to a department.

**What they do:** Enable Analytic Accounting, create a "Departments" plan with Admin, Sales and R&D, set 100% R&D on the office-supplies line, post the bill.

**What happens:** One analytic item: amount −(line balance), the R&D column set, financial account = the expense account, linked to the journal item. R&D's balance shows the cost.

### Scenario 2: One invoice line, two projects

**Situation:** A consulting line covers two projects, 60/40.

**What they do:** Distribution `{"<Project A id>": 60, "<Project B id>": 40}`.

**What happens:** Two analytic items, 60% and 40% of the line balance. Amounts are rounded to the currency and the rounding difference is spread over the items so they sum to the balance ([account_move_line.py:3622](../addons/account/models/account_move_line.py#L3622)).

### Scenario 3: Project and department on the same line

**Situation:** A cost belongs to Project A and to R&D.

**What they do:** Distribution `{"<Project A id>,<R&D id>": 100}`: **one comma-joined key**.

**What happens:** **One** analytic item with both columns set. A comma key is one combination spanning plans; separate keys are separate allocations. The two accounts must belong to different root plans.

### Scenario 4: Distribution filled by rule

**Situation:** All bills from one vendor go to the same cost center.

**What they do:** Create a Distribution Model with that partner and the cost center.

**What happens:** New bill lines for that vendor get the distribution pre-filled. The rule order and overlap rules are explained below.

### Worked amounts

| Distribution | Result for a GL debit of 100 |
|---|---|
| `{"12": 100}` | one item, −100 |
| `{"12": 60, "13": 40}` | two items, −60 and −40 |
| `{"12,7": 100}` | one item, −100, with both plan columns set |

IDs are placeholders.

---

## How Things Work Under the Hood

### Plans create columns

When a root plan is created, `_sync_all_plan_column()` adds a stored Many2one column to every model that inherits `analytic.plan.fields.mixin`: analytic items, budget lines and projects ([analytic_plan.py:312](../addons/analytic/models/analytic_plan.py#L312)).

- The plan stored in the system parameter `analytic.project_plan` uses the column `account_id`; every other root plan uses `x_plan{id}_id` ([analytic_plan.py:113](../addons/analytic/models/analytic_plan.py#L113)). Without that parameter Odoo raises "A 'Project' plan needs to exist..." ([analytic_plan.py:103](../addons/analytic/models/analytic_plan.py#L103)). The project plan cannot get a parent.
- Sub-plans share their root plan's column. They only add a non-stored field for grouping by hierarchy level.
- Every analytic item needs at least one plan account: "At least one analytic account must be set" ([analytic_line.py:94](../addons/analytic/models/analytic_line.py#L94)).

`auto_account_id` is a helper field over all plan columns. Reading it needs `analytic_plan_id` in the context (otherwise it is empty); writing it fills the column of the account's plan; searching it ORs all plan columns ([analytic_line.py:26](../addons/analytic/models/analytic_line.py#L26)).

### The distribution JSON

`analytic.mixin` gives source models a stored `analytic_distribution` JSON ([analytic_mixin.py:17](../addons/analytic/models/analytic_mixin.py#L17)). Keys are analytic account IDs (comma-joined for combinations); values are percentages rounded to the **Percentage Analytic** precision (2 digits by default). A GIN index on the account IDs in the keys makes "lines of analytic account X" searches fast ([analytic_mixin.py:33](../addons/analytic/models/analytic_mixin.py#L33)).

### Materialization at posting

- `_create_analytic_lines()` validates mandatory plans, builds one item per key and creates them with `skip_analytic_sync` so the change does not bounce back ([account_move_line.py:3546](../addons/account/models/account_move_line.py#L3546)).
- When a plan reaches 100% on its last key, that slice is computed as the remainder, so each plan's items sum to the balance. Zero amounts are skipped.
- Category: `invoice` for customer documents, `vendor_bill` for vendor documents, `other` otherwise.

### The link back to the journal item

On `account.analytic.line`, `account` adds ([account_analytic_line.py:19](../addons/account/models/account_analytic_line.py#L19)):

| Field | Behavior |
|---|---|
| `move_line_id` | The journal item; deleting it deletes its analytic items (cascade) |
| `general_account_id` | The financial account; must equal the journal item's account ([account_analytic_line.py:82](../addons/account/models/account_analytic_line.py#L82)) |
| `journal_id` | Stored related journal |
| `analytic_profitability` | Revenue, loss or uncategorized, used by budgets ([account_analytic_line.py:98](../addons/account/models/account_analytic_line.py#L98)) |

The sync works both ways. Creating, editing or deleting an analytic item rewrites the journal item's distribution ([account_move_line.py:3612](../addons/account/models/account_move_line.py#L3612)). Editing the distribution of a posted journal item deletes and recreates its analytic items ([account_move_line.py:1793](../addons/account/models/account_move_line.py#L1793)). Reset to draft deletes them, keeping the distribution for the next posting ([account_move.py:6904](../addons/account/models/account_move.py#L6904)); Cancel resets to draft first.

### Splitting an analytic item

Analytic items also have an `analytic_distribution` field, computed as their own combination at 100% ([analytic_line.py:244](../addons/analytic/models/analytic_line.py#L244)). Editing it splits the item into several, one per key. The amount is split; for project timesheets the hours are split instead and the cost is recomputed ([account_analytic_line.py:483](../addons/hr_timesheet/models/account_analytic_line.py#L483)).

### Mandatory plans (applicability)

A plan has a default applicability: Optional, Mandatory or Unavailable. Applicability rules can override it. `_get_applicability()` starts from a score of 0.5 and takes the best rule scoring above it ([analytic_plan.py:244](../addons/analytic/models/analytic_plan.py#L244)):

| Rule criterion | Score |
|---|---|
| Company set on the rule and on the document | +0.5 |
| Business domain equals the document's (Invoice, Vendor Bill, Miscellaneous...) | +1; a different domain disqualifies the rule |
| Financial account prefix matches (`account`) | +1; no match disqualifies |
| Product category matches (`account`) | +1; no match disqualifies |

A rule with only a company never beats the default. Sources: [analytic_plan.py:447](../addons/analytic/models/analytic_plan.py#L447), [account_analytic_plan.py:58](../addons/account/models/account_analytic_plan.py#L58).

At posting, product lines are checked for business domain `invoice`, `bill` or `general` ([account_move_line.py:3513](../addons/account/models/account_move_line.py#L3513)). Each mandatory root plan must total exactly 100%: "One or more lines require a 100% analytic distribution." The check runs only with the `validate_analytic` context, which the Confirm buttons of the entry form pass ([analytic_mixin.py:182](../addons/analytic/models/analytic_mixin.py#L182)). Posting from code or by the auto-post cron does not enforce it.

### Distribution Models

Criteria: partner, partner category and company ([analytic_distribution_model.py:61](../addons/analytic/models/analytic_distribution_model.py#L61)), plus product, product category and financial-account prefixes from `account` ([account_analytic_distribution_model.py:34](../addons/account/models/account_analytic_distribution_model.py#L34)). An empty criterion matches anything; prefixes are compared after the search and may be separated by commas or semicolons.

- Rules are read by **sequence, then newest first**. They are not ranked by how specific they are.
- A rule is skipped completely if any of its root plans is already covered by an earlier rule, even if it also covers a new plan. Otherwise it is merged into the result.
- A rule shared between companies cannot use company-specific analytic accounts ([analytic_distribution_model.py:41](../addons/analytic/models/analytic_distribution_model.py#L41)).

### Account balances

Debit, credit and balance of an analytic account are computed on read, not stored ([analytic_account.py:156](../addons/analytic/models/analytic_account.py#L156)). Debit is the total of negative items, credit of positive ones, balance = credit − debit. The totals cover the allowed companies, respect `from_date` / `to_date` in the context, and convert foreign currencies at today's rate.

An analytic account's company cannot change once it has items outside that company and its branches ([analytic_account.py:97](../addons/analytic/models/analytic_account.py#L97)). Moving an account to another root plan moves its items to the new plan's column, and is refused when some of them already have a value there ([analytic_account.py:197](../addons/analytic/models/analytic_account.py#L197)).

---

## Configuration & Settings

- **Analytic Accounting** (Accounting → Configuration → Settings) — adds the group `analytic.group_analytic_accounting` ([res_config_settings.py:10](../addons/analytic/models/res_config_settings.py#L10)). Without it the analytic fields and menus are hidden in Sales, Purchase, Expenses and Accounting.
- **`analytic.project_plan`** system parameter — which plan owns the `account_id` column. Change it only through the UI or ORM: the change is validated and rebuilds the plan columns ([ir_config_parameter.py:11](../addons/analytic/models/ir_config_parameter.py#L11)).
- **Percentage Analytic** decimal precision — rounding of distribution percentages ([analytic_data.xml](../addons/analytic/data/analytic_data.xml)).

Menus (with the group): Accounting → Configuration → Analytic Accounting → Analytic Distribution Models, Analytic Accounts, Analytic Plans; Accounting → Accounting → Transactions → Analytic Items; Accounting → Reporting → Management → Analytic Report ([account_menuitem.xml:64](../addons/account/views/account_menuitem.xml#L64)).

---

## Dependencies

| Requires | Why |
|---|---|
| `base`, `mail`, `uom` | ORM, chatter on accounts, units on items ([__manifest__.py](../addons/analytic/__manifest__.py)) |

| Works With (optional) | What It Adds |
|---|---|
| `account` | Distribution on journal items, analytic items at posting, profitability, applicability by account/product, distribution models by product/account |
| `sale`, `purchase`, `hr_expense` | Distribution on their lines, passed to invoices, bills and expense entries |
| `hr_timesheet` | Timesheets as analytic items: amount = −hours × employee hourly cost |
| `account_budget`, `account_budget_purchase`, `project_account_budget` | Budgets on analytic items and purchase commitments — see [analytic_budget.md](analytic_budget.md) |
| `account_asset`, `account_accountant` (deferrals) | Distribution copied onto depreciation and deferral entries |

---

## Gotchas & Non-Obvious Behavior

- **No items until posted.** A draft entry's distribution appears in no analytic report. Timesheets and manual items are the exception.
- **Comma key = one combination.** `{"12,7": 100}` is one item on two plans; `{"12": 50, "7": 50}` is two items.
- **Mandatory means exactly 100% per root plan**, and only on form posting (the `validate_analytic` context).
- **Rule order, not specificity.** A broad Distribution Model with a lower sequence wins; overlapping rules are skipped whole.
- **Posted edits recreate items.** Changing a posted line's distribution deletes and recreates its analytic items; do not rely on their IDs.
- **Balances use today's rate.** Foreign-currency items are converted at today's rate, not at their transaction date.
- **Analytic balance ≠ budget achieved.** Budgets filter by account type, profitability, dates and company; the account balance does not.
- **The project plan is a parameter, not ID 1.** Code must resolve it with `_get_all_plans()`.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`analytic_budget.md`](analytic_budget.md) — budgets read these analytic items
- [`accounting_fixed_costs_guide.md`](accounting_fixed_costs_guide.md) — analytic distribution from the fixed-cost angle
- [`accounting_multicompany_branches.md`](accounting_multicompany_branches.md) — analytic accounting with branches
- [`deferred_expenses_revenue.md`](deferred_expenses_revenue.md) — analytic distribution on deferral entries

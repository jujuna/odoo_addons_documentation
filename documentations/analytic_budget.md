# Analytic Budget

> **Module:** `account_budget` (+ `account_budget_purchase`, `project_account_budget`) | **Path:** [`enterprise/account_budget/`](../enterprise/account_budget/), [`enterprise/account_budget_purchase/`](../enterprise/account_budget_purchase/), [`enterprise/project_account_budget/`](../enterprise/project_account_budget/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does

An analytic budget sets a planned amount for a combination of analytic accounts over a date range, and shows how much of it has been used. **Actuals come from analytic items** (`account.analytic.line`): posted journal items with analytic distribution, timesheets and manual analytic items, not only invoices. With purchases installed, confirmed purchase orders show as **committed** before they are billed. Projects linked to an analytic account get a budget panel with planned, spent and progress.

`account_budget` depends on `accountant` ([__manifest__.py](../enterprise/account_budget/__manifest__.py)). `account_budget_purchase` (purchase commitments) and `project_account_budget` (project panel) install automatically when their other dependency is present.

---

## Business Flow

```
Create Budget (Draft): name, period, budget type, responsible
      │   (or Budgets list → Generate: one budget per month/quarter/year)
      ▼
Add Budget Lines: analytic accounts (one column per plan) + Commitment amount
      ▼
Open (state "confirmed")
      ▼
Posted entries / timesheets / manual items with matching analytic accounts ──► Achieved
Confirmed purchase orders not yet billed ──► Committed (with account_budget_purchase)
      ▼
Budget form, Budget Report, project panel  ──►  Done  (or Revise ──► new version)
```

Menu: Accounting → Accounting → Transactions → **Analytic Budget**, for Accounting Administrators ([budget_analytic_views.xml:170](../enterprise/account_budget/views/budget_analytic_views.xml#L170)).

### States

| State (UI label) | Buttons on the form | Notes |
|---|---|---|
| `draft` (Draft) | Open, Cancel Budget | Can be deleted |
| `confirmed` (Open) | Revise, Done, Reset to Draft | Tracked by the project panel |
| `revised` (Revised) | Reset to Draft | Set when a revision of it is opened |
| `done` (Done) | Reset to Draft | Still tracked by the project panel |
| `canceled` (Canceled) | Reset to Draft | Can be deleted |

Sources: [budget_analytic.py:29](../enterprise/account_budget/models/budget_analytic.py#L29), [budget_analytic_views.xml:9](../enterprise/account_budget/views/budget_analytic_views.xml#L9). The buttons are the only guard: the actions set the state directly.

- **Revise** copies the budget into a new draft named "Name - REV(date time)", linked by `parent_id` ([budget_analytic.py:87](../enterprise/account_budget/models/budget_analytic.py#L87)). The original stays Open until the revision is opened; then it becomes Revised ([budget_analytic.py:73](../enterprise/account_budget/models/budget_analytic.py#L73)).
- **Delete** only in Draft or Canceled ([budget_analytic.py:69](../enterprise/account_budget/models/budget_analytic.py#L69)).
- The achieved-amount calculation itself does not look at the state: a draft or canceled budget also shows achieved amounts. Only the project panel and project totals limit themselves to Open and Done budgets.

### Generate budgets per period

The Budgets list's **Generate** button opens a wizard: start and end date, period (month, quarter, year) and analytic plans. It creates one draft **expense** budget per period, each with a line for every combination of the accounts of the chosen plans ([budget_split_wizard.py:33](../enterprise/account_budget/wizards/budget_split_wizard.py#L33)). Enter the amounts afterwards.

---

## Key Models and Amounts

| Field | Meaning |
|---|---|
| `budget.analytic.budget_type` | `expense` (default), `revenue`, or `both`. Duplicate resets it to Expense; Revise keeps it |
| `budget.line` plan columns | One field per root plan (`account_id`, `x_plan{N}_id`); empty columns match anything |
| `budget_amount` (**Commitment**) | The planned amount ([budget_line.py:22](../enterprise/account_budget/models/budget_line.py#L22)) |
| `liquidation_amount` (**Liquidation**) | A second planned amount, equal to Commitment until you change it; not computed from payments |
| `achieved_amount` | Sum of the matching actuals from the budget report ([budget_line.py:82](../enterprise/account_budget/models/budget_line.py#L82)) |
| `achieved_percentage` | Achieved / **Liquidation** |
| `theoritical_amount` / `theoritical_percentage` | Planned progress by elapsed days (the field names are misspelled in the source) |
| `is_above_budget` | Achieved > Commitment; the form shows achieved in red for expense and both budgets |
| `committed_amount` (purchase) | Achieved + confirmed purchases not yet billed ([budget_line.py:9](../enterprise/account_budget_purchase/models/budget_line.py#L9)) |
| `committed_percentage` (purchase) | Committed / Commitment |

**Commitment** (a plan) and **Committed** (actuals plus open purchases) are different amounts.

---

## How Matching Works

`budget.report` is a SQL model built on each read, combining budget rows, analytic-item rows and (with purchases) purchase rows ([budget_report.py:63](../enterprise/account_budget/reports/budget_report.py#L63)). An analytic item counts for a budget line when:

| Condition | Rule |
|---|---|
| Date | Inside the budget's dates, both ends included |
| Company | Equal to the budget's company, or the budget has no company |
| Analytic accounts | Every plan column set on the budget line matches the item; empty columns match anything ([analytic_plan_fields_mixin.py:13](../enterprise/account_budget/models/analytic_plan_fields_mixin.py#L13)) |
| Financial account | None, or an Income / Expense group account, or `asset_current`, `asset_non_current`, `asset_fixed` ([budget_report.py:65](../enterprise/account_budget/reports/budget_report.py#L65)) |
| Budget type | Expense takes items classified `loss`, Revenue takes `revenue`, Both takes all ([budget_report.py:127](../enterprise/account_budget/reports/budget_report.py#L127)) |

Cash, receivable, payable, prepayment, liability and equity accounts never count.

**Achieved** = analytic amount × −1 for expense budgets, × 1 for revenue and both ([budget_report.py:153](../enterprise/account_budget/reports/budget_report.py#L153)). An expense debit gives a negative analytic amount, so it shows as a positive expense actual.

A department-only line counts every project of that department; a project-and-department line needs both. One analytic item can match several overlapping budget lines, so adding budgets together can count it twice.

### What each budget type counts

The classification is `analytic_profitability` on the analytic item ([account_analytic_line.py:98](../addons/account/models/account_analytic_line.py#L98)):

| Analytic item | Profitability | Expense | Revenue | Both |
|---|---|---|---|---|
| Expense account (`expense`, `expense_*`) | loss | yes | no | yes |
| Income account (`income`, `income_other`) | revenue | no | yes | yes |
| `asset_current`, `asset_non_current`, `asset_fixed` | loss | yes | no | yes |
| No account, category `other`, amount < 0 (normal timesheet) | loss | yes | no | yes |
| No account, category `other`, amount > 0 | revenue | no | yes | yes |
| No account, category `vendor_bill` | loss | yes | no | yes |
| No account, category `invoice`; or `other` with amount 0 | uncategorized | no | no | yes |
| Cash, receivable, payable, prepayments, liability, equity | not eligible | no | no | no |

Account type decides, not the sign: a credit on an expense account stays `loss` and reduces an expense budget.

### Quick reference

| | `expense` | `revenue` | `both` |
|---|---|---|---|
| Purpose | Cost ceiling | Revenue target | Net position |
| Expense lines | counted, positive | not counted | counted, negative |
| Income lines | not counted | counted, positive | counted, positive |
| Timesheets (positive hours) | counted | not counted | counted, negative |
| Vendor credit note | reduces achieved | — | increases achieved |
| Customer credit note | — | reduces achieved | reduces achieved |
| Empty-budget progress on projects | 1.0 | −1.0 | −1.0 |

For `both`, set the Commitment to the net result you target (revenues minus costs). Example: bills −100 and −300, invoices +200 and +400, manual items +200 and −100 give achieved **+300**.

---

## When the Budget Is Consumed

### Vendor bills and customer invoices

Posting creates analytic items with `amount = -balance × percentage / 100` ([analytic_accounting.md](analytic_accounting.md)). A bill line on an expense account consumes an expense budget; an invoice line on an income account fills a revenue budget. Resetting a posted entry to draft deletes its analytic items, so its achieved amount disappears; Cancel resets to draft first.

### Timesheets

`amount = -hours × employee hourly cost`, converted to the analytic account's currency at the timesheet date ([account_analytic_line.py:451](../addons/hr_timesheet/models/account_analytic_line.py#L451)). Normal hours are negative amounts, classified `loss`: they consume expense budgets. A negative-hours correction is a positive amount, classified `revenue`: it goes to revenue and both budgets instead of reducing the expense budget. Zero-cost timesheets change nothing.

### Miscellaneous journal entries

The entry must be posted and the line must carry the distribution. The line's account decides:

```
Expense budget:  DR Expense account  + analytic distribution   (counted)
                 CR Bank / payable / any account                (not needed, not counted)
Revenue budget:  CR Income account   + analytic distribution   (counted)
```

An entry between a bank account and a current-asset account: the bank line never counts; the current-asset line, if it carries a distribution, counts as a cost.

### Asset purchase and depreciation

A 1,400 bill on a Fixed Assets account with 100% distribution gives an analytic item of −1,400 on `asset_fixed`: an expense budget sees **+1,400 at once**. Depreciation entries copy the asset's distribution to both lines ([account_move.py:319](../enterprise/account_asset/models/account_move.py#L319)). For a 100 depreciation:

| Line | Analytic amount | Expense-budget achieved |
|---|---|---|
| Credit accumulated depreciation (an eligible asset type) | +100 | −100 |
| Debit depreciation expense | −100 | +100 |
| Net | 0 | 0 |

So with eligible asset accounts the budget carries the full cost from the purchase date and depreciation does not change it. The result depends on the types of the accounts involved.

### Deferred expenses and revenues

Deferral entries carry the distribution on both lines. With a Current Assets holding account (the Georgian chart's 170910 Other Prepaid Expenses is one), an expense budget takes the full bill at the bill date; with a Prepayments holding account it is consumed month by month. Details: [deferred_expenses_revenue.md](deferred_expenses_revenue.md).

### Manual analytic items

Created from Analytic Items with no financial account: the category and the sign decide (table above).

### Not counted

Draft or canceled entries; lines on cash, receivable, payable, prepayment, liability or equity accounts; items outside the dates, on other analytic accounts, or of another company when the budget has one.

---

## Purchase Commitments (`account_budget_purchase`)

A purchase order line adds a **committed** row when its order is confirmed (state `purchase`), the order date falls inside the budget, company and analytic accounts match, the budget is not a revenue budget, and the ordered quantity is above the quantity on **posted** bills net of posted refunds ([budget_report.py:12](../enterprise/account_budget_purchase/reports/budget_report.py#L12)). Draft bills do not reduce it.

```
committed row = (subtotal + non-deductible tax) / ordered qty
                × (ordered qty − billed qty) / order currency rate × analytic share
```

It is positive for expense budgets and negative for both budgets. Achieved rows also count as committed, so **Committed = Achieved + not-yet-billed purchases**.

Example: a 1,000 purchase with a posted 400 bill gives achieved 400, open commitment 600, committed 1,000.

On the purchase order, the **Budget** button opens the budget report for the order's analytic accounts. It turns red, and the lines are highlighted, when a matching open budget line's Committed, plus this order while it is not confirmed yet, exceeds its Commitment ([purchase_order.py:23](../enterprise/account_budget_purchase/models/purchase_order.py#L23), [purchase_views.xml:10](../enterprise/account_budget_purchase/views/purchase_views.xml#L10)). The line check uses only the first entry of the line's distribution ([purchase_order_line.py:25](../enterprise/account_budget_purchase/models/purchase_order_line.py#L25)).

---

## Theoretical Amount

The budget line field uses inclusive days and multiplies the elapsed share by the Commitment ([budget_line.py:94](../enterprise/account_budget/models/budget_line.py#L94)). Before the start date it already returns **one day's** share. The report's theoretical column returns **zero** before the start date ([budget_report.py:50](../enterprise/account_budget/reports/budget_report.py#L50)). Both reach the full amount at the end. It is a straight line: it does not know seasonal or front-loaded spending.

---

## Project Integration (`project_account_budget`)

A project matches budget lines through its analytic account. Only **Open and Done** budgets count ([project_project.py:24](../enterprise/project_account_budget/models/project_project.py#L24), [project_project.py:85](../enterprise/project_account_budget/models/project_project.py#L85)).

```
progress = (spent − allocated) / |allocated| × (−1 for expense, +1 for revenue and both)
```

| Spent of 500 | Expense progress | Revenue / both progress |
|---|---|---|
| 0 | 1.0 | −1.0 |
| 375 | 0.25 | −0.25 |
| 500 | 0 | 0 |
| 625 | −0.25 | 0.25 |

The project card icon: exactly −1.0 grey ("Budget allocated"), ≥ 0.25 green ("Budget on track"), ≥ 0 orange ("Budget soon overspent"), else red ("Budget overspent") ([project_project_views.xml:14](../enterprise/project_account_budget/views/project_project_views.xml#L14)). For revenue budgets, green means the target is beaten by 25%.

**Add Budget** from the project: the new line gets the project's analytic account ([budget_line.py:10](../enterprise/project_account_budget/models/budget_line.py#L10)), and a single budget created this way is opened at once ([budget_analytic.py:10](../enterprise/project_account_budget/models/budget_analytic.py#L10)).

---

## Gotchas & Non-Obvious Behavior

- **Assets count at once.** Fixed and current asset accounts are eligible, so an analytic purchase of equipment consumes the expense budget on the bill date.
- **Prepayments do not count.** `asset_prepayments` is not an eligible type: choose the deferral holding account type knowingly.
- **Draft budgets show actuals too.** Only the project panel filters by state.
- **Achieved % uses Liquidation**, Theoretical % and Committed % use Commitment.
- **Overlapping lines double count.** One item can match several budget lines.
- **Budget and analytic balance differ.** The analytic account balance has no eligibility, date or company filter.
- **The Budgets link on a journal entry** lists budgets whose lines match the entry's analytic accounts ([account_move.py:14](../enterprise/account_budget/models/account_move.py#L14)); it ignores dates and eligibility, so it does not prove the entry is counted.
- **Duplicate resets the budget type** to Expense; use Revise to keep it.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`analytic_accounting.md`](analytic_accounting.md) — plans, distributions and analytic items
- [`deferred_expenses_revenue.md`](deferred_expenses_revenue.md) — how deferrals move budget consumption

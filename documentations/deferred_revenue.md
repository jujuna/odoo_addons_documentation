# Deferred Revenue

> **Module:** `account_accountant` (+ `account_reports`) | **Path:** [`enterprise/account_accountant/`](../enterprise/account_accountant/), [`enterprise/account_reports/`](../enterprise/account_reports/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

A company invoices a customer 3,600 GEL on 1 April for a twelve-month service. Without deferral, April shows 3,600 of revenue and the following months nothing. With deferral, each month recognizes 300, and a liability shows the service still owed to the customer.

Deferral works on the invoice's journal-item balance, not on cash: it applies whether or not the customer has paid, and it does not settle the receivable. The dates and method must reflect when the service is delivered; Odoo does not read that from the invoice text.

This doc covers the customer side. Calculation methods, grouped generation internals, the cron and troubleshooting are shared with expenses: see [deferred_expenses_revenue.md](deferred_expenses_revenue.md).

---

## How It Differs from Deferred Expenses

| | Deferred expense | Deferred revenue |
|---|---|---|
| Documents | Vendor bills, refunds, receipts | Customer invoices, credit notes, receipts |
| Line account | Expense group | Income group (`income`, `income_other`) |
| Holding account (settings filter) | Current Assets or Prepayments | Current Liabilities |
| Balance-sheet meaning | Paid, not yet consumed | Invoiced, not yet earned |
| Initial reclassification | DR Holding / CR Expense | DR Revenue / CR Holding |
| Recognition | DR Expense / CR Holding | DR Holding / CR Revenue |
| Report | Deferred Expenses | Deferred Revenues |
| Settings | `deferred_expense_*` | `deferred_revenue_*` |

Both sides run through the same `_generate_deferred_entries()` ([account_move.py:280](../enterprise/account_accountant/models/account_move.py#L280)); only the account group and the settings differ.

---

## Configuration

Accounting → Configuration → Settings → Deferred Revenues ([res_config_settings_views.xml:74](../enterprise/account_accountant/views/res_config_settings_views.xml#L74)):

| Setting | Field | Values |
|---|---|---|
| Journal | `deferred_revenue_journal_id` | a Miscellaneous journal |
| Account | `deferred_revenue_account_id` | a Current Liabilities account (Georgian chart: 310610 Deferred Income (Advances Received), [template_ge.py:41](../addons/l10n_ge/models/template_ge.py#L41)) |
| Generate Entries | `generate_deferred_revenue_entries_method` | On invoice validation (default), Manually & Grouped |
| Periodicity | `deferred_revenue_periodicity` | Monthly (default), Yearly; shown for on-validation only |
| Computation | `deferred_revenue_amount_computation_method` | By Months (default), By Days, By Full Months |

Source: [res_company.py:55](../enterprise/account_accountant/models/res_company.py#L55). An income account can also carry **Deferred** (dates required on its lines) and its own **Deferred Account** ([account_account.py:8](../enterprise/account_accountant/models/account_account.py#L8)). The invoice keeps the normal revenue account; the holding account is used only in the deferral entries.

---

## Walkthrough: 3,600 GEL Annual Service Invoice

GEL company, By Months, Monthly, on invoice validation, no tax, invoice date 1 April 2026.

1. Set the revenue journal and holding account in Settings.
2. Create the invoice on the service's income account.
3. Enter the deferred dates **1 April 2026 – 31 March 2027** under the Account cell (switch on the optional Deferred Date column if the account is not flagged Deferred).
4. Add the analytic distribution if needed.
5. Confirm, then open **Deferral Entries**.

| Entry | Date | Debit | Credit | Amount |
|---|---|---|---|---|
| Invoice | 1 Apr | Receivable | Service revenue | 3,600 |
| Reclassification | 1 Apr | Service revenue | Deferred revenue | 3,600 |
| Recognition | 30 Apr | Deferred revenue | Service revenue | 300 |
| Recognition | each month end to 31 Mar 2027 | Deferred revenue | Service revenue | 300 |

After April: liability 3,300, recognized revenue 300. Recognitions dated on or before the confirmation day post at once; the others wait as drafts with Auto-post "At Date" until the daily cron posts them on their date.

### Why the signs work

A revenue line's balance is negative. The reclassification writes −1 × balance on the revenue account and +1 × balance on the holding account: debit revenue, credit liability. Each recognition writes the period share with +1 on revenue and −1 on holding: credit revenue, debit liability ([account_move.py:351](../enterprise/account_accountant/models/account_move.py#L351)). Expense lines have positive balances, so the same code gives the expense directions.

### Other amounts

For partial months, days-based splits and Full Months see [Calculation Methods](deferred_expenses_revenue.md#calculation-methods). A 900 GEL service for 15 April – 14 June gives 240 / 450 / 210 by months and 450 / 450 / 0 by full months. Yearly periodicity creates one recognition per fiscal year.

---

## Manually & Grouped

Nothing is created at posting. At each month end, open Accounting → Review → Regularization Entries → **Deferred Revenues**, select the month and click **Generate entry** ([account_deferred_reports.py:514](../enterprise/account_reports/models/account_deferred_reports.py#L514)). The period must end on a month end and must not be locked.

For 3,600 invoiced with 300 earned by 30 April:

```
30 April:  DR Service revenue 3,300 / CR Deferred revenue 3,300
1 May:     DR Deferred revenue 3,300 / CR Service revenue 3,300   (reversal)
```

At 31 May a new adjustment sets the remaining 3,000 aside, and so on.

---

## Deferred Revenues Report

Menu: Accounting → Review → Regularization Entries → Deferred Revenues ([menuitems.xml:31](../enterprise/account_reports/data/menuitems.xml#L31)). It lists lines on `income` and `income_other` accounts with both dates ([account_deferred_reports.py:39](../enterprise/account_reports/models/account_deferred_reports.py#L39)).

Viewing April 2026 for the example:

| Total | Not Started | Before | April 2026 | Recognized | ≤ 12 Months | > 12 Months |
|---|---|---|---|---|---|---|
| 3,600 | 0 | 0 | 300 | 300 | 3,300 | 0 |

A line whose start, end and invoice date are all inside the selected period is hidden: a contract invoiced and fully delivered within one year vanishes from a full-year view. Select a month. Column meanings and the Group by option: [Deferred Reports](deferred_expenses_revenue.md#deferred-reports).

---

## Taxes, Analytics and Reports

### VAT

Output VAT is on a tax account, not an income account, so it is never deferred: it stays on the invoice date and in that period's tax report. Only tax amounts posted to the income account itself (distribution lines not used in the tax closing) take the line's dates ([account_tax.py:28](../enterprise/account_accountant/models/account_tax.py#L28)).

For a 3,540 invoice (3,000 + 540 VAT at 18%): 540 is output VAT on the invoice date; 3,000 is spread.

### Analytic distribution and budgets

Both lines of each deferral entry carry the invoice's distribution. The revenue account gives +3,600 at invoicing, −3,600 at reclassification and +300 at each recognition. Current Liabilities accounts do not count for budgets, so a **revenue budget** follows the monthly recognition. The analytic account balance also includes the holding-side items, so it can differ from the budget. See [analytic_budget.md](analytic_budget.md).

### Financial reports

| Report | What it shows |
|---|---|
| Balance Sheet | Deferred revenue under Current Liabilities: invoiced, not yet earned |
| Profit & Loss | Only the posted recognitions of each period |
| Cash | The receivable is settled by payments, independently of the deferral |

Recognition uses the invoice's company-currency amount; it is not revalued each month.

---

## Credit Notes and Changes

- A credit note made from the invoice (reversal) copies the deferred dates ([account_move.py:656](../enterprise/account_accountant/models/account_move.py#L656)) and gets its own schedule with opposite signs. For an early termination, change the credit note's dates or amount before confirming; Odoo does not work out the remaining period.
- A customer credit note uses the revenue generation mode but the **expense periodicity** (money goes out). With different periodicities on the two sides its schedule does not mirror the invoice's ([account_move.py:161](../enterprise/account_accountant/models/account_move.py#L161)).
- Reset to draft deletes or reverses the deferral entries; it is refused for an invoice included in a grouped entry: create a credit note instead ([account_move.py:120](../enterprise/account_accountant/models/account_move.py#L120)).
- The account of a deferred line with entries cannot be changed ([account_move.py:664](../enterprise/account_accountant/models/account_move.py#L664)).

---

## Common Mistakes

| What went wrong | How to recognize it | Fix |
|---|---|---|
| Report empty | Full-year period containing the whole contract | Select a month |
| No deferral entries | Start, end and invoice date in the same month; Manually & Grouped mode | Extend the dates or generate from the report |
| Odd monthly amounts | End date = first of the next month (warning color on the dates) | Use the last day of the service |
| Revenue and holding account are the same | Entries net to zero | Use a separate Current Liabilities account |
| Want to edit a grouped invoice | Reset to draft refused | Use a credit note |
| Entry stays draft after its date | Cron error; Auto-post set to No | Read the chatter, fix, post by hand |

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`deferred_expenses_revenue.md`](deferred_expenses_revenue.md) — shared mechanics, calculation methods, cron, troubleshooting
- [`analytic_budget.md`](analytic_budget.md) — revenue budgets and deferrals
- [`accounting_reports.md`](accounting_reports.md) — reporting engine
- [`accounting_coa.md`](accounting_coa.md) — account types

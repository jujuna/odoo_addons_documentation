# Deferred Expenses and Revenues

> **Module:** `account_accountant` (+ `account_reports`) | **Path:** [`enterprise/account_accountant/`](../enterprise/account_accountant/), [`enterprise/account_reports/`](../enterprise/account_reports/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

A company pays 1,200 GEL on 1 January for a one-year software license. Without deferral, January shows a 1,200 expense and February to December nothing. With deferral, each month shows 100, and the balance sheet shows how much of the prepayment is still unused. Revenue works the same way: a 3,600 GEL annual service invoiced in April is recognized 300 per month.

Deferral works on **journal-item balances**, not on payments. A bill can be deferred before it is paid, an invoice before it is collected. Accountants use it for prepaid licenses, insurance, rent, support contracts and subscriptions billed in advance. For the customer-invoice walkthrough see [deferred_revenue.md](deferred_revenue.md).

---

## The Big Picture — How It Works

| Entry | Expense deferral | Revenue deferral |
|---|---|---|
| Original bill / invoice | DR Expense / CR Payable | DR Receivable / CR Revenue |
| Initial reclassification (bill date) | DR Holding asset / CR Expense | DR Revenue / CR Holding liability |
| Each recognition (period end) | **DR Expense / CR Holding asset** | **DR Holding liability / CR Revenue** |

```
Bill line with deferred dates ──► Post
   ├── On bill validation:  reclassification (bill date) + one recognition per period,
   │                        future ones scheduled and posted by the daily cron
   └── Manually & Grouped:  nothing at posting; at month end the Deferred Expenses report
                            "Generate entry" posts one grouped adjustment + its reversal next day
```

### Key decision points

- **Generation mode:** one schedule per line at posting, or one grouped month-end adjustment.
- **Computation:** by months (30-day months), by days, or by full months.
- **Periodicity:** monthly or yearly recognition entries (on-validation mode).
- **Holding account type:** Current Assets or Prepayments for expenses. It decides how analytic budgets see the cost (see Analytics and Budgets).

---

## When to Use It (and When Not To)

### Use it for:

| Situation | Example |
|---|---|
| Annual software license | 12-month subscription paid upfront |
| Support or maintenance contract | Yearly IT maintenance |
| Prepaid insurance | Property insurance for the year |
| Prepaid rent | Six months of office rent |
| Revenue billed in advance | Annual SaaS subscription, retainer, membership |

### Do not use it for:

- Monthly bills paid as you go — post them to expense directly.
- Purchases consumed within the month.
- Fixed assets — use the Assets module (`account_asset`).

---

## Configuration

Accounting → Configuration → Settings → Deferred Expenses / Deferred Revenues ([res_config_settings_views.xml:48](../enterprise/account_accountant/views/res_config_settings_views.xml#L48)). Fields live on the company ([res_company.py:17](../enterprise/account_accountant/models/res_company.py#L17)); expense and revenue are set independently.

| Setting | Values | What it changes |
|---|---|---|
| Journal | a Miscellaneous journal | Where deferral entries go. Required: "Please set the deferred journal in the accounting settings." |
| Account | expense side: Current Assets or Prepayments; revenue side: Current Liabilities (selection filters) | Default holding account |
| Generate Entries | On bill (invoice) validation (default), Manually & Grouped | When entries are created |
| Periodicity | Monthly (default), Yearly; shown only for on-validation | One recognition entry per month or per fiscal year |
| Computation | By Months (default), By Days, By Full Months | How the amount is split |

When a chart does not set them, loading it picks the Miscellaneous journal and the chart's first Current Assets / Current Liabilities account ([account_chart_template.py:10](../enterprise/account_accountant/models/account_chart_template.py#L10)). The Georgian chart sets 170910 Other Prepaid Expenses (Current Assets) and 310610 Deferred Income (Advances Received) (Current Liabilities) ([template_ge.py:39](../addons/l10n_ge/models/template_ge.py#L39)).

### Per account

On an Expenses, Other Expenses, Income or Other Income account ([account_account_views.xml:27](../enterprise/account_accountant/views/account_account_views.xml#L27), [account_account.py:8](../enterprise/account_accountant/models/account_account.py#L8)):

- **Deferred** — deferred dates become required on invoice and bill lines using this account.
- **Deferred Account** — holding account for this account; it wins over the company default, in both generation modes.

---

## Which Lines Can Be Deferred

[`_has_deferred_compatible_account()`](../enterprise/account_accountant/models/account_move.py#L759):

| Document | Account internal group |
|---|---|
| Vendor bill, refund, receipt | Expense |
| Customer invoice, credit note, receipt | Income |
| Journal entry | Expense or Income |

On any other account the dates are cleared. A journal entry mixing deferred expense and income lines is refused when the two sides use different generation modes: "Having different deferred entries generation methods for expenses and revenues is not supported on journal entries involving both expense and revenue accounts." ([account_move.py:141](../enterprise/account_accountant/models/account_move.py#L141)).

### Entering the dates

- **Invoice and bill lines:** a date range under the Account cell. It shows when the account is flagged Deferred, or when the optional **Deferred Date** column is switched on in the lines' column menu ([m2o_cell_with_extra_fields.js:9](../enterprise/account_accountant/static/src/components/m2o_cell_with_extra_fields/m2o_cell_with_extra_fields.js#L9)). It turns read-only once deferral entries exist.
- **Journal Items tab:** an optional **Deferred Date** range column ([account_move_views.xml:61](../enterprise/account_accountant/views/account_move_views.xml#L61)).

Both dates are **inclusive**; the end date need not be a month end. A start without an end, or a start after the end, is refused ([account_move.py:796](../enterprise/account_accountant/models/account_move.py#L796)). Setting one date copies it to the other if empty; an end date without a start takes the invoice date as start ([account_move.py:790](../enterprise/account_accountant/models/account_move.py#L790)). A range of N months plus one day (1 January – 1 January) is flagged with a warning color: use 31 December ([account_move.py:740](../enterprise/account_accountant/models/account_move.py#L740)).

---

## Walkthrough: Annual Vendor Bill

1,200 GEL, 1 January – 31 December, By Months, Monthly, on validation, no tax.

1. Set the expense journal and holding account in Settings.
2. Enter the bill on its normal expense account with both dates; add the analytic distribution if needed.
3. Confirm the bill. Open **Deferral Entries** (smart button) to see the schedule.

| Entry | Date | Debit | Credit | Amount |
|---|---|---|---|---|
| Bill | 1 Jan | Expense | Payable | 1,200 |
| Reclassification | 1 Jan (bill accounting date) | Holding asset | Expense | 1,200 |
| Recognition | 31 Jan | Expense | Holding asset | 100 |
| Recognition | each month end to 31 Dec | Expense | Holding asset | 100 |

After January the holding account shows 1,100 and the P&L 100. At the end the holding balance is zero. Paying the bill changes none of this.

### Partial months

33 GEL, 10 March – 11 July, bill accounting date 9 March, By Months:

| Entry | Date | Amount |
|---|---|---|
| Reclassification | 9 March | 33.00 |
| Recognition | 31 March | 5.68 |
| Recognition | 30 April | 8.11 |
| Recognition | 31 May | 8.11 |
| Recognition | 30 June | 8.11 |
| Recognition | 11 July | 2.99 |

The last period ends on the end date and takes the remainder, so the total is exactly 33.00.

---

## Calculation Methods

Sources: [`_get_deferred_diff_dates()`](../enterprise/account_accountant/models/account_move.py#L182), [`_get_deferred_period_amount()`](../enterprise/account_accountant/models/account_move.py#L201).

| Method | How a period is weighted |
|---|---|
| By Months | 30-day months: a month end counts as day 30, so February, March and April weigh the same |
| By Days | Actual calendar days |
| By Full Months | Boundaries moved to the first of their month: a started month counts in full, a short final month can get nothing |

900 GEL, 15 April – 14 June, monthly:

| Method | April | May | June |
|---|---|---|---|
| By Months | 240 | 450 | 210 |
| By Full Months | 450 | 450 | 0 (entry deleted) |

900 GEL, 1 April – 30 June, By Days (91 days): 296.70, 306.59, 296.71.

With By Full Months, when the span from the first day of the start month to the end date is under two months, Odoo moves the end date back one month before the same-month check ([account_move.py:315](../enterprise/account_accountant/models/account_move.py#L315)). So 100 GEL for 15 March – 14 April, posted in March, is **not deferred at all**; By Months gives 53.33 / 46.67.

---

## On Validation

`_post()` generates the schedule for moves in this mode ([account_move.py:112](../enterprise/account_accountant/models/account_move.py#L112)). `_generate_deferred_entries()` returns unless the move is really posted, so a future-dated bill only scheduled for posting gets its schedule when the cron posts it ([account_move.py:280](../enterprise/account_accountant/models/account_move.py#L280)).

For each deferred line:

1. Skips the line when start month, end month and the bill's accounting month are the same ([account_move.py:322](../enterprise/account_accountant/models/account_move.py#L322)), and when there is a single period starting in the accounting month ([account_move.py:830](../enterprise/account_accountant/models/account_move.py#L830)).
2. Takes the account's Deferred Account, else the company default; neither raises "Please set a deferred account on the related account or in the accounting settings."
3. Creates the reclassification at the bill's accounting date and one recognition per period, dated at the period end (the last one at the end date).
4. Forces the last amount to the remaining balance; deletes zero-amount entries.
5. Posts with `_post(soft=True)`: entries dated today or earlier post at once; later ones stay draft with Auto-post "At Date".

Each deferral line keeps the source line's analytic distribution, product and partner. Taxes are not recomputed on deferral entries, so a default tax on the expense account is not added ([account_move.py:878](../enterprise/account_accountant/models/account_move.py#L878)).

### Yearly periodicity

Periods follow the company's fiscal years (`compute_fiscalyear_dates`), clipped to the deferral dates. Computation and periodicity are independent: yearly entries can still be computed by months or days.

### Which settings a document uses

| Document | Generation mode | Periodicity |
|---|---|---|
| Vendor bill, vendor refund | expense | bill: expense; **vendor refund: revenue** |
| Customer invoice, credit note | revenue | invoice: revenue; **customer credit note: expense** |
| Journal entry | by the deferred lines' accounts | revenue |

Periodicity follows the money direction (`is_outbound()`), not the account ([account_move.py:161](../enterprise/account_accountant/models/account_move.py#L161)). It matters only when the two periodicities differ.

---

## Manually & Grouped

Nothing happens at posting. At month end, open Accounting → Review → Regularization Entries → **Deferred Expenses** (or Deferred Revenues), select the month and click **Generate entry** ([account_deferred_reports.py:514](../enterprise/account_reports/models/account_deferred_reports.py#L514)).

- The selected period must **end on the last day of a month**: "You cannot generate entries for a period that does not end at the end of the month." This applies to the report period, not to invoice lines.
- A locked period is refused: "You cannot generate entries for a period that is locked."
- Only posted originals are included; originals already covered by an entry at that date (posted, or scheduled for the future) are skipped.

It creates two entries: at the period end, a grouped adjustment that leaves on the expense accounts only what is recognized so far and moves the rest to the holding accounts; the next day, its exact reversal ("Reversal of Grouped Deferral Entry of ..."). Both go through `_post(soft=True)`. The reversal clears the snapshot, so next month's generation builds a fresh one.

Example: 1,200 of which 100 is recognized at 31 January: DR Holding 1,100 / CR Expense 1,100 on 31 January, reversed on 1 February.

Lines are grouped by original account and by holding account. Analytic distribution is weighted by each source line's balance. The link to every original bill is written directly in SQL, so a grouped entry keeps no partner or product per bill; open it through the original.

**Source defect:** the grouped generation passes a boolean where the expense/revenue type is expected, so grouped **expense** entries are computed with the **revenue** computation method ([account_deferred_reports.py:511](../enterprise/account_reports/models/account_deferred_reports.py#L511), [account_deferred_reports.py:588](../enterprise/account_reports/models/account_deferred_reports.py#L588)). The report columns use the right method. Keep both computation methods equal when you use Manually & Grouped for expenses.

---

## Deferred Reports

Accounting → Review → Regularization Entries → Deferred Expenses / Deferred Revenues ([menuitems.xml:31](../enterprise/account_reports/data/menuitems.xml#L31)).

| Column | Meaning |
|---|---|
| Total | Full amount of the lines shown |
| Not Started | Deferrals starting after the selected period |
| Before | Share of periods before the selected one |
| (selected periods) | Share of each selected period |
| Recognized | Share up to the end of the selected period |
| ≤ 12 Months | Still to recognize within 12 months after the period |
| > 12 Months | Still to recognize after that |

Sources: [account_deferred_reports.py:197](../enterprise/account_reports/models/account_deferred_reports.py#L197). Amounts are computed from the source lines' dates and balances; they are not a sum of posted deferral entries. **Group by** switches between Account, Product Category and Product. Click an amount to see the journal items.

Which lines appear ([account_deferred_reports.py:39](../enterprise/account_reports/models/account_deferred_reports.py#L39)):

- Expense report: account types `expense`, `expense_depreciation`, `expense_direct_cost`. Revenue report: `income`, `income_other`. An **Other Expenses** line can be deferred but does not appear in the expense report.
- A line whose start date, end date **and** bill date all fall inside the selected period is hidden ([account_deferred_reports.py:26](../enterprise/account_reports/models/account_deferred_reports.py#L26)). A deferral fully inside one year disappears from a full-year view: select a month.

In manual mode a banner says whether entries were never, partly or fully generated for the period ([account_deferred_reports.py:382](../enterprise/account_reports/models/account_deferred_reports.py#L382)).

---

## Taxes, Currency, Analytics and Budgets

### Taxes

Deferral moves only income and expense lines. A normal VAT line sits on a tax account and stays in the bill's period. Tax amounts posted to the expense or income account itself (tax distribution lines not used in the tax closing, such as non-deductible VAT) take the line's dates and are deferred with it ([account_tax.py:28](../enterprise/account_accountant/models/account_tax.py#L28)).

For a 1,180 bill (1,000 net + 180 VAT): 180 goes to the VAT account on the bill date; the 1,000 is spread.

### Currency

Recognition uses the source line's company-currency balance: the rate of the bill date stays, there is no monthly revaluation. The amounts are rounded with the document currency's precision ([account_move.py:375](../enterprise/account_accountant/models/account_move.py#L375)). Payment exchange differences are separate: [currency_exchange_transit.md](currency_exchange_transit.md).

### Analytics and budgets

Both lines of every deferral entry carry the source distribution, so analytic items follow the usual `amount = -balance` rule on both sides. What an **expense budget** sees depends on the holding account type ([analytic_budget.md](analytic_budget.md)):

| Posting | Analytic amount | Budget, holding = Current Assets | Budget, holding = Prepayments |
|---|---|---|---|
| Bill, expense debit 1,200 | −1,200 | +1,200 | +1,200 |
| Reclassification, expense credit | +1,200 | −1,200 | −1,200 |
| Reclassification, holding debit | −1,200 | +1,200 | not counted |
| Recognition, expense debit 100 | −100 | +100 | +100 |
| Recognition, holding credit 100 | +100 | −100 | not counted |
| **Net at bill date / per month** | | **1,200 / 0** | **0 / 100** |

Current Assets accounts count for budgets and Prepayments accounts do not. With the Georgian default (170910, Current Assets) the expense budget takes the full bill on the bill date. Revenue holding accounts (Current Liabilities) never count, so a revenue budget follows the monthly recognition.

---

## Resetting, Editing and Credit Notes

- **Reset to draft** ([account_move.py:120](../enterprise/account_accountant/models/account_move.py#L120)) is refused when a deferral entry covers more than one original (grouped mode): "You cannot reset to draft an invoice that is grouped in deferral entry. You can create a credit note instead." Otherwise each deferral entry is:
  - deleted if it was never posted;
  - deleted if posted in an open period (canceled instead when the company keeps a restrictive audit trail);
  - reversed if it is in a locked period or hashed; the reversal is dated in the first open period ([account_move.py:5920](../addons/account/models/account_move.py#L5920)).
- **Changing the account** of a deferred line with entries is refused ([account_move.py:664](../enterprise/account_accountant/models/account_move.py#L664)). Changing the dates on a posted bill does not rebuild the schedule: reset to draft, fix, confirm again.
- **Credit notes:** Duplicate does not copy the dates, but a credit note made by reversal does ([account_move.py:656](../enterprise/account_accountant/models/account_move.py#L656)). The credit note gets its own opposite schedule for the same dates. For an early termination, change its dates before confirming.

---

## Automatic Posting

The daily cron "Account: Post draft entries with auto_post enabled and accounting date up to today" posts draft entries dated today or earlier with Auto-post set ([service_cron.xml:3](../addons/account/data/service_cron.xml#L3), [account_move.py:7155](../addons/account/models/account_move.py#L7155)). A missed day is caught up on the next run. When an entry fails (a lock date, for example), the cron posts the error in its chatter and sets Auto-post to **No**: it will not be retried by itself. Fix the cause, then post it by hand.

---

## Troubleshooting

| What went wrong | Why | Fix |
|---|---|---|
| No deferral entries | Manual mode; line not deferrable; start, end and bill date in one month; Full Months short range | Check the mode, the account type and the dates |
| Report is empty | Period contains the whole deferral and the bill date; account type not in the report filter (Other Expenses) | Select a month; use an Expenses account |
| Odd split amounts | End date = first day of the next month | Use the last day of the period |
| Last partial month gets 0 | By Full Months | Expected; the zero entry is deleted |
| Recognition is yearly | Periodicity Yearly for that side (refunds use the other side's) | Check both periodicities |
| Cannot reset a grouped bill | A deferral entry covers several bills | Use a credit note |
| Entry stays draft after its date | Cron error; Auto-post was set to No | Read the chatter, fix, post by hand |
| Budget takes the whole bill at once | Holding account is Current Assets | Use a Prepayments holding account if the budget must follow recognition |
| Entries net to zero | Holding account = the expense account | Use a separate holding account |

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`deferred_revenue.md`](deferred_revenue.md) — customer-invoice walkthrough
- [`analytic_budget.md`](analytic_budget.md) — what budgets count
- [`analytic_accounting.md`](analytic_accounting.md) — analytic items from deferral entries
- [`currency_exchange_transit.md`](currency_exchange_transit.md) — foreign-currency bills

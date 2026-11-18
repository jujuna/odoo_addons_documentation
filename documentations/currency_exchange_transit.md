# Currency Exchange and Transit Accounts

> **Module:** `account` (+ `accountant`, `account_accountant`, `account_reports`) | **Path:** [`addons/account/`](../addons/account/), [`odoo/addons/base/models/res_currency.py`](../odoo/addons/base/models/res_currency.py)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

Every journal item keeps two amounts: `balance` in company currency and `amount_currency` in the line's own currency. A USD bill booked at one rate and paid at another leaves the payable at zero in USD but not in GEL. Reconciliation closes that gap with an **exchange difference** entry, a realized gain or loss.

A **transit account** solves a different problem: money that leaves one bank account and arrives in another, often in another currency and on another day. Each bank records its own transaction; the transit account holds the amount in between.

At period end, the **currency revaluation** (Enterprise) restates open foreign-currency balances at the closing rate with an entry that reverses the next day, an unrealized gain or loss.

| Concept | Purpose |
|---|---|
| `balance`, `amount_currency` | Signed amounts in company currency and in the line currency |
| `amount_residual`, `amount_residual_currency` | What is still open, in both currencies |
| Transfer account ("Internal Transfer" setting) | Clearing account for bank-to-bank movements |
| Outstanding Receipts / Payments | Clearing accounts between a registered payment and the bank transaction |
| Bank suspense | Temporary counterpart of a bank transaction not yet matched |
| Exchange gain / loss accounts | Realized differences created by reconciliation |
| Revaluation provision accounts | Unrealized differences posted by the revaluation wizard |

---

## The Big Picture — How It Works

```
Invoice / bill (rate on its date)  ──►  Payment or bank transaction (rate on its date)
                                              │
                                              ▼
                              Reconciliation matches the open items
                                              │
              amounts match in the foreign currency but not in company currency
                                              ▼
                   Exchange difference entry (gain or loss) closes the gap

Bank A transaction ──► Transfer account ◄── Bank B transaction      (internal transfer)
Month end: Multicurrency Revaluation ──► adjustment + reversal next day (unrealized)
```

---

## Configuration

1. **Multi-Currencies** — General Settings. It is the `base.group_multi_currency` group, defined in `base_setup` ([res_config_settings.py:31](../addons/base_setup/models/res_config_settings.py#L31)).
2. **Currencies and rates** — activate the currencies and enter rates, or enable **Automatic Currency Rates** in Accounting settings (`currency_rate_live`, [res_config_settings.py:98](../addons/account/models/res_config_settings.py#L98)). For a Georgian company the default provider is the National Bank of Georgia ([res_config_settings.py:159](../enterprise/currency_rate_live/models/res_config_settings.py#L159)).
3. **One bank journal per currency** — see [bank_journal_multicurrency_setup.md](bank_journal_multicurrency_setup.md).
4. **Default accounts** — Accounting → Configuration → Settings → Default Accounts:

| Setting | Field | Rule |
|---|---|---|
| Exchange difference entries → Journal | `currency_exchange_journal_id` | a Miscellaneous journal; shown only with Multi-Currencies ([res_config_settings_views.xml:296](../addons/account/views/res_config_settings_views.xml#L296)) |
| Gain | `income_currency_exchange_account_id` | an income-group account ([company.py:137](../addons/account/models/company.py#L137)) |
| Loss | `expense_currency_exchange_account_id` | an Expenses or Other Expenses account ([company.py:142](../addons/account/models/company.py#L142)) |
| Internal Transfer | `transfer_account_id` | a reconcilable Current Assets account ([company.py:116](../addons/account/models/company.py#L116)) |

The chart creates these. The generic chart creates "Funds in Transit" as the transfer account ([chart_template.py:904](../addons/account/models/chart_template.py#L904)). The Georgian chart uses 100001 Liquidity Transfer, 810110 Foreign Exchange Gains Realized and 820110 Foreign Exchange Losses Realized ([template_ge.py:32](../addons/l10n_ge/models/template_ge.py#L32)).

5. **Outstanding accounts** — each payment method line of a bank journal has an optional Outstanding Receipts / Payments account (Incoming / Outgoing Payments tabs). They are empty by default except in a few localizations ([account_journal.py:1089](../addons/account/models/account_journal.py#L1089)). What that changes is explained in "Payments" below.

### Which rate is used

`_get_rates()` resolves the company to its root company (branches share the parent's rates), then takes the latest rate dated **strictly before** the requested date. With no earlier rate it takes the oldest rate, and with none at all it uses 1.0 ([res_currency.py:171](../odoo/addons/base/models/res_currency.py#L171)). So **a rate applies from the day after its date**: a rate entered on 14 March values documents dated 15 March onward. Enter a rate dated the day before the first day it should apply. `_convert()` rounds the result in the target currency ([res_currency.py:356](../odoo/addons/base/models/res_currency.py#L356)).

The examples below give the effective rate of each document.

---

## Payments: When a Journal Entry Exists

A payment's outstanding account comes from its payment method line ([account_payment.py:687](../addons/account/models/account_payment.py#L687)). A payment gets its own journal entry only if it has one ([account_payment.py:1145](../addons/account/models/account_payment.py#L1145)).

| Setup | Payment entry | What happens next |
|---|---|---|
| Enterprise (`accountant` installed), no outstanding account on the method line | None. Posting sets the payment to **Paid**; the invoice shows **In Payment** | The bank transaction is matched with the invoice itself; the payment becomes **Reconciled** ([account_bank_statement.py:2208](../enterprise/account_accountant/models/account_bank_statement.py#L2208)) |
| Outstanding account set on the method line | DR/CR receivable or payable against the outstanding account, created when posted | The bank transaction is matched with the outstanding line |
| Community (no `accountant`) | Always: an empty outstanding account is filled from the chart's Outstanding Receipts/Payments, else the transfer account ([account_payment.py:986](../addons/account/models/account_payment.py#L986), [account_payment.py:1012](../addons/account/models/account_payment.py#L1012)) | No bank matching tool |

`accountant` switches the invoice state to In Payment ([account_move.py:7](../enterprise/accountant/models/account_move.py#L7)), and that switch is how `create()` knows not to force a payment entry. The context key `force_payment_move` forces one anyway; the bank reconciliation uses it for early-payment discounts ([account_bank_statement.py:1636](../enterprise/account_accountant/models/account_bank_statement.py#L1636)).

---

## Example 1: A USD Vendor Bill in a GEL Company

A bill of USD 5,000 is valued at 2.70 GEL/USD; the payment at 2.75. No tax.

**Bill:**

| Account | Debit GEL | Credit GEL | USD |
|---|---|---|---|
| Expenses | 13,500 | | 5,000 |
| Accounts Payable | | 13,500 | -5,000 |

**Payment, Enterprise without outstanding account:** Register Payment creates no entry. When the USD bank transaction is matched with the bill, the bank entry is:

| Account | Debit GEL | Credit GEL | USD |
|---|---|---|---|
| Accounts Payable | 13,750 | | 5,000 |
| Bank USD | | 13,750 | -5,000 |

With an outstanding account, the same lines appear on the payment entry with Outstanding Payments instead of the bank, and the bank match later clears Outstanding Payments.

**Exchange difference:** the payable is settled in USD, but 13,750 − 13,500 = 250 GEL stays open. Reconciliation posts:

| Account | Debit GEL | Credit GEL |
|---|---|---|
| Loss Exchange Rate Account | 250 | |
| Accounts Payable | | 250 |

**Gain or loss:** a positive amount to fix on the reconciled line takes the loss account, anything else the gain account ([account_move_line.py:3310](../addons/account/models/account_move_line.py#L3310)). With the rates reversed (bill at 2.75, payment at 2.70) the same bill gives DR Accounts Payable 250 / CR Gain Exchange Rate Account 250.

No exchange entry appears when both rates are equal or when all lines are in company currency.

---

## Example 2: Internal Transfer USD → EUR (Company Currency USD)

The company moves USD 138.66 from its USD bank; the EUR bank receives EUR 120. Effective rate 1.1555 USD/EUR, no fee.

Odoo 20 has no internal-transfer payment: `is_internal_transfer` and `destination_journal_id` do not exist in 20.0. Record the two bank transactions and clear them through the transfer account.

1. **USD bank transaction** (-138.66): in bank reconciliation, book it to the transfer account. The chart ships an "Internal Transfers" reconciliation model that books 100% to the transfer account ([chart_template.py:1210](../addons/account/models/chart_template.py#L1210), [chart_template.py:799](../addons/account/models/chart_template.py#L799)).
2. **EUR bank transaction** (+120): match it with the open transfer line from step 1 ([account_bank_statement.py:1720](../enterprise/account_accountant/models/account_bank_statement.py#L1720)).

| Entry | Account | Debit USD | Credit USD | Line currency |
|---|---|---|---|---|
| USD bank transaction | Transfer account | 138.66 | | USD 138.66 |
| | Bank USD | | 138.66 | USD -138.66 |
| EUR bank transaction | Bank EUR | 138.66 | | EUR 120.00 |
| | Transfer account | | 138.66 | depends on the matched line |

The two transfer lines reconcile and the transfer account is back to zero. A difference remains when the company-currency values differ: another date and rate on the second side, the bank's own conversion rate, or a fee. Reconciling the transfer lines then creates an exchange entry; book a bank fee as a fee first, or it ends up in the exchange result.

Manual journal entries are not a shortcut here: the Journal Items tab of a journal entry does not list Bank and Cash accounts ([account_move_views.xml:1536](../addons/account/views/account_move_views.xml#L1536)). Bank movements are recorded as bank transactions.

The Georgian chart's 100001 Liquidity Transfer is reconcilable, so it can clear both sides. A transfer account with no currency is not in the revaluation report, so a transfer still open at month end is not revalued (see Revaluation below).

---

## Example 3: A EUR Receipt for a USD Invoice (Company Currency GEL)

A USD 3,000 invoice is valued at 2.70 (8,100 GEL). The customer pays EUR 2,760 at 2.94 (8,114.40 GEL). On the receipt date USD is worth 2.75, so USD 3,000 would be 8,250 GEL.

Lines in two different foreign currencies reconcile in company currency ([account_move_line.py:2597](../addons/account/models/account_move_line.py#L2597)), because a EUR line offers only EUR and GEL amounts and a USD line only USD and GEL ([account_move_line.py:2477](../addons/account/models/account_move_line.py#L2477)). Reconciling a EUR receipt already booked on the receivable with the invoice therefore settles 8,100 GEL:

- the invoice is fully matched in GEL, and its USD residual follows at the invoice's own rate, so no exchange entry is created;
- 14.40 GEL (EUR 4.90) stays open on the receipt as a customer credit.

In bank reconciliation the receivable line is sized to what the invoice still owes, and the rest of the bank transaction stays on the suspense account for further matching.

Whether USD 3,000 was really paid is a business question: at the receipt-date rates the customer paid 135.60 GEL less than USD 3,000. When the payment is registered from the invoice, the payment wizard shows the difference and lets you keep it open or mark the invoice as fully paid with a write-off ([account_payment_register.py:145](../addons/account/wizard/account_payment_register.py#L145)).

---

## How Things Work Under the Hood

### Exchange differences during reconciliation

`reconcile()` builds a reconciliation plan ([account_move_line.py:3468](../addons/account/models/account_move_line.py#L3468), [account_move_line.py:3109](../addons/account/models/account_move_line.py#L3109)). Each debit/credit pair becomes a partial reconciliation in `_prepare_reconciliation_single_partial()` ([account_move_line.py:2552](../addons/account/models/account_move_line.py#L2552)):

1. **Reconciliation currency:** the lines' shared foreign currency when both can express it, otherwise company currency.
2. **What gets fixed** ([account_move_line.py:2757](../addons/account/models/account_move_line.py#L2757)):
   - company-currency reconciliation: when a line is fully matched, the leftover **foreign** amount is fixed;
   - foreign-currency reconciliation (the common case: USD bill, USD payment): when a line is fully matched, the leftover **company-currency** amount is fixed; a partly matched line is fixed so its open amounts keep the line's own rate.
3. **The entry** ([account_move_line.py:3315](../addons/account/models/account_move_line.py#L3315)): two lines per fixed item, one on the item's account (reconciled with it), one on the gain or loss account; an optional exchange analytic distribution goes on the gain/loss line. Journal: the exchange journal. Date: the latest of the reconciled lines' dates, moved forward past lock dates by the journal.
4. **Posting** ([account_move_line.py:3414](../addons/account/models/account_move_line.py#L3414)): missing journal or gain/loss account raises "You have to configure the 'Exchange Gain or Loss Journal'..." or the gain/loss equivalent. The entry is posted only when both reconciled items are posted ([account_move_line.py:2826](../addons/account/models/account_move_line.py#L2826)).

The context keys `no_exchange_difference` and `no_exchange_difference_no_recursive` skip this computation; Odoo sets the first when it creates the exchange entries themselves.

### Unreconciling

Removing a partial reconciliation handles its exchange entry through `_unlink_or_reverse()` ([account_partial_reconcile.py:107](../addons/account/models/account_partial_reconcile.py#L107)):

- a posted exchange entry cannot be deleted ([account_move.py:5920](../addons/account/models/account_move.py#L5920)), so it is reversed, dated on its own date or on the day after the lock date;
- an entry that was never posted is deleted;
- payments without their own entry go back from Reconciled to Paid.

The next reconciliation computes a new difference.

---

## Unrealized Revaluation (Enterprise)

**Accounting → Review → Regularization Entries → Unrealized Currencies** ([menuitems.xml:30](../enterprise/account_reports/data/menuitems.xml#L30)) is the Multicurrency Revaluation report. It lists open amounts ([account_multicurrency_revaluation_report.py:302](../enterprise/account_reports/models/account_multicurrency_revaluation_report.py#L302)) that:

- sit on an account whose currency differs from the company currency (the bank GL account of a USD journal), or
- are receivable/payable items in a foreign currency;

and leaves out income, expense and off-balance accounts, currencies excluded on the account (`exclude_provision_currency_ids`), and exchange difference entries.

For each account and currency: foreign balance, value at the operation rate, value at the current rate, and **Adjustment** = current − operation.

**Adjustment Entry** opens the wizard ([multicurrency_revaluation.py:50](../enterprise/account_reports/wizard/multicurrency_revaluation.py#L50)):

| Field | Default |
|---|---|
| Journal | company `account_revaluation_journal_id` |
| Expense / Income provision accounts | company `account_revaluation_expense_provision_account_id` / `..._income_...` ([res_company.py:43](../enterprise/account_reports/models/res_company.py#L43)) |
| Date | report end date |
| Reversal date | report end + 1 day; editable |

`create_entries()` posts the adjustment and its reversal at once, the reversal with the reversal date ([multicurrency_revaluation.py:169](../enterprise/account_reports/wizard/multicurrency_revaluation.py#L169)). A negative adjustment is credited to the account and debited to the expense provision; a positive one the other way ([multicurrency_revaluation.py:108](../enterprise/account_reports/wizard/multicurrency_revaluation.py#L108)). With nothing to adjust the wizard raises "No adjustment needed".

**Example:** a USD 10,000 bill open at month end, booked at 2.70 (27,000 GEL), closing rate 2.80 (28,000 GEL). Adjustment −1,000:

| Date | Account | Debit GEL | Credit GEL |
|---|---|---|---|
| 31 March | Expense provision | 1,000 | |
| 31 March | Accounts Payable | | 1,000 |
| 1 April (reversal) | Accounts Payable | 1,000 | |
| 1 April (reversal) | Expense provision | | 1,000 |

The adjustment lines carry no foreign amount; the bill itself is unchanged. When the bill is paid, reconciliation books the realized difference as usual.

| | Realized | Unrealized |
|---|---|---|
| Trigger | Reconciliation | Adjustment Entry in the report |
| Automatic | Yes | No |
| Lasting | Yes, until unreconciled | Reversed on the reversal date |
| Accounts | Exchange gain / loss | Income / expense provision |
| Scope | The reconciled items | All open items in the report |

---

## Gotchas & Non-Obvious Behavior

- **Rates apply from the next day.** A rate dated on the transaction date is not used for that transaction. Check the dates of manual rates and of rates from your provider.
- **[Certain] National Bank of Georgia rates are applied one day late.** NBG publishes around 17:00 the rate valid from the next day, and its feed dates the rate with that next day (`validFromDate`). [`_parse_nbg_data`](../enterprise/currency_rate_live/models/res_config_settings.py#L490) stores the rate under that date ([line 501](../enterprise/currency_rate_live/models/res_config_settings.py#L501)), and [`_generate_currency_rates`](../enterprise/currency_rate_live/models/res_config_settings.py#L270) does not shift it. With the strictly-before lookup, a document dated 25 September is valued at the rate valid on 24 September. Checked against the live feed on 2026-09-24 (published 24 September 17:01, `validFromDate` 25 September). Until this is corrected, compare foreign-currency documents with the official NBG rate of the document date.
- **Missing exchange configuration blocks reconciliation.** Without the exchange journal or the gain/loss accounts, reconciling foreign-currency items raises an error.
- **Enterprise payments often have no entry.** That is normal without outstanding accounts; the bank match does the accounting.
- **No internal-transfer payment.** Transfers are two bank transactions and a transfer account; nothing creates the other side for you.
- **Bank accounts are not on manual entries.** The Journal Items tab hides Bank and Cash accounts.
- **Unreconcile reverses posted exchange entries.** It does not delete them; expect a reversal entry in the exchange journal.
- **Revaluation is manual and temporary.** Run it each closing; it reverses itself.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`bank_journal_multicurrency_setup.md`](bank_journal_multicurrency_setup.md) — one journal per currency, bank accounts
- [`accounting_coa.md`](accounting_coa.md) — account types used by the exchange and transfer accounts
- [`accounting_fixed_costs_guide.md`](accounting_fixed_costs_guide.md) — reconciliation from the cost side
- [`deferred_expenses_revenue.md`](deferred_expenses_revenue.md) — deferrals keep the original company-currency value

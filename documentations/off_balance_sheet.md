# Off-Balance Sheet Accounts

> **Module:** `account` | **Path:** [`addons/account/`](../addons/account/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

Off-Balance Sheet is an account type for memo records: commitments and exposures the company must track but that are not yet assets, liabilities, income or expenses. Typical examples are a guarantee given for another company's loan, a pending lawsuit, or assets pledged as collateral.

Odoo keeps these accounts in a closed circle. An entry that uses one off-balance account may use only off-balance accounts, carries no taxes, and is never reconciled. So the memo amounts never mix with the real books: they cannot change a balance sheet total, a profit, or a tax report.

Whether an item belongs off balance sheet is an accounting decision (for example, IFRS 16 puts most leases on the balance sheet). Odoo only enforces the isolation rules.

---

## The Big Picture — How It Works

```
Commitment arises          Commitment ends                  Commitment becomes real
DR Off-balance account     Reverse the memo entry           Reverse the memo entry
CR Off-balance counterpart (Reverse Entry button)           + post a normal entry on real accounts
```

Every memo entry is one journal entry with two or more lines, all on off-balance accounts. Because each entry balances inside that circle, the sum of all off-balance accounts is always zero. Each account on its own shows the open amount of its commitment.

### The isolation rules

| Rule | Where it is enforced |
|---|---|
| If one line of an entry is off-balance, all lines must be: "If you want to use "Off-Balance Sheet" accounts, all the accounts of the journal entry must be of this type" | [`_check_off_balance()`](../addons/account/models/account_move_line.py#L1849) |
| No taxes on off-balance lines: "You cannot use taxes on lines with an Off-Balance account" | same constraint |
| Off-balance lines cannot be reconciled | same constraint |
| An off-balance account cannot be reconcilable or carry default taxes | [`_constrains_reconcile()`](../addons/account/models/account_account.py#L166); the type also sets Allow Reconciliation to off ([account_account.py:711](../addons/account/models/account_account.py#L711)) and clears default taxes in the form ([account_account.py:883](../addons/account/models/account_account.py#L883)) |

### Key decision points

- **Which pair of accounts:** one account for the commitment, one counterpart. You need at least two off-balance accounts, since an entry must balance and cannot touch other types.
- **When to reverse:** when the commitment ends, or when it turns into a real liability (then also post the real entry separately).

---

## When to Use It (and When Not To)

### This account type is for:

- **Guarantees given or received** — a parent guarantees its subsidiary's bank loan.
- **Contingent liabilities** — a pending lawsuit with an uncertain outcome.
- **Pledged assets** — inventory or equipment given as collateral: the asset stays on its normal account, the pledge is the memo.
- **Assets held for others** — goods in custody or on consignment that the company does not own.

### Use something else when:

- The company owes or owns the amount now — use a liability or asset account.
- The item has a tax effect — off-balance lines cannot carry taxes.
- You need matching, payment or bank reconciliation — off-balance lines cannot be reconciled.

---

## Real-World Scenarios

### Scenario 1: Bank guarantee for a subsidiary

**Situation:** A parent company guarantees a 500,000 EUR loan taken by its subsidiary. The parent owes nothing today, but auditors must see the exposure.

**What they do:** Create "Guarantees Given" and "Guarantees Given - Counterpart" as Off-Balance Sheet accounts. Post a miscellaneous entry: DR Guarantees Given 500,000 / CR Guarantees Given - Counterpart 500,000.

**What happens:** The Trial Balance shows 500,000 on each account. The Balance Sheet does not show it (see Reports below). If the subsidiary defaults, reverse the memo entry and post the real liability. If the loan is repaid, reverse the memo entry only.

### Scenario 2: Pending lawsuit

**Situation:** A construction company is sued for 200,000 EUR. Its lawyers cannot predict the outcome.

**What they do:** DR Contingent Liabilities - Litigation 200,000 / CR its counterpart 200,000, on off-balance accounts.

**What happens:** The exposure is visible in the Trial Balance without changing the result. If the case is lost, reverse the memo and post the expense and liability. If it is dismissed, reverse the memo.

### Scenario 3: Pledged inventory

**Situation:** A manufacturer pledges 300,000 EUR of inventory as collateral for a credit line.

**What they do:** Leave the inventory on its stock accounts. Post a memo: DR Pledged Assets 300,000 / CR its counterpart 300,000.

**What happens:** Readers of the books see that 300,000 of stock is encumbered. Release the pledge by reversing the memo.

### Quick reference

| Event | Off-balance accounts | Regular accounts |
|---|---|---|
| Guarantee given | Post the memo | Nothing yet |
| Guarantee called | Reverse the memo | Post the liability and the payment |
| Guarantee released | Reverse the memo | Nothing |
| Lawsuit filed | Post the memo for the claimed amount | Nothing yet |
| Lawsuit lost | Reverse the memo | Post the expense and the liability |
| Lawsuit dismissed | Reverse the memo | Nothing |

---

## How Things Work Under the Hood

### The account type

`off_balance` is one of the account types ([account_account.py:86](../addons/account/models/account_account.py#L86)). Its internal group is `off`, taken from the type name ([account_account.py:688](../addons/account/models/account_account.py#L688)); no other type shares it. Off-balance accounts bring their balance forward into the next fiscal year like balance sheet accounts: only income, expense and current-year-earnings accounts restart at zero ([account_account.py:679](../addons/account/models/account_account.py#L679)).

### Where you can and cannot pick an off-balance account

| Place | Off-balance allowed? | Source |
|---|---|---|
| Journal entry → **Journal Items** tab | Yes (any account except Bank and Cash) | [account_move_views.xml:1536](../addons/account/views/account_move_views.xml#L1536) |
| Invoice and bill lines | No | [account_move_views.xml:1334](../addons/account/views/account_move_views.xml#L1334) |
| Journal item account field outside the entry form | No (field domain) | [account_move_line.py:112](../addons/account/models/account_move_line.py#L112) |
| Product and product category income/expense accounts | No | [product.py:10](../addons/account/models/product.py#L10) |
| Tax distribution accounts | No | [account_tax.py:5154](../addons/account/models/account_tax.py#L5154) |
| Reconciliation model lines | No | [account_reconcile_model.py:18](../addons/account/models/account_reconcile_model.py#L18) |
| Accrual (cut-off) wizard accounts | No | [account_automatic_entry_wizard.py:40](../addons/account/wizard/account_automatic_entry_wizard.py#L40) |
| Payment method outstanding accounts | No (current assets/liabilities only) | [account_payment_method.py:116](../addons/account/models/account_payment_method.py#L116) |

So memo entries are made as miscellaneous journal entries, on the Journal Items tab.

### Reports

| Report | What you see | Source |
|---|---|---|
| Balance Sheet | Nothing. The "OFF BALANCE SHEET ACCOUNTS" line is a single total of all off-balance accounts, with no breakdown by account. That total is always zero, and the line is set to hide when zero | [balance_sheet.xml:247](../enterprise/account_reports/data/balance_sheet.xml#L247), [account_report.py:3021](../enterprise/account_reports/models/account_report.py#L3021) |
| Profit & Loss | Nothing | — |
| Trial Balance, General Ledger | Each off-balance account with its balance: the trial balance groups all journal items by account, with no account-type filter | [trial_balance.xml:5](../enterprise/account_reports/data/trial_balance.xml#L5) |
| Multicurrency Revaluation | Excluded: foreign-currency memo amounts are never revalued | [account_multicurrency_revaluation_report.py:300](../enterprise/account_reports/models/account_multicurrency_revaluation_report.py#L300) |

To list open commitments, use the Trial Balance, or Journal Items grouped by account and filtered on the off-balance accounts.

---

## Configuration & Settings

There is no setting. Create the accounts in Accounting → Configuration → Chart of Accounts with **Type = Off-Balance Sheet**, in pairs (commitment and counterpart). The form hides Default Taxes for this type and the list hides Allow Reconciliation ([account_account_views.xml:108](../addons/account/views/account_account_views.xml#L108)).

Many charts ship off-balance accounts already. The Georgian chart (`l10n_ge`) has the group 990000 "Zero-Balance Control Accounts" with 990010 Customer Balancing, 990020 Supplier Balancing, 990030 Payroll Settlement, 990040 Tax Settlement (Non-CIT), 990050 Intercompany Settlement, 990060 Temporary Posting and 990070 Off-Balance Sheet Counterpart Account, all of type Off-Balance Sheet ([account.account-ge.csv:300](../addons/l10n_ge/data/template/account.account-ge.csv#L300)).

---

## Dependencies

| Requires | Why |
|---|---|
| `account` | The account type and the isolation constraints |

| Works With (optional) | What It Adds |
|---|---|
| `account_reports` | Balance Sheet line, Trial Balance and General Ledger views of the memo accounts |

---

## Gotchas & Non-Obvious Behavior

- **Never mixed with real accounts.** You cannot move an amount from a receivable to an off-balance account in one entry. The Georgian 9900xx "balancing" and "settlement" accounts are off-balance too, so they cannot serve as clearing accounts in normal entries; any entry that includes one must be all off-balance.
- **The Balance Sheet never shows them.** Use the Trial Balance to report commitments.
- **At least two accounts.** A single off-balance account cannot hold a balance, because each entry must balance inside the off-balance circle.
- **No automatic release.** Nothing reverses a memo when a guarantee expires or a case closes. Reverse it yourself (Reverse Entry on the posted entry).
- **Changing an existing account to Off-Balance Sheet.** Allow Reconciliation switches off by itself. Default taxes are cleared only by the form, so a type change written from code with taxes still set is refused ("An Off-Balance account can not have taxes"). The change is not checked against the account's existing journal items: do it only on unused accounts.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`accounting_coa.md`](accounting_coa.md) — all account types, including off-balance
- [`accounting_reports.md`](accounting_reports.md) — Balance Sheet and Trial Balance engine

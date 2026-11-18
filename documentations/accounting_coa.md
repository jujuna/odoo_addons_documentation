# Chart of Accounts (COA)

> **Module:** `account` | **Path:** [`addons/account/`](../addons/account/)
> **Odoo Apps category:** Accounting / Invoicing
> Verified against Odoo 20 source on 2026-09-24.

---

## Glossary for Beginners

Before diving in, here are the key terms you will see throughout this document.

| Term | Simple Definition | Real-World Analogy |
|---|---|---|
| Chart of Accounts (COA) | The complete list of all accounts your company uses to record money movements | Like a table of contents for your financial books |
| Account | A category bucket where money is recorded as coming in or going out | "Bank Account", "Sales Revenue", "Office Expenses" |
| Journal Entry | A record of a single financial transaction, always balanced (debits = credits) | When you send an invoice, Odoo creates: Debit Receivable + Credit Revenue |
| Debit | Left side of an accounting entry — increases assets, decreases liabilities | Money a customer owes you (Receivable) is a debit |
| Credit | Right side of an accounting entry — decreases assets, increases liabilities | Revenue you earned is a credit |
| Reconciliation | Matching two journal entry lines that cancel each other out | Matching a $500 customer payment against their $500 invoice |
| Fiscal Position | Rules that swap accounts and taxes based on where the customer is located | EU customer gets a different tax account than a domestic customer |
| Opening Balance | The starting balance of an account when you first begin using Odoo | If you had $10,000 in the bank before Odoo, you set opening balance = 10,000 |
| Account Type | A classification that tells Odoo how the account behaves automatically | "Receivable" type means Odoo forces reconciliation on and tracks customer debts |
| Parent Account | An account that sits above others in the chart and totals them | "Property, Plant & Equipment" is the parent of "Land", "Construction", "Installations" |
| Balance Sheet | Financial report showing what the company owns (assets), owes (liabilities), and is worth (equity) at a point in time | A snapshot of the company's financial position on Dec 31 |
| Profit & Loss (P&L) | Financial report showing income minus expenses over a period | How much the company earned/lost during the year |
| Stock Variation | The difference between physical inventory value and what the accounting ledger shows | You have $10,000 of goods in the warehouse but the books say $9,500 — the $500 gap is stock variation |

---

## What It Does

The Chart of Accounts is the master list of all ledger accounts a company uses to record financial transactions.
Every journal entry line (`account.move.line`) must be posted to an account from the COA.
Accounts are organized by type, arranged into a tree through `parent_id`, and tagged for reporting.
The COA is per-company but accounts can be shared across a parent-child company hierarchy.
Odoo installs a COA automatically by loading a localized chart template when a company is first set up.

---

## How Everything Connects — Visual Overview

This diagram shows how the COA fits into the full accounting lifecycle, from initial setup to financial reporting.

```
STEP 1: COMPANY SETUP
  Company created with: Country + Fiscal Country + Currency
                              |
                              v
STEP 2: CHART TEMPLATE LOADING
  Odoo picks a template based on company country (e.g. l10n_us, l10n_de)
  Creates records in dependency order:
    1. Accounts (100-500+ accounts depending on country,
       with parent_id links where the localization defines a tree)
    2. Fiscal positions
    3. Taxes (VAT, sales tax, etc.)
    4. Journals (Sales, Purchase, Bank, Cash, Credit Card, Miscellaneous)
                              |
                              v
STEP 3: DEFAULT ACCOUNTS SET
  ir.default stores company-wide defaults:
    - All partners get a default Receivable account (e.g. 1100)
    - All partners get a default Payable account (e.g. 2000)
    - All product categories get default Income/Expense accounts
                              |
                              v
STEP 4: DAILY USE — INVOICE CREATED
  User creates an invoice line
    Product selected?
      YES -> Get account from: Product > Category > Company default
      NO  -> Use partner's most frequently used account (last 2 years)
      Still nothing? -> Use journal's default account
    Apply fiscal position substitution (if set)
                              |
                              v
STEP 5: JOURNAL ENTRY POSTED
  account.move.line created with:
    - account_id (resolved from step above)
    - debit / credit amounts
    - amount_currency (if account has a foreign currency set)
                              |
                              v
STEP 6: FINANCIAL REPORTS
  Balance Sheet: Shows accounts where balance carries forward year-to-year
                 (assets, liabilities, equity)
  Profit & Loss: Shows accounts that reset to zero each fiscal year
                 (income, expenses)
  Grouped by: account.root (first 2 digits) -> account.account.parent_id (the tree)
```

---

## Prerequisites Before Using the COA

Before any account exists, three things must be configured on the company:

### 1. Company Country + Fiscal Country

| Field (Python) | UI Label | Model | Purpose |
|---|---|---|---|
| `country_id` | "Country" | `res.company` | Determines which localized chart template is available |
| `account_fiscal_country_id` | "Fiscal Country" | `res.company` | The country whose tax rules apply; computed from `country_id` but can differ (e.g., foreign branch) |

`account_fiscal_country_id` is stored on `res.company`, computed by
[`compute_account_tax_fiscal_country()`](../addons/account/models/company.py).

### 2. Chart Template

A chart template is the blueprint that creates accounts, groups, taxes, and journals for a company.
It is loaded by [`AccountChartTemplate.try_loading()`](../addons/account/models/chart_template.py#L151).

**How templates are discovered:**

The abstract model `account.chart.template` scans all installed modules for methods decorated with
`@template(code)` via [`_template_register`](../addons/account/models/chart_template.py#L78).
Each localization module (e.g., `l10n_us`, `l10n_de`) registers its own template code.
The generic fallback is `generic_coa` (US-style, no country lock).

**Key template method decorators:**
- `@template('generic_coa')` — registers template metadata (name, country, property_ keys)
- `@template('generic_coa', 'account.account')` — registers accounts to create
- `@template('generic_coa', 'res.company')` — registers company fields to set (prefixes, special accounts)

Source: [`template_generic_coa.py`](../addons/account/models/template_generic_coa.py)

**What `generic_coa` sets on the company:**

| Company field | Value set | Purpose |
|---|---|---|
| `bank_account_code_prefix` | `'1014'` | Auto-prefix for new bank accounts |
| `cash_account_code_prefix` | `'1015'` | Auto-prefix for new cash accounts |
| `transfer_account_code_prefix` | `'1017'` | Internal transfer intermediary |
| `account_fiscal_country_id` | `base.us` | US tax rules |
| `anglo_saxon_accounting` | `True` | Only adds price-difference lines to vendor bills ([`account_move.py:6001`](../addons/account/models/account_move.py#L6001)). COGS lines are posted on customer invoices for every perpetual product, whatever the flag |

#### Chart Template Loading — Step by Step

When you select a chart template (or Odoo auto-selects one for your country), this is the exact sequence:

```
1. AccountChartTemplate.try_loading('generic_coa', company)
   Validates the company, resolves template code.
   Source: chart_template.py:151

2. Is the template already loaded? (reload scenario)
   If yes: _pre_reload_data() runs first (line 276)
     - Preserves existing journals (does not overwrite)
     - Prefixes old tax names with "[old]" to avoid name conflicts
     - Strips reconcile model links
     - Does NOT delete accounts

3. _get_chart_template_data('generic_coa')  (line 826)
   Scans all @template('generic_coa', model) decorated methods.
   Collects creation data for the models in TEMPLATE_MODELS
   (chart_template.py:22) plus res.company:
     - account.account          (the actual accounts, incl. parent_id)
     - account.fiscal.position
     - account.tax.group
     - account.tax              (tax definitions)
     - account.journal          (journals to create)
     - account.reconcile.model
     - res.company              (company settings to write)

4. _pre_load_data()  (line 494)
   Preprocessing before any records are created:
     - Sets company.account_fiscal_country_id BEFORE creating taxes
       (taxes depend on country for tax tags)
     - Applies code_digits padding to all account codes
     - Creates utility accounts (suspense, transfer, etc.)

5. _load_data()  (line 578)
   Creates records in TEMPLATE_MODELS order:
     a. account.account          (parents resolve by xml id, within the batch)
     b. account.fiscal.position
     c. account.tax.group
     d. account.tax              (repartition lines reference accounts)
     e. account.journal          (references accounts as defaults)
     f. account.reconcile.model  (references accounts)

   Why order matters: taxes reference accounts in their repartition lines,
   journals reference accounts as defaults. Creating them out of order fails.

6. res.company values written (@template('generic_coa', 'res.company'))
   Including the four "default account" company fields that Odoo 20 uses
   in place of direct ir.default writes:
     receivable_account_id  -> res.partner.property_account_receivable_id
     payable_account_id     -> res.partner.property_account_payable_id
     income_account_id      -> product.category.property_account_income_categ_id
     expense_account_id     -> product.category.property_account_expense_categ_id
   Source: template_generic_coa.py:25

7. _post_load_data()  (line 733)
   Post-processing hook: opening move, journal defaults, demo, translations.
```

> The parent links come straight from the template's `parent_id` column (where the localization defines
> one) and are never recomputed after loading — there is no group-hierarchy rebuild pass.

### 3. Currency

| Field | Model | UI Label |
|---|---|---|
| `currency_id` | `res.company` | "Currency" |

All `Monetary` fields on accounts use `company_currency_id`.
If an account has its own `currency_id` set, every journal line on that account is forced to use that currency
(used for foreign currency bank accounts).

---

## Dependencies

### Requires (must be installed)

| Module | Why |
|---|---|
| `base_setup` | Company setup wizard, country/currency data |
| `onboarding` | Onboarding panel and setup steps |
| `product` | Product accounts (`account_id`, `property_account_income_id`) |
| `analytic` | Analytic account field on journal lines |
| `portal` | Customer portal access to invoices |
| `digest` | KPI digest emails |

### Provides To

| Consumer module | What it uses |
|---|---|
| `account_payment` | `account.account` for payment journals |
| `stock_account` | COGS, stock valuation accounts |
| `hr_payroll_account` | Salary journal accounts |
| `account_reports` | Account tags + account types for P&L, Balance Sheet |
| All `l10n_*` modules | Extend `account.chart.template` with country COA |

---

## Core Model: `account.account`

> [`models/account_account.py`](../addons/account/models/account_account.py)

This is the central record — one row per ledger account.

### Key Fields

The model inherits `mail.thread` and `mail.activity.mixin` in Odoo 20 — most config fields are `tracking=True`, so every code, type, or reconcile change lands in the account's chatter.

| Field | Type | UI Label | Purpose |
|---|---|---|---|
| `code` | `Char` (computed, `size=64`) | "Code" | Account code; company-dependent via `code_store` |
| `code_store` | `Char` (company_dependent) | — | Raw storage of code per company root |
| `name` | `Char` | "Account Name" | Human-readable account name |
| `description` | `Text` | "Description" | **New in 20.** Free text shown under the account in the picker dropdown |
| `account_type` | `Selection` | "Type" | Controls behavior, reporting, and balance logic (see below) |
| `internal_group` | `Selection` (computed) | "Internal Group" | Derived from `account_type` prefix (e.g. `asset_*` -> `asset`) |
| `reconcile` | `Boolean` | "Payment Reconciliation" | Whether journal lines on this account can be matched/reconciled |
| `currency_id` | `Many2one` `res.currency` | "Account Currency" | If set, forces all lines to use this currency |
| `company_ids` | `Many2many` `res.company` | "Companies" | Companies that share this account |
| `tax_ids` | `Many2many` `account.tax` | "Default Taxes" | Taxes auto-applied when this account is selected on a line |
| `tag_ids` | `Many2many` `account.account.tag` (computed, stored) | "Tags" | Custom tags for reporting; precomputed from the nearest account by code |
| **`parent_id`** | `Many2one` `account.account` | "Parent Account" | **New in 20** — replaces `group_id`. The account above this one in the chart |
| `parent_path` / `parent_ids` | `Char` / `Many2many` (computed) | — | `_parent_store` plumbing: materialised ancestor path and ancestor set |
| `code_path` / `name_path` | `Char` (computed) | — | Ancestor chain joined by code / by name. Drives `_order` and search |
| `root_id` | `Many2one` `account.root` (computed) | — | Virtual node: first 2 chars of code |
| `active` | `Boolean` | "Active" | Inactive accounts are hidden but preserved. Pure header accounts often ship `active = False` |
| `used` | `Boolean` (computed) | — | **New in 20.** Whether any journal item exists on this account |
| `non_trade` | `Boolean` | "Non Trade" | Marks receivable/payable as non-trade for report filters |
| `code_mapping_ids` | `One2many` `account.code.mapping` | "Mapping" tab | Per-company code editor, shown when the user has more than one company |
| `opening_debit` | `Monetary` (computed/inverse) | "Opening Debit" | Balance from the company opening journal entry |
| `opening_credit` | `Monetary` (computed/inverse) | "Opening Credit" | Balance from the company opening journal entry |
| `current_balance` | `Float` (computed) | — | Sum of posted `account.move.line.balance` for the active company |
| `account_stock_variation_id` / `account_stock_expense_id` | `Many2one` `account.account` | "Variation Account" / "Expense Account" | Lives in core `account`. See [Inventory Variation](#inventory-variation-account-account_stock_variation_id) |
| `related_taxes_amount` | `Integer` (computed) | — | Count of taxes with a repartition line on this account; drives a smart-button badge on the account form ([account_account.py:148](../addons/account/models/account_account.py#L148)) |

`code`, `placeholder_code`, `code_path`, `name_path`, `used`, `internal_group`, `root_id` and `company_currency_id` are non-stored but declare `compute_sql=`, which gives the ORM a SQL expression for the field — so they stay filterable, groupable and sortable (`_order = "code_path, account_type, name_path"` relies on this) without being stored columns ([account_account.py:44-132](../addons/account/models/account_account.py#L44-L132)).

---

## Account Types — Complete Reference

`account_type` is a `Selection` field. It is the "brain" of an account — it automatically controls three critical behaviors:

1. **Which financial statement** the account appears in (Balance Sheet vs P&L)
2. **Whether the balance carries forward** year-to-year (`include_initial_balance`)
3. **Whether reconciliation is allowed** (matching payments against invoices)

Source: [`account_account.py:66`](../addons/account/models/account_account.py#L66)

### How Account Types Control Behavior Automatically

When you set an account type, Odoo enforces several behaviors behind the scenes. Understanding these prevents confusion when fields appear locked or values change unexpectedly.

#### A. Reconciliation — Enforced by Type

Source: [`_check_reconcile()`](../addons/account/models/account_account.py#L35)

```python
@api.constrains('account_type', 'reconcile')
def _check_reconcile(self):
    for account in self:
        if account.account_type in ('asset_receivable', 'liability_payable') and not account.reconcile:
            raise ValidationError(...)
```

**What this means in practice:**

| If you set type to... | Reconciliation becomes... | Why |
|---|---|---|
| Receivable | Forced ON (cannot uncheck) | You must match customer payments against their invoices |
| Payable | Forced ON (cannot uncheck) | You must match your payments against vendor bills |
| Income, Expense, Equity | Defaults to OFF | You don't match individual payments against revenue/expense lines |
| Current Assets, etc. | Optional (your choice) | Some asset accounts benefit from reconciliation (e.g., intercompany) |

#### B. Balance Carry-Forward — Determined by Type

Source: [`_compute_include_initial_balance()`](../addons/account/models/account_account.py#L679)

```python
@api.depends('account_type')
def _compute_include_initial_balance(self):
    for account in self:
        account.include_initial_balance = (
            account.internal_group not in ['income', 'expense']
            and account.account_type != 'equity_unaffected'
        )
```

**What this means in practice:**

| Account category | Balance at year-end | What happens Jan 1 | Why |
|---|---|---|---|
| Balance Sheet (Assets, Liabilities, Equity) | Carries forward | Same balance continues | The bank still has $50,000; the loan is still $30,000 |
| P&L (Income, Expense) | Resets to zero | Starts fresh | Last year's revenue is done; new year starts from zero |
| `equity_unaffected` (Current Year Earnings) | Does NOT carry forward | Computed fresh | It's always "this year's net P&L" — Odoo calculates it on the fly |

#### C. Internal Group — Auto-Derived from Type

Source: [`_get_internal_group()`](../addons/account/models/account_account.py#L688)

```python
def _get_internal_group(self, account_type):
    return account_type.split('_', maxsplit=1)[0]
```

| `account_type` | `internal_group` | Used for |
|---|---|---|
| `asset_cash` | `asset` | Report grouping, filters |
| `asset_receivable` | `asset` | Report grouping, filters |
| `liability_payable` | `liability` | Report grouping, filters |
| `income` | `income` | Report grouping, filters |
| `income_other` | `income` | Report grouping, filters |
| `expense_direct_cost` | `expense` | Report grouping, filters |

When you filter reports by "Asset", Odoo matches all `asset_*` types. You never set `internal_group` manually.

### Balance Sheet Accounts (`include_initial_balance = True`)

These accounts **carry their balance forward** every fiscal year — they represent what the company owns, owes, or has invested.

#### Assets

| `account_type` value | UI label | `reconcile` default | When to use | Real example |
|---|---|---|---|---|
| `asset_receivable` | "Receivable" | **True** (enforced) | Money customers owe you. Every customer invoice posts a debit here. Must be reconcilable — payments match against these lines. | "Accounts Receivable 1100" |
| `asset_cash` | "Bank and Cash" | False | Bank and cash accounts linked to a journal. Cannot be shared across companies. | "Checking Account 1010" |
| `asset_current` | "Current Assets" | Optional | Assets expected to be converted to cash within 1 year: inventory prepayments, VAT receivable. | "VAT Receivable 1410" |
| `asset_non_current` | "Non-current Assets" | Optional | Assets held >1 year, excluding fixed assets. | "Long-term deposits 1600" |
| `asset_prepayments` | "Prepayments" | Optional | Costs paid in advance for future periods (prepaid insurance, prepaid rent). | "Prepaid Expenses 1300" |
| `asset_fixed` | "Fixed Assets" | Optional | Property, plant, equipment. Used by `account_asset` module for depreciation. | "Equipment 1500" |

> **Beginner note — Current vs Non-current vs Fixed Assets**
>
> | Category | Rule of thumb | Examples | Odoo account type |
> |---|---|---|---|
> | **Current Assets** | Can be converted to cash **within 1 year** | Cash, inventory, customer invoices (receivables), VAT refunds, prepaid rent | `asset_cash`, `asset_receivable`, `asset_current`, `asset_prepayments` |
> | **Non-current Assets** | Kept **longer than 1 year**, not physical equipment | Long-term deposits, goodwill, deferred tax assets, long-term investments | `asset_non_current` |
> | **Fixed Assets** | **Physical things** you use in operations (not sell), that **depreciate** over time | Trucks, machines, office furniture, computers, buildings | `asset_fixed` |
>
> The hierarchy: Non-current Assets is the broad parent category for anything held >1 year.
> Fixed Assets is a **subset** of non-current — specifically the tangible, depreciable items.
> Odoo's `account_asset` module only auto-creates depreciation boards for accounts typed `asset_fixed`.
>
> ```
> All Assets
> ├── Current Assets        (cash, inventory, receivables — < 1 year)
> └── Non-Current Assets    (everything long-term — > 1 year)
>     ├── Fixed Assets      (physical: trucks, machines — depreciated)
>     ├── Intangible Assets (patents, software — amortized, use asset_non_current)
>     └── Financial Assets  (long-term investments — use asset_non_current)
> ```

#### Liabilities

| `account_type` value | UI label | `reconcile` default | When to use | Real example |
|---|---|---|---|---|
| `liability_payable` | "Payable" | **True** (enforced) | Money you owe vendors. Every vendor bill posts a credit here. Must be reconcilable. | "Accounts Payable 2000" |
| `liability_credit_card` | "Credit Card" | False | Credit card bank journals. Treated like a bank account but on the liability side. | "Visa Card 2010" |
| `liability_current` | "Current Liabilities" | Optional | Short-term obligations due within 1 year: VAT payable, accrued expenses. | "VAT Payable 2200" |
| `liability_non_current` | "Non-current Liabilities" | Optional | Long-term debt (>1 year): bonds, long-term loans. | "Bank Loan 2500" |

#### Equity

| `account_type` value | UI label | `include_initial_balance` | When to use | Real example |
|---|---|---|---|---|
| `equity` | "Equity" | True | Shareholder capital, retained earnings from previous years | "Share Capital 3000" |
| `equity_unaffected` | "Current Year Earnings" | **False** | Special account: Odoo writes the net P&L of the current fiscal year here. Excluded from initial balance logic — it's always computed. | "Retained Earnings 3100" |

> **Important:** `equity_unaffected` is the one account with `internal_group = equity` but `include_initial_balance = False`.
> Source: [`_compute_include_initial_balance()`](../addons/account/models/account_account.py#L679)

### P&L Accounts (`include_initial_balance = False`)

These accounts **reset to zero** at the start of each fiscal year. Their year-end balance is transferred to the equity account.

| `account_type` value | UI label | When to use | Real example |
|---|---|---|---|
| `income` | "Income" | Primary revenue from sales of goods/services. Odoo auto-suggests these for customer invoice lines. | "Sales Revenue 4000" |
| `income_other` | "Other Income" | Non-operating income: interest earned, asset disposal gains. | "Interest Income 4900" |
| `expense` | "Expenses" | Primary operating costs: purchases, services consumed. Odoo auto-suggests for vendor bill lines. | "Operating Expenses 6000" |
| `expense_other` | "Other Expenses" | Non-operating losses: bank charges, fines. | "Bank Fees 6900" |
| `expense_depreciation` | "Depreciation" | Depreciation charges posted by `account_asset`. | "Depreciation 6600" |
| `expense_direct_cost` | "Cost of Revenue" | COGS — direct cost of goods sold. For perpetual products the COGS lines of customer invoices debit the product's expense account ([`_get_cogs_lines_vals()`](../addons/account/models/account_move.py#L6020)); give that account this type to report it as Cost of Revenue. | "Cost of Goods Sold 5000" |

### Special

| `account_type` value | UI label | Notes |
|---|---|---|
| `off_balance` | "Off-Balance Sheet" | Not on Balance Sheet or P&L. Cannot be reconcilable. Cannot have taxes. Used for contingent liabilities, guarantees. |

### Computed fields derived from `account_type`

| Computed field | Logic | Source |
|---|---|---|
| `internal_group` | `account_type.split('_')[0]` — e.g. `asset_cash` -> `asset` | [`_compute_internal_group()`](../addons/account/models/account_account.py#L692) |
| `include_initial_balance` | `True` if not income/expense and not `equity_unaffected` | [`_compute_include_initial_balance()`](../addons/account/models/account_account.py#L679) |
| `reconcile` | Auto-set True for receivable/payable; False for income/expense/equity/cash/credit card/off-balance; unchanged for other asset/liability types | [`_compute_reconcile()`](../addons/account/models/account_account.py#L711) |

---

## Account Code — Technical Details

Account codes are stored as a **company-dependent JSON field** (`code_store`), not a plain char.

### Why company-dependent?

In a multi-company hierarchy, multiple subsidiaries can share the same `account.account` record
(e.g., a shared "Sales Revenue" account). Each company can have its own code for the same account.

`code_store` is a JSONB column: `{"<root_company_id>": "4000"}`.

**`code` field** (what you see and edit) is computed from `code_store` for the active company root:

```python
# _compute_code: reads code_store for self.env.company.root_id
record.code = record_root.code_store
```

Source: [`_compute_code()`](../addons/account/models/account_account.py#L315)

### Real-World Multi-Company Example

Imagine your company has two subsidiaries:

| Company | Country | Wants code for "Sales Revenue" |
|---|---|---|
| Parent (US) | United States | `4000` |
| Subsidiary (UK) | United Kingdom | `4100` |

**Without** company-dependent codes, you would need two separate `account.account` records. This breaks consolidated reporting because the two records have no link to each other.

**With** company-dependent codes, there is ONE `account.account` record for "Sales Revenue". The database stores:

```json
code_store = {
    "1": "4000",
    "2": "4100"
}
```

At runtime:
- When logged into US company: `account.code` reads `code_store["1"]` and returns `"4000"`
- When logged into UK company: `account.code` reads `code_store["2"]` and returns `"4100"`

**Key constraint:** Both companies must share the same `root_id` (parent company). Companies in completely separate hierarchies cannot share account records.

### Code format constraints

- Only alphanumeric characters and dots: validated by `ACCOUNT_CODE_REGEX = r'^[A-Za-z0-9.]+$'`
- Source: [`_check_account_code()`](../addons/account/models/account_account.py#L289)

### Auto-incrementing new codes

[`_search_new_account_code(start_code)`](../addons/account/models/account_account.py#L504) finds the next available code:

| Input code | Codes checked |
|---|---|
| `102100` | `102101`, `102102`, `102103`, ... |
| `1598` | `1599`, `1600`, `1601`, ... |
| `10.01.08` | `10.01.09`, `10.01.10`, ... |
| `hello` | `hello.copy`, `hello.copy2`, ... |

### `placeholder_code`

When an account has no code in the **current** company but exists in another company,
the display shows `<code> (<company_name>)` as a read-only placeholder.
Source: [`_compute_placeholder_code()`](../addons/account/models/account_account.py#L338)

---

## Account Hierarchy — Two Layers

> `account.group` does not exist in 20.0 — accounts form their own tree instead.

```
LAYER 1: account.root (virtual, no DB table)
  Purpose: search panel filter in COA list view
  How: first 2 chars of account code
  Parent logic: "12" -> parent "1" (trim last char)
  Fully automatic — you never configure it

LAYER 2: account.account -> parent_id (real, manual)
  Purpose: the chart's actual shape — hierarchical list view and report subtotals
  How: you (or the localization CSV) point one account at another
  Parent logic: none. It is whatever you set.
```

The two layers are unrelated. `account.root` is still derived from the code and still drives the search panel; `parent_id` is an explicit link that owes nothing to the codes.

### Full hierarchy example

Taken from the UAE chart ([account.account-ae.csv](../addons/l10n_ae/data/template/account.account-ae.csv)):

```
account.account 110000 "Property, Plant & Equipment (PP&E)"   active = False   <- header
  ├── account.account 110100 "Land"           parent_id -> 110000
  ├── account.account 110200 "Construction"   parent_id -> 110000
  └── account.account 110300 "Installations"  parent_id -> 110000
```

Notice two things that were impossible with `account.group`:

- The parent is a **real account**. Nothing stops you posting to "Property, Plant & Equipment" directly if you make it active — it can be used as an intermediary account on a bill.
- Header-only nodes are expressed by `active = False`, not by a separate model.

---

## Parent Accounts (`parent_id`)

Accounts form their own tree. `_parent_store = True` on the model gives the usual Odoo plumbing.

| Field | Type | Purpose |
|---|---|---|
| `parent_id` | `Many2one` `account.account` | The account above this one. Domain `['!', ('id', 'child_of', id)]` blocks cycles. `ondelete='restrict'` — you cannot delete a parent that still has children |
| `parent_path` | `Char` (indexed) | Materialised `/`-separated ancestor id path, maintained by the ORM |
| `parent_ids` | `Many2many` (computed) | The ancestor set, used by `code_path` / `name_path` |
| `code_path` | `Char` (computed) | Ancestor chain joined by **code**. Drives `_order` so the list view comes out in tree order |
| `name_path` | `Char` (computed) | Ancestor chain joined by **name**. Used in `display_name` and in search |

Source: [account_account.py:133](../addons/account/models/account_account.py#L133) (`parent_id`), [:141](../addons/account/models/account_account.py#L141)-[142](../addons/account/models/account_account.py#L142) (`parent_path` / `parent_ids`), [:49](../addons/account/models/account_account.py#L49)-[63](../addons/account/models/account_account.py#L63) (`code_path` / `name_path`)

### Where it shows up

| Place | Effect |
|---|---|
| Chart of Accounts list | `js_class="account_hierarchy_list"` renders an indented, foldable tree ([account_account_views.xml:100](../addons/account/views/account_account_views.xml#L100)) |
| Account form | "Parent Account" field, placeholder "Root account" ([account_account_views.xml:72](../addons/account/views/account_account_views.xml#L72)) |
| Account dropdown on a journal line | `display_name` shows `code name_path`, so you see the full branch, not just the leaf name |
| `_order` | `code_path, account_type, name_path` — accounts sort under their parents regardless of their own code |

### Setting it up

There is no automatic resolution. You have three options:

1. **Use a localization that ships one.** 37 `l10n_*` modules define a `parent_id` column in their `account.account-*.csv` — `l10n_ae`, `l10n_ar`, `l10n_ca`, `l10n_cn`, `l10n_ge`, `l10n_in`, `l10n_mx`, `l10n_tr`, `l10n_us_account`, …
2. **Build it by hand.** Create header accounts (typically `active = False`), then set `parent_id` on the leaves. Accounting → Accounting → Chart of Accounts, "Parent Account" field on the form.
3. **Leave it flat.** `generic_coa` sets no parents at all. A generic US chart works exactly as before, just without subtotals from the hierarchy.

### Constraints

- A cycle is refused by the `parent_id` domain plus the standard `_parent_store` check.
- `ondelete='restrict'`: deleting a parent with children raises. There is no re-parenting-on-delete behaviour: deleting a parent does not move its children elsewhere.
- `check_company=True`: parent and child must be compatible company-wise.

---

## Account Root (`account.root`)

> [`models/account_root.py`](../addons/account/models/account_root.py)

`account.root` is a **virtual model** (`_auto = False`, `_table_sql = SQL('(0)')` — renamed from `_table_query = '0'` in Odoo 20).
It has no database table — it is entirely computed in Python.

An account root is simply the **first 2 characters of an account code**.
For code `4100`, the root is `41`. For code `41`, the root is still `41`.

**Purpose:** provides a grouping node for the left-side search panel in the COA list view.
Users can click `41` to filter all 41xx accounts.

### Fields

| Field | Type | How it's computed |
|---|---|---|
| `id` | `Char` (string-based) | First 2 chars of account code — e.g. `"41"` |
| `name` | `Char` (computed) | Same as `id` — [`account_root.py:39`](../addons/account/models/account_root.py#L39) |
| `parent_id` | `Many2one` `account.root` (computed) | `id[:-1]` — trim last character. `"41"` -> parent `"4"`, `"4"` -> `False` (no parent) — [`account_root.py:40`](../addons/account/models/account_root.py#L40) |

### Parent-child logic

The parent chain is built by progressively trimming the last character of the root ID:

```
"41" -> parent "4" -> parent False (top level)
"10" -> parent "1" -> parent False (top level)
```

This creates a virtual 2-level tree (single digit -> two digits) used solely for the search panel `child_of` filtering.

### Search restrictions

`_search()` only supports two domain forms ([`account_root.py:25-31`](../addons/account/models/account_root.py#L25-L31)):
- `('id', 'in', ids)` — exact match
- `('id', 'parent_of', ids)` — returns all prefixes of the given IDs using `accumulate()`. E.g., `parent_of ['41']` returns `{'4', '41'}`.

Any other domain raises `UserError`.

### How accounts link to roots

`account.root._from_account_code(code)` returns `self.browse(code[:2])`.
Source: [`account_root.py:34`](../addons/account/models/account_root.py#L34)

Each `account.account` has a computed `root_id` field that calls this method on its `placeholder_code`.
Source: [`_compute_account_root()`](../addons/account/models/account_account.py#L446)

---

## Account Tags (`account.account.tag`)

> [`models/account_account_tag.py`](../addons/account/models/account_account_tag.py)

Tags are free-form labels attached to accounts (or taxes, or products).

### Fields

| Field | Type | Purpose |
|---|---|---|
| `name` | `Char` | Tag label |
| `applicability` | `Selection` | `accounts` / `taxes` / `products` — controls where tag is usable |
| `country_id` | `Many2one` `res.country` | Limits tag to one country (mainly for tax tags) |
| `report_expression_id` | `Many2one` (computed) | If generated by a report line (`tax_tags` engine), links back to it |
| `balance_negate` | `Boolean` (computed) | If True, the report uses `-balance` for this tag |

**Unique constraint:** `(name, applicability, country_id)` — no duplicate tag per scope.

**How tags auto-propagate to new accounts:**

`tag_ids` is a **computed, stored, precomputed** field in Odoo 20 (`_compute_account_tags`). When you create an
account with a code but no explicit tags, Odoo calls
[`_get_closest_parent_account()`](../addons/account/models/account_account.py#L653)
to find the nearest account by code (binary search over the sorted codes) and copies its `tag_ids`.
Same helper, same rule, as the `account_type` inference below. Set tags explicitly and the compute leaves them alone.

**Account tags vs tax tags:**
- `applicability = 'accounts'` — used for custom reporting groupings on the COA.
- `applicability = 'taxes'` — generated by report engine; linked to `account.report.expression` records; used in tax declarations.

---

## Opening Balances

When migrating from another system, you set the starting balance for each account. This is how Odoo knows what your financial position was before you started using it.

### How it works — the hidden journal entry

Behind the scenes, Odoo does not store opening balances as a simple number on the account. Instead, it creates a real journal entry (a proper accounting transaction) that represents your starting position.

The company has a special journal entry: `company.account_opening_move_id`. This is a single journal entry that holds ALL opening balance lines for every account.

Fields `opening_debit` / `opening_credit` / `opening_balance` on `account.account` are computed
by reading lines from this single move.

**Example:** You had $50,000 in the bank and $20,000 in customer receivables before Odoo:

```
Opening Journal Entry (account_opening_move_id):
  Line 1: Debit  Bank Account (1010)         $50,000
  Line 2: Debit  Accounts Receivable (1100)   $20,000
  Line 3: Credit Opening Balance Equity       $70,000  (balancing entry)
```

### What happens when you set an opening balance

Source: [`_set_opening_balance()`](../addons/account/models/account_account.py#L729)

```python
def _set_opening_balance(self):
    for account in self:
        balance = account.opening_balance
        # Positive balance -> Debit line
        # Negative balance -> Credit line
        account._set_opening_debit_credit(abs(balance) if balance > 0.0 else 0.0, 'debit')
        account._set_opening_debit_credit(abs(balance) if balance < 0.0 else 0.0, 'credit')
```

### Performance optimization — batch writing

If you import 500 accounts with opening balances, Odoo does NOT update the opening journal entry 500 separate times. Instead:

Source: [`_set_opening_debit_credit()`](../addons/account/models/account_account.py#L736)

```python
# Odoo batches all opening balance writes using a precommit hook
if 'import_account_opening_balance' not in self.env.cr.precommit.data:
    data = self.env.cr.precommit.data['import_account_opening_balance'] = {}
    self.env.cr.precommit.add(self._load_precommit_update_opening_move)
```

It collects all changes, then writes them to the opening move in a single operation just before the database transaction commits. This is critical for import performance.

### Company fields involved

| Field | UI Label | Purpose |
|---|---|---|
| `account_opening_move_id` | "Opening Journal Entry" | The move that holds all opening balances |
| `account_opening_journal_id` | "Opening Journal" | Related via `account_opening_move_id.journal_id` |
| `account_opening_date` | "Opening Entry" | Date of the opening entry |

Source: [`company.py:175`](../addons/account/models/company.py#L175)

---

## How Odoo Picks Accounts Automatically

This is the core COA automation: when a user creates an invoice line, Odoo resolves the correct account without manual selection. The logic is in [`_compute_account_id()`](../addons/account/models/account_move_line.py#L725).

**For managers:** You do not need to pick an account every time you create an invoice. Odoo figures out which account to use based on the product, the customer, and company defaults. Here is the exact decision process.

### Complete Invoice Line Account Resolution Flow

```
User creates a Customer Invoice line
                |
                v
+--------- What type of line is this? ---------+
|                                               |
v                                               v
PAYMENT TERM LINE                          PRODUCT LINE
(the "total amount due" line               (a line with a product or
 that tracks what customer owes)            amount to invoice)
        |                                       |
        v                                       v
  1. Was an account previously           Is a product selected?
     set on this invoice?                    |           |
     (SQL lookup on same move)              YES          NO
        |                                   |            |
     YES -> use it                          v            v
     NO  -> continue                  Product has     Partner set?
        |                             accounts?        |        |
        v                                |            YES       NO
  2. Partner's receivable account       YES            |         |
     partner.commercial_partner_id       |             v         v
     .property_account_receivable_id     v        Use partner's  Fall
     (or _payable_id for vendor bills)  Get it:   most frequent  through
        |                               1. Product-level account       |
     Found -> use it                       property_account_income_id  |
     Empty -> continue                  2. Category-level              |
        |                                  categ_id.property_          |
        v                                  account_income_categ_id     |
  3. Company partner's account          3. Company default             |
     company.partner_id.property_          company.income_account_id   |
     account_receivable_id                    |                        |
        |                                     v                        |
        v                              Apply fiscal position           |
  4. First active receivable/payable
     account in the company (SQL fallback)               map_account() if set            |
        |                                                              |
        v                              <-------------------------------+
  Apply fiscal position                         |
  map_account() if set                          v
                                    FALLBACK (still no account):
                                      1. Do previous 2 lines on this
                                         invoice use the same account?
                                         YES -> use it
                                      2. journal.default_account_id
```

Source: [`account_move_line.py:725`](../addons/account/models/account_move_line.py#L725) and [`product.py:125`](../addons/account/models/product.py#L125)

### Key points

- Fiscal position is **always applied last** — it substitutes the resolved account with a mapped one. It never picks the account from scratch; it only replaces it.
- The "most frequent account for partner" lookup searches the last 2 years of invoice lines for that partner, filtered by `internal_group` (`income` for sales, `expense` for purchases).
  Source: [`_get_most_frequent_accounts_for_partner()`](../addons/account/models/account_account.py#L776)

---

## Property Account System — How Defaults Cascade

This is the mechanism that makes the account resolution flow above work — where the "default" accounts for partners and products come from.

### What it is

Odoo uses `ir.default` records to store company-specific default field values. `property_account_*` fields on `res.partner` and `product.template` are `company_dependent=True` fields backed by `ir.default`.

**Odoo 20 changed how those defaults get written.** Instead of the chart template calling `ir.default.set()` directly, each default is exposed as a plain field on `res.company`, wired through the helper
[`company_default_for(fname, target_model, target_fname)`](../odoo/addons/base/models/res_company.py) — a compute/inverse pair that reads and writes the underlying `ir.default` record:

| Company field | Backs this `ir.default` | Set by |
|---|---|---|
| `receivable_account_id` | `res.partner.property_account_receivable_id` | [company.py:322](../addons/account/models/company.py#L322) |
| `payable_account_id` | `res.partner.property_account_payable_id` | [company.py:328](../addons/account/models/company.py#L328) |
| `income_account_id` | `product.category.property_account_income_categ_id` | [company.py:306](../addons/account/models/company.py#L306) |
| `expense_account_id` | `product.category.property_account_expense_categ_id` | [company.py:313](../addons/account/models/company.py#L313) |
| `account_stock_valuation_id` | `product.category.property_stock_valuation_account_id` | [company.py:340](../addons/account/models/company.py#L340) |
| `account_stock_journal_id` | `product.category.property_stock_journal` | [company.py:355](../addons/account/models/company.py#L355) |
| `inventory_valuation` | `product.category.property_valuation` | [company.py:349](../addons/account/models/company.py#L349) |
| `cost_method` | `product.category.property_cost_method` | [company.py:373](../addons/account/models/company.py#L373) |

The chart template now just writes these company fields in its `@template(code, 'res.company')` block ([template_generic_coa.py:25](../addons/account/models/template_generic_coa.py#L25)); the inverse does the `ir.default.set()`. Practical consequence: **the company setting and the `ir.default` are the same value, in both directions.** Change "Expense Account" in Accounting Settings and every product category without its own override follows immediately.

### Concrete Example — Which Expense Account Gets Used?

You create a vendor bill for an "Office Supplies" product. Which expense account does Odoo use?

```
Product: "Office Supplies"
  property_account_expense_id = ? (empty — not set on this product)
    |
    v  Falls back to...
Category: "Supplies"
  property_account_expense_categ_id = ? (empty)
    |
    v  NEW IN 20: walk up the category tree...
Parent Category: "Consumables"
  property_account_expense_categ_id = ? (empty)
    |
    v  ...and keep walking until a category sets one, then...
Company Settings
  expense_account_id = "6000 - Operating Expenses"   <-- USED
```

The code that implements this cascade:

Source: [`product.py:125`](../addons/account/models/product.py#L125), [`_get_category_account`](../addons/account/models/product.py#L150)
```python
def _get_product_accounts(self):
    # ... cached in self.env.cr.cache for the transaction ...
    stock_valuation = self._get_category_account('property_stock_valuation_account_id') \
        or (self.company_id or self.env.company).account_stock_valuation_id
    return {
        'income': (
            self.property_account_income_id
            or self._get_category_account('property_account_income_categ_id', 'income_account_id')
        ),
        'expense': (
            self.property_account_expense_id
            or self._get_category_account('property_account_expense_categ_id')
            or (self.company_id or self.env.company).expense_account_id
        ),
        'stock_valuation': stock_valuation,
        'stock_variation': stock_valuation.account_stock_variation_id,
    }

def _get_category_account(self, field_name, company_field=None):
    categ = self.categ_id
    while categ:                       # <- the Odoo 20 change
        if categ[field_name]:
            return categ[field_name]
        categ = categ.parent_id
    return (self.company_id or self.env.company)[company_field] if company_field else ...
```

The category lookup walks `categ.parent_id` up to the root before falling back to the company default, and the result is cached per transaction (`env.cr.cache['account_product_accounts']`). `_get_product_accounts()` returns `income`, `expense`, `stock_valuation` and `stock_variation`; `get_product_accounts()` adds `stock_journal`.

### Override hierarchy — when to use each level

| Level | Where to Set | When to Use | Example |
|---|---|---|---|
| Product | Product form > Accounting tab > "Expense Account" | When THIS specific product needs a different account | "Hardware Purchases" product posts to 5100 instead of 6000 |
| Category | Product Category form > Accounting Properties | When all products in this category share the same account | All "Software" products post to 5200 |
| Company | Settings > Accounting > "Expense Account" | Default for all products without overrides | Everything else posts to 6000 |

**Important:** These are `company_dependent=True` fields — you can set different defaults per company in a multi-company setup.

**In practice:** most companies never touch partner-level overrides. The category-level override is used when different product lines (e.g., software vs. hardware) post to different revenue accounts.

---

## Fiscal Position (Account Mapping)

A fiscal position overrides which account (and taxes) are used when invoicing a partner in a specific country or VAT regime.

**For managers:** If you sell to customers in different countries, a fiscal position automatically swaps the account and tax used on their invoices. For example, a domestic sale might use "Sales Revenue (Domestic)" with 20% VAT, while an EU sale uses "Sales Revenue (EU)" with 0% VAT — and this swap happens automatically.

### How it works

`map_account(account)` at [`partner.py:165`](../addons/account/models/partner.py#L177):

```python
def map_account(self, account):
    return self.env['account.account'].browse(
        (self.account_map or {}).get(account.id, account.id)
    )
```

`account_map` is a `{src_id: dest_id}` dict computed from `account.fiscal.position.account` lines.
If the account has no mapping, it passes through unchanged.

### Which fiscal position is used

[`_get_fiscal_position()`](../addons/account/models/partner.py#L259) resolution order:

1. `delivery.property_account_position_id` — manually set on the delivery address
2. `partner.property_account_position_id` — manually set on the partner
3. Auto-apply: searches all `AccountFiscalPosition` with `auto_apply = True`, picks the first matching one

### Auto-apply matching criteria

| Field | Matches when |
|---|---|
| `country_id` | Partner's delivery country equals this |
| `country_group_id` | Partner's delivery country is in this group (e.g., EU) |
| `state_ids` | Partner's delivery state is in this list |
| `zip_from` / `zip_to` | Partner's zip code is in this range |
| `vat_required = True` | Only apply if partner has a VAT number set |

All set criteria must match. Positions are evaluated in `sequence` order.

### `foreign_vat` — your company in another country

If your company registers for VAT in another country (e.g., you're a UK company registered for French VAT), set `foreign_vat` on the fiscal position. This links the position to a second tax registration. Odoo can then load that country's taxes via `action_create_foreign_taxes()`.

Source: [`partner.py:73`](../addons/account/models/partner.py#L73)

### Where to configure

Accounting > Configuration > Fiscal Positions

---

## Account Suggestions on Invoice Lines

When a user picks an account on a journal line, Odoo suggests accounts ordered by frequency of use for that partner.

**Logic:**
1. Look up `account.move.line` for the same partner, last 2 years.
2. Order by count of usage (most used first).
3. Filter by `internal_group`: `income` for customer invoices, `expense` for vendor bills.

Source: [`_get_most_frequent_accounts_for_partner()`](../addons/account/models/account_account.py#L776)

In the formatted dropdown ([`_compute_display_name()`](../addons/account/models/account_account.py#L913)) each entry shows:

```
<code> <name_path>  `Suggested`  `Asset`
--<description>--
```

- `code` only for users in `account.group_account_readonly`
- `name_path` — the full parent chain, not just the leaf name (new in 20)
- `` `Suggested` `` — the partner-frequency hit above
- `` `Asset` `` — the account feeds the Fixed Assets module
- `description` — the account's free-text `description` field, on its own line (new in 20)

---

## Configuration — Company Settings

Settings are in `res.config.settings` (transient), mostly relayed to `res.company`.

Source: [`models/res_config_settings.py`](../addons/account/models/res_config_settings.py)

| Setting field | UI Label | Where stored | Effect |
|---|---|---|---|
| `currency_id` | "Currency" | `company_id.currency_id` | Company's primary currency |
| `chart_template` | (COA picker) | `company_id.chart_template` | Which chart of accounts is loaded |
| `account_fiscal_country_id` | "Fiscal Country Code" | `company_id.account_fiscal_country_id` | Country for tax reporting |
| `tax_calculation_rounding_method` | "Tax Calculation Rounding Method" | `company_id.tax_calculation_rounding_method` | `round_globally` (per tax) vs `round_per_line` |
| `currency_exchange_journal_id` | "Exchange Gain or Loss Journal" | `company_id.currency_exchange_journal_id` | Journal for FX gain/loss entries |
| `income_currency_exchange_account_id` | "Gain Exchange Rate Account" | `company_id.income_currency_exchange_account_id` | Account for FX gains (`internal_group = income`) |
| `expense_currency_exchange_account_id` | "Loss Exchange Rate Account" | `company_id.expense_currency_exchange_account_id` | Account for FX losses (`account_type = expense`) |
| `account_journal_suspense_account_id` | "Bank Suspense" | `company_id.account_journal_suspense_account_id` | Temporary account for unreconciled bank imports |
| `transfer_account_id` | "Internal Transfer" | `company_id.transfer_account_id` | Intermediary account between two bank journals |
| `group_cash_rounding` | "Cash Rounding" | `implied_group = account.group_cash_rounding` | Enables cash rounding on invoices |
| `tax_exigibility` | "Cash Basis" | `company_id.tax_exigibility` | Enables cash basis tax computation |

---

## Security Groups

Source: [`security/account_security.xml`](../addons/account/security/account_security.xml)

| Group | XML ID | Who it gives | Implied by |
|---|---|---|---|
| Billing (Invoice) | `group_account_invoice` | Create/edit invoices, payments | `group_account_basic`, `group_account_manager` |
| Basic Accounting | `group_account_basic` | Invoice + basic bank reconciliation | `group_account_user` |
| Read-only Accounting | `group_account_readonly` | See everything (entries, reports, advanced config) | `group_account_user` |
| Accountant (User) | `group_account_user` | Full accounting except advanced config | — |
| Accounting Manager | `group_account_manager` | Everything including lock dates, COA setup | — |
| Secured Entries | `group_account_secured` | Hash-locked entry integrity | — |
| Cash Rounding | `group_cash_rounding` | Enabled by "Cash Rounding" setting | — |

**Who can see account codes in dropdowns:**
`group_account_readonly` — the `display_name` of an account only shows its code
to users in this group. Others (Invoicing users) see only the name.
Source: [`_compute_display_name()`](../addons/account/models/account_account.py#L913)

---

## Multi-Company Account Sharing

An `account.account` belongs to `company_ids` (Many2many).
Two companies in the same root hierarchy can share the same account record while each having a different code stored in `code_store`.

**Constraints:**
- `asset_cash` accounts **cannot** be shared — they are per-company (bank accounts).
  Source: [`_check_company_consistency()`](../addons/account/models/account_account.py#L248)
- You cannot remove a company from an account if that company has posted journal lines on it.
- `asset_receivable` and `liability_payable` accounts must always have `reconcile = True`.
  Source: [`_check_reconcile()`](../addons/account/models/account_account.py#L35)

---

## Common Mistakes and How Odoo Prevents Them

These are the most frequent errors users encounter when working with the COA. Odoo blocks all of them with validation errors, but understanding WHY they are blocked helps avoid confusion.

### Mistake 1: Making a Receivable/Payable Account Non-Reconcilable

**What you tried:** Unchecked "Allow Reconciliation" on a Receivable account.

**Why Odoo blocks it:** Receivable and Payable accounts MUST be reconcilable. Reconciliation is how Odoo matches a customer's $500 payment against their $500 invoice. Without it, you could never close out invoices.

Source: [`_check_reconcile()`](../addons/account/models/account_account.py#L35)

### Mistake 2: Setting a Receivable/Payable Account as a Journal Default

**What you tried:** Changed a Sales journal's default account to a Receivable-type account.

**Why Odoo blocks it:** Sales/Purchase journals expect income/expense accounts as their default. The receivable/payable line is auto-generated separately by the payment term logic. If the default account were Receivable, every invoice line would post to Receivable — making it impossible to track revenue.

Source: [`_check_account_type_sales_purchase_journal()`](../addons/account/models/account_account.py#L269)

### Mistake 3: Currency Mismatch Between Account and Journal

**What you tried:** Set a EUR currency on an account, but the journal using it is set to USD.

**Why Odoo blocks it:** If a journal forces a currency (e.g., a EUR bank journal), every account it uses must either have no currency set (flexible) or match the journal's currency exactly. A mismatch would produce journal entries with conflicting currency amounts.

Source: [`_check_journal_consistency()`](../addons/account/models/account_account.py#L175)

### Mistake 4: Deleting a Parent Account That Still Has Children

**What you tried:** Deleted the "Property, Plant & Equipment" header account while "Land" and "Construction" still pointed at it.

**Why Odoo blocks it:** `parent_id` is declared `ondelete='restrict'` and account parents are never re-parented automatically. Move the children first (clear or repoint their `parent_id`), then delete.

Source: [`parent_id`](../addons/account/models/account_account.py#L133)

---

## UI Entry Points

| Entry Point | Path in UI | What It Does |
|---|---|---|
| Chart of Accounts list | Accounting > Accounting > Chart of Accounts | Indented hierarchy of all accounts; filter by root in the search panel; edit codes, types, tags |
| Account form | Click any account in COA list | Edit account details; set the **Parent Account**; set opening balance; view related taxes |
| Mapping tab (account form) | Visible when the user has >1 company | Per-company code editor (`account.code.mapping`) |
| Account Tags | Accounting > Configuration > Account Tags | Create/edit tags (applicability: accounts/taxes/products) |
| Settings > Accounting | Settings > Accounting | Chart template, currency, fiscal country, special accounts |
| Setup Wizard | First access to Accounting app | Walks through chart template selection + opening date |

---

## Business Flow — First-Time Setup

```
New company created
    |
    v
Odoo shows Setup Wizard (onboarding)
    |
    v
User picks chart template (or country auto-selects one)
    |
    v
AccountChartTemplate.try_loading() runs
    |
    v
account.account records created (100-500+ accounts depending on localization,
  with parent_id links if the localization ships a tree)
account.fiscal.position / account.tax.group / account.tax records created
account.journal records created (Sales, Purchase, Bank, Cash, Credit Card, Misc)
    |
    v
Company fields set: bank_account_code_prefix, special account IDs,
  receivable/payable/income/expense defaults (which write the ir.defaults)
    |
    v
User sets Opening Date (account_opening_date)
    |
    v
User enters opening balances on each account (writes to account_opening_move_id)
    |
    v
User posts opening entry -> accounting is live
```

---

## Inventory Variation Account (`account_stock_variation_id`)

> These fields and the whole closing flow live in core `account`. `stock_account` only *overrides* the base implementation to use real stock valuation instead of a `qty_available × standard_price` approximation.
> Fields defined at: [`account/models/account_account.py:156`](../addons/account/models/account_account.py#L156)

### What it is

A field on `account.account` that points to another account used as the counterpart when recording inventory value adjustments at period close.

```python
account_stock_variation_id = fields.Many2one(
    'account.account', string='Variation Account',
    help="At closing, register the inventory variation of the period into a specific account")
```

There is also a companion field on the same model:

| Field | Type | Purpose |
|---|---|---|
| `account_stock_variation_id` | `Many2one` `account.account` | Counterpart for inventory value adjustments (stock variation) |
| `account_stock_variation_active` | `Boolean` (related) | Warns in the UI when the chosen variation account was archived |
| `account_stock_expense_id` | `Many2one` `account.account` | Counterpart for continental perpetual accounting adjustments |
| `account_stock_expense_active` | `Boolean` (related) | Same, for the expense account |

Source: [`account/models/account_account.py:156-163`](../addons/account/models/account_account.py#L156-L163)

### The problem it solves

During a fiscal period, stock moves create journal entries hitting the **Stock Valuation Account** (e.g., `1400 - Stock Valuation`). At period close, there can be a gap between:

- **Inventory system value** — what the WMS/stock module says the inventory is worth (based on `product.total_value`)
- **Accounting ledger value** — sum of all posted `account.move.line.balance` on the stock valuation account

This gap is the **stock variation**. Causes include: timing differences (goods received but not yet invoiced), rounding, manual adjustments, inventory adjustments (shrinkage, damage), or cost method differences. The variation account is where Odoo records the adjustment entry to bring the books in line with actual inventory.

### Where it's configured

The variation account is set **on the stock valuation account itself**, not on the product or category. The chain:

```
Product Category (product.category)
  -> property_stock_valuation_account_id  (e.g. "1400 Stock Valuation")
       -> account_stock_variation_id      (e.g. "6100 Stock Variation")
```

The product category also exposes it as a related field for convenience:
Source: [`account/models/product.py:48-51`](../addons/account/models/product.py#L48-L51)

```python
# on product.category
account_stock_variation_id = fields.Many2one(
    'account.account', string="Stock Variation Account", readonly=False,
    related="property_stock_valuation_account_id.account_stock_variation_id")
```

### Company-level settings involved

These are on `res.company`, **in core `account`** since Odoo 20 ([company.py:337-375](../addons/account/models/company.py#L337-L375)):

| Field | UI Label | Purpose |
|---|---|---|
| `account_stock_journal_id` | "Stock Journal" | The journal where closing entries are posted. Backs `product.category.property_stock_journal` |
| `account_stock_valuation_id` | "Stock Valuation Account" | Company-level fallback valuation account. Backs `property_stock_valuation_account_id` |
| `inventory_period` | "Inventory Period" | `manual` / `daily` / `monthly` — controls the auto-close cron |
| `inventory_valuation` | "Valuation" | `periodic` (at closing) / `real_time` (at invoicing). Backs `property_valuation` |
| `cost_method` | "Cost Method" | `standard` / `average` in core; **`fifo` is added by `stock_account`** ([stock_account/models/res_company.py:13](../addons/stock_account/models/res_company.py#L13)). Backs `property_cost_method` |

All of these use `company_default_for(...)`, so the company setting *is* the `ir.default` for the matching `product.category` property — see [Property Account System](#property-account-system--how-defaults-cascade).

### The full closing flow — step by step

When you click **"Close Inventory Valuation"** (or the cron runs), `action_close_stock_valuation()` executes.
Source: [`account/models/company.py:1278`](../addons/account/models/company.py#L1278) — the whole flow moved from `stock_account` to core in Odoo 20.

```
0. Guard: refuse if a closing entry already exists after `at_date`.

   If include_accruals: post the accrual entries (bills to receive, billed not
   received, invoices to issue, invoiced not delivered) via
   _create_accrual_moves(). NEW IN 20.
     - stock installed  -> accruals posted BEFORE the closing is computed,
       so Stock Variation already reflects them
     - stock NOT installed -> posted AFTER, so their GL impact isn't absorbed

1. _action_close_stock_valuation()          (company.py:1434)
   orchestrates the three value-building steps below.

2. _get_extra_closing_aml_vals()            [STEP A: Location reclassification]
   Core returns []; stock_account overrides it with
   _get_location_valuation_vals() — if stock locations carry their own
   valuation_account_id, value is moved from the location account to the
   product's stock valuation account. Multi-warehouse scenarios only.

3. _get_stock_valuation_account_vals()      [STEP B: Global stock variation]
   (company.py:1489) Compares, per valuation account:
     get_inventory_value()            -> what the goods on hand are worth
     get_inventory_accounting_value() -> sum of posted lines on that account
   Difference goes to account.account_stock_variation_id.
   Fallback: company.expense_account_id. If neither is set, the account is
   silently skipped.

   Without `stock_account`, get_inventory_value() is the approximation
   qty_available * standard_price; with it, the real stock valuation.

4. _get_continental_realtime_variation_vals() [STEP C: Continental perpetual]
   (company.py:1522) Only for accounts that have BOTH
   account_stock_variation_id and account_stock_expense_id.
   Computes the accounting value change over the fiscal year
   (today vs fiscal year start), net of the variation account's own balance.
   Posts between the expense and variation accounts.

5. Creates a single account.move in account_stock_journal_id, flagged
   inventory_closing = True, dated at_date, ref "Stock Closing".
   Raises if the Stock Journal or Valuation Account is unset.
   If triggered by cron (auto_post=True), posts automatically.
```

### Real-world example — periodic valuation (standard cost)

**Setup:**
- Company uses periodic valuation with standard costing
- Product "Laptop" — standard price $500, category "Electronics"
- Electronics category: `property_stock_valuation_account_id` = `1400 Stock Valuation`
- Account `1400` has: `account_stock_variation_id` = `6100 Stock Variation`

**During the month:**
1. Receive 100 laptops from vendor (PO receipt) — stock module records 100 units
2. Ship 20 laptops to customers (delivery orders) — stock module records 80 units remaining
3. Inventory adjustment: 2 laptops damaged — stock module records 78 units remaining

**At month-end closing:**

| Source | Value |
|---|---|
| Inventory system (`product.total_value`) | 78 units x $500 = **$39,000** |
| Accounting ledger (sum of posted lines on `1400`) | e.g. **$38,500**, last month's closing balance: in periodic mode bills post to expense, so `1400` moves only at closings |
| **Gap** | **$500** |

Odoo creates:

```
Stock Closing Journal Entry (in Stock Journal):
  Debit   1400 Stock Valuation     $500
  Credit  6100 Stock Variation     $500
  Ref: "Closing: Stock Variation Global for company [My Company]"
```

After posting, the ledger on `1400` now shows $39,000 — matching inventory.

### Real-world example — continental perpetual (real-time)

**Setup:**
- Company uses perpetual/real-time valuation (European/Continental style)
- Same product category, but `inventory_valuation = 'real_time'`
- Account `1400` also has: `account_stock_expense_id` = `6000 Operating Expenses`

**During the month:**
- Vendor bills post to `1400` and customer invoices carry COGS lines; receipts, deliveries and adjustments post nothing unless a location has a valuation account
- But the **variation** (difference between expenses recognized and inventory movement) is NOT posted during the period

**At month-end closing:**

Odoo computes:
```
accounting_value_today       = sum of posted lines on 1400 as of today
accounting_value_fiscal_start = sum of posted lines on 1400 as of Jan 1
variation_over_period        = today - fiscal_start + existing_variation_balance
```

If variation is non-zero:

```
Stock Closing Journal Entry:
  Debit   6000 Operating Expenses    $300
  Credit  6100 Stock Variation       $300
  Ref: "Closing: Stock Variation Over Period"
```

Note: in continental mode, both `account_stock_variation_id` AND `account_stock_expense_id` must be set on the valuation account. If either is missing, the account is silently skipped.
Source: [`account/models/company.py:1522`](../addons/account/models/company.py#L1522)

### Automatic closing via cron

Source: [`account/models/company.py:1447`](../addons/account/models/company.py#L1447), cron record [`service_cron.xml`](../addons/account/data/service_cron.xml)

The cron `_cron_post_stock_valuation()` selects companies where `inventory_valuation != 'real_time'` **and**:
- `inventory_period = 'daily'` — runs every day
- `inventory_period = 'monthly'` — added to the selection only on the last day of the month

It calls `action_close_stock_valuation(auto_post=True, raise_error_if_closed=False)`, which creates AND posts the closing entry automatically, skipping companies with nothing to close.

### In the generic COA

The stock variation account is [`110200 - Inventory Variation`](../addons/account/data/template/account.account-generic_coa.csv#L33), type `asset_current`; the valuation account is `1101 - Inventory Valuation`, also `asset_current`. `@template('generic_coa', 'account.account')` wires `stock_valuation.account_stock_variation_id = stock_variation` ([template_generic_coa.py:65](../addons/account/models/template_generic_coa.py#L65)); the company's fallback is `account_stock_valuation_id = 'stock_valuation'` ([template_generic_coa.py:51](../addons/account/models/template_generic_coa.py#L51)).

### How the balance calculation works in code

Source: [`account/models/company.py:1377-1433`](../addons/account/models/company.py#L1377-L1433)

```python
# Inventory value — core approximation, overridden by stock_account
def get_inventory_value(self, at_date=None):
    # core: qty_available * standard_price per valuation account
    # stock_account override: product.with_context(to_date=at_date).total_value

# Accounting value: from posted journal entries
def get_inventory_accounting_value(self, at_date=None):
    # SELECT account_id, SUM(balance)
    # FROM account_move_line
    # WHERE account_id IN (valuation_accounts) AND parent_state = 'posted'
```

The variation = `get_inventory_value() - get_inventory_accounting_value()`. If positive, inventory is worth more than the books show (increase valuation). If negative, inventory is worth less (shrinkage/loss).

### Summary table — which accounts are involved

| Account | Role | Example code | Where configured |
|---|---|---|---|
| Stock Valuation | Holds inventory value on balance sheet | `1101` | Product Category > `property_stock_valuation_account_id`, company fallback `account_stock_valuation_id` |
| Inventory Variation | Receives the closing adjustment (counterpart) | `110200` | On the valuation account > `account_stock_variation_id` |
| Stock Expense | Continental perpetual expense counterpart | `6000` | On the valuation account > `account_stock_expense_id` |
| Stock Journal | Journal where closing entries are posted | `STJ` | Settings > `account_stock_journal_id` |

---

## Edge Cases & Gotchas

- **`equity_unaffected` is special:** It is the only equity account where `include_initial_balance = False`. Odoo uses it to show "current year earnings" on the balance sheet. If you use a wrong account type here, your balance sheet will not balance.

- **Changing `account_type` is blocked when used as a journal default:** If a **sale or purchase** journal has `default_account_id` pointing to an account, changing its type to `asset_receivable` or `liability_payable` raises a `ValidationError`. General/bank/cash journals are not affected. Source: [`_check_account_type_sales_purchase_journal()`](../addons/account/models/account_account.py#L269).

- **Changing currency on account checks journal consistency:** If a journal uses this account and has a currency set, both must match. Source: [`_check_journal_consistency()`](../addons/account/models/account_account.py#L175).

- **Account codes are per company root, not per company:** In a branch setup, `company_id = branch` and `company_id.root_id = parent`. The branch's accounts share codes with the parent via `code_store[root_id]`. Changing a code in one company changes it for all companies sharing the same root.

- **`account.root` is not a real DB model:** It has `_auto = False` and `_table_sql = SQL('(0)')`. Searching it with any domain other than `('id', 'in', ...)` or `('id', 'parent_of', ...)` raises `UserError`. Source: [`account_root.py:25`](../addons/account/models/account_root.py#L25).

- **`off_balance` accounts:** Cannot have `reconcile = True` and cannot have `tax_ids`. Odoo enforces both. Source: [`_constrains_reconcile()`](../addons/account/models/account_account.py#L166).

- **Reloading a chart template** (when the same template is already installed): `_pre_reload_data()` runs first. It strips reconcile models, skips existing journals, and preserves tax names by prefixing old ones with `[old]`. It does NOT delete accounts. Source: [`chart_template.py:276`](../addons/account/models/chart_template.py#L276).

- **New account type auto-inference:** When you create an account with a code but no type, Odoo calls `_get_closest_parent_account()` to find the nearest account by code (binary search on sorted codes) and copies its `account_type`. Default if nothing matches: `asset_current`. The same helper also copies `tag_ids`. Source: [`_compute_account_type()`](../addons/account/models/account_account.py#L644).

- **`account.group` no longer exists.** Any custom code, report, or export referencing `account.group`, `group_id`, `code_prefix_start` / `code_prefix_end`, or `_adapt_parent_account_group()` will break on Odoo 20. The replacement is `account.account.parent_id`. Odoo ships an upgrade script ([odoo/upgrade#9357](https://github.com/odoo/upgrade)) that converts existing groups into parent accounts.

- **`parent_id` has no automatic resolution.** Codes and parents are independent. An account coded `1501` is not automatically a child of an account coded `15` — nothing links them unless you set `parent_id`.

- **Ordering follows the tree, not the code.** `_order = "code_path, account_type, name_path"`. A child sorts under its parent even if its own code would place it elsewhere.

---

## Related Docs

- [`INDEX.md`](INDEX.md)

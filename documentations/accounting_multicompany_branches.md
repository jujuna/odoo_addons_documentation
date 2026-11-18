# Accounting: Multi-Company vs Branches -- Decision Guide with Examples

> **Modules:** `account`, `account_inter_company_rules`, `account_reports`, `account_accountant`, `analytic`
> **Paths:** [`addons/account/`](../addons/account/), [`enterprise/account_inter_company_rules/`](../enterprise/account_inter_company_rules/), [`enterprise/account_reports/`](../enterprise/account_reports/), [`addons/analytic/`](../addons/analytic/)
> **Odoo Version:** 20
>
> Odoo 20 changed two things that matter a lot here: record rules moved to the unified `ir.access` model, and the Interco Comparison report was added. See [What Changed in Odoo 20](#what-changed-in-odoo-20).

---

## The Core Question

You have one business with multiple locations or divisions. Odoo gives you three ways to organize them:

| | **Analytic Accounts** | **Branches** | **Multi-Company** |
|---|---|---|---|
| What it is | Tags on journal entries | Divisions inside ONE legal entity | Separate legal entities |
| Legal identity | None -- just labels | None -- parent's VAT | Each has own VAT |
| Chart of Accounts | 1 shared | 1 shared | 1 per company (separate records) |
| Currency | One | Must match parent | Can differ per company |
| Tax return | 1 combined | 1 combined | 1 per company (unless Tax Unit) |
| Fiscal year | Shared | Shared (delegated from root) | Independent per company |
| Lock dates | Shared | Inherited from root (max of ancestors) | Independent per company |
| Bank accounts | Shared | 1 per branch (required, cannot share) | 1 per company |
| Invoice sequences | Shared | Per branch journal | Per company journal |
| Inter-entity invoicing | N/A | Not needed | Required (auto or manual) |
| Balance Sheet split | Not possible by location | Filter by branch | Separate per company |
| Reports | Analytic filter on P&L only | Company filter on everything | Consolidation toggle |
| Access control per location | Not possible | Yes (company-based) | Yes (company-based) |
| Setup effort | 30 seconds per location | 5 minutes per branch | Hours per company |

**Think of it this way:**
- **Analytic Accounts** = sticky notes on your journal entries ("this cost belongs to Batumi")
- **Branches** = departments inside your company with their own bank accounts and invoice numbers
- **Multi-Company** = completely separate businesses that happen to share one Odoo database

---

## Quick Decision Checklist

Answer each question. If ANY answer is "yes" -- use Multi-Company.

| Question | YES = | NO = |
|---|---|---|
| Separate legal entities (different VAT numbers)? | Multi-Company | Could be branches |
| Separate tax returns? | Multi-Company | Could be branches |
| Different currencies? | Multi-Company | Could be branches |
| Independent Chart of Accounts? | Multi-Company | Could be branches |
| Different fiscal years? | Multi-Company | Could be branches |
| Can one entity sue the other? | Multi-Company | Branches |

ALL answers "no"? Then ask:

| Question | YES = | NO = |
|---|---|---|
| Need per-location bank accounts? | Branches | Could be analytic |
| Need per-location invoice numbering? | Branches | Could be analytic |
| Need per-location access control? | Branches | Could be analytic |
| Need per-location Balance Sheet? | Branches | Could be analytic |

ALL answers "no"? Use **Analytic Accounts** (simplest).

---

## Running Example: "Atlas Group"

Throughout this document, one consistent example shows how each approach works.

**Business:** Atlas Group operates from 3 locations:
- **Tbilisi HQ** -- head office, admin, finance
- **Batumi Office** -- sales team, coastal region
- **Kutaisi Warehouse** -- logistics, distribution

**Monthly numbers (simplified):**

| | Tbilisi HQ | Batumi Office | Kutaisi Warehouse | Total |
|---|---|---|---|---|
| Revenue | 80,000 | 50,000 | 20,000 | 150,000 |
| COGS | 30,000 | 20,000 | 15,000 | 65,000 |
| Salaries | 25,000 | 12,000 | 8,000 | 45,000 |
| Rent | 5,000 | 3,000 | 4,000 | 12,000 |
| **Net Income** | **20,000** | **15,000** | **-7,000** | **28,000** |

---

## Approach A: Branches (Recommended for Atlas Group)

### What Are Branches?

Branches are child companies that share their parent's Chart of Accounts, taxes, and fiscal positions. They are NOT separate legal entities. Think of them as departments with their own bank accounts and journal sequences.

**When Luka in Batumi creates an invoice, the invoice says "Atlas Group" (the legal entity) but internally Odoo knows it belongs to the Batumi branch.**

### Setup

Atlas Group is ONE legal entity, one VAT, one currency (GEL). Use branches.

```
Atlas Group (root company)        <-- CoA, taxes, fiscal positions live here
  |-- Batumi Office (branch)      <-- inherits CoA, gets own journals + bank
  |-- Kutaisi Warehouse (branch)  <-- inherits CoA, gets own journals + bank
```

**Source:** [`res_company.py:87-92`](../odoo/addons/base/models/res_company.py#L87-L92) -- `parent_id`, `child_ids`, `all_child_ids`, `parent_ids`, `root_id` define the hierarchy.

**Important:** Once you create a branch under a parent, you **cannot change the parent later**. The hierarchy is locked at creation. **Source:** [`res_company.py:400`](../odoo/addons/base/models/res_company.py#L400) -- raises UserError: "The company hierarchy cannot be changed."

### Chart of Accounts: ONE shared CoA

All 3 locations use the same accounts. When the CoA template loads on the root company, it recursively loads on all children.

**Source:** [`_load() — chart_template.py:259-260`](../addons/account/models/chart_template.py#L259-L260)

```
110000  Accounts Receivable     --> shared by all 3 locations
210000  Accounts Payable        --> shared by all 3 locations
400000  Sales Revenue           --> shared by all 3 locations
500000  Cost of Goods Sold      --> shared by all 3 locations
600000  Salaries Expense        --> shared by all 3 locations
620000  Rent Expense            --> shared by all 3 locations
```

**How sharing works technically:** `account.account` uses `company_ids` (Many2many) -- one account record is linked to multiple companies. **Source:** [`account_account.py:120`](../addons/account/models/account_account.py#L120)

The `code_store` field is `company_dependent=True` -- the same account can show different codes per company if needed, exposed through the computed `code` field and the `code_mapping_ids` tab. **Source:** [`code` / `code_store` — account_account.py:46-47`](../addons/account/models/account_account.py#L46-L47)

**Exception:** Bank/Cash accounts CANNOT be shared between companies. If an account has type `asset_cash` and `len(company_ids) > 1`, Odoo raises "Bank & Cash accounts cannot be shared between companies." **Source:** [`account_account.py:258-259`](../addons/account/models/account_account.py#L258-L259)

**Odoo 20 additions that change branch COA work:**

| Change | Effect on branches |
|---|---|
| `account.account` is a tree (`parent_id`, `_parent_store`); `account.group` removed | The hierarchy shown in reports comes from parent accounts, and parent accounts are shared through `company_ids` like any other account |
| A code is no longer required for every company | A grouping account can exist without a code in a branch that does not use it |
| Creating an `asset_cash` / `liability_credit_card` account auto-creates a journal in that account's first company | Adding a branch bank account creates the branch's bank journal for you — [`_create_default_journals() — account_account.py:1129`](../addons/account/models/account_account.py#L1129) |
| Account codes may contain dashes | `1100-BAT` style branch-suffixed codes are now legal |
| `account.account.account_stock_variation_id` / `account_stock_expense_id` | Periodic inventory closing accounts, set per account and therefore shared by branches |

### Journals: Each Branch Gets Its Own

Each branch gets its own set of journals so entries are traceable and sequences are separate.

| Journal | Company | Code | Example Invoice |
|---|---|---|---|
| Customer Invoices | Atlas Group (HQ) | INV | INV/2026/0001 |
| Customer Invoices | Batumi Office | INV | INV/2026/0001 (separate counter) |
| Customer Invoices | Kutaisi Warehouse | INV | INV/2026/0001 (separate counter) |
| Bank | Atlas Group (HQ) | BNK1 | -- |
| Bank | Batumi Office | BNK2 | -- |
| Petty Cash | Kutaisi Warehouse | CSH1 | -- |

Journal entries automatically assign to the branch the user is working in via `_compute_company_id()`. **Source:** [`account_move.py:932-939`](../addons/account/models/account_move.py#L932-L939)

```python
# How company auto-assigns on journal entries (Odoo 20):
@api.depends('journal_id')
def _compute_company_id(self):
    for move in self:
        if move.journal_id.company_id not in move.company_id.parent_ids:
            move.company_id = (
                (move.journal_id.company_id in self.env.company.parent_ids and self.env.company)
                or move.journal_id.company_id
                or self.env.company
            )
```

Odoo 19 resolved this through `._accessible_branches()[:1]`. Odoo 20 states the intent directly: **if the journal belongs to an ancestor of the company you are working in, the entry stays in your company**; otherwise it follows the journal.

**Key insight:** Branches can ACCESS journals from the parent company via the `parent_of` access rule. But the entry's `company_id` will still be set to the user's branch. **Source:** [`journal_comp_rule — ir.access.csv:49`](../addons/account/security/ir.access.csv#L49)

### Fiscal Year & Lock Dates: Inherited from Root

**Root-delegated fields** (set once on root, automatically inherited by all branches):

| Field | Purpose |
|---|---|
| `currency_id` | Company currency — delegated at the base level |
| `fiscalyear_last_day` | Last day of fiscal year |
| `fiscalyear_last_month` | Last month of fiscal year |
| `account_storno` | Use storno accounting (reversal entries) |
| `tax_exigibility` | Cash-basis vs accrual VAT |

**Source:** [`_get_company_root_delegated_field_names() — company.py:401`](../addons/account/models/company.py#L401), base list at [`res_company.py:163`](../odoo/addons/base/models/res_company.py#L163) -- the values are copied from the root and shown readonly on branches.

**Lock dates:** Each branch CAN technically have its own lock date value, but the effective lock date is the **maximum across all ancestors**, less any active `account.lock_exception` for the current user. `_get_user_lock_date()` iterates over `parent_ids` and takes the strictest (latest) date.

**Source:** [`_get_user_lock_date() — company.py:749`](../addons/account/models/company.py#L749)

**Example:** If Atlas Group (root) sets `fiscalyear_lock_date = 2025-12-31`, then Batumi and Kutaisi also cannot post entries on or before 2025-12-31, even if they haven't set their own lock date.

### What the Profit & Loss Looks Like

**P&L -- Atlas Group (all branches, January 2026)**

| Account | Tbilisi HQ | Batumi | Kutaisi | **Total** |
|---|---|---|---|---|
| 400000 Sales Revenue | 80,000 | 50,000 | 20,000 | **150,000** |
| 500000 COGS | (30,000) | (20,000) | (15,000) | **(65,000)** |
| **Gross Profit** | **50,000** | **30,000** | **5,000** | **85,000** |
| 600000 Salaries | (25,000) | (12,000) | (8,000) | **(45,000)** |
| 620000 Rent | (5,000) | (3,000) | (4,000) | **(12,000)** |
| **Net Income** | **20,000** | **15,000** | **(7,000)** | **28,000** |

**How to get this:**
1. Go to Accounting > Reporting > Profit & Loss
2. In the company filter (top-right), select all branches
3. Reports automatically include all accessible branches via `_accessible_branches()`. **Source:** [`res_company.py:502`](../odoo/addons/base/models/res_company.py#L502)

**P&L -- Batumi Office only:** Switch active company to "Batumi Office" -- the report filters to that branch's journal entries automatically.

### What the Balance Sheet Looks Like

**Balance Sheet -- Atlas Group (all branches, Jan 31, 2026)**

| Account | Amount |
|---|---|
| **Assets** | |
| 110000 Accounts Receivable | 42,000 |
| 120000 Bank (HQ) | 95,000 |
| 120001 Bank (Batumi) | 23,000 |
| 120002 Bank (Kutaisi) | 8,000 |
| 150000 Inventory | 65,000 |
| **Total Assets** | **233,000** |
| **Liabilities** | |
| 210000 Accounts Payable | 38,000 |
| 230000 Tax Payable | 12,000 |
| **Total Liabilities** | **50,000** |
| **Equity** | |
| 300000 Share Capital | 155,000 |
| 350000 Retained Earnings | 28,000 |
| **Total Equity** | **183,000** |

**Key:** ONE balance sheet, ONE set of equity accounts. Bank accounts are separate per branch (enforced by Odoo) but everything else consolidates naturally. No elimination entries needed.

### Tax Return

ONE tax return for the entire entity. All branch transactions roll up. The VAT is shared (or inherited from parent if branch has none).

**Source:** [`_get_branches_with_same_vat() — enterprise/account_reports/models/res_company.py:207`](../enterprise/account_reports/models/res_company.py#L207) -- collects all branches sharing the same VAT number. `get_options()` uses it to decide whether export buttons stay enabled when only some branches are selected.

### Pros and Cons

**Pros:**

| Advantage | Example |
|---|---|
| Simple setup -- create branch, done | Adding a new Zugdidi office: create branch, assign users, start invoicing. No CoA, no taxes. 5 minutes. |
| One CoA to maintain | Tax authority adds new account code? Update once. With multi-company and 10 entities, that's 10 updates. |
| One tax return, no intercompany invoicing | Tbilisi provides IT services to Batumi? Just a journal entry. No invoice, no bill, no reconciliation. |
| Reports auto-aggregate | Open P&L, select all branches -- combined result instantly. No consolidation module. |
| Shared fiscal year and lock dates | Accountant locks January for all locations in one action. |
| Low ongoing maintenance | One set of tax rates, one set of payment terms. VAT changes from 18% to 20%? One update. |

**Cons:**

| Disadvantage | Example |
|---|---|
| Cannot have different currencies | Batumi starts invoicing in USD -- impossible. Must restructure to multi-company. |
| Cannot have independent fiscal years | Acquired entity with March 31 year-end must switch to December 31. |
| All locations see the same accounts | Kutaisi accountant can accidentally post to HQ's consulting revenue account. |
| Lock dates cascade from root | Unlocking November for Kutaisi unlocks it for everyone. The effective lock date is the max across all ancestors. |
| Cannot do separate external audits | No standalone financials for one branch. The audit covers the entire legal entity. |
| Payroll requires separate runs per branch | Cannot combine all employees in one payslip run. |

**Best for:** Retail chains (same country/owner), regional sales offices, construction companies with project offices, any single legal entity wanting per-location P&L.

**Not for:** Different countries/currencies, locations that might become separate legal entities, need for strict data isolation between locations.

---

## Approach B: Multi-Company (Separate Legal Entities)

### What Is Multi-Company?

Each company is a fully independent legal entity with its own Chart of Accounts, its own journals, its own taxes, its own bank accounts, its own fiscal year, and its own lock dates. They happen to share one Odoo database.

**When Luka in Batumi Trading LLC creates an invoice, it says "Batumi Trading LLC" and is legally a Batumi Trading document. Atlas Group cannot see it unless they have cross-company access.**

### When Atlas Group Needs This Instead

Suppose Batumi is actually "Batumi Trading LLC" (VAT: GE987654321) and Kutaisi is "Kutaisi Logistics LLC" (VAT: GE111222333). Now you MUST use multi-company.

```
Atlas Holding (root)           <-- parent, may or may not have its own accounting
  |-- Batumi Trading LLC       <-- separate company, own CoA, own VAT
  |-- Kutaisi Logistics LLC    <-- separate company, own CoA, own VAT
```

Or 3 completely independent companies with no parent-child at all:
```
Atlas Group LLC          <-- company 1
Batumi Trading LLC       <-- company 2
Kutaisi Logistics LLC    <-- company 3
```

### Chart of Accounts: Separate per Company

Each company loads its own CoA template independently. They CAN use the same template (e.g., all install Georgian CoA) but the resulting account records are physically separate.

**Source:** [`_load() — chart_template.py:184`](../addons/account/models/chart_template.py#L184) -- creates accounts per company, then recurses into `company.child_ids`.

| | Atlas Group | Batumi Trading | Kutaisi Logistics |
|---|---|---|---|
| 110000 A/R | Record #101 | Record #201 | Record #301 |
| 400000 Revenue | Record #102 | Record #202 | Record #302 |

Even if codes are identical, these are separate `account.account` records. You maintain 3 copies.

**Can they have different CoA structures?** Yes. Atlas uses a 6-digit CoA while Batumi uses a 4-digit CoA. This is impossible with branches.

### What the P&L Looks Like

Each company sees ONLY its own numbers:

**P&L -- Batumi Trading LLC only (January 2026)**

| Account | Amount |
|---|---|
| 400000 Sales Revenue | 50,000 |
| 500000 COGS | (20,000) |
| 600000 Salaries | (12,000) |
| 620000 Rent | (3,000) |
| **Net Income** | **15,000** |

To see the combined picture, you need the consolidation toggle (see below).

### What the Balance Sheet Looks Like

Each company has its OWN balance sheet with its OWN equity:

**Balance Sheet -- Batumi Trading LLC (Jan 31, 2026)**

| Account | Amount |
|---|---|
| 110000 Accounts Receivable | 15,000 |
| 120000 Bank | 23,000 |
| 150000 Inventory | 18,000 |
| **Total Assets** | **56,000** |
| 210000 Accounts Payable | 11,000 |
| **Total Liabilities** | **11,000** |
| 300000 Share Capital | 30,000 |
| 350000 Retained Earnings | 15,000 |
| **Total Equity** | **45,000** |

**Key difference from branches:** Each company has its own equity. Investments between companies show as assets/liabilities (intercompany receivables/payables), not as shared equity.

### Inter-Company Transactions

When Atlas Group sells goods to Batumi Trading for 10,000:

**Without inter-company rules (manual):**
1. Atlas creates Sales Invoice to Batumi Trading: DR A/R 10,000 / CR Revenue 10,000
2. Someone manually creates Purchase Bill in Batumi Trading: DR COGS 10,000 / CR A/P 10,000
3. You do both manually -- error-prone, time-consuming

**With `account_inter_company_rules` (automatic):**
1. Atlas posts Sales Invoice to Batumi Trading
2. Odoo automatically creates matching Bill in Batumi Trading
3. The bill lands in Batumi's configured `intercompany_purchase_journal_id`

**Source:** [`enterprise/account_inter_company_rules/models/account_move.py:11-25`](../enterprise/account_inter_company_rules/models/account_move.py#L11-L25)

**Configuration per company:**

| Field | Purpose | Source |
|---|---|---|
| `intercompany_generate_bills_refund` | Enable auto-bill creation when invoiced by another company | [`res_company.py:7`](../enterprise/account_inter_company_rules/models/res_company.py#L7) |
| `intercompany_document_state` | `'draft'` (review first) or `'posted'` (auto-post) | [`res_company.py:11`](../enterprise/account_inter_company_rules/models/res_company.py#L11) |
| `intercompany_purchase_journal_id` | Which journal receives the auto-generated bills | [`res_company.py:19`](../enterprise/account_inter_company_rules/models/res_company.py#L19) |

**Removed in Odoo 20:** `intercompany_user_id`. The mirror document is now created with `SUPERUSER_ID` and the target company in context, so there is no per-company technical user to configure (or to get wrong).
Source: [`_post() — account_inter_company_rules/models/account_move.py:11`](../enterprise/account_inter_company_rules/models/account_move.py#L11)

The company behind a partner is resolved with `_find_company_from_partner()`, which matches on `('partner_id', 'parent_of', partner_id)` — so invoicing a *contact* of another company also triggers the mirror bill.
Source: [`_find_company_from_partner() — res_company.py:27`](../enterprise/account_inter_company_rules/models/res_company.py#L27)

**Example journal entries for 10,000 intercompany sale:**

In **Atlas Group** books:
```
DR  110100  Intercompany A/R - Batumi    10,000
    CR  400000  Sales Revenue                        10,000
```

In **Batumi Trading** books (auto-generated):
```
DR  500000  COGS / Purchases             10,000
    CR  210100  Intercompany A/P - Atlas             10,000
```

### Consolidated P&L

To see the group-wide picture, use the consolidation feature in `account_reports`.

**How to generate:**
1. Accounting > Reporting > Profit & Loss
2. Select all 3 companies in the company filter
3. Enable the "Consolidation" toggle
4. Report groups by account code across companies

**Source:** [`_init_options_consolidation() — enterprise/account_reports/models/account_report.py:2220`](../enterprise/account_reports/models/account_report.py#L2220)

The toggle only appears when more than one company is selected **and** the report groups by `account_id`. It is on by default, and switching from one company to several turns it back on.

**Consolidated P&L -- simple (January 2026)**

| Account | Atlas | Batumi | Kutaisi | **Consolidated** |
|---|---|---|---|---|
| 400000 Revenue | 80,000 | 50,000 | 20,000 | **150,000** |
| 500000 COGS | (30,000) | (20,000) | (15,000) | **(65,000)** |
| 600000 Salaries | (25,000) | (12,000) | (8,000) | **(45,000)** |
| 620000 Rent | (5,000) | (3,000) | (4,000) | **(12,000)** |
| **Net Income** | **20,000** | **15,000** | **(7,000)** | **28,000** |

**WARNING:** This simple consolidation does NOT eliminate intercompany transactions. If Atlas sold 10,000 to Batumi, both Atlas revenue AND Batumi COGS are inflated. True consolidated P&L requires manual elimination entries:

**With elimination (what accountants actually need):**

| Account | Atlas | Batumi | Kutaisi | Elimination | **True Consolidated** |
|---|---|---|---|---|---|
| 400000 Revenue | 80,000 | 50,000 | 20,000 | (10,000) | **140,000** |
| 500000 COGS | (30,000) | (20,000) | (15,000) | 10,000 | **(55,000)** |
| **Net Income** | **20,000** | **15,000** | **(7,000)** | **0** | **28,000** |

Odoo's consolidation toggle is additive only (sum by account code). For IFRS-compliant elimination, you need manual consolidation journal entries.

**Odoo 20 gives you the detection half of the problem.** The new **Interco Comparison** report lists, per counterpart company and per account-type bucket, what each side booked and the difference — so you can find the intercompany balances that need eliminating instead of reconciling them in a spreadsheet. It does not post the elimination entries for you.

```
Currency → Counterpart company → Account type bucket → Account
                                   Main Company | Counterpart | Difference
```

Buckets are mirror pairs: receivable ↔ payable, income ↔ expense, current assets ↔ current liabilities, non-current assets ↔ equity & non-current liabilities, liquidity ↔ liquidity.

**Source:** [`interco_comparison_report.py`](../enterprise/account_reports/models/interco_comparison_report.py), [`interco_comparison_report.xml`](../enterprise/account_reports/data/interco_comparison_report.xml)

Defaults worth knowing: tax lines are hidden (`hide_tax_lines`), exchange-difference moves are excluded, and selecting a single company produces a warning because the report needs a counterpart.

### Tax Returns

Each company files its own tax return independently. Unless you set up a **Tax Unit** (group VAT filing) which groups companies sharing one VAT return.

A `account.tax.unit` groups companies that file one VAT return: it carries the unit's `country_id`, `vat`, `company_ids` and a `main_company_id` (the one actually reporting and paying). Creating one also creates an `account.report.horizontal.group` so the tax report can show the member companies side by side.

**Source:** [`account.tax.unit` — enterprise/account_reports/models/account_tax.py:8](../enterprise/account_reports/models/account_tax.py#L8)

### Pros and Cons

**Pros:**

| Advantage | Example |
|---|---|
| True legal separation | Batumi Trading LLC has its own VAT (GE987654321). If Batumi gets sued, Atlas Group's assets are protected. |
| Different currencies | Atlas operates in GEL, Batumi invoices in USD. Each has own functional currency. |
| Independent fiscal years | Atlas closes December 31. Acquired German subsidiary closes March 31. No forced alignment. |
| Independent lock dates | Atlas locked Q1 but Batumi still needs to fix a March entry. Batumi unlocks its own without affecting Atlas. |
| Independent audits | Each LLC hands its auditor a clean, standalone set of financials. |
| Different CoA structures | Atlas uses Georgian CoA, German subsidiary uses SKR04. They coexist. |
| Data isolation | Batumi's accountant cannot see or post to Atlas's accounts. |

**Cons:**

| Disadvantage | Example |
|---|---|
| Complex setup (CoA x N) | Adding a 4th entity: install CoA, configure 15+ journals, set up tax rates, create fiscal positions. Hours, not minutes. |
| Inter-company invoicing overhead | Atlas charges Batumi 5,000/month consulting. That's 12 invoices + 12 bills per year for one recurring charge. |
| Nx maintenance | Tax rate 18% -> 20%? Update in each company separately. Forget one = incorrect calculations. |
| Consolidation is extra work | "What's our total revenue?" requires selecting all companies, toggling consolidation. Still doesn't eliminate intercompany. |
| Users switch companies constantly | CFO reviewing 3 entities must switch active company repeatedly. Wrong company = posting in wrong entity. |
| Intercompany balances must reconcile at month-end | Atlas's "IC A/R from Batumi" must match Batumi's "IC A/P to Atlas" exactly. |

**Best for:** Multiple legal entities, different countries/currencies, holding+subsidiary structures, franchises, joint ventures.

**Not for:** All locations part of one legal entity (use branches), 10+ entities with limited staff, very frequent inter-entity transactions.

---

## Approach C: Analytic Accounts (Simplest, No Company Overhead)

### What Are Analytic Accounts?

Analytic accounts are tags on journal entry lines. They add reporting dimensions (location, department, project) without creating any company or branch structure. The accounting structure stays completely flat -- one company, one CoA, one set of journals.

**When Luka tags an invoice line with "Batumi Office" analytic, nothing changes about the journal entry itself. The analytic tag is just metadata for filtering reports later.**

### How It Works Technically

**Analytic Plans** define the dimensions you want to track. **Analytic Accounts** are the values within each plan.

```
Atlas Group LLC (single company, no branches)
  Analytic Plan: "Location"           <-- the dimension
    - Tbilisi HQ                      <-- an analytic account
    - Batumi Office                   <-- an analytic account
    - Kutaisi Warehouse               <-- an analytic account
  Analytic Plan: "Department"         <-- second dimension (optional)
    - Sales
    - Operations
    - Admin
```

**Key models:**

| Model | What it is | Company-scoped? | Source |
|---|---|---|---|
| `account.analytic.plan` | A reporting dimension (Location, Department, Project) | Applicability rules are company-dependent | [`analytic_plan.py:14`](../addons/analytic/models/analytic_plan.py#L14) |
| `account.analytic.account` | A value within a plan (e.g., "Batumi Office") | Optional -- `company_id` defaults to the active company but is **not required**; leave it empty to share the account across companies | [`analytic_account.py:61`](../addons/analytic/models/analytic_account.py#L61) |
| `analytic_distribution` | JSON field on `account.move.line` storing the distribution | Stored as JSON dict | [`account_move_line.py:502`](../addons/account/models/account_move_line.py#L502) |

A company-less analytic account is usable from every company, which is what makes "same Department/Project plans across all three entities" practical in a multi-company setup.

**How distribution is stored:** The `analytic_distribution` field is a JSON dictionary. Keys are analytic account IDs (comma-separated if combined), values are percentages:

```python
# Example: 100% to Batumi Office (ID=5)
{"5": 100.0}

# Example: 60% Batumi, 40% Kutaisi
{"5": 60.0, "7": 40.0}

# Example: multi-plan -- Batumi Office + Sales Department
{"5,12": 100.0}  # 5 = Batumi (Location plan), 12 = Sales (Department plan)
```

**Example journal entry -- Batumi sale for 5,000:**
```
DR  110000  Accounts Receivable    5,000   [analytic_distribution: {"5": 100}]
    CR  400000  Sales Revenue              5,000   [analytic_distribution: {"5": 100}]
```

### Multiple Plans Simultaneously

You can have multiple analytic plans active at once. Each plan creates its own column on journal entry lines.

**Example:** Atlas Group wants to track by Location AND Department AND Project:

| Invoice Line | Amount | Location | Department | Project |
|---|---|---|---|---|
| Consulting for Client X | 5,000 | Batumi | Sales | Project Alpha |
| Warehouse supplies | 2,000 | Kutaisi | Operations | -- |
| Office rent | 3,000 | Tbilisi | Admin | -- |

This gives you multi-dimensional analysis: "Show me all Sales department costs in Batumi for Project Alpha" -- a single report filter.

**Source:** Plans support hierarchy via `parent_id` and `_parent_store = True`. [`analytic_plan.py:14`](../addons/analytic/models/analytic_plan.py#L14), [`parent_id — analytic_plan.py:27`](../addons/analytic/models/analytic_plan.py#L27)

### Can You Force Users to Tag Entries? (Mandatory Analytics)

**YES.** Each plan has an `default_applicability` field with three options:

| Value | Meaning |
|---|---|
| `optional` | Users can skip the analytic tag |
| `mandatory` | Users MUST tag 100% of the amount. Posting fails otherwise. |
| `unavailable` | Plan doesn't appear on this document type |

**Source:** [`default_applicability — analytic_plan.py:75`](../addons/analytic/models/analytic_plan.py#L75) -- `company_dependent=True`, so each company (and therefore each branch) can set its own value

Enforcement happens in `_validate_analytic_distribution()` on `account.move.line`. If a mandatory plan doesn't have 100% distribution, Odoo raises a `RedirectWarning` and blocks posting.

**Source:** [`_validate_analytic_distribution() — account_move_line.py:3513`](../addons/account/models/account_move_line.py#L3513)

**You can also set per-document-type rules** via `account.analytic.applicability` records. Example: Location is mandatory on customer invoices but optional on journal entries.

### What the P&L Looks Like

Same numbers as branches, but breakdown comes from analytic filter, not company filter:

**Analytic P&L -- by Location (January 2026)**

| Account | Tbilisi HQ | Batumi Office | Kutaisi WH | **Unallocated** | **Total** |
|---|---|---|---|---|---|
| 400000 Revenue | 80,000 | 50,000 | 20,000 | 0 | **150,000** |
| 500000 COGS | (30,000) | (20,000) | (15,000) | 0 | **(65,000)** |
| 600000 Salaries | (25,000) | (12,000) | (8,000) | 0 | **(45,000)** |
| 620000 Rent | (5,000) | (3,000) | (4,000) | 0 | **(12,000)** |
| **Net Income** | **20,000** | **15,000** | **(7,000)** | **0** | **28,000** |

**Critical gotcha:** If someone forgets the analytic tag, it falls into "Unallocated." With branches, every entry is automatically assigned to the user's branch. Set `default_applicability = 'mandatory'` to prevent this.

**Balance Sheet CANNOT split by location.** Analytic filtering only works on P&L (income/expense accounts). A/R, A/P, bank balances are always company-wide. You cannot produce a "Batumi Balance Sheet" with analytics.

### Pros and Cons

**Pros:**

| Advantage | Example |
|---|---|
| Simplest setup | Adding "Rustavi Office" = create one analytic account. 30 seconds. |
| One CoA, one set of journals | Accountant manages one chart, one tax config. Zero duplication. |
| Multi-dimensional analysis | Track by location AND department AND project simultaneously. "Batumi + Sales + Project Alpha" in one filter. |
| No company switching | Users never change active company. No "oops, wrong company." |
| Easy to add/remove | Close Kutaisi? Stop using that analytic account. No company to deactivate. |

**Cons:**

| Disadvantage | Example |
|---|---|
| Human error risk (forgetting tags) | 50 invoices without analytic = 50 entries in "Unallocated." Mitigate with `mandatory` applicability. |
| No access control per location | Kutaisi bookkeeper can see and edit Tbilisi entries. No restriction possible. |
| No separate invoice sequences | All invoices share one sequence: INV/2026/0001, 0002... No BAT/2026/0001. |
| No separate bank accounts per location | All banks belong to the single company. |
| No per-location lock dates | Lock January for everyone or no one. |
| Balance Sheet doesn't split | A/R, bank, equity are company-wide. Only P&L splits by analytic. |
| No legal standing | "Batumi Office" as analytic has no VAT, no legal identity. |

**Best for:** Department-level P&L, project costing (consulting firms, construction), small company with 2-3 locations sharing everything, temporary tracking (events, pop-ups).

**Not for:** Locations needing own bank accounts, invoice numbering, access control, Balance Sheet split, or any legal/regulatory independence.

---

## Side-by-Side: All 3 Approaches

### Setup Complexity

| Task | Analytic Only | Branches | Multi-Company |
|---|---|---|---|
| Create locations | Create analytic accounts | Create branch companies | Create full companies |
| CoA setup | 1 CoA | 1 CoA (shared) | 1 CoA per company |
| Journal setup | 1 set | 1 set per branch (auto) | 1 set per company (manual) |
| Tax setup | 1 set | 1 set (shared) | 1 set per company |
| Bank accounts | Shared | 1 per branch (required) | 1 per company |
| Access rights | Standard | Branch-aware | Company-aware |
| **Total effort** | **Minutes** | **Hours** | **Days** |

### Report Behavior

| Report | Analytic Only | Branches | Multi-Company |
|---|---|---|---|
| P&L per location | Analytic filter | Company filter | Switch company |
| P&L combined | Default view | Select all branches | Consolidation toggle |
| Balance Sheet per location | **Not possible** | Filter by branch | Switch company |
| Balance Sheet combined | Default view | Select all branches | Consolidation toggle |
| Tax return | 1 combined | 1 combined | 1 per company |
| Intercompany elimination | N/A | N/A | Manual entries needed |

### Scenario Decision Table

| Scenario | Recommended | Why |
|---|---|---|
| 3 stores, same country, same VAT | **Branches** | Shared CoA simplifies, per-store bank accounts |
| HQ + factory, same legal entity | **Branches** | Different journals per branch handle workflow separation |
| Parent + 2 subsidiaries, different VATs | **Multi-Company** | Legal separation required |
| Holding + subsidiaries, different countries | **Multi-Company** | Different currencies, fiscal years, tax rules |
| Single company, department cost tracking | **Analytic Only** | No company/branch overhead |
| Franchise (legally independent stores) | **Multi-Company** | Each franchise is its own legal entity |
| Department P&L, no balance sheet split | **Analytic Only** | Simplest possible |
| Regional offices with own bank accounts | **Branches** | Need separate bank accounts but shared CoA |
| All 3: legal entities with internal divisions + project tracking | **Multi-Company + Branches + Analytics (hybrid)** | Companies for legal, branches for offices, analytics for projects |

---

## Case Studies: Atlas Group Decisions

### Case 1: All Locations Are Departments (Same Legal Entity)

**Decision: Branches**

- One VAT: GE123456789
- One bank relationship (separate accounts per branch)
- One tax return
- Per-location P&L needed
- Year-end: one set of closing entries

Setup time: ~1 hour. Ongoing maintenance: minimal.

### Case 2: Batumi Is a Separate LLC, Kutaisi Is a Department

**Decision: Hybrid -- Multi-Company for Batumi + Branch for Kutaisi**

```
Atlas Group LLC (root)           <-- own CoA, VAT: GE123456789
  |-- Kutaisi Warehouse (branch) <-- shares Atlas CoA
Batumi Trading LLC               <-- own CoA, VAT: GE987654321
```

- Atlas + Kutaisi file one tax return
- Batumi files its own
- Intercompany rules handle Atlas <-> Batumi invoicing
- Kutaisi entries auto-roll into Atlas reports

### Case 3: All Three Are Separate LLCs + Project Tracking

**Decision: Multi-Company + Analytics**

```
Atlas Holding (parent, no operations)
  |-- Atlas Group LLC         <-- Analytic plans: Department, Project
  |-- Batumi Trading LLC      <-- Same analytic plans
  |-- Kutaisi Logistics LLC   <-- Same analytic plans
```

Each company is independent for accounting. Inside each company, analytic accounts track departments and projects. The CFO uses the consolidation toggle for group-wide views.

---

## Part 2: Cross-Module Impact

> How branches and multi-company affect Sales, Purchase, Inventory, Expenses, Payroll, and Analytic Reporting.

---

## Security Model: How Company Filtering Works

### Odoo 20 replaced `ir.model.access` and `ir.rule` with `ir.access`

This is a framework-level change, and every security file in every module moved. There is no `ir.model.access.csv` and no `ir.rule` model left in Odoo 20 — both are now rows in **`security/ir.access.csv`** backed by the `ir.access` model.

| | Odoo 19 | Odoo 20 |
|---|---|---|
| Group permissions | `ir.model.access` rows in `ir.model.access.csv` (`perm_read/write/create/unlink`) | `ir.access` rows with `group_id` set and an `operation` string |
| Record rules | `ir.rule` records in XML (`domain_force`, `groups`, `global`) | the same `ir.access` rows, with a `domain` column |
| Operation flags | four booleans | one `operation` string: any subset of `c`, `r`, `u`, `d` (e.g. `crud`, `cru`, `r`) |
| Global vs group rule | `ir.rule` with no groups = global | `ir.access` row with **no** `group_id` = a *restriction* |

```csv
id,name,model_id,group_id/id,operation,domain
access_account_cash_rounding_uinvoice,account.cash.rounding,account.cash.rounding,account.group_account_invoice,crud,
account_cash_rounding_comp_rule,Account cash rounding multi-company,account.cash.rounding,,crud,"['|', ('company_id', '=', False), ('company_id', 'parent_of', company_ids)]"
```

The first row is a permission (it has a group). The second has no group, so it is a restriction applying to everyone.

**How they combine:**

- **Permissions** (rows with a `group_id`) are **OR-ed**. A user needs at least one permission granting the operation, and the record must satisfy at least one of the matching permissions' domains.
- **Restrictions** (rows without a `group_id`) are **AND-ed**. Every restriction on the model must be satisfied. Multi-company rules are restrictions.

Source: [`ir.access` — ir_access.py:64](../odoo/addons/base/models/ir_access.py#L64), `kind` computed at [ir_access.py:129](../odoo/addons/base/models/ir_access.py#L129)

**Practical consequence for this document:** everything below about `in` vs `parent_of` still holds exactly as it did in 19 — the *domains* did not change. What changed is where you read and write them. To inspect a multi-company rule now, open `security/ir.access.csv` in the module (or Settings → Technical → Access) instead of hunting for an `ir.rule` in an XML file.

### The three company-domain patterns

| Pattern | Meaning | Used For |
|---|---|---|
| `('company_id', 'in', company_ids)` | User sees records ONLY in their assigned companies | Transactional data (SO, PO, invoices, pickings, payslips) |
| `('company_id', 'parent_of', company_ids)` | User sees records from their company AND all ancestors | Config data (journals, taxes, fiscal positions, payment terms) |
| `('company_ids', 'parent_of', company_ids)` | Same, for models linked to several companies | `account.account` |
| `('company_id', 'in', company_ids + [False])` or `'|' ('company_id','=',False)` | User sees company-scoped OR shared records | Master data (locations, routes, products, cash rounding) |

**Source:** [`addons/account/security/ir.access.csv`](../addons/account/security/ir.access.csv) — e.g. `journal_comp_rule` (line 49), `account_comp_rule` (line 58), `tax_comp_rule` (line 61)

**`company_ids`** is a context variable (not a field) automatically populated with the user's allowed companies. When the user switches companies in the top-right selector, `company_ids` changes and all record visibility re-evaluates instantly.

### Who Can See What?

| Scenario | Can See? | Why |
|---|---|---|
| Branch user sees parent's config (journals, taxes, CoA) | **YES** | `parent_of` restriction on config records |
| Branch user sees parent's transactions (invoices, SOs) | **NO** | `in` restriction -- parent not in branch user's `company_ids` by default |
| Branch user sees sibling branch's records | **NO** | Siblings don't have `parent_of` or `in` relationship |
| Parent user sees branch records | Only if assigned | User must have the branch in their `company_ids` |

**Source:** [`_accessible_branches() — res_company.py:502`](../odoo/addons/base/models/res_company.py#L502)

### User Company Assignment

Each user has two fields:
- `company_id` -- current active company ("working as")
- `company_ids` -- all companies they're allowed to access

`self.env.company` returns the active `company_id`. The company switcher changes which companies are active. All `ir.rule` filters re-evaluate instantly.

---

## Sales Module

### Company Scoping

| Aspect | Behavior | Source |
|---|---|---|
| SO `company_id` default | `self.env.company` (user's active company) | [`sale_order.py:73`](../addons/sale/models/sale_order.py#L73) |
| Changeable? | Yes in draft, locked after confirmation | Same |
| Warehouse must match company | Enforced by `_check_company_auto` on the warehouse | [`sale_stock/models/sale_order.py`](../addons/sale_stock/models/sale_order.py) |

**Branch behavior:** When Luka (Batumi salesman) creates an SO:
1. SO gets `company_id = Batumi Office`
2. Warehouse auto-selects Batumi WH
3. Invoice from SO inherits `company_id = Batumi Office`
4. Delivery picking inherits company from warehouse's picking type

**Who sees Luka's SO:**
- Batumi users: YES
- Tbilisi HQ users: Only if Batumi is in their `company_ids`
- Kutaisi users: NO (sibling branch)

### Inter-Company SO/PO Flow

When SO in Company A is confirmed for a partner that IS Company B:

```
1. SO confirmed in Company A (customer = Company B's partner)
2. If Company B has intercompany_generate_purchase_orders = True:
   -> Auto-creates PO in Company B (vendor = Company A's partner)
   -> auto_generated = True prevents infinite loop
```

**Source:** [`_action_confirm() — enterprise/sale_purchase_inter_company_rules/models/sale_order.py:50`](../enterprise/sale_purchase_inter_company_rules/models/sale_order.py#L50)

Reverse works too: PO in Company B can auto-create SO in Company A (`intercompany_generate_sales_orders`).

Odoo 20 also keeps the two orders in sync after confirmation: adding a line to the source order propagates it to the mirror order, and cancelling one posts a message on the other. The sync can be suppressed with the `skip_intercompany_sync` context key.

### Practical Issues

| Issue | Branches | Multi-Company |
|---|---|---|
| Salesman in A sells to customer in B's territory | Works fine -- customer is shared | Works fine -- separate SO in A |
| Shared pricelist | Works -- pricelists can be company-agnostic | Each company needs own pricelist |
| SO needs stock from different location | Internal transfer (simple) | Inter-company PO/SO chain (complex) |

---

## Purchase Module

### Company Scoping

| Aspect | Behavior | Source |
|---|---|---|
| PO `company_id` default | `self.env.company` | [`purchase_order.py:177`](../addons/purchase/models/purchase_order.py#L177) |
| Vendor bill from PO | Bill created with `company_id = PO.company_id` | [`purchase_order.py`](../addons/purchase/models/purchase_order.py) — `action_create_invoice()` |

### Practical Issues

| Issue | Branches | Multi-Company |
|---|---|---|
| Central purchasing for all locations | PO in HQ, goods to branch warehouse | PO in Company A, inter-company transfer to B |
| Vendors shared? | Yes -- vendors not company-scoped | Yes -- same partner across companies |
| Different payment terms per location | Not possible -- inherited from parent | Each company has its own |

---

## Inventory / Stock Module

### Company Scoping -- Strictest Module

Inventory is the most strictly company-scoped module. Key rules:

| Model | Shared Allowed? | Source |
|---|---|---|
| `stock.warehouse` | NO -- one per company, required | [`stock_warehouse.py:37`](../addons/stock/models/stock_warehouse.py#L37) |
| `stock.picking` | NO -- company related from picking type | [`stock_picking.py:114`](../addons/stock/models/stock_picking.py#L114) |
| `stock.move` | NO | [`addons/stock/security/ir.access.csv`](../addons/stock/security/ir.access.csv) |
| `stock.quant` | Via location (company-scoped) | [`addons/stock/models/stock_quant.py`](../addons/stock/models/stock_quant.py) |
| `stock.location` | YES (`company_id` can be NULL) | [`addons/stock/models/stock_location.py`](../addons/stock/models/stock_location.py) |

**Warehouse:** Each branch MUST have its own warehouse. Cannot share. Name and code must be unique per company.

**Quant company:** `company_id` is a related field from `location_id.company_id`. One company cannot see another's inventory.

**Picking company chain:** `Warehouse -> Picking Type -> Picking` -- unbreakable.

### Atlas Group with Branches -- Inventory

```
Atlas Group (root)
  |-- Warehouse: "Tbilisi Central" (company: Atlas Group)
  |-- Batumi Office (branch)
       |-- Warehouse: "Batumi WH" (company: Batumi Office)
  |-- Kutaisi Warehouse (branch)
       |-- Warehouse: "Kutaisi WH" (company: Kutaisi Warehouse)
```

- Internal transfer Kutaisi -> Batumi = simple internal transfer (same root company)
- Total inventory view: user with access to all branches sees all warehouses
- Each branch has own picking types and sequences

### Practical Issues

| Issue | Branches | Multi-Company |
|---|---|---|
| Transfer between locations | Internal transfer (simple) | Inter-company transfer (requires Enterprise module + PO/SO chain) |
| Central inventory visibility | Select all branches in filter | Must switch between companies |
| SO in branch A, stock in branch B | Create internal transfer B -> A first | Requires inter-company PO from A to B |

### Inter-Company Stock Transfers (Multi-Company Only)

Requires `sale_purchase_stock_inter_company_rules` (Enterprise).

**Simplified in Odoo 20.** The per-company `intercompany_warehouse_id` and `intercompany_receipt_type_id` fields are gone. One boolean remains:

| Field | Purpose | Source |
|---|---|---|
| `intercompany_sync_delivery_receipt` | On by default. When a Sale or Purchase Order is confirmed with another company, links the delivery to the matching receipt in the other company | [`res_company.py:8`](../enterprise/sale_purchase_stock_inter_company_rules/models/res_company.py#L8) |

The warehouse is now resolved from the mirror order's own company rather than from a dedicated setting, so there is no longer a "forgot to set `intercompany_warehouse_id`" failure mode.

---

## HR Expenses

### Company Scoping

| Aspect | Behavior | Source |
|---|---|---|
| `company_id` default | `self.env.company` (user's active company at creation) | [`hr_expense.py:89`](../addons/hr_expense/models/hr_expense.py#L89) |
| `company_id` readonly | YES -- locked after creation | Same field, `readonly=True` |
| Record visibility | `[('company_id', 'in', company_ids)]` | [`hr_expense_comp_rule — ir.access.csv:18`](../addons/hr_expense/security/ir.access.csv#L18) |

### How Expense Approval Works Across Branches

Approval rules check employee relationships (department manager, expense manager, subordinates) but do NOT explicitly filter by company. The global `company_ids` rule acts as the backstop.

**This means:** A manager in Tbilisi CAN approve expenses from Batumi employees IF:
1. The manager has Batumi in their `company_ids` AND
2. The employee relationship allows it (department manager, expense manager)

**Source:** [`addons/hr_expense/security/ir.access.csv`](../addons/hr_expense/security/ir.access.csv) -- the multi-company restriction `hr_expense_comp_rule` is the backstop; the approval logic itself lives in `hr_expense.py`.

### Expense to Journal Entry Flow

1. Expenses grouped by `company_id`
2. Journal selected from `company.expense_journal_id` (constrained to type `purchase`) or the first purchase journal in that company
3. Journal entry created in the expense's company
4. Analytic distribution from expense line carries through to the journal entry

**Source:** [`expense_journal_id — hr_expense/models/res_company.py:10`](../addons/hr_expense/models/res_company.py#L10), [`hr_expense.py`](../addons/hr_expense/models/hr_expense.py) -- `action_post()` / move-creation helpers

**Key:** Journal entry always goes to the expense's company (set at creation, readonly). Employee traveling to another branch still gets the expense in their home branch.

### Practical Example

**Scenario:** Luka (Batumi) travels to Tbilisi for a meeting, spends 500 GEL on hotel.

| Approach | What Happens |
|---|---|
| **Branches** | Luka's active company = Batumi at expense creation time. Expense `company_id = Batumi Office`. Journal entry posts to Batumi's expense journal. Batumi P&L shows the 500 cost. Nino (CFO) with all-branch access can approve. |
| **Multi-Company** | Same -- expense in Batumi Trading LLC. Journal entry in Batumi. But Nino must have Batumi Trading in her `company_ids` to see and approve it. |
| **Analytic** | Expense in the single company. Luka tags it "Batumi Office" analytic. No company switching needed. Any manager can approve (no company barrier). |

### Practical Issues

| Issue | Branches | Multi-Company | Analytic |
|---|---|---|---|
| Employee travels to another location | Expense stays in employee's branch | Expense stays in employee's company | Tag with destination analytic |
| Cross-location approval | Works if manager has access to employee's branch | Works if manager has access to employee's company | No barrier -- single company |
| Expense report for all locations | Manager with all-branch access sees all | Must switch between companies | Single report, filter by analytic |
| Employee transfers to new branch | New expenses in new branch; old stay in old | Same | Just change analytic tag |

---

## HR Payroll

### Company Scoping -- Strictly Per Company

| Aspect | Behavior | Source |
|---|---|---|
| Payslip `company_id` | **Computed from `employee_id.company_id`** -- not user's active company | [`hr_payslip.py:98`](../enterprise/hr_payroll/models/hr_payslip.py#L98) |
| Payslip Run `company_id` | `self.env.company` (one run per company/branch) | [`hr_payslip_run.py:59`](../enterprise/hr_payroll/models/hr_payslip_run.py#L59) |
| Employee belongs to one company | YES -- `company_id` is `required` on `hr.employee` | [`hr_employee.py:147`](../addons/hr/models/hr_employee.py#L147) |

### Salary Structures: Shared by Country, Not Company

Structures are scoped by **country**, not company. All companies in the same country share structures.

**Source:** [`country_id — hr_payroll_structure.py:48`](../enterprise/hr_payroll/models/hr_payroll_structure.py#L48) -- the domain restricts the choice to countries of `self.env.companies`.

**This means:** Whether you use branches or multi-company, if all entities are in Georgia, they share the same salary structures. The difference is only in how payslip runs and journal entries are organized.

### Contracts: Tied to Employee's Company

Version (contract) `company_id` is computed from the employee and stored.

**Source:** [`company_id — hr_version.py:66`](../addons/hr/models/hr_version.py#L66)

### Practical Example

**Atlas Group with Branches -- Payroll January 2026:**

```
Branch: Tbilisi HQ      -> 15 employees -> Payslip Run "January 2026 - Tbilisi"
Branch: Batumi Office    ->  8 employees -> Payslip Run "January 2026 - Batumi"
Branch: Kutaisi WH       ->  5 employees -> Payslip Run "January 2026 - Kutaisi"
```

- **3 separate payslip runs** -- one per branch, even though they share CoA
- All salary structures shared (same country = Georgia)
- Journal entries post to each branch's journals (Batumi payslip -> Batumi salary journal)
- HR manager with all-branch access can view all payslips
- **Cannot combine into one payslip run.** This is a hard limitation.

### Payroll with Multi-Company

Exactly the same behavior -- one payslip run per company. The only difference: structures would also be shared if companies are in the same country. If companies are in different countries, each uses its country's structures.

### Practical Issues

| Issue | Branches | Multi-Company | Analytic |
|---|---|---|---|
| Run payroll for all locations at once | NO -- one run per branch | NO -- one run per company | YES -- single company, one run for all |
| Employee in two locations | One company only -- must choose primary | Same | Single company -- use analytic tags |
| Different pay scales per location | Salary rules with branch-specific conditions | Each company can have different rule parameters | Not supported by analytics alone |
| Payroll journal entries | Each branch's salary journal | Each company's salary journal | Single salary journal |
| Payroll report across all locations | Multi-branch access sees all | Must switch companies | Single report |

---

## Analytic Accounting: How It Works With Branches and Multi-Company

### Analytics Are Orthogonal to Company Structure

Analytic accounts work the SAME way regardless of whether you use branches, multi-company, or no branches at all. They add reporting dimensions on top of whatever company structure you choose.

**Example combinations:**
- Branches + Analytics: Track by branch (company filter) AND by department (analytic filter)
- Multi-Company + Analytics: Track by legal entity (company) AND by project (analytic)
- Just Analytics: Track everything by analytic plans only

### What Reports Can Filter By Analytic

The switch is the `filter_analytic_groupby` boolean on `account.report`. **This is a rename: Odoo 19 called it `filter_analytic` and declared it in `account`; Odoo 20 calls it `filter_analytic_groupby` and declares it in `account_reports`.** Any custom report setting `filter_analytic` must be updated.

| Report | Analytic Filter Available? |
|---|---|
| P&L | YES -- via analytic groupby/filter |
| Balance Sheet | Partial -- only meaningful for P&L-type accounts |
| General Ledger | YES |
| Trial Balance | YES |

**How report filtering works:** `_init_options_analytic_groupby` (forced to sequence 995, i.e. after column headers and before columns) adds the analytic account and analytic plan groupby options. The report then filters on `account.move.line.analytic_distribution`; with groupby enabled it builds a shadowing query that projects `account.analytic.line` data into the move-line schema.

**Source:** [`filter_analytic_groupby — account_analytic_report.py:14`](../enterprise/account_reports/models/account_analytic_report.py#L14), [`_init_options_analytic_groupby() — account_analytic_report.py:26`](../enterprise/account_reports/models/account_analytic_report.py#L26)

### Analytics + Branches: Best of Both Worlds

Use branches for operational isolation (bank accounts, invoice sequences, access control) and analytics for additional dimensions:

```
Atlas Group (root)
  |-- Batumi Office (branch)      <-- company-level isolation
  |-- Kutaisi Warehouse (branch)  <-- company-level isolation

Analytic Plans (cross-cutting):
  Department: Sales, Operations, Admin, Finance
  Project: Project Alpha, Project Beta, Client X
```

This gives you:
- P&L by branch (company filter)
- P&L by department (analytic filter)
- P&L by branch + department (both filters)
- Separate bank accounts per branch
- Separate invoice sequences per branch
- Access control per branch
- Multi-dimensional project cost tracking via analytics

---

## Cross-Module Summary: How Company Is Determined

| Module | `company_id` Source | Readonly? | Source |
|---|---|---|---|
| Sale Order | `self.env.company` (user's active company) | No (draft) | [`sale_order.py:73`](../addons/sale/models/sale_order.py#L73) |
| Purchase Order | `self.env.company` | No (draft) | [`purchase_order.py:177`](../addons/purchase/models/purchase_order.py#L177) |
| Invoice | Computed from `journal_id.company_id`, preferring the active company when the journal belongs to an ancestor | No (editable but recomputed) | [`account_move.py:932`](../addons/account/models/account_move.py#L932) |
| Stock Picking | Related from `picking_type_id.company_id`, stored | YES | [`stock_picking.py:114`](../addons/stock/models/stock_picking.py#L114) |
| Expense | `self.env.company` | YES | [`hr_expense.py:89`](../addons/hr_expense/models/hr_expense.py#L89) |
| Payslip | Computed from `employee_id.company_id` | YES | [`hr_payslip.py:98`](../enterprise/hr_payroll/models/hr_payslip.py#L98) |

### What Branches Share vs Isolate

| Resource | Branches | Multi-Company |
|---|---|---|
| Chart of Accounts | **SHARED** (one CoA, `company_ids` Many2many) | **SEPARATE** per company |
| Journals | **SHARED access** (`parent_of`), but each branch has own set | **SEPARATE** per company |
| Tax rates | **SHARED** (`parent_of`) | **SEPARATE** per company |
| Fiscal positions | **SHARED** (`parent_of`) | **SEPARATE** per company |
| Products | **SHARED** (`company_id` can be False) | **SHARED** (`company_id` can be False) |
| Customers/Partners | **SHARED** (not company-scoped) | **SHARED** (not company-scoped) |
| Employees | **ISOLATED** per branch | **ISOLATED** per company |
| Warehouses | **ISOLATED** per branch | **ISOLATED** per company |
| Inventory (quants) | **ISOLATED** per branch warehouse | **ISOLATED** per company |
| Sale/Purchase Orders | **ISOLATED** per branch | **ISOLATED** per company |
| Invoices | **ISOLATED** per branch | **ISOLATED** per company |
| Expenses | **ISOLATED** per branch | **ISOLATED** per company |
| Payslips | **ISOLATED** per branch | **ISOLATED** per company |
| Salary Structures | **SHARED** (by country) | **SHARED** (by country) |
| Lock Dates | Inherited from root (max of ancestors) | **INDEPENDENT** per company |
| Fiscal Year | **SHARED** from root (delegated) | **INDEPENDENT** per company |

---

## Common Pitfalls & How to Fix Them

### 1. "User Posted in Wrong Company"

**Symptom:** User forgets to switch active company before creating records.

| Approach | Risk | Mitigation |
|---|---|---|
| Branches | MEDIUM -- user sees all branches in switcher | Train users to check active company. `_check_company_auto` catches mismatches. |
| Multi-Company | HIGH -- completely wrong legal entity | Same training. Consider per-user default company. |
| Analytic | LOW -- single company | No company switching needed. |

### 2. "Manager Can't Approve Employee's Expense"

**Root cause:** Manager does not have the employee's branch in their `company_ids`.

**Fix:** Add the employee's branch to the manager's allowed companies. Expense approval checks employee relationships but the global `company_ids` filter blocks access first.

### 3. "Payroll Run Doesn't Include All Employees"

**Root cause:** Payslip runs are per-company. Each branch needs its own run.

**Fix:** Create separate payslip runs per branch. Cannot combine. This is by design.

### 4. "SO Confirmed but No Delivery Created"

**Root cause:** Warehouse doesn't match SO's company, or warehouse not configured for that branch.

**Fix:** Each branch needs a warehouse. SO auto-picks warehouse matching `company_id`.

### 5. "Inter-Company Transfer Creates Nothing"

**Root cause (Odoo 20):** Missing module or configuration:
- `sale_purchase_stock_inter_company_rules` not installed
- `intercompany_generate_purchase_orders` (or `intercompany_generate_sales_orders`) not enabled on the target company
- `intercompany_sync_delivery_receipt` turned off
- The customer/vendor partner is not linked to a company — `_find_company_from_partner()` found nothing

`intercompany_user_id` and `intercompany_warehouse_id` no longer exist in Odoo 20; if a checklist still mentions them, it is a 19-era checklist.

### 6. "Branch User Sees Parent's Journals but Not Parent's Invoices"

**This is by design.** Journals use `parent_of` (config = shared). Invoices use `in company_ids` (transactions = isolated). Branch user can POST to a parent journal (creating an entry in the branch) but CANNOT READ the parent's existing entries unless parent is in their `company_ids`.

### 7. "Employee Transferred Between Branches -- Old Records Invisible"

**Root cause:** Employee gets new `company_id`. Old records stay in old branch. New branch users can't see old branch data.

**Fix:** User needs both companies in `company_ids` to see full history. Or: HR manager with all-company access views complete records.

---

## Permissions Matrix: Atlas Group Example

### Users and Access

| User | Role | `company_ids` | Active Company |
|---|---|---|---|
| Nino (CFO) | Finance Manager | Atlas + Batumi + Kutaisi | Atlas Group |
| Giorgi | Batumi Sales Manager | Atlas + Batumi | Batumi Office |
| Tamta | Kutaisi Warehouse Mgr | Atlas + Kutaisi | Kutaisi WH |
| Luka | Batumi Salesman | Batumi only | Batumi Office |
| Ana | Kutaisi Stock Clerk | Kutaisi only | Kutaisi WH |

### What Each User Sees (Branches Setup)

| Record | Nino (CFO) | Giorgi (Batumi Mgr) | Luka (Batumi Sales) | Ana (Kutaisi Stock) |
|---|---|---|---|---|
| Tbilisi SOs | YES | YES (Atlas in companies) | NO | NO |
| Batumi SOs | YES | YES | YES (own) | NO |
| Kutaisi SOs | YES | NO | NO | NO |
| Batumi inventory | YES | YES | NO | NO |
| Kutaisi inventory | YES | NO | NO | YES |
| Journals/CoA/Taxes (config) | ALL | ALL (parent_of) | ALL (parent_of) | ALL (parent_of) |

**Key observations:**
1. Config (journals, accounts, taxes) is ALWAYS visible via `parent_of` -- every branch user sees the root's config
2. Transactions (SOs, invoices, pickings) are ISOLATED via `in company_ids` -- only visible if user has that company
3. Luka with ONLY Batumi is fully isolated from Kutaisi and HQ transactions
4. Nino with ALL 3 companies sees everything

---

## End-to-End Flow: Sale to Payment

### Branch Flow (Batumi is a branch)

```
1. Luka creates SO in Batumi
   -> company_id = Batumi Office (auto from active company)
   -> warehouse = Batumi WH (auto from company)

2. SO confirmed
   -> Delivery created: company_id = Batumi (from picking type)
   -> Stock reserved in Batumi WH

3. Delivery validated
   -> Stock moves in Batumi company
   -> Quants updated in Batumi WH

4. Invoice created from SO
   -> company_id = Batumi (from SO)
   -> Journal: Batumi's sales journal
   -> Sequence: INV/2026/0001 (Batumi's own counter)

5. Payment received
   -> Batumi's bank journal
   -> Reconciled against Batumi AR

6. Reporting
   -> Nino opens P&L, selects all branches -> sees combined
   -> Filters Batumi only -> sees Batumi P&L
   -> Same CoA, same account codes, no consolidation needed
```

### Multi-Company Flow (Batumi Trading LLC is separate)

```
1. Luka creates SO in Batumi Trading LLC
   -> company_id = Batumi Trading LLC
   -> warehouse = Batumi WH

2. SO confirmed
   -> IF customer IS Atlas Group: auto-creates PO in Atlas Group (inter-company)
   -> Delivery in Batumi Trading

3. Delivery validated
   -> IF inter-company: syncs receipt in Atlas Group

4. Invoice created
   -> company_id = Batumi Trading LLC
   -> Separate CoA, separate journal, separate sequence
   -> IF customer IS Atlas Group: auto-creates vendor bill in Atlas Group

5. Payment received
   -> Batumi Trading's bank journal, Batumi's own AR

6. Reporting
   -> Nino must use consolidation toggle for combined view
   -> Inter-company transactions inflate totals without elimination
   -> Manual elimination entries needed for true consolidated view
```

---

## FAQ

**Q: Can I switch from branches to multi-company later?**
A: Technically possible but painful. You'd need to create new companies, migrate journal entries, reassign all documents. Plan this decision carefully upfront.

**Q: Can I switch from multi-company to branches?**
A: Even harder. Separate CoAs must be merged, intercompany balances reconciled and eliminated. Avoid this scenario.

**Q: Can branches have different currencies?**
A: No. `currency_id` is a root-delegated field. Branches must use the root company's currency. Need different currencies = use multi-company.

**Q: Can I mix branches AND multi-company AND analytics?**
A: Yes. Common pattern: separate legal entities as companies, branches inside each company for locations, analytics for projects/departments. All three work together.

**Q: Can I make analytic tagging mandatory to prevent "Unallocated" entries?**
A: Yes. Set `default_applicability = 'mandatory'` on the analytic plan. Odoo will block posting any entry that doesn't have 100% distribution for that plan.

**Q: Are payslip runs always per-company, even with branches?**
A: Yes. Each branch needs its own payslip run. This is a hard limitation. With analytics (no branches), you'd have one run for all employees.

**Q: How do lock dates work with branches?**
A: The effective lock date for a branch is the **maximum** across itself and all ancestor companies. Root sets lock date = all branches inherit. Branches CAN set their own (stricter) but cannot be less strict than the root.

**Q: What modules do I need?**

| Need | Module | License |
|---|---|---|
| Branches | `account` (built-in) | Community |
| Multi-company | `account` + company setup | Community |
| Inter-company invoicing | `account_inter_company_rules` | Enterprise |
| Inter-company SO/PO | `sale_purchase_inter_company_rules` | Enterprise |
| Inter-company stock transfers | `sale_purchase_stock_inter_company_rules` | Enterprise |
| Inter-company POS | `pos_sale_purchase_stock_inter_company_rules` | Enterprise |
| Report consolidation | `account_reports` | Enterprise |
| Interco balance comparison | `account_reports` (Interco Comparison report) | Enterprise |
| Tax units (group VAT) | `account_reports` (`account.tax.unit`) | Enterprise |
| Analytic accounting | `analytic` + `account` | Community |

---

## One-Line Summary

| Situation | Use |
|---|---|
| One legal entity, multiple locations | **Branches** |
| Multiple legal entities, same group | **Multi-Company + Inter-company Rules** |
| Just need cost center / project tracking | **Analytic Accounts** |
| Legal entities + internal divisions + project tracking | **Multi-Company + Branches + Analytics** |

---

## What Changed in Odoo 20

| Area | Odoo 19 | Odoo 20 | Why it matters here |
|---|---|---|---|
| Security files | `ir.model.access.csv` + `ir.rule` XML | unified `ir.access.csv` / `ir.access` model; a row with a group is a *permission*, a row without is a *restriction* | Every multi-company rule quoted in this doc now lives in `security/ir.access.csv`. The domains are unchanged |
| Invoice company resolution | `(journal.company_id or env.company)._accessible_branches()[:1]` | explicit: keep `env.company` when the journal belongs to an ancestor | Same outcome for branches, clearer to reason about |
| Chart of accounts | `account.group` prefix ranges | `account.account.parent_id` tree; `account.group` removed | The shared branch COA now carries its own hierarchy; report hierarchy follows it |
| Bank/cash accounts | journal created manually | creating the account auto-creates the journal in its first company | Adding a branch bank account is one step, not two |
| Company accounting defaults | product-category and partner properties | company fields backed by `ir.default` via `company_default_for` (`receivable_account_id`, `payable_account_id`, `income_account_id`, `expense_account_id`, `account_stock_valuation_id`, `cost_method`, …) | Each branch can carry its own default accounts without touching product data |
| Intercompany rules | `intercompany_user_id` per company | removed — mirror documents are created with `SUPERUSER_ID` | One less piece of configuration to get wrong |
| Intercompany reconciliation | manual / spreadsheet | **Interco Comparison** report | The elimination workstream finally has a report |
| Report analytic filter | `filter_analytic` | `filter_analytic_groupby` | Custom reports must be updated |
| Report currency conversion | `currency_table` JOIN | `consolidation_rate` / `consolidation_balance` on `account.move.line`, with CTA rules per account type | Consolidated multi-currency reports balance via an explicit CTA line |
| Multi-ledger | — | `account.journal.group` drives `res.company.has_ledger`; assets get per-ledger variants | Relevant if a group needs statutory and tax books side by side |

Everything else in this document — the branch vs multi-company decision, the `in` / `parent_of` domain patterns, the per-module company scoping, the pitfalls — behaves the same in 20 as in 19.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`accounting_reports.md`](accounting_reports.md) -- consolidation, the company filter, and the Interco Comparison report
- [`accounting_migration.md`](../dev_notes/reference/accounting_migration.md) -- opening balances and lock dates per company

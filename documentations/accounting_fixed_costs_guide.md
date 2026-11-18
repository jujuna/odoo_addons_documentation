# Accounting — Fixed Costs: Chart of Accounts, Journal Entries & Budgets

> **Who this is for:** Accountants, finance managers, and business owners using Odoo — not developers.
> **What you'll learn:** How to set up your chart of accounts correctly, when to use journal entries, how to handle fixed monthly costs, how to control them with budgets, how taxes work, how reconciliation works, and how year-end closing happens.
> **Modules covered:** `account` · `account_budget` · `account_asset` · `account_accountant`
> **Verified against Odoo 20 source (2026-09-22).**
>
> **Three things changed in Odoo 20 that affect this guide:**
> 1. **Account groups are gone.** The `account.group` model was deleted; accounts now form their own tree via `parent_id`. See [Account hierarchy](#account-hierarchy--parent-accounts-replaces-account-groups).
> 2. **Budget vocabulary changed.** "Budgeted" is now **Commitment**, and a new **Liquidation** amount sits between Commitment and Achieved. See [Part 10](#part-10--budgets-planning-and-tracking-fixed-costs).
> 3. **Fixed assets were restructured** around `account.asset.variant` and `account.depreciation.model`. The user-facing flow in Option D is unchanged, but the internals differ — see [`account_asset.md`](account_asset.md).

---

## The Big Picture

Every financial transaction in Odoo follows this path:

```
Something happens in the business
        ↓
Odoo records it as a Journal Entry
(two sides: money comes from somewhere, goes somewhere)
        ↓
Each side lands on an Account
(a named bucket that tracks one type of money)
        ↓
If there are taxes → additional lines created automatically
        ↓
If there's analytic distribution → analytic lines created for budget tracking
        ↓
Accounts roll up into financial reports (P&L, Balance Sheet)
        ↓
Budgets compare what you planned vs. what actually happened
```

The Chart of Accounts is the master list of all those buckets (accounts) your company uses.

---

## Part 1 — The Chart of Accounts: Your Financial Filing System

### What an account is

Think of the chart of accounts as a filing cabinet. Each drawer is an account. Every time money moves — you pay rent, receive a payment, buy equipment — it goes into one or more specific drawers.

Each account has:
- A **number** (code) — used for ordering and grouping. e.g., `6200`
- A **name** — e.g., "Office Rent"
- A **type** — tells Odoo how to treat this account in reports and at year-end

The type is the most important setting. It answers two questions Odoo needs to know:
1. Does this account appear on the Balance Sheet or the Profit & Loss?
2. Does the balance carry over to next year, or reset to zero?

---

### The two families of accounts

**Balance Sheet accounts** — these track what your company *has* and *owes*. The balance carries forward every year.

| Category | Plain Meaning | Examples |
|---|---|---|
| Assets | Things you own or are owed | Bank accounts, customer debts, equipment, prepaid expenses |
| Liabilities | Things you owe to others | Vendor debts, loans, VAT you collected but haven't paid yet |
| Equity | What the company is worth to its owners | Share capital, retained profits |

**Profit & Loss accounts** — these track *income and spending* during the year. They are filtered to the current fiscal year in reports (see Part 9 on year-end).

| Category | Plain Meaning | Examples |
|---|---|---|
| Income | Money earned from your business | Sales revenue, consulting fees |
| Other Income | Money earned outside your main business | Interest received, rent received from tenants |
| Expenses | Day-to-day operating costs | Salaries, rent, utilities, subscriptions |
| Cost of Revenue | Direct cost of what you sell | Raw materials, production labor |
| Depreciation | The annual write-down of equipment/vehicles | Monthly depreciation of a delivery van |
| Other Expenses | Non-operational costs | Bank fees, fines, exchange losses |

---

### All 19 account types — reference table

Source: [account_account.py:66–90](../addons/account/models/account_account.py#L66). Unchanged between Odoo 19 and 20.

| Type (technical name) | Label in Odoo | Family | Carries Over | Can Be Matched | Use For |
|---|---|---|---|---|---|
| `asset_receivable` | Receivable | Asset | Yes | **Required** | What customers owe you |
| `asset_cash` | Bank and Cash | Asset | Yes | No | Your bank accounts and cash registers |
| `asset_current` | Current Assets | Asset | Yes | Optional | Short-term items: inventory, deposits |
| `asset_non_current` | Non-current Assets | Asset | Yes | Optional | Long-term investments |
| `asset_prepayments` | Prepayments | Asset | Yes | Optional | Costs paid upfront, not yet expensed |
| `asset_fixed` | Fixed Assets | Asset | Yes | Optional | Equipment, vehicles, buildings |
| `liability_payable` | Payable | Liability | Yes | **Required** | What you owe vendors |
| `liability_credit_card` | Credit Card | Liability | Yes | No | Credit card accounts |
| `liability_current` | Current Liabilities | Liability | Yes | Optional | Short-term debt, VAT payable |
| `liability_non_current` | Non-current Liabilities | Liability | Yes | Optional | Long-term loans |
| `equity` | Equity | Equity | Yes | No | Share capital, retained earnings |
| `equity_unaffected` | Current Year Earnings | Equity | Accumulates | No | Running profit/loss — never resets (see Part 9) |
| `income` | Income | P&L | Filtered | No | Revenue from your core business |
| `income_other` | Other Income | P&L | Filtered | No | Non-core revenue (interest, subletting) |
| `expense` | Expenses | P&L | Filtered | No | Operating costs (rent, salaries, software) |
| `expense_other` | Other Expenses | P&L | Filtered | No | Bank charges, fines, non-core costs |
| `expense_depreciation` | Depreciation | P&L | Filtered | No | Depreciation of fixed assets |
| `expense_direct_cost` | Cost of Revenue | P&L | Filtered | No | Direct production or delivery costs |
| `off_balance` | Off-Balance Sheet | — | No | No | Guarantees, contingencies — not in P&L or balance sheet |

**"Can Be Matched"** = Reconcilable. Odoo can link two entries together to mark a debt as settled. Required on Receivable and Payable so Odoo can track which invoices have been paid.

**"Filtered"** = P&L accounts aren't zeroed at year-end — instead, reports filter them by fiscal year date range. See Part 9 for the full explanation.

---

### When to create a separate account

**The rule:** Create a new account whenever you want to see that cost as its own line in a report.

| Situation | Separate Account? | Why |
|---|---|---|
| Each bank account | Always — Odoo requires it | Bank accounts cannot be shared between companies |
| Office rent | Yes | You want "Rent" as its own line in the P&L |
| Software subscriptions | Yes | Separate from office supplies; easier to budget and monitor |
| Salaries | Yes | Required in most legal charts of accounts |
| Electricity and Internet | Yes (if different reports), No (if combined is enough) | Depends on how detailed your P&L needs to be |
| Trade receivables vs. owner loan | Yes, two accounts | Owner loans are "non-trade" — different report sections |
| Two different currencies | Yes, one account per currency | Mixing currencies on one account causes reconciliation problems |
| Same type, not important to track separately | No | One shared account is fine |

**Practical minimum chart for a small company:**

```
── ASSETS ───────────────────────────────────────────────
1100  Accounts Receivable       ← what customers owe you
1200  Prepaid Expenses          ← costs paid upfront (insurance, etc.)
1500  Fixed Assets              ← equipment, furniture

── LIABILITIES ──────────────────────────────────────────
2100  Accounts Payable          ← what you owe vendors
2500  VAT Payable               ← collected VAT to remit

── EQUITY ───────────────────────────────────────────────
3000  Share Capital
3900  Retained Earnings (Current Year)  ← auto-accumulates profit/loss

── INCOME ───────────────────────────────────────────────
4000  Revenue

── EXPENSES ─────────────────────────────────────────────
5000  Cost of Goods Sold        ← direct production cost
6100  Salaries                  ← personnel
6200  Office Rent               ← facilities
6300  Software & Subscriptions  ← tools
6400  Utilities                 ← electricity, internet
6500  Bank Fees                 ← financial costs
6600  Depreciation              ← wear and tear on assets
```

---

### Account hierarchy — parent accounts (replaces account groups)

> **Changed in Odoo 20.** The separate `account.group` model, with its code-prefix ranges, was removed.
> Accounts now point at each other: an account can have a **Parent Account**.

Source: [account_account.py:133](../addons/account/models/account_account.py#L133)

**How it works:** on the account form, set "Parent Account". The Chart of Accounts list then renders an
indented, foldable tree, and reports subtotal by branch.

**Example structure:**

```
Operating Expenses            6000     (parent, often inactive — a header)
  └─ Personnel                6100     parent_id -> Operating Expenses
       ├─ Salaries            6101     parent_id -> Personnel        28,000
       └─ Bonuses             6110     parent_id -> Personnel         2,000
  └─ Facilities               6200     parent_id -> Operating Expenses
       ├─ Rent                6201     parent_id -> Facilities       12,000
       └─ Utilities           6210     parent_id -> Facilities        3,000
```

What is different in practice:

| | Odoo 19 (account groups) | Odoo 20 (parent accounts) |
|---|---|---|
| Set up by | defining a code range, accounts fall in automatically | setting "Parent Account" on each account |
| Codes | mandatory, and must be designed around the ranges | optional; the tree ignores them |
| Can you post to a group? | No — it was not an account | Yes, if the parent account is active |
| Header-only node | a group | an account with **Active = off** |
| Where to configure | Accounting → Configuration → Account Groups | Accounting → Accounting → Chart of Accounts, on the account itself |

> If your localization ships a tree (37 `l10n_*` modules do, e.g. UAE, Argentina, Canada, China, Georgia), you get it for
> free. The generic US chart ships **no** parents — it stays flat until you build the hierarchy yourself.

---

## Part 2 — How Taxes Work with Accounts

### The link between a tax and an account

When you charge VAT on a sales invoice, that VAT amount does not just "float" — it must land in a specific account. This is controlled by **tax repartition lines**.

Every tax has two sets of repartition lines:
- One set for **invoices** (what happens when you charge the tax)
- One set for **refunds** (what happens when you reverse it)

Each repartition line says:
- What **percentage** of the tax applies (usually 100%)
- Whether it applies to the **base amount** (the sale price) or the **tax amount** (the VAT itself)
- Which **account** receives that portion
- Which **tax tag** marks it for the tax report (VAT declaration)

Source: [account_tax.py:5135–5170](../addons/account/models/account_tax.py#L5135)

**Example — 20% VAT on a 1,000 sale:**

```
Invoice posted → Odoo auto-creates 3 journal lines:

  Debit   1100 Accounts Receivable     1,200   (customer owes full amount)
  Credit  4000 Revenue                 1,000   (base amount — base repartition line)
  Credit  2500 VAT Payable               200   (tax amount — tax repartition line)
```

You never create the VAT line manually. Odoo reads the tax, finds the repartition line, and creates the entry automatically.

---

### Account tags — connecting accounts to your tax declaration

Account tags (with `applicability = taxes`) mark which line of your VAT return a transaction falls into.

| Item | What it is |
|---|---|
| Tax tag | A label like "Box 1A" or "Standard Rate Output" |
| Where it lives | On the tax repartition line — set by your accountant or via the localization |
| What it does | When the tax is applied, the tag flows to the journal entry line |
| Where it appears | In the Tax Report (VAT return) — each report line sums all entries carrying that tag |

Source: [account_account_tag.py:12](../addons/account/models/account_account_tag.py#L12), [account_move_line.py:267](../addons/account/models/account_move_line.py#L267)

**In practice:** You don't set up tax tags manually unless you're building a localization. Your country's module (e.g., `l10n_de`, `l10n_gb`) installs the correct tags and wires them to the tax repartition lines. Your job is to choose the correct tax on the invoice — the tags flow automatically.

**Two types of tags** — don't confuse them:

| Type | Used On | Purpose |
|---|---|---|
| `applicability = accounts` | Directly on accounts | Custom grouping for financial analysis (operating, financing, investing cash flows) |
| `applicability = taxes` | On tax repartition lines | VAT/tax declaration grid boxes |

---

## Part 3 — Reconciliation: Matching Invoices and Payments

### What reconciliation means

When you send a customer invoice for 1,000 and they later pay 1,000, those are two separate journal entries. Reconciliation **links them together** so Odoo knows the debt is settled.

Without reconciliation: the Receivable account shows both the +1,000 (invoice) and -1,000 (payment) as separate open items. Your outstanding invoice report looks wrong — it still shows the invoice as unpaid.

With reconciliation: the two entries are linked. The residual (remaining) amount becomes zero. The invoice is marked as paid. It disappears from the outstanding invoice report.

Source: [account_partial_reconcile.py:12–70](../addons/account/models/account_partial_reconcile.py#L12), [account_move_line.py:280–312](../addons/account/models/account_move_line.py#L280)

---

### How Odoo tracks the outstanding balance

Every receivable and payable journal line has an **Amount Residual** — the portion that hasn't been matched yet.

```
Invoice posted:
  Receivable line: balance = 1,000, residual = 1,000

Payment registered:
  Receivable line: balance = -1,000, residual = -1,000

Reconciliation created:
  Both lines linked via account.partial.reconcile
  Invoice residual → 0
  Payment residual → 0
  Status: "Reconciled" (appears as paid)
```

Source: [`_compute_amount_residual()`](../addons/account/models/account_move_line.py#L1159)

---

### Partial reconciliation

If the customer pays only 600 out of 1,000:

```
Invoice: residual = 1,000
Payment of 600 received and reconciled:
  Invoice residual → 400 (still open, appears in aged receivables)
  Payment residual → 0 (fully used)

Second payment of 400 later:
  Invoice residual → 0 (fully settled)
  Full reconciliation record created
```

You can also reconcile one payment against multiple invoices, or multiple payments against one invoice. Odoo creates one `account.partial.reconcile` record per matched pair.

---

### What reconciliation affects

| Without reconciliation | With reconciliation |
|---|---|
| Invoice shows as "In Payment" or "Outstanding" | Invoice shows as "Paid" |
| Outstanding amounts on partner's account | Clean zero balance |
| Payment sits unmatched in bank | Payment linked to specific invoice |
| Aged receivables/payables report shows open items | Items cleared from aged reports |

**When Odoo reconciles automatically:**
- When you click **Register Payment** on an invoice → Odoo reconciles the payment to the invoice immediately
- When you match bank statement lines to invoices in the bank reconciliation → Odoo reconciles them
- When you use the **Reconcile** action on the partner's account (Accounting → Customers → Customers → open a partner → View Journal Items)

---

### Multi-currency reconciliation

When invoice and payment are in different currencies, reconciliation also creates an **exchange difference entry** automatically — a journal entry that absorbs the gain or loss from the rate difference. This is booked to a dedicated exchange gain/loss account configured in your company settings.

Source: [`_prepare_exchange_difference_move_vals()`](../addons/account/models/account_move_line.py#L3315) and [`_create_exchange_difference_moves()`](../addons/account/models/account_move_line.py#L3414)

---

## Part 4 — Journal Entries: When to Use Them and When Not To

### What a journal entry is

Every financial event is recorded as a journal entry — two or more lines that must always balance: every debit has a matching credit of the same total amount.

**Examples:**

| Event | Debit (money goes to) | Credit (money comes from) |
|---|---|---|
| Customer pays an invoice | Bank account +1,000 | Accounts Receivable -1,000 |
| You pay monthly rent | Rent Expense +3,000 | Bank account -3,000 |
| You buy a laptop | Fixed Assets +1,200 | Bank account -1,200 |

Odoo creates most journal entries **automatically** when you work with invoices, payments, and other documents. You rarely need to create them manually.

---

### The six types of journals

Journals are labeled folders where Odoo files entries based on what they relate to.

Source: [account_journal.py:95–108](../addons/account/models/account_journal.py#L95)

| Journal | What goes in it | Who creates entries here |
|---|---|---|
| **Sales** | Customer invoices and credit notes | Odoo, when you post an invoice |
| **Purchase** | Vendor bills and credit notes | Odoo, when you post a bill |
| **Bank** | Payments in and out of bank | Odoo, when you register a payment or import a bank statement |
| **Cash** | Cash payments in and out | Odoo, when you register a cash transaction |
| **Credit Card** | Card charges and repayments | Odoo, when you register a card transaction or import a card statement |
| **Miscellaneous** (General) | Everything else — corrections, accruals, adjustments | Accountant — manually |

---

### When to create a manual journal entry

Go to **Accounting → Accounting → Journal Entries → New** only in these cases:

| Situation | Example | Why not an invoice or payment? |
|---|---|---|
| Month-end accrual | Salary for December not yet paid — you need to show the cost in December's P&L | No bill exists yet. The cost happened but the document hasn't |
| Opening balances | Migrating to Odoo and entering historical balances | Historical data — no real-time document |
| Error correction | Wrong account used on a posted entry — reverse it and rebook correctly | Fixing an existing mistake |
| Intercompany transfer | Cash moved between two of your own companies | No external vendor involved |
| Provision | You estimate 5,000 of invoices will go bad — create a doubtful debt provision | Estimate, not a real invoice |
| Manual VAT adjustment | Tax authority correction | Required by regulation |

---

### When NOT to create a manual journal entry

Odoo creates journal entries automatically in all these cases. Creating them manually too gives you duplicates.

| What you want to do | Use this instead |
|---|---|
| Record a customer invoice | Accounting → Customers → Invoices → New |
| Record a vendor bill | Accounting → Vendors → Bills → New |
| Record a payment | "Register Payment" on the invoice, or bank reconciliation |
| Depreciate a fixed asset | Fixed Assets module — depreciation board posts automatically |
| Recognize deferred revenue/expense monthly | Deferred Entries feature — entries post automatically |

---

### What Odoo creates automatically — reference

Source: [account_move.py:297–316](../addons/account/models/account_move.py#L297), [`account_payment._prepare_move_line_default_vals()`](../addons/account/models/account_payment.py#L430), [`account_asset.compute_depreciation_board()`](../enterprise/account_asset/models/account_asset.py#L465)

| What you do | What Odoo creates automatically |
|---|---|
| Post a customer invoice | Journal entry: Debit Receivable / Credit Revenue + Tax lines |
| Post a vendor bill | Journal entry: Debit Expense + Tax lines / Credit Payable |
| Register a payment | Journal entry: Debit/Credit Bank / Counter account |
| Reconcile invoice + payment | Partial/full reconcile record, clears residual |
| Confirm a fixed asset | Depreciation schedule → one entry per period |
| Set up deferred expense/revenue | Monthly recognition entries |
| Reconcile in a foreign currency | Exchange gain/loss entry |

---

## Part 5 — Payment Terms: Due Dates and Installments

### What payment terms do

A payment term defines **when** and **how much** a customer or vendor must pay. Instead of one lump sum due immediately, you can split it:
- 40% on invoice date
- 60% due in 30 days

When you apply a payment term to an invoice, Odoo creates **multiple lines** on the Receivable/Payable account — one per installment — each with its own **due date**.

Source: [`_compute_terms()`](../addons/account/models/account_payment_term.py#L169)

**Example — "40/60 net 30":**

```
Invoice posted for 1,000 with payment term "40% now, 60% in 30 days":

  Debit  Receivable  400   due: invoice date (Jan 1)
  Debit  Receivable  600   due: Jan 31
  Credit Revenue    1,000
```

The Receivable account now has two open lines. When the customer pays 400 on Jan 1, it reconciles against the first line. When they pay 600 on Jan 31, it reconciles against the second.

---

### Early payment discounts

If you offer a discount for paying early (e.g., 2% off if paid within 10 days), Odoo records:
- The **discount date** on the receivable line
- The **discounted amount** that would settle the invoice if paid before that date

Source: [account_move_line.py:508–520](../addons/account/models/account_move_line.py#L508) (`discount_date`, `discount_amount_currency`)

**Important:** Early payment discount can handle taxes in three ways (depends on your country's rules):
- Tax included in the discount
- Tax excluded (customer pays full tax regardless)
- Mixed treatment

---

### Where you see due dates

- **Aged Receivables report:** Groups unpaid invoices by how far past their due date they are (current, 0–30 days, 30–60 days, etc.)
- **Follow-up report:** Shows which customers are overdue
- **Partner ledger:** Lists all open items per customer/vendor with their due date

---

## Part 6 — Lock Dates: Protecting Past Periods

### What lock dates do

Once you've closed a period and filed your VAT return or submitted financial statements, you don't want anyone accidentally posting entries into that period. Lock dates prevent this.

Odoo has five separate lock dates:

Source: [company.py:79–115](../addons/account/models/company.py#L79)

| Lock Date | What it protects | Who can override |
|---|---|---|
| **Fiscal Year Lock** | General accounting periods | Users with an active lock exception |
| **Tax Lock** | Tax periods — set automatically when VAT closing entry is posted | Users with an active lock exception |
| **Sales Lock** | Only entries in the Sales journal | Users with an active lock exception |
| **Purchase Lock** | Only entries in the Purchase journal | Users with an active lock exception |
| **Hard Lock** | Everything — absolute barrier | Nobody. Cannot be removed or moved backward |

---

### Soft lock vs. hard lock

**Soft lock** (Fiscal, Tax, Sales, Purchase): If an authorized user needs to correct something in a locked period, an administrator can grant them a **lock exception** — a temporary permission to post to dates before the lock. The lock itself doesn't move.

**Hard lock**: Irreversible. Once set, no entry can ever be posted before that date. Not even administrators can bypass it. Use this after finalizing annual financial statements.

---

### How lock dates are set

| Automatic | Manual |
|---|---|
| Tax lock date: set automatically when you validate the tax return (Enterprise) | Fiscal year lock: set manually in Accounting → Configuration → Settings → Lock Dates |
| | Hard lock: set manually — with caution |

**Path:** Accounting → Configuration → Settings → Lock Date section (or Accounting → Accounting → Lock Dates)

> **Changed in Odoo 20:** reopening a filed tax return no longer rolls the tax lock date back for you.
> Validation still moves `tax_lock_date` forward automatically; resetting the return refuses outright while the
> lock still covers the period. Lower the lock first, then reset. Details in [`account_returns.md`](account_returns.md#reopening-a-validated-return).

---

### What happens when you violate a lock date

If you try to post or edit an entry with a date before a lock date, Odoo shows an error and prevents the action. You cannot backdate entries into locked periods without an exception.

---

## Part 7 — Year-End: What Odoo Actually Does

### The common misconception

Many people expect Odoo to "zero out" income and expense accounts at year-end with a big closing journal entry. It doesn't work that way.

Odoo's approach: **P&L accounts accumulate entries forever. Reports filter them by fiscal year date range.**

Source: [account_account.py:679–686](../addons/account/models/account_account.py#L679)

---

### How year-end really works

Every account has an `include_initial_balance` setting (computed automatically from the account type):

| Account type | include_initial_balance | Meaning |
|---|---|---|
| Asset, Liability, Equity | **True** | Balance Sheet — show all entries from the beginning of time |
| Income, Expense | **False** | P&L — show only entries within the selected fiscal year |
| Current Year Earnings (`equity_unaffected`) | **False (special)** | Accumulates all profit/loss — never filtered, never resets |

When you open the P&L report in Odoo and select "Fiscal Year 2024", Odoo runs a query filtered to `date >= 2024-01-01 AND date <= 2024-12-31` on income and expense accounts. The previous year's entries are simply excluded from the query — not deleted, not moved.

---

### The "Current Year Earnings" account

This is the most important account you might not know about. It is type `equity_unaffected` and it accumulates your company's net profit and loss over time.

**What it contains:** The sum of all income minus all expenses — your running profit. This is not filtered by year. It is the "score" your business is keeping.

**Why it's on the Balance Sheet:** Profit belongs to the owners (equity). As the year progresses, your running profit lives in this account. At year-end, your accountant typically creates one manual entry that moves the year's profit into a "Retained Earnings" account — but Odoo doesn't force you to do this.

Source: [`get_unaffected_earnings_account()`](../addons/account/models/company.py#L977)

---

### The opening entry

When you first set up Odoo (or start a new fiscal year), you create an **opening entry** — a single journal entry dated the day before your fiscal year starts that loads your balance sheet opening balances.

This entry is what causes your bank account, receivables, payables, and equity to show the correct starting balances. Income and expense accounts do NOT need an opening entry because they start tracking from day one of the fiscal year.

---

### Year-end checklist (what you do, not Odoo)

1. Run the P&L for the full fiscal year — confirm income and expense
2. Post any missing accruals or adjustments (manual journal entries)
3. Reconcile all receivable and payable accounts — everything should be matched or explained
4. Run the Tax Closing (if applicable) — Odoo sets the tax lock date automatically
5. Set the Fiscal Year Lock Date to the last day of the closed year
6. Optionally: post one manual entry to move Current Year Earnings → Retained Earnings account
7. Start the new year — Odoo's reports automatically filter from the new fiscal year start

---

## Part 8 — Fixed Monthly Costs: Which Odoo Feature to Use

### "I have a cost that repeats every month. What do I do?"

```
What is the nature of this cost?
│
├─ Vendor sends me a new invoice each month (rent, cleaning, SaaS)
│    → Option A: Recurring vendor bill
│
├─ Bank charges me automatically — no invoice arrives (standing order, bank fee)
│    → Option B: Recurring journal entry
│
├─ I paid the full year upfront in one payment (annual insurance, annual license)
│    → Option C: Deferred expense — Odoo spreads it over 12 months automatically
│
└─ I bought something valuable that lasts several years (laptop, van, machinery)
     → Option D: Fixed asset depreciation — Odoo writes it down gradually
```

---

### Option A — Recurring vendor bill

**When:** Vendor sends a monthly invoice.

**How to set it up:**

1. Go to **Accounting → Vendors → Bills → New**
2. Fill in the bill as normal (vendor, amount, expense account)
3. Before posting — find the **Recurring** field and set it to `Monthly`
4. Set **Recurring Until** = the last month you expect this cost (e.g., `2025-12-31`)
5. Post the bill

**What happens next:** Odoo automatically creates the next month's draft bill. Every night at 2 AM, a scheduled job posts any recurring bills whose date has arrived.

Source: [account_move.py:297–316](../addons/account/models/account_move.py#L297) (`auto_post`, `auto_post_until`, `auto_post_origin_id`), [service_cron.xml:3–11](../addons/account/data/service_cron.xml#L3)

| Setting | What it does |
|---|---|
| Recurring = Monthly | Creates a copy for the next month after posting |
| Recurring = Quarterly | Creates a copy every 3 months |
| Recurring Until | Stops creating copies after this date |

> The analytic distribution on the template entry is copied to every recurring copy. Set it correctly on the first entry.

---

### Option B — Recurring journal entry (no invoice)

**When:** The bank debits you automatically each month with no incoming invoice.

**How to set it up:**

1. Go to **Accounting → Accounting → Journal Entries → New**
2. Journal = Miscellaneous
3. Add the two lines:
   - Line 1: Account = `6200 Rent`, Debit = 3,000
   - Line 2: Account = `Bank`, Credit = 3,000
4. Set Analytic Distribution = your cost center (see Part 9 for details)
5. Set **Recurring = Monthly** and **Recurring Until**
6. Post

The cron creates and posts a copy every month until the end date.

---

### Option C — Deferred expense (paid upfront, spread monthly)

**When:** You paid the full year upfront in January. The cost covers 12 months but you only want to show 1/12 in each month's P&L.

**Example:** Annual software license: 12,000 paid January 1. Without deferral, January P&L shows a 12,000 hit. With deferral, each month shows 1,000.

**How it works:**

1. Post the vendor bill for 12,000
2. On the bill line — set the account to your **Prepaid Expenses** account (type: Prepayments, e.g., `1200`)
3. Set **Deferral Start Date** = Jan 1 and **Deferral End Date** = Dec 31
4. Post the bill

Odoo moves 12,000 to the Prepaid balance sheet account and creates 12 monthly journal entries, each moving 1,000 from Prepaid → Expense. They post automatically each month.

Full details: [deferred_expenses_revenue.md](deferred_expenses_revenue.md)

> **Requires:** `account_accountant` enterprise module + Deferred Expense Account configured in Accounting → Settings → Deferred Entries

---

### Option D — Fixed asset depreciation

**When:** You bought equipment, a vehicle, or a building that lasts several years.

**Why not expense immediately:** A 30,000 delivery van serves the company for 5 years. Booking 30,000 as expense in month one makes that month look terrible and future months artificially good. Depreciation spreads the cost fairly across the years of actual use.

**How it works:**

1. Post the vendor bill with the account set to a **Fixed Assets** account (type: `asset_fixed`)
2. Odoo prompts: "Create an asset from this line?" → Yes
3. On the asset record: set the method (straight-line) and duration (e.g., 60 months = 5 years)
4. Click **Confirm** → Odoo computes the board: 500/month for 60 months
5. Each month: Debit Depreciation Expense 500 / Credit Accumulated Depreciation 500 — posted automatically

Source: [`compute_depreciation_board()`](../enterprise/account_asset/models/account_asset.py#L465) — in Odoo 20 this delegates to `current_selected_variant_id`, part of the new `account.asset.variant` / `account.depreciation.model` structure.

Full details: [account_asset.md](account_asset.md)

---

## Part 9 — Analytic Accounts and Distribution: The Budget Tracking Layer

### What analytic accounts are

An analytic account is a **tag** that answers "which project, department, or cost center did this spending belong to?"

It is separate from the expense account. The expense account answers "what type of cost is it." The analytic account answers "who or what caused it."

| Regular account | Analytic account |
|---|---|
| `6200 Office Rent` | `Operations Department` |
| Tells you: type of expense | Tells you: which part of the business |
| Appears in P&L | Appears in budget tracking and analytic reports |

---

### Analytic plans

Analytic accounts belong to **plans** — the grouping dimension. Common plans:

| Plan | Example accounts inside |
|---|---|
| Departments | Operations, Sales, HR, IT |
| Projects | Project Alpha, Project Beta |
| Cost Centers | Office Berlin, Office Paris |

You can have multiple plans active at once. A single bill line can be distributed across multiple plans simultaneously.

---

### How analytic distribution works

When you post a bill line with analytic distribution, Odoo writes a JSON value on that line and creates **analytic line records** automatically.

Source: [analytic_mixin.py:17–22](../addons/analytic/models/analytic_mixin.py#L17), [`_create_analytic_lines()`](../addons/account/models/account_move_line.py#L3546)

**The JSON format:**

```json
{
  "42": 100
}
```
Means: 100% to analytic account with ID 42.

```json
{
  "42": 60,
  "87": 40
}
```
Means: 60% to account 42, 40% to account 87 (splitting across two departments or projects).

```json
{
  "42,87": 60,
  "15": 40
}
```
Means: 60% split across two analytic accounts that belong to *different plans simultaneously* (account 42 from one plan, account 87 from another plan — both get 60% of the expense), plus 40% to account 15. This is how multi-plan distribution works.

**What gets created:**

When you post the bill:
- Odoo creates one `account.analytic.line` per analytic account
- The amount on each line = bill line amount × that account's percentage
- These analytic lines are what the budget system reads to compute "Achieved"

**What happens if no analytic distribution is set:**

No analytic lines are created. The expense is invisible to the budget. It still appears in your P&L (because P&L reads from `account.move.line`, not `account.analytic.line`), but your budget report will not count it.

---

### Where to see analytic spending

**Option 1 — Analytic Items list:**
Path: Accounting → Analytic → Analytic Items

Shows every analytic line created from posted entries. Filter by date, analytic account, partner, etc. Pivot and graph views available.

**Option 2 — From the analytic account:**
Path: Accounting → Analytic → Analytic Accounts → open an account → click the smart button

Shows all spending (and income) tagged to that analytic account.

Source: [analytic_line_views.xml:122–170](../addons/analytic/views/analytic_line_views.xml#L122)

---

## Part 10 — Budgets: Planning and Tracking Fixed Costs

### What budgets do in Odoo

A budget answers: **"Did we spend what we planned?"**

You set a planned amount for a period. As you post bills and journal entries with analytic distribution, Odoo tracks the actual spend.

> **Renamed in Odoo 20.** The planned figure, the field `budget_amount`, is now labelled **Commitment** (it was "Budgeted"),
> and a new **Liquidation** amount was added alongside it. `achieved_percentage` is now measured against Liquidation,
> not against Commitment.

| Column | Field | What it means | Example (rent budget: 36,000/year, checked Feb 15) |
|---|---|---|---|
| **Commitment** | `budget_amount` | What you said you'd spend for the full period | 36,000 |
| **Liquidation** | `liquidation_amount` | The amount you expect to actually settle. Defaults to Commitment, editable | 36,000 |
| **Achieved** | `achieved_amount` | What you've actually posted so far (via analytic lines) | 6,000 (Jan + Feb bills) |
| **Theoretical** | `theoritical_amount` | What you *should* have spent by today, proportionally | 4,520 (46 days ÷ 365 × 36,000) |
| **Committed** | `committed_amount` | Confirmed POs not yet invoiced (needs `account_budget_purchase`) | 0 |

If Achieved > Theoretical → spending faster than planned.
If Achieved > Commitment → over budget → `is_above_budget`, red highlight.

Source: [budget_line.py:22–45](../enterprise/account_budget/models/budget_line.py#L22), [`_compute_all`](../enterprise/account_budget/models/budget_line.py#L82), [`_compute_theoritical_amount`](../enterprise/account_budget/models/budget_line.py#L94)

> **What counts as Achieved.** Only analytic lines whose general account is income/expense or
> `asset_current` / `asset_non_current` / `asset_fixed` (or that carry no general account at all) are summed
> — a filter added in Odoo 20 ([budget_report.py:65](../enterprise/account_budget/reports/budget_report.py#L65)).
> An analytic line posted against, say, a payable account no longer inflates Achieved.

---

### Budget states

Source: [budget_analytic.py](../enterprise/account_budget/models/budget_analytic.py)

| State (technical) | Label in the UI | Meaning | Can You Edit? |
|---|---|---|---|
| `draft` | Draft | Being prepared | Yes — add/edit budget lines |
| `confirmed` | **Open** | Active — tracking is live | No — locked. Create a revision to adjust |
| `revised` | Revised | A newer version replaced this one | No |
| `done` | Done | Manually closed | No |
| `canceled` | Canceled | Abandoned | No |

> A draft budget does not track anything. You must confirm it before spending is counted.

---

### Setting up a budget for a fixed monthly cost — step by step

**Example:** Office rent is 3,000/month. You want to budget 36,000 for 2025.

**Step 1 — Create an analytic account** (if you don't have one)

Path: Accounting → Configuration → Analytic Accounts → New
- Name: `Office Rent` or `Facilities`

**Step 2 — Create the budget**

Path: Accounting → Accounting → Budgets → New

- Name: `Facilities Budget 2025`
- Date From: `2025-01-01` · Date To: `2025-12-31`
- Budget Type: `Expense`
- Add one budget line:
  - Analytic Account: `Office Rent`
  - Planned Amount: `36,000`

**Step 3 (optional) — Split into monthly lines**

Click **Split Budget** → Period: Month → Odoo creates 12 lines of 3,000 each.

Use this if you want to see monthly Planned / Achieved / Theoretical (e.g., if some months are higher than others).

Source: [`action_budget_split()`](../enterprise/account_budget/wizards/budget_split_wizard.py#L33)

**Step 4 — Confirm the budget**

Click **Confirm**. Tracking begins. To adjust later → use **Create Revision** (creates a copy, sets original to `revised` state).

**Step 5 — Tag every rent transaction with the analytic account**

On each vendor bill, on the expense line:
- Set **Analytic Distribution** = `100% → Office Rent`

On recurring journal entries, the analytic tag is copied automatically each month.

**Step 6 — Monitor**

Path: Accounting → Accounting → Budgets → open your budget

- **Achieved** column = real spending
- **Theoretical** column = on-track reference
- Red highlight on any line where Achieved > Planned

---

### Budget alerts — where they appear

Source: [budget_analytic_views.xml:59](../enterprise/account_budget/views/budget_analytic_views.xml#L59), [`purchase_order_line._compute_above_budget()`](../enterprise/account_budget_purchase/models/purchase_order_line.py#L56)

| Where | What you see | When |
|---|---|---|
| Budget form — Achieved column | Red background | Actual spend exceeds planned |
| Budget form — Committed column | Red background | POs + actual spend exceeds planned |
| Purchase order form | Red "Budget" button at the top | Any PO line would push spending over budget |
| Purchase order lines | Red row | That specific line pushes over budget |

---

### Committed amount — early warning from purchase orders

**What it is:** Approved (confirmed) purchase orders that haven't been invoiced yet.

**Why it matters:** You create a PO today for next month's delivery. The money isn't spent yet (no invoice), but it's committed. Without committed tracking, your budget shows green until the invoice arrives — too late to act.

**What counts as committed:**
- Only purchase orders in **confirmed state** (`state = 'purchase'`)
- Only the **uninvoiced quantity** — if you've invoiced 3 out of 10 units, only 7 units' worth counts as committed
- Formula: `(quantity_ordered - quantity_invoiced) × unit_price × analytic_distribution_%`

Source: [budget_report.py:50–75](../enterprise/account_budget_purchase/reports/budget_report.py#L50) — the PO line query joins confirmed orders to matching budget lines and keeps only `product_qty > qty_invoiced`

> Requires the `account_budget_purchase` enterprise module.

---

### Budget Report — where to see planned vs actual across all budgets

Path: **Accounting → Reporting → Budget Report**

Source: [budget_report_view.xml:81–94](../enterprise/account_budget/reports/budget_report_view.xml#L81)

This report opens in **Pivot view by default** (the best view for comparison):

| View | What it shows |
|---|---|
| **Pivot** | Rows = analytic accounts, Columns = budgets, Measures = Budget vs Achieved side by side |
| **List** | Flat list of all budget lines and analytic lines — filter to "Budgeted" or "Achieved" |
| **Graph** | Time-series of budget vs actual |

**Default filter:** `search_default_open_budget` — only budgets in the `confirmed` ("Open") state. Odoo 20 also groups by budget line by default (`search_default_group_by_budget_line_id`).

**Drill-down from Achieved:** Click on an achieved amount → Odoo opens the original business document (the vendor bill, journal entry, etc.) that generated that analytic line.

Source: [`action_open_reference()`](../enterprise/account_budget/reports/budget_report.py#L181)

---

### How the budget system connects to the P&L

| P&L Report | Budget Report |
|---|---|
| Reads from `account.move.line` | Reads from `account.analytic.line` |
| Groups by expense account | Groups by analytic account |
| Filters by fiscal year date range | Filters by budget period date range |
| Shows every expense regardless of analytic tagging | Only shows expenses tagged with analytic accounts |
| No planned/achieved comparison | Shows planned vs achieved vs theoretical |

**Key insight:** These are complementary reports, not alternatives. P&L shows you the full picture. Budget report shows you performance against plan for the items you chose to budget.

If an expense is not tagged with an analytic account → it appears in the P&L but NOT in the budget report.
If an expense IS tagged → it appears in both.

---

### Financial budget vs. analytic budget — the confusion explained

You may hear these terms used as if they're two different systems. In Odoo 20, as in 19, there is **one budget system**.

- **"Financial budget"** = the overall concept of tracking planned vs actual money
- **"Analytic budget"** = the Odoo implementation, which uses analytic accounts as dimensions

They are the same thing. When someone says "analytic budget" in Odoo, they mean the `account_budget` module that uses analytic accounts for budget lines.

---

## Part 11 — Complete Example: Office Rent, Start to Finish

**Setup (do once at the start of the year):**

```
1. Create account 6200 "Office Rent"    type: Expenses
2. Create analytic account "Rent"       plan: Departments
3. Create budget "Rent 2025"
   - Date: Jan 1 – Dec 31, 2025
   - Budget type: Expense
   - Line: analytic = "Rent", planned = 36,000
4. Confirm the budget → tracking begins
```

**Every month (recurring):**

```
Option A — Landlord sends invoices:
  1. Accounting → Vendors → Bills → New
  2. Line: account = 6200 Rent, amount = 3,000
  3. Set Analytic Distribution = 100% Rent
  4. Set Recurring = Monthly, Recurring Until = 2025-12-31
  5. Post

  Odoo creates automatically:
  - Journal entry: Debit 6200 Rent 3,000 / Credit Payable 3,000
  - Analytic line: "Rent" account, amount = 3,000
  - Budget report updates: Achieved += 3,000

Option B — Bank auto-debits, no invoice:
  1. Accounting → Journal Entries → New
  2. Line 1: 6200 Rent, Debit 3,000, Analytic = 100% Rent
  3. Line 2: Bank, Credit 3,000
  4. Set Recurring = Monthly
  5. Post
```

**Monitoring at any point during the year:**

```
Budget form (Feb 15):
  Planned:     36,000
  Achieved:     6,000  (Jan + Feb bills posted)
  Theoretical:  4,520  (46/365 × 36,000)
  → Achieved > Theoretical: you're spending on track (both months paid correctly)

If landlord raises rent in July to 3,500:
  → Post the 3,500 bill as normal (analytic = Rent)
  → Budget will show Achieved trending above Theoretical after July
  → If Achieved looks like it'll exceed 36,000: create a budget revision
     (Confirm button → Create Revision → edit planned to 39,500 → Confirm)
```

**At year-end:**

```
P&L report shows: 6200 Office Rent = 38,000 (12 months of payments)
Budget report shows: Achieved 38,000 vs Planned 39,500 → under budget by 1,500

Lock the fiscal year: Accounting → Settings → Lock Date = 2025-12-31
Tax lock set automatically after VAT closing

New year starts: P&L report (filtered to 2026) shows 0 for rent
Balance sheet shows Accounts Payable with any outstanding rent bills
```

---

## Common Mistakes to Avoid

- **Posting a bill with no analytic account.** It won't appear in your budget. Always set the analytic distribution on expense lines.
- **Using the wrong account type.** If you use an asset account for rent, it won't appear in the P&L at all — it goes on the balance sheet. Check the account type when creating accounts.
- **Creating a manual journal entry for something Odoo handles automatically.** Posting invoices, payments, and assets already generates entries. Doing it again by hand creates duplicates.
- **Setting "Recurring Until" too early.** The last copy won't be created. Set it to the last date of the final period you want to recur.
- **Not confirming the budget.** A draft budget doesn't track anything. You must confirm it.
- **Forgetting to split the budget if you want monthly visibility.** One annual line shows total vs total. Monthly lines show whether each month's spend was on track.
- **Confusing Prepaid account with Expense account in deferred entries.** The bill line goes to the Prepaid (balance sheet) account. Odoo then moves it monthly to the Expense account. If you put it directly in the Expense account, deferral has no effect.
- **Not setting a lock date after closing a period.** Without a lock, anyone can accidentally post into the closed period and corrupt your filed financials.
- **Expecting Odoo to zero out income/expense accounts at year-end.** It doesn't. Reports filter by date range. Entries stay in the database forever.
- **Thinking committed amount includes all POs.** Only confirmed purchase orders (`state = 'purchase'`) count. Draft POs are not in committed.
- **Expecting account groups to still exist (Odoo 20).** There are no code-range groups any more. If your reports relied on them, rebuild the hierarchy with parent accounts.
- **Expecting a budget reset when you reopen a tax return (Odoo 20).** Reopening a return no longer lowers the tax lock date — do that yourself first, or the reset is refused.

---

## Related Docs

- [INDEX.md](INDEX.md)
- [deferred_expenses_revenue.md](deferred_expenses_revenue.md) — full detail on prepaid/deferred expense recognition
- [account_asset.md](account_asset.md) — full detail on fixed asset depreciation
- [accounting_coa.md](accounting_coa.md) — full chart of accounts reference with multi-company and template loading
- [analytic_budget.md](analytic_budget.md) — budget system with project integration
- [accounting_reports.md](accounting_reports.md) — all standard reports: P&L, Balance Sheet, Cash Flow, Aged Receivables
- [accounting_migration.md](../dev_notes/reference/accounting_migration.md) — opening balances, lock dates, suspense account pattern

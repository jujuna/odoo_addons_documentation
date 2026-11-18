# Georgia - Profit Tax Declaration (`gec_profit_tax_report`)

Builds the monthly profit tax declaration for rs.ge (form II-086) from posted accounting. Odoo fills
the rows it can read from journal entries. You type the rest, check the result and confirm.

**Who this is for:** accountants who file the monthly profit tax declaration, and the administrator who
sets it up. Developers: see [README_DEV.md](README_DEV.md).

## What it does

| Feature | What you get |
|---|---|
| Part III from accounting | Dividends, loans, advances, penalties, gifts, shortages and representation expenses fill their rows from posted journal items |
| Contact rules | A contact's status decides whether its items count: dividends to a Georgian LLC stay out, a loan to a person counts |
| Limits | Representation (1%) and charity (10%) limits run over the year, so nothing is taxed twice |
| Market price | Sales below or purchases above a market value you enter fill rows 16.3 and 16.4 |
| Money back | A loan repaid or an advance settled later returns its tax on rows 27.1 and 27.2 |
| Two columns | Column 2 at 15%; column 3 for international, investment and innovation statuses |
| Annexes and part IV | Annexes 1, 1.1-1.7, 2, 3 and 4, and part IV for gambling organisers |
| Corrections and booking | Corrected declarations, and optionally the profit tax entry on confirm |
| Export | An XLSX workbook in the form's layout, with the journal items behind each row |

## Quick facts

| | |
|---|---|
| Menus | **Accounting > Reporting > Profit Tax Declaration (II-086)**, **Accounting > Reporting > Profit Tax Taxed Items**, **Accounting > Configuration > Accounting > Profit Tax Declaration Rows** (administrators) |
| Added to existing screens | Contact form, **Sales & Purchase** tab: group **rs.ge Profit Tax**. Account form: **Profit Tax Row** and **Profit Tax Balance Group**. Journal entry lines: **Profit Tax Row** column (hidden by default). Invoice and bill lines: **Market Value** column (hidden by default). Countries: **Preferential Taxation** |
| Settings | **Accounting > Configuration > Settings**, block **Profit Tax Declaration** |
| Who can use it | Accounting users create, recalculate and confirm. Only accounting administrators use **Back to Draft** and edit the row list |
| Needs | Georgian localization (GEC). The default rows and accounts come with the Georgian chart of accounts |

## How it works

```text
 Post entries, bills and invoices as usual
               │
               ▼
 Each journal item ──► its row (the item's own row, else its account's row)
               │        the contact decides whether it counts
               ▼
 Recalculate ──► Part III, annexes, checks
               │
               ▼
 You type what accounting cannot know, check, Confirm
               │
               ▼
 Export XLSX ──► file on rs.ge          (optional: profit tax entry posted)
```

Every row read from accounting has a list button that opens the journal items behind it. Each row has
two parts: **Calculated** (Odoo) and **Adjustment** (you). The amount filed is the sum of the two.

## Set it up (once)

1. **Accounting > Configuration > Settings**, block **Profit Tax Declaration**:
   - **Profit Tax Status**: part I box 6, the same three choices as on rs.ge (Resident Enterprise, Permanent
     Establishment of a Non-Resident, International Company).
   - **Special Status**: only for an investment company, innovative startup, innovative small or medium company
     or research and development company. It is not printed in part I; it decides column 3 (see
     [Two columns](#two-columns)).
   - **Special Activities**: tick **Bank, Credit Union, Microfinance or Lending Entity** or **Insurance
     Organisation** if one of them applies.
   - **Post Profit Tax Entry**: leave it off until you have checked a few declarations.
2. **Contacts > Configuration > Localization > Countries**: tick **Preferential Taxation** on each
   country of the Government list. The list ships empty, and rows 18.1 see no offshore person until
   you fill it.
3. On each shareholder, borrower and special supplier, fill **rs.ge Profit Tax** on the **Sales &
   Purchase** tab (see [Contacts](#contacts)).
4. **Accounting > Configuration > Accounting > Chart of Accounts**: check the **Profit Tax Row**
   defaults below and add your own accounts.

On the Georgian chart these defaults are already set:

| Account | Row | Counts when |
|---|---|---|
| 340120 Accrued Dividends Payable | 16.1 | dividend paid (debit), receiver not a Georgian Enterprise |
| 280210 Debt Investments | 18.1.1 | issuer preferential or exempt |
| 820610 Compensation & Settlements Paid | 18.1.2 | receiver preferential or exempt |
| 150110, 150120 Advances | 18.1.3 | supplier preferential or exempt |
| 760200 Bad Debt Write-Offs | 18.1.5 | debtor preferential, exempt or budget organisation |
| 280110 Equity Investments | 18.2 | non-resident or exempt, not listed abroad |
| 140410, 140710, 270510, 270990 Loans | 18.1.4, 18.3 or 18.4 | see [Loans](#loans) |
| 820710 Donations | 19 | see [Gifts and charity](#gifts-and-charity) |
| 820510 Shortages | 19.1 | always |
| 750300 Representation Expenses | 20 | above the yearly limit |

Accounts like 820990 "Other non-operating expenses" have no row on purpose. When one item there is not
business-related, open the entry and set **Profit Tax Row** on that line (for example 17.1 or 17.2).
A row chosen on the line always counts, whatever the contact.

## Contacts

The group **rs.ge Profit Tax** on the **Sales & Purchase** tab. Contact persons inherit it from their company.

| Field | Effect |
|---|---|
| **Profit Tax Status** | Georgian Enterprise: dividends to it are not taxed. Exempt from Profit Tax (free zone, special trading company…): feeds 16.4 and 18. Budget Organisation / NBG or Deposit Insurance Agency: left out of 16.4 and most of 18.1, gifts to them not taxed. Bank, Credit Union…: dividends to it are taxed. Empty: an individual, foreign person or non-commercial entity |
| **Related Party** | Deals with a market value feed 16.3. Per company |
| **Share in Capital (%)** | For banks and lenders only: decides row 18.4. Per company |
| **Charity Organisation** | Donations taxed only above the 10% limit |
| **Micro Business Status**, **Fixed Tax Payer** | Their bills feed 17.3. Untick when the income is taxed under the general rule |
| **Shares Listed on a Recognised Foreign Exchange** | Buying its shares stays out of 18.2 and 18.3 |

Odoo treats a contact as an individual when **Is a Company** is off. Without a Tax ID, Odoo leaves it
off, so give companies their Tax ID.

## Rows and their rules

### Dividends (16.1)

The tax is due when the dividend is **paid**, so 16.1 reads payments on 340120.

- The CIT wizard credits 340120 with the dividend **minus** the 5% withholding. When you match the
  payment with the wizard's entry, Odoo adds the withholding back.
- **Example:** net dividend 10,000, withholding 500, shareholder paid 9,500 → 16.1 = 10,000, tax
  1,764.71. A payment of 3,000 to a Georgian LLC → nothing.
- The wizard already books the dividend tax, so **Tax to Book** leaves it out.

Rows 16.1.1 and 16.1.2 (dividends out of old profits) are typed by you. Annexes 1 and 1.3 then
compute the credit on rows 25.1 and 25.3.

### Market price (16.3, 16.4)

Open the invoice or bill **while it is a draft**, show the **Market Value** column and enter the line's
market value in GEL.

| Contact | Sale below market | Purchase above market |
|---|---|---|
| Exempt from Profit Tax | 16.4.1 | 16.4.2 |
| Related Party (not a Georgian Enterprise) | 16.3.1 | 16.3.2 |

**Example (instruction example 2):** bill from a free-zone supplier 10,000, market value 8,000 → 16.4.2 = 2,000.

### Expenses (17)

- 17.1 and 17.2: set **Profit Tax Row** on the entry line.
- 17.3: bills from micro business and fixed tax contacts fill it automatically. For interest above the
  ministry cap, or special trading company purchases above customs value, type an **Adjustment**.

### Loans

A loan account feeds one of three rows. The contact decides which:

| Borrower | Your company is a bank or lender | Otherwise |
|---|---|---|
| In a preferential country | 18.1.4 | 18.1.4 |
| Exempt or budget organisation | 18.4 if a shareholder | 18.1.4 |
| Individual, or non-resident | 18.4 if a shareholder (individuals: share at least 1%) | 18.3 |
| Georgian company | nothing | nothing |

A deposit pledged for a shareholder's loan (18.3, 27.3) has no account rule: type it.

### Money back (27.1, 27.2, annex 1.2)

Amounts taxed on 18.1.1, 18.1.3, 18.1.4, 18.2 and 18.3 go to **Profit Tax Taxed Items** when the
declaration is confirmed. Later credits on the same account and contact count as money back, oldest first.

**Example:** January, loan 5,000 to a person → 18.3 = 5,000. February, 2,000 repaid → 27.2 = 2,000, tax
back 352.94 on row 29. The taxed item shows 3,000 remaining.

Settling an advance with a vendor bill counts the same way. Tax audit demands go in annex 1.5 (row 27.4).

### Gifts and charity (19)

- Gifts to a budget organisation, NBG or the Deposit Insurance Agency are not taxed.
- Donations to a **Charity Organisation** are taxed only above 10% of last year's net profit, counted
  over the year.
- **Example (instruction example 4):** net profit last year 100,000 → limit 10,000. January 5,000 → 0.
  February 7,500 → 2,500.
- Shortages (19.1) count on 19 too.

### Representation (20)

The limit is 1% of last year's income, or of last year's expenses when they were higher. In the founding
year it is 1% of this year's expenses so far.

**Example:** last year income 300,000, expenses 200,000 → limit 3,000. January 2,000 → 0. February
+2,500 → 1,500.

### Two columns

| Status | Goes to column 3 | Rate |
|---|---|---|
| Resident or permanent establishment, no special status | nothing | — |
| International Company (part I) | 16.1.3, from annex 1.6 | 5% |
| Special status Investment Company | 16.1.4, which you type in column 3 | 5% |
| Special status Innovative Startup or Innovative Small or Medium Company | everything | 15% |
| Special status Research and Development Company | everything | 10% (check it) |

The rs.ge e-form shows only three choices in part I box 6, while the printed form lists seven; the other four are
the special statuses above.

**Example (instruction example 7):** international company, net profit 100,000, dividend 20,000,
expenses in Georgia 60,000 → reduction 12,000, row 16.1.3 = 8,000, tax 421.05.

Both statuses and the rate (**Column 3 Rate**) are on the **Part I** tab and can be changed on a draft.

## Annexes

| Annex | Tab | Filled by |
|---|---|---|
| 1, 1.3 | **Dividend Credits** | Lines 2-4 typed once, then carried to the next declaration. Line 5 = line 1 × line 2 / (line 3 − line 4). Example: 20,000 × 50,000 / 400,000 = 2,500 |
| 1.1, 1.4 | **Dividend Credits** | Typed, for corrections of those credits |
| 1.6 | **Dividend Credits** (international companies) | One row per profit year |
| 1.7 | **Dividend Credits** (special status innovative small or medium company) | Columns 2 and 3 typed. Column 4 adds up earlier months |
| 1.2, 1.5 | **Money Back** | 1.2 automatic. 1.5 typed (demand number, date, amount) |
| 2 | **Balances**, March only | Inventory and fixed assets at last year end, from accounts with **Profit Tax Balance Group** |
| 3 | **Balances** | Loans given and received, own capital, capital in other enterprises: opening, increase, decrease, closing |
| 4 | **Annex 4**, March | Typed, when last year's international controlled transactions exceeded 500,000 GEL |
| Part IV | after annex 1, always shown as on rs.ge | Gambling organisers type the amounts. Taxes at 20%, 7%, 20%, 5% and 5%. Example: 1,000 online casino + 1,000 online betting → 270 |
| 1.1, 1.4 part I | after part IV | Type the month (10/2026); lines 25.1/25.3 and 16.1.1/16.1.2 come locked from that month's confirmed declaration |

## Step by step: the monthly declaration

1. **Accounting > Reporting > Profit Tax Declaration (II-086)** → **New**. Pick the **Month**. Part I
   is copied from the settings.
2. Click **Recalculate**. The rows, annexes and the yellow checks box fill in.
3. Read the checks box. Open a row's journal items with its list button when an amount looks wrong.
4. Type what accounting cannot know in **Adjustment** (16.1.1, 16.1.2, 16.5, 22, 25.2, 27.3, …) and in
   the annex tabs. Formula rows update at once.
5. Click **Confirm**. The declaration locks. With **Post Profit Tax Entry** on, the entry is posted.
6. Click **Export XLSX** and file the figures on rs.ge.
7. Found a mistake later? Click **Correct** on the confirmed declaration. A corrected version opens
   with your typed amounts. Recalculate, then confirm it. Booking posts only the difference.

```text
 Draft ──Confirm──► Confirmed ──Correct──► new Draft (version 2)
                        │
                        └──Back to Draft (administrator)──► Draft
```

## When Odoo refuses

| Message starts with | Why | What to do |
|---|---|---|
| A confirmed declaration cannot be changed. | It is confirmed | **Back to Draft** (administrator), or **Correct** |
| One declaration per company, month and version. | That month already has a declaration | Open it, or use **Correct** on it |
| … is still a draft: finish or delete it first. | A correction of this month is already open | Finish or delete that draft |
| A later corrected version of … is confirmed | You tried to reopen an older version | Reopen the latest version instead |
| Confirmed declarations … already count money back | Later months used its taxed items | Set those months back to draft first, newest first |
| Set the profit tax journal and accounts | Booking is on but not set up | Fill them in the settings, or turn **Post Profit Tax Entry** off |

## Rules to remember

- A row chosen on a journal line always counts. A row taken from the account counts only when the contact makes it count.
- Dividends count when paid, not when declared.
- Market values must be entered before the invoice is posted.
- The 1% and 10% limits look at the whole year, so confirm the months in order.
- Back to Draft reverses the posted entry.

## Common questions

**Why is 16.1 lower than the dividend?** The payment is not matched with the CIT wizard entry, so the
withholding is missing. The checks box says so. Match the payment, or adjust.

**Why does a Georgian company's loan show on 18.3?** Its contact has no Tax ID, so Odoo treats it as
an individual. Add the Tax ID.

**Can I upload the file to rs.ge?** The XLSX follows the form's layout for typing or copying. The
rs.ge import format is not known yet.

## Known limitations

- The preferential country list ships empty. Fill it from the Government list.
- Dividends out of 2008-2016 profits, or redistributed foreign dividends, are not told apart
  automatically: adjust 16.1, 16.1.1 and 16.1.2.
- Row 23 is calculated as (21 − 22) ÷ 0.85 (column 3: ÷ (1 − rate)). This reading is not yet
  confirmed with rs.ge.
- The 10% column 3 rate for research and development companies is not confirmed.
- Credit notes and manual entries are not compared with market values; only invoices, bills and receipts are.

## Glossary

| Word | Meaning |
|---|---|
| Calculated / Adjustment | What Odoo computed / what you typed on top. Column 2 and column 3 each have both |
| Taxed item | An amount taxed on 18.1.1, 18.1.3, 18.1.4, 18.2 or 18.3 that comes back when the money returns |
| Preferential country | A country on the Government of Georgia list of preferential tax jurisdictions |

# Georgia - Income Tax Declaration (rs.ge Form 30) (`gec_income_tax_report`)

Builds the monthly withholding declaration (Form 30) from what Odoo already knows: paid
payslips, paid journal entries and vendor bills that carry a withholding tax, and company cars
used privately. It checks every row against the rs.ge rules and exports the files the portal
imports.

**Who this is for:** accountants who file Form 30, and the administrator who sets up taxes and
contacts. Developers: [README_DEV.md](README_DEV.md).

---

## 1. What it does

| Feature | What you get |
|---|---|
| **Annex A** | One row per paid payslip, and per recipient of a paid journal entry or vendor bill with a withholding tax, built when you press **Generate Lines** |
| **Annex E** | Fees to people who pay their own income tax (ი/მ, small business) go here instead of annex A |
| **Not Declared** | Lists the entries and payslips that are booked but not paid, and the entries Odoo cannot declare, so nothing is missed silently |
| **Withholding tax proposal** | When you post a manual journal entry, Odoo recognises a withholding from its accounts (**Account Rules**) and puts the right withholding tax on it |
| **Manual rows** | **Add Manual Row** for a payment Odoo cannot see; Generate Lines keeps it |
| **Annex D** | A grid for company cars used privately; plate, engine band, driver and tax fill in from the vehicle |
| **Main part, cells 16–69** | Odoo computes the cells the portal locks and proposes the ones you type, so you copy the page instead of calculating it |
| **rs.ge rules built in** | Categories, income types, allowed rates and country codes, each with its validity period; a row rs.ge would refuse is never created |
| **Export rs.ge Files** | One import file per annex that has rows |
| **Explanations** | A question mark on every main-part cell shows how it was calculated; **Explanation Workbook** puts the whole declaration in one Excel file |
| **Tax and RS rule changes** | **Apply Tax / RS Change** on a withholding tax replaces a rate from a given month and keeps the old periods |

It does not calculate or book any tax (payroll and the withholding taxes do), send anything to
rs.ge, build page 1 of the declaration, or produce the pension file.

## 2. Quick facts

| | |
|---|---|
| Menus | **Accounting > Reporting > Income Tax Declaration (Form 30)** · **Accounting > Configuration > rs.ge Form 30 (Advanced)** (Accounting Administrators): Recipient Categories, Income Types, Account Rules, Withholding Taxes, Allowed Rates, Car Engine Bands, Service Types |
| Added to existing screens | Contact, **Sales & Purchase** tab: group **rs.ge Form 30** · Withholding tax: **Form 30 Income Type**, **Form 30 Service Type**, **Declare in Annex E** and the **RS Declaration Rules** tab with **Apply Tax / RS Change** · Posted manual journal entry: **Set Withholding Tax** and **Detect Again** · Accounting settings: **Pension Liability Accounts**, **Employer Pension Expense Accounts** · Vehicle, **Model** tab, **Engine** group: **rs.ge Engine Band** · Work location: **Form 30 Autonomous Republic** |
| Who uses it | Accounting Read-only: open declarations. Accounting Bookkeeper: create, generate, export, add car rows, edit category history. Contact Creation: edit category history. Accounting Administrator: the rs.ge tables, RS rules and **Apply Tax / RS Change**. Each user sees only the declarations of their own companies |
| Needs | Payroll with `geo_payroll`, the Georgian chart and taxes (`gec_localization`), Fleet |
| Works with | `gec_payroll_bank` (**Pay Salaries** writes the real payment date on the payslip) |

## 3. How it works

```text
Payslip, paid ─────────────────────────────────────► Annex A
Journal entry with a withholding tax, paid ──┬─────► Annex A
Vendor bill with a withholding tax, paid ────┤
                                             └─────► Annex E  (recipient pays own tax)
Booked but not paid ───────────────────────────────► Not Declared tab
Company cars used privately (you add the rows) ────► Annex D
Anything else (Add Manual Row) ────────────────────► Annex A

Annex A + annex D + journal items of the month ────► Main part, cells 16–69

Export rs.ge Files ──► one file per annex ──► upload on eservices.rs.ge
```

A declaration covers one company and one month. **No payment, no row:** a payslip, entry or
bill becomes a row only in the month its recipient was paid, dated on the payment (section 7).
**Generate Lines** reads everything paid in the month, as it is at that moment, and rebuilds
annex A, annex E and the main part. Nothing changes in the declaration when you pay something
later: press Generate Lines again. The portal computes the tax and pension itself; Odoo shows
its own figures only so you can compare.

```text
Draft ──Export rs.ge Files──► Exported ──Reset to Draft──► Draft
```

## 4. Set it up (once)

1. **Withholding taxes** (**Accounting > Configuration > Accounting > Taxes**, the tax,
   **RS Declaration Rules** tab):
   - **Form 30 Income Type**: filled at install on the Georgian withholding taxes. Set it
     yourself on any withholding tax you create. A withholding tax without it is not seen by
     Form 30 at all.
   - **Form 30 Service Type**: one of the 8 kinds rs.ge offers (rent, IT, transport, cleaning,
     construction, marketing, design, other). Needed only for recipients who pay their own tax
     (section 7); set it on the tax or on the contact.
2. **Account Rules** (**Accounting > Configuration > rs.ge Form 30 (Advanced) > Account Rules**):
   which accounts mark a journal entry as a withholding of each income type (section 6). Rules
   are installed for the Georgian chart; review them once with your own accounts.
3. **Pension accounts** (**Accounting > Configuration > Settings**): **Pension Liability
   Accounts** and **Employer Pension Expense Accounts**, used when a journal entry also books
   pension.
4. **Every contact you pay outside payroll** (**Contacts > Contacts**, the contact):
   - **Country** is the residency. **Tax ID** is the ID number: 11 digits for a person, 9 for a
     company, the foreign tax number for a foreign recipient.
   - **Sales & Purchase** tab, **rs.ge Form 30**: a row in the category history (section 5).
   - Tick **Individual Entrepreneur (ი/მ)** or **Small Business Status (მცირე მეწარმე)** for
     anyone who pays their own income tax.
   - **Tax Exempt Under International Agreement** only for a recipient exempt under a treaty
     (section 6).
5. **Employees**: **Identification No** on each employee (11 digits), and **Nationality
   (Country)** for foreigners. Optional but recommended: give each employee's work contact a
   category history row **1.1** with both dates empty. Without it every salary row still gets 1.1,
   but carries a warning.
6. **Work locations in Adjara or Abkhazia** (**Employees > Configuration > Employee > Work
   Locations**): set **Form 30 Autonomous Republic**. Leave it empty everywhere else. Feeds cells
   57¹ and 57².
7. **Cars that employees use privately** (**Fleet > Fleet > Fleet**, the car, **Model** tab):
   **rs.ge Engine Band**.
8. **Pay salaries** with **Pay Salaries** or **Register Payment** on the payslip, so the salary
   is matched with a payment. **Mark as Paid** without a payment dates the row on the payslip's
   paid date (often today) with a warning, which can put it in the wrong month.

Works without setup: the rs.ge tables and country codes, the income types of the Georgian
withholding taxes, the Account Rules of the Georgian chart, and salary rows (they default to
1.1 / Georgia with a warning).

## 5. Recipient category and residency

The **category** says who the recipient is for rs.ge. It lives in the contact's **Form 30
Category History**: one row per period with **Category**, **Valid From**, **Valid To**. Each row
of the declaration takes the category valid on its **payment date**.

| Rule | Why |
|---|---|
| Both dates are included; an empty Valid From means "always before", an empty Valid To means "still applies" | Leave Valid From empty for a category that always applied |
| Periods must not overlap | End the old period the day before the new one starts |
| A payment date no period covers gets no category and a warning, and blocks the export | A gap is never filled with a guess |
| Changing the history does not change rows already generated | Press Generate Lines again |

Example: a freelancer becomes an employee on 15 September.

| Category | Valid From | Valid To |
|---|---|---|
| 1.2.1 (20%, unregistered individual) | empty | 14.09.2026 |
| 1.1 (employee) | 15.09.2026 | empty |

A payment on 14 September is declared as 1.2.1, even when you regenerate in October.

**Current Form 30 Category** shows the category valid today. **Category Without History** appears
only on contacts that carry a single category from before the history: it is used for every date
until the first history row is added, and never after. So when you add history to such a contact,
also add a row for the old category.

**Which category?**

| Recipient | Category |
|---|---|
| Your employee (Georgian or foreign) | 1.1 |
| Resident individual paid for services, taxed 20% | 1.2.1 |
| Resident individual in the 5% regime, or renting you a flat | 1.2.2 |
| Resident individual receiving dividends, interest, royalties or a stipend | 1.4 |
| Resident company (dividends and interest) | 2 |
| Foreign company / foreign individual | 3.3 / 3.4 |
| Company / individual in a preferential tax country | 3.1 / 3.2 |

Category **4 "უცხო ქვეყნის მოქალაქეობის მქონე პირები"** is not for foreigners in general: on
rs.ge it is only for gambling payouts. A foreign employee is 1.1 with a foreign country.

**Residency** is the contact's **Country**; each country carries its rs.ge code (Georgia 268).
For salary rows Odoo takes the work contact's country, else the employee's **Nationality
(Country)**, else Georgia with a warning. For other rows there is no default. 16 countries have
no rs.ge code (for example Serbia, Kosovo, Sudan); a row with one of them cannot be exported. A
3.x category with Georgia, or a resident category with a foreign country, only warns.

## 6. Withholding taxes and income types

**The tax decides the income type and the rate. The contact decides the category.** rs.ge allows
only certain (category, income type, rate) combinations for each month; Odoo refuses any other.

| What you pay | Tax to use | Income type | Contact category |
|---|---|---|---|
| Dividends to a resident individual | WHT 5% - Resident Individual Dividends | 2 | 1.1 or 1.4 |
| Interest to a resident individual | WHT 5% - Resident Individual Interest | 3 | 1.1 or 1.4 |
| Royalties to a resident individual | WHT 20% - Resident Individual Royalties | 17 | 1.1 or 1.4 |
| Services from an unregistered individual | WHT 20% - Resident Individual Services (unregistered) | 7 | 1.2.1 |
| Services in the 5% regime | WHT 5% - Resident Individual Services (5% regime) | 7 | 1.2.2 |
| Rent of a flat from an individual | WHT 5% - Resident Individual Residential Rent | 19 | 1.2.2 |
| Stipend | WHT 20% - Stipend | 5 | 1.1 or 1.4 |
| Dividends / interest / royalties abroad | WHT 5% - Non-resident Dividends / Interest / Royalties | 2 / 3 / 17 | 3.3 or 3.4 |
| Management or technical services from abroad | WHT 10% - Non-resident Mgmt/Technical Fees | 7 | 3.3 or 3.4 |
| Rent to a foreign individual for property in Georgia | WHT 20% - Non-resident GE Property Rent | 19 | 3.4 |
| Royalties / interest / services to a preferential tax country | WHT 15% - Offshore Royalties / Interest / Services/Other | 17 / 3 / 7 | 3.1 or 3.2 |

The allowed combinations are under **Accounting > Configuration > rs.ge Form 30 (Advanced) >
Allowed Rates**, and per tax in its **RS Declaration Rules** tab. Never reuse a tax for another
kind of income because the rate matches: royalties paid with the services tax are declared as
services.

**Where the tax goes.** Odoo only reads the withholding tax; it never books the amounts for you.

| Document | Where the withholding tax goes | What you book |
|---|---|---|
| Journal entry (manual, Miscellaneous journal) | On the expense line. Odoo proposes it when you post (below) | The whole withholding by hand: expense, the person's payable, the tax on a withholding-tax account |
| Vendor bill | In the **Taxes** column of the bill line | Nothing else: the tax line is calculated |

On a bill each withholding tax comes in two versions: the plain one deducts the tax from the
person (price 1,000 at 20% → person 800, tax 200), and the **(company pays)** one adds it on top
(price 1,000 at 20% → person 1,000, tax 250, gross 1,250).

**The proposal on journal entries.** Each Account Rule names, for one income type, the
**Accrual Debit (C)** accounts (the expense), the **Accrual Credit (D)** accounts (the person's
payable) and the **Withholding Credit (F)** accounts (the tax, with no partner or the State
Treasury). When you post a manual entry that debits a C account, credits a D account and credits
an F account, Odoo looks for the one withholding tax that fits: same income type, valid on the
entry date, resident or non-resident like the person, and a rate rs.ge allows for the person's
category. Exactly one fits: it goes on the expense line. None or several: a yellow message says
"Form 30 will not declare …"; press **Set Withholding Tax** and choose it. After fixing a contact
or a rule, **Detect Again** reposts the entry and proposes again.

Example: dividend 5,000 to a 1.4 contact.

| Account | Partner | Debit | Credit |
|---|---|---|---|
| 530110 | | 5,000.00 | |
| 340120 | the shareholder | | 5,000.00 |
| 340120 | the shareholder | 250.00 | |
| 331210 | | | 250.00 |

The income type 2 rule (C 530110, D 340120, F 331210) matches, so Odoo puts **WHT 5% - Resident Individual
Dividends** on the 530110 line. When the shareholder is paid 4,750, the row is amount 5,000,
tax 250, rate 5.

One entry, one withholding tax, and recipients of one kind: an entry with two withholding taxes,
or with one person who pays their own tax and one who does not, gets a blocker. Split it.

**Treaty allowance.** **Tax Exempt Under International Agreement** on the contact is an amount of
tax. Each new row for that recipient draws its withheld tax from it, up to what is left, and
reports the draw in the column "Tax exempt or reduced under an international agreement". **Usage**
lists every draw with the balance before and after; **Exempted So Far** and **Still Exemptible**
show the totals. One allowance per person, shared by every company. The column is a disclosure:
it does not lower cell 57.

## 7. Annex A and annex E: where the rows come from

| Rows | Taken when | Left out |
|---|---|---|
| Salary | Validated or paid payslip whose net salary was paid in the month | Draft and canceled payslips, refunds, salary paid in another month |
| Journal entry | Posted manual entry with a withholding tax, one row per person whose payable line was paid in the month | Unpaid entries (listed under **Not Declared**), entries reversed before payment |
| Vendor bill | Posted bill or receipt with a withholding tax line, paid in the month; one row per withholding tax | Unpaid bills, bills created from employee expenses |
| Payment | A payment that carries a withholding line (Odoo's withholding at payment), paid in the month | Draft, canceled, rejected and incoming payments |
| Manual | You add it with **Add Manual Row** | Never touched by Generate Lines |

**The row date** is the day the money left, but never before the bill, entry or payslip itself (an advance counts in the document's month): the bank statement date when the payment is matched
with the bank, otherwise the payment date with a warning. **Part payments** are split by month:
an entry paid half in December and half in January gives two rows, each with half the amount and
half the tax. Money already in an exported file is never declared again (section 12).

**Annex E.** A row goes to annex E instead of annex A when the contact has **Individual
Entrepreneur** or **Small Business Status** ticked. A vendor bill also reaches annex E without
any withholding when a bill line carries a tax with **Declare in Annex E** ticked. Annex E has 7
columns: ID, name, surname, service type (from the tax, else the contact), amount, address,
residency.

**Not Declared** (a tab on the declaration, shown only when it has something) lists what Odoo
saw but could not declare:

| List | Means | What to do |
|---|---|---|
| Unpaid Entries | Entries with a withholding tax, and payslip entries, dated up to the end of the month and not paid by then | Normal if payment comes later; otherwise pay and regenerate |
| Entries Without a Payable Recipient | The person is on an account that is not a reconcilable payable, so Odoo cannot see the payment | Book the person on a payable account |
| Entries Missing a Withholding Tax | The entry credits a withholding-tax account but has no withholding tax | **Set Withholding Tax** on the entry |

Annex A has 14 columns. The grid shows two more, the employee pension and **Tax withheld at
source (GEL)**, for comparison only: they never leave Odoo.

| Column | Salary row | Entry, bill or payment row |
|---|---|---|
| ID number | Employee's **Identification No**; if empty, the work contact's **Tax ID** with a warning | Contact's **Tax ID**; spaces and a leading "GE" are removed |
| First name / legal form, Last name / company name | Employee's legal name, split after the first word | Person: split after the first word. Company: the legal form (შპს, სს, ი/მ, LLC, Ltd, JSC …) must be the first word. A contact whose **Tax ID** is a Georgian 11-digit personal number is a person |
| Address | Employee's private street and city | Contact's address on one line |
| Residency | Section 5 | Section 5 |
| Category | Work contact's history on the payment date; no history: 1.1 with a warning | Contact's history on the payment date; no default |
| Income type | 1 ხელფასი | The tax's **Form 30 Income Type** |
| Amount | Payslip GROSS + advance pay-outs on it | Entry: what the person was paid + the tax + the pension. Bill and payment: the withholding base. In GEL |
| Other relief | Employees with an income tax exemption: amount − pension − withheld tax ÷ 20% (Example C); others 0 | 0 |
| Payment date | The day the net salary was paid | The day the person was paid |
| Rate | 20 | The tax's percentage |
| Treaty exemption | From the treaty allowance (section 6) | From the treaty allowance |
| Foreign tax credit, Paid from Treasury | 0, empty | 0, empty |
| Tax withheld at source (not exported) | Income tax + tax prepaid on advances | The tax booked on the withholding-tax account, in GEL |
| Employee pension (not exported) | Employee pension + pension prepaid on advances | Entry: the pension booked on the pension accounts of the settings; otherwise 0 |

### Examples

**A. Employee, pension member, gross 1,000 paid on 5 March.** Payroll withheld pension 20 and
income tax 196; the employee received 784. Row: amount 1000, relief 0, 05.03.2026, rate 20;
control tax 196, control pension 20. The portal computes (1,000 − 20) × 20% = 196. A non-member
has no pension, tax 200 and the same row.

**B. Advance paid separately.** Advance 1,000 on 20 March, salary 2,000 on 5 April with the 1,000
repaid. March: a row of 1,000 (the advance is declared when paid). April: a row of 1,000, because
payroll's GROSS already has the repayment taken off. Total declared 2,000.

**C. Exempt employee (6,000 a year), first month.** Gross 4,390 + advance 10,000, pension member.
Payroll withheld pension 287.80 and income tax 1,644.44.

| Column | Value | How |
|---|---|---|
| Amount | 14,390.00 | 4,390 + 10,000 |
| Other relief | 5,880.00 | 14,390 − 287.80 − 1,644.44 ÷ 0.20 |
| Tax withheld at source | 1,644.44 | from payroll |

The portal computes (14,390 − 287.80 − 5,880) × 20% = 1,644.44, the tax that was withheld. The
relief is not the full 6,000 because payroll takes pension off the taxed part only, while the
portal takes the full 2% first.

**D. Dividend by journal entry.** See the example in section 6: paid 4,750, row amount 5,000,
tax 250, rate 5, income type 2, category 1.4 from the contact.

**E. Service bill from an unregistered person (category 1.2.1).** Bill line 1,000 with **WHT 20%
- Resident Individual Services (unregistered)**: the person gets 800, the tax is 200. Paid on
18 December: row amount 1,000, tax 200, rate 20, income type 7, dated 18.12. With the
**(company pays)** tax: the person gets 1,000, row amount 1,250, tax 250.

## 8. Annex D: company cars used privately

rs.ge charges a fixed monthly tax when an employee uses a company car privately. It depends only
on the engine:

| Band | Engine | Tax per month |
|---|---|---|
| 1 | over 3500 cm3 | 300 |
| 2 | 2500–3500 cm3 | 200 |
| 3 | under 2500 cm3 | 100 |
| 4 | hybrid | 60 |

Odoo cannot know who drove privately, so you add the rows: tab **3. Annex D**, **Add a Line**,
pick the vehicle. Plate, band and driver fill in from Fleet, then the name and personal number
from the employee; every field stays editable. The tax follows the band and cannot be typed.
Generate Lines never touches these rows. The file has 5 columns: plate, band number (1–4),
"Surname,Name", personal number, tax. The amounts per band are under **Car Engine Bands**.

Example: a car under 2500 cm3 used privately in March gives one row with band 3 and tax 100,
and adds 100 to cell 57.

## 9. Main part: cells 16–69

The tab **5. Main part** mirrors the portal's main part. There is no file for it: you copy the
numbers. Three kinds of cell:

| Icon | Cells | Who fills it | Refreshed |
|---|---|---|---|
| padlock | 16 to 57 (44 cells), locked on the portal | Odoo, from the annex rows | At every Generate Lines and Export; you cannot type |
| wand | 57¹, 57², 58, 59, 61, 63, 65 to 69 | Odoo proposes, you may overwrite | At every Generate Lines and Export, until you type your own value. Hover the wand to see the proposal; type it back to hand the cell to Odoo |
| none | 56¹, 60, 62, 64 | You | Never |

Two words used below: a row's **base** is amount − pension − other relief; its **tax** is
base × rate. **Organizations** are categories 2, 3.1, 3.3, 3.7 and 3.8; every other category is
a natural person.

| Cells | Source |
|---|---|
| 16, 17 | Salary rows: amount, base |
| 18 to 38 | Natural persons, by income type, rate and category; amount cells and base cells |
| 39 | Tax of every natural-person row, salary included |
| 40 to 55, 56 | The same for organizations; 56 is their tax |
| 56² | 12% of what you type in 56¹ |
| 57 | 39 + 56 + 56² + annex D tax − the foreign tax credit column |
| 57¹, 57² | Tax of salary rows whose work location is marked Adjara / Abkhazia |
| 58 | Income accounts: credit minus debit of posted items dated in the month |
| 59 | Ticked when a posted expense item exists in the month |
| 61, 65, 66 | Salary rows per person: number of persons, highest total, lowest total above 0 |
| 63 | Incoming payments received in cash journals in the month |
| 67 | Balance of the cash journals' accounts at month end |
| 68, 69 | Account 140311 at month end: sum of the persons who owe, and their number |

The question mark at the end of each row opens that cell alone: the formula in words, the stored
value, whether it is locked, proposed or typed, and every row or journal item that went into it,
with a link. A locked cell whose stored value differs from a fresh calculation shows in red: press
Generate Lines or Export.

Example: two salary rows (1,000 pension member, 2,000 non-member), one dividend of 5,000 at 5% to
a 1.4 contact, one band-3 car.

| Cell | Value | How |
|---|---|---|
| 16 | 3,000.00 | 1,000 + 2,000 |
| 17 | 2,980.00 | 980 + 2,000 |
| 22, 23 | 5,000.00 | dividend amount, base |
| 39 | 846.00 | 196 + 400 + 250 |
| 57 | 946.00 | 846 + 100 car tax |
| 61, 65, 66 | 2 · 2,000.00 · 1,000.00 | two persons |

**Confirm these assumptions with your accountant once**; they come from the rs.ge instruction,
not from a portal upload:

- 58 includes every income account, asset sales too.
- 63 counts customer payments in cash journals, not all cash debits, so internal transfers do
  not count.
- 68 reads only account 140311; advances on another account are not seen.
- Rent to a non-resident individual at 20% has no cell among 28–32, so it goes to 19.
- 18 is shown for information and not added into 39, since those royalties are already in 19.

## 10. Explanation Workbook

**Explanation Workbook** in the header downloads `form30_explained_YYYYMM.xlsx` and keeps a copy
on the form. Every category, income type and tax is named, not coded, and every row links to its
payslip or payment.

| Sheet | Shows |
|---|---|
| Read me | Declaration, month, what each sheet holds, the terms and the assumptions of section 9 |
| Annex A | Each row with base, the tax as the portal will compute it, the tax Odoo withheld, the difference, and the cells it feeds |
| Payslips | Salary rows from the payslip side: GROSS, advances, tax, pension, exemption, relief formula, and where the ID, category and residency came from |
| Payments | Payment rows: payment, bills, tax, base and withheld amount in both currencies, the history row that gave the category, and why the row went to annex A or E |
| Annex D, Annex E | The car and service-fee rows |
| Main part | Every cell with value, kind, status and formula |
| Cell details | Every contribution to every cell, with its arithmetic |

It shows the stored values; download it again after the last Generate Lines. An accountant
without Payroll access still gets the Payslips sheet.

## 11. Changing a tax rate or an RS rule

On a withholding tax, the **RS Declaration Rules** tab shows the allowed categories, rates and
periods of its income type. These rules are shared by every company and every tax with that
income type. Editing the tax's percentage alone never changes them. When the law changes, an
Accounting Administrator presses **Apply Tax / RS Change**:

| Choice | Result |
|---|---|
| Tax percentage and RS rules | A replacement tax from the effective month, and the old rate replaced by the new one for the selected categories |
| Tax percentage only | A replacement tax; the RS rules stay, so the new rate must already be allowed |
| RS rules only | **Replace an allowed rate**, **Allow a rate for categories** or **Stop allowing a rate for categories**; no tax changes |

1. **Effective Month**: the first day of the month.
2. **New Rate (%)** and **Affected Categories** (proposed from the old rate).
3. **Replacement Tax Name** for a tax change.
4. Read **Review the change**, then **Apply Change**.

Example: WHT 5% - Resident Individual Dividends becomes 10% from 1 October 2026. A combined change
keeps the 5% tax for payments up to 30 September, creates "WHT 5% - Resident Individual Dividends
(10%, from 2026-10)" at 10%, ends the selected 5% rules at 2026-09 and allows 10% from 2026-10.
Earlier payments are not touched.

Afterwards select the new tax on payments yourself: products, fiscal positions and draft payments
are not switched. A payment whose tax is used outside its validity dates gets a row with the version
valid on its date and a warning, or a blocked row when no version is valid.
Salary tax is not affected: it comes from the payroll rules.

## 12. Step by step: the month

1. **Accounting > Reporting > Income Tax Declaration (Form 30)**, **New**. Odoo proposes last
   month. Save.
2. **Generate Lines.** A row that breaks an rs.ge rule is still made, with a blocker that says why;
   it never goes into the file (section 13). Fix the contact or the tax and generate again.
3. **Review annex A.** Rows with a problem carry a warning or a blocker: hover the triangle at the
   start of the row to read it. The open icon next to it opens the row's payslip, entry, bill or
   payment. Fix the source, then Generate Lines again: automatic rows cannot be edited.
4. **Not Declared**, if the tab shows: check each listed entry (section 7).
5. **Annex D**, if a company car was used privately: **Add a Line** per car. **Add Manual Row**
   for a payment Odoo cannot see.
6. **Main part.** Check the wand cells, type 60, 62, 64 (and 56¹ in the rare case of salaries
   accrued before 2008).
7. **Rows with warnings** are left out of the files and the main part (**Rows Left Out** in the
   header counts them). Once you have checked them, tick **Export rows with warnings** to include
   them. Rows with a blocker are never included.
8. **Export rs.ge Files.** Odoo checks every included row; if something is missing it lists the
   problems and exports nothing. Otherwise `form30_a_YYYYMM.xml`, `form30_d_YYYYMM.xml` and
   `form30_e_YYYYMM.xml` appear on the form (only for annexes with rows), the rows in them are
   marked **In File**, and the state becomes **Exported**.
9. On eservices.rs.ge upload each file in its annex (annex A on page 2, D on page 3, E on page 4)
   and copy the main part onto page 5.
10. Compare the portal's tax and pension with **Total Withheld Tax** and **Total Pension 2%**, and
    its cell 57 with Odoo's. When a number differs, the Explanation Workbook shows which rows made
    it.
11. Submit on the portal by the 15th.

**In File rows.** A row that went into an exported file is kept as it is: Generate Lines does not
delete it, and money already in a file is not declared again, in this month or another. If its
source changes after the export (payment cancelled, entry reversed), the row gets the blocker
"Filed, but its payment or source changed after the export".

To correct a filed month: **Reset to Draft**, fix the source, **Clear In File Marks** so the
filed rows can be rebuilt, Generate Lines, Export, and upload the whole annex again. Check on the
portal that the earlier rows were replaced and not added to.

The annex A grid shows 100 rows per page. Its filter row and footer totals apply to the current
page only; the totals in the form header cover the whole declaration. **Clear Filters** removes
the filters, **Fit Columns** resets the column widths.

## 13. When Odoo warns or refuses

Each row problem has a level. A **blocker** keeps the row out of the file for good. A
**warning** keeps it out until you tick **Export rows with warnings**. A **note** only informs.

| Message | Why | What to do |
|---|---|---|
| Several withholding taxes in one entry: split it per tax. | One journal entry carries two withholding taxes | Split the entry. Blocker |
| Recipients of different status in one entry (own tax and withheld): split the entry. | One person pays their own tax, another does not | Split the entry. Blocker |
| Set a Form 30 service type on the Withholding Tax or on the contact. | Annex E row without a service type | Set it, regenerate. Blocker |
| Payment not matched with a bank transaction yet: dated on the payment date. | The payment is not yet matched with the bank statement | Match it, regenerate, so the row takes the bank date |
| Settled by an offset entry: declare it in this month unless the advance was already taxed, and keep the signed offset act. | The amount was closed by an offset journal entry, not by money | Check the signed offset act; if the advance was already taxed, leave the row out, else export it |
| Paid in advance, before the document: declared in the document's month unless the advance was already taxed. | The money left before the bill, entry or payslip existed | If the advance was already declared when paid, leave the row out, else export it |
| The booked tax differs from the Withholding Tax rate on net + tax. | The entry's tax amount is not the tax's rate of (paid + tax) | Correct the entry |
| Late: the tax was due with the payment on … and is not paid yet. | The person was paid but the tax is still open (note) | Pay the tax to the State Treasury |
| Also withheld at payment: check for a double declaration. | The entry is withheld twice: on the entry and at payment | Remove one |
| Reversed after payment: correct the declaration. | The entry or bill was reversed after it was paid | Correct the declaration |
| A manual row exists for this recipient and income type: check for a double declaration. | A manual row and an automatic row look alike | Delete the manual row if it duplicates |
| Employee ID taken from the work contact Tax ID, verify it. | The employee has no Identification No | Fill Identification No, regenerate |
| Relief derived from the withheld tax, verify on the portal. | The employee has an income tax exemption (Example C) | Compare the portal's tax with the control tax after upload |
| Category/residency defaulted to 1.1/Georgia, confirm on the employee contact. | The work contact has no category history, or neither the contact nor the employee has a country | Fine for Georgian employees; otherwise add the history row or the country |
| No Form 30 category covers the payment date; update the partner's category history. | A gap in the history | Extend a period, regenerate. Blocks the export |
| Set the Form 30 category and residency on the partner. | A payment contact without category or country | Fill them, regenerate. Blocks the export |
| Residency and category disagree: … | 3.x with Georgia, or 1.x / 2 with a foreign country | Check the contact |
| No payment matched, date taken from the payslip. | The payslip was marked paid without a payment | Check its paid date |
| Payslip lines were edited manually. | Someone changed the payslip lines by hand | Check amount, tax and relief |
| Tax … has no Form 30 income type. | The tax is not mapped | Set Form 30 Income Type, regenerate. Blocks the export |
| Tax … is not a percentage, set the rate manually. | A fixed-amount withholding tax | Use a percentage tax on the payment |
| Payment has no journal entry, the withholding is not booked. | The payment method creates no entry | Ask the bookkeeper |
| Legal form not detected in the company name. | The company name does not start with a legal form | Rename, for example "შპს ალფა", regenerate |
| The rs.ge classifier does not allow this category, income type and rate for the month. | The category, income type or rate is not in the rs.ge table for that month | Fix the contact's category or the tax, regenerate. The row is never exported |
| No version of … is valid for Form 30 on the payment date. | The tax was replaced and no version covers the date (section 11) | Select the tax valid on that date, regenerate. The row is never exported |
| Booked with an old tax version: this row uses …, valid on the payment date. | The payment uses a replaced tax (section 11) | The row already uses the valid version; check it |

**Refusals.**

| Message starts with | When | What to do |
|---|---|---|
| One declaration per company and month. | Saving a second declaration | Open the existing one |
| The declaration month must start on the first day of the month. | Saving | Set the 1st |
| You cannot change the company of a declaration that has lines. | Saving | Create a declaration for the other company |
| Reset the declaration to draft before regenerating it. | Generate Lines on an exported declaration | **Reset to Draft** |
| These lines are not allowed by the rs.ge classifier for the declaration period: | Saving a manual row, or changing the month of a declaration with manual rows | Each line says why: "… is not valid for this period" (an abolished category or income type), "category/income type combination not allowed", "rate N not allowed (allowed: …)". Fix the category, income type or rate of the row |
| There is nothing to export. | Export | Generate first, or add a car row |
| Nothing selected for the file: every row has a blocker or a warning. | Export | Fix the rows, or tick **Export rows with warnings** |
| … has a withholding tax but is not balanced: Odoo added an Automatic Balancing Line … | Posting a journal entry | Add the missing person or State Treasury line, then post |
| Set Withholding Tax works on posted manual journal entries only … | **Set Withholding Tax** or **Detect Again** on a payment, bank or payroll entry | Use it on a manual entry only |
| These entries are in the file of a Form 30 declaration: … | **Set Withholding Tax** or **Detect Again** on a filed entry | **Reset to Draft** the declaration first |
| Reset the declaration to draft before adding a manual row. | **Add Manual Row** on an exported declaration | **Reset to Draft** |
| Fix these lines before exporting: | Export, annex A | "missing ID number / residency / category / income type / date", "… has no rs.ge country code", "a Georgian ID number must have 9 or 11 digits", "date outside the declaration month", "amount must be positive". Fix the source, regenerate |
| Fix these annex D rows before exporting: | Export | Fill plate, "Surname, Name" and a 9- or 11-digit personal number |
| Fix these annex E rows before exporting: | Export | Usually the **Form 30 Service Type** on the tax; or the contact's Tax ID or country |
| Form 30 category periods must not overlap for … | Saving a contact | End the previous period before the next one starts |
| Only accounting managers can apply Tax / RS changes. | **Apply Tax / RS Change** | Ask an Accounting Administrator |
| … needs a …% rule starting before and covering the effective month. | **Apply Change** | The old rate is not allowed for that category in that month; check the RS rules |
| An overlapping future rule exists for … | **Apply Change** | A future rule already covers part of the period; review it first |

## 14. Rules to remember

- **No payment, no row.** A row belongs to the month the money was paid. An August salary paid on
  3 September is a September row; an entry booked in March and paid in May is a May row.
- **Generate Lines rebuilds the automatic rows.** Manual and In File rows stay. Fix the payslip,
  entry, bill, contact or tax, never the row.
- **Rows are snapshots.** A changed category, country or tax reaches the declaration only at the
  next Generate Lines.
- **One bad row does not stop the month.** It is made with a blocker that names the problem and
  never goes into the file, so nothing is missed silently.
- **The old file stays on a draft.** After Reset to Draft the previous export stays visible until
  you export again. Do not upload it.
- **One withholding tax per journal entry.** Split an entry that pays two kinds of income.

## 15. Common questions

**The declaration is empty.** Rows follow the day the money was paid, not the payslip period or
the entry date, and New proposes last month. August payslips paid on 5 September belong to the
September declaration.

**An entry I booked is missing.** Look at the **Not Declared** tab: it is either not paid yet, its
person is not on a payable account, or it has no withholding tax.

**The portal shows 16 columns, our file has 14.** The portal computes pension and tax itself; they
are not part of the import file.

**Can I prepare a past month?** Yes. The rs.ge rules of that month apply, and each row takes the
category valid on its payment date.

**A payslip was refunded and recomputed.** Refunds are never declared. If the month was filed,
correct it as an amendment; otherwise regenerate once the new payslip is paid.

**Why does a row's tax differ from the portal's?** A few tetri of rounding is normal. A larger gap
comes from an exempt employee (Example C) or from the portal's own pension membership data.

**Two companies in one database?** Each company has its own declaration per month.

## 16. Known limitations

| Limitation | Workaround |
|---|---|
| Automatic rows cannot be edited | Fix the source record, or use **Add Manual Row** |
| A journal entry to an ი/მ without a withholding tax does not reach annex E | Book it as a vendor bill with a **Declare in Annex E** tax, or add a manual row |
| A reversed entry whose person was paid only from the bank statement is not declared | Odoo warns; add a manual row |
| Salary rows always use rate 20 | Other salary rates need manual rows |
| The foreign tax credit and Paid from Treasury columns are always 0 and empty | Change them on the portal |
| No file for the main part or page 1 | Copy them on the portal |
| The explanation page, the workbook and the work-location field are in English on the Georgian screen | — |
| The main part has not yet been compared with a portal-computed declaration | Compare cell 57 with the portal before submitting |

## 17. Glossary

| Term | Meaning |
|---|---|
| შემოსავლის მიმღებ პირთა კატეგორია | Recipient category: **Form 30 Category History** on the contact |
| განაცემის სახე | Income type: **Form 30 Income Type** on the withholding tax |
| პირის რეზიდენტობა | Residency: the contact's **Country** |
| სხვა შეღავათები | **Other relief** on the row |
| Base | Amount − pension − other relief; the portal taxes it at the row's rate |
| Organization | Categories 2, 3.1, 3.3, 3.7, 3.8; they feed cells 40–56 |
| Proposed cell | A main-part cell you type on the portal but Odoo fills from its records (wand icon) |
| Treaty allowance | **Tax Exempt Under International Agreement** on the contact |

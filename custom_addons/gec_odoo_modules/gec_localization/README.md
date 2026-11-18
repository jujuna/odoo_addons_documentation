# Georgia - Accounting Extensions (`gec_localization`)

Adds what Odoo's own Georgian accounting does not ship: withholding, turnover and profit taxes,
a few extra accounts, payroll account settings, default taxes per contact, one-click profit
distribution with CIT, and bank name and BIC filled from a Georgian IBAN.

**Who this is for:** accountants, finance managers and the admin who sets up a Georgian company.
Developers: [README_DEV.md](README_DEV.md). Odoo's Georgian chart, VAT Report and the reasons
behind each choice: [documentations/l10n_ge.md](../../../documentations/l10n_ge.md).

---

## 1. What it does

| Feature | What it gives you |
|---|---|
| 14 extra accounts | Foreign-currency cash, acquiring, conversion, accountable persons, loans issued, input VAT on fixed assets and other daily postings that Odoo's Georgian chart has no account for |
| 32 extra taxes | 23 withholding taxes, small business turnover 1% and 3%, CIT 15%, out of scope, VAT exempt and non-deductible purchases, 18% fixed assets, reverse charge III-19. Odoo's Georgian taxes cover VAT only |
| Payroll account settings and Treasury Code | Salaries, pension and income tax post on accounts that Pay Salaries can pay; the State Treasury is paid by its treasury code |
| Withholding certificate numbers | Each company numbers its own certificates: WHT/2026/00001, WHT/2026/00002 ... |
| Default taxes per contact | A non-VAT vendor or an exempt customer gets the right tax on every line without editing each one |
| Not Taxed products | Deposits, penalties and pass-through costs get no tax proposed |
| Profit Distribution (CIT) | One posted entry for a dividend: gross-up, 15% CIT and dividend withholding |
| Bank name and BIC from the IBAN | Type a Georgian IBAN; bank name and BIC fill in when you save |
| Contact Categories | Your own classification of contacts, separate from Tags; contacts of a company take its categories |
| Person or company from the Tax ID | A contact whose Tax ID is a Georgian 11-digit personal number is a person, not a company ([section 14](#14-rules-to-remember)) |

Not in this module:

| Need | Where |
|---|---|
| VAT declaration | Odoo's **VAT Report**: **Accounting > Reporting > Taxes & Fiscal > Tax Report**, choose VAT Report |
| Salaries, income tax and pension on payslips | GEO Payroll |
| Paying salaries, pension and income tax through the bank | Payroll Bank Channels (**Pay Salaries**) |
| rs.ge Form 30, the withholding declaration | Georgia - Income Tax Declaration (rs.ge Form 30) |

---

## 2. Quick facts

| Item | Value |
|---|---|
| Menus | **Accounting > Accounting > Profit Distribution (CIT)** (Accounting Administrators) · **Contacts > Contact Categories** (every internal user) |
| Added to the contact form | **Contact Categories** after Tags · **Default Sales Tax** and **Default Purchase Tax** on the **Sales & Purchase** tab, after Fiscal Position · **Treasury Code** on the **Invoicing** tab (**Accounting** with the Accounting app), on every contact without a parent company |
| Added to the product form | **Not Taxed**, just before Sales Taxes |
| Added to the contact list | A **Contact Categories** side panel in list and kanban view |
| Installs with it | Georgia - Accounting (Odoo's Georgian chart and VAT Report), Contacts, Withholding Tax, Sales, Purchase |
| Works with | GEO Payroll, Payroll Bank Channels, Basis / BOG / TBC Bank Integration, the Form 30 declaration, Waybill - Revenue Service (Georgia) |
| New access groups | None |

---

## 3. How it works

```text
Company country = Georgia
        │
        ▼
Fiscal Localization = Georgian Chart of Accounts (IFRS)
        │
        ▼
Odoo's accounts and VAT taxes  +  this module's accounts, taxes, settings
        │
        ├──► Orders, invoices, bills: tax from product or contact default
        ├──► Bill payments: withholding taken, certificate numbered
        ├──► Payslips: salary, pension and income tax on payable accounts
        └──► Dividends: Profit Distribution (CIT) posts one entry
```

Choosing the Georgian chart loads Odoo's accounts and taxes and this module's records in one
step. After that the module works inside screens you already use: the tax proposed on a line,
the **Pay** dialog, the payslip entry. Posted documents are never changed.

---

## 4. Set it up (once)

1. **Settings > Users & Companies > Companies**: set the company's country to **Georgia**.
2. **Accounting > Configuration > Settings**, **Fiscal Localization**: choose **Georgian Chart of
   Accounts (IFRS)**. Odoo's chart and taxes load, and this module's accounts, taxes and
   certificate counter load with them.
3. If the company already had the Georgian chart when this module was installed, the install
   adds the accounts and taxes to it. Then open account **331310** and switch off **Payment
   Reconciliation** (why: [section 6](#6-payroll-account-settings)).
4. With payroll: open the contact **სახელმწიფო ხაზინა** (State Treasury) and check that its
   **Treasury Code** is **101001000**. GEO Payroll fills it when it creates that contact.
5. With the Form 30 declaration: set **Form 30 Income Type** on the five withholding taxes
   marked "no" in [section 7](#withholding-taken-at-payment).
6. With Waybill - Revenue Service (Georgia): set **RS.GE Waybill VAT Type** on Odoo's 0% export
   and exempt taxes (**Zero-rated — exempt with credit (Art 172)** or **Exempt — without credit
   (Arts 170–171)**). Every tax starts as **Standard (18%)**.

Works without setup: default taxes per contact, Not Taxed, bank name and BIC, Contact
Categories, Profit Distribution (CIT).

---

## 5. Accounts this module adds

| Code | Name | ქართული | Type | Under |
|---|---|---|---|---|
| 110120 | Cash in Foreign Currency | ნაღდი ფული უცხოურ ვალუტაში | Bank and Cash | 110000 Cash on Hand |
| 120300 | Amounts Receivable via Acquiring | ექვაირინგით მისაღები თანხები | Bank and Cash | 120000 Cash in Bank Accounts |
| 120980 | Conversion | კონვერტაცია | Bank and Cash | 120000 Cash in Bank Accounts |
| 140311 | Settlements with Accountable Persons | ანგარიშსწორება ანგარიშვალდებულ პირებთან | Receivable | 140310 Receivables from Employees |
| 140810 | Receivables from Loans Issued | მოთხოვნები გაცემულ სესხებზე | Receivable | 140000 Accounts Receivable |
| 160310 | Computer Assembly | კომპიუტერის აწყობა | Current Assets | 160000 Inventory |
| 160910 | Additional Expenses | დამატებითი ხარჯები | Current Assets | 160000 Inventory |
| 310250 | Gift Card | სასაჩუქრე ბარათი | Payable | 310000 Short-Term Liabilities |
| 331320 | Employee Personal Income Tax (PIT) Transit | საშემოსავლო გადასახადის ტრანზიტული ანგარიში | Payable, non-trade | 330000 Tax and Government Liabilities |
| 334011 | Input VAT Local Purchases - Fixed Assets | ჩასათვლელი დღგ — ძირითადი საშუალებები | Current Assets | 330000 Tax and Government Liabilities |
| 710500 | Purchased Goods Returns | შეძენილი საქონლის დაბრუნება | Cost of Revenue | 710000 Cost of Goods Sold |
| 710700 | Direct Services & Subcontractors | პირდაპირი მომსახურება / ქვეკონტრაქტორები | Cost of Revenue | 710000 Cost of Goods Sold |
| 731000 | Freight-out & Logistics Services | მიწოდების ტრანსპორტი და ლოჯისტიკა | Expenses | 730000 Sales & Marketing Expenses |
| 740430 | Security & Guarding Services | დაცვის მომსახურება | Expenses | 740000 General & Administrative Expenses |

Receivable and Payable accounts allow reconciliation. Rental income has no account of its own
here: use Odoo's **651010 Rental Income**.

---

## 6. Payroll account settings

GEO Payroll posts salaries on Odoo's accounts, and **Pay Salaries** can pay a line only if its
account allows it. So three of Odoo's accounts are set differently, and one account is new.
A fourth Odoo account, 331211, is set differently for paying withheld tax to the State Treasury:

| Account | Odoo's setting | This module | Why |
|---|---|---|---|
| 310310 Salaries Payable | Current Liabilities, reconcilable | **Payable**, reconcilable | The accountant's choice: salaries owed show per employee |
| 332010 Pension Contribution Accrued | Current Liabilities, not reconcilable | **Payable, reconcilable** | Pay Salaries pays the Pension Agency only from Payable, reconcilable lines |
| 331320 PIT Transit (new) | none | **Payable, reconcilable, non-trade** | Payroll income tax posts here, and Pay Salaries pays it to the State Treasury in the same run as the salaries |
| 331310 Employee Personal Income Tax (PIT) Accrued | Current Liabilities, reconcilable | **not reconcilable** | Only the two salary withholding taxes post here. While it is reconcilable, Pay Salaries refuses a payslip with income tax on 331310; not reconcilable, it only warns |
| 331211 Withholding Tax (WHT) Settled | Expense | **Payable, reconcilable, non-trade** | The accountant moves withheld tax here from 331210 with the State Treasury as partner, then pays it with **Pay** on the entry line |

Payroll income tax has its own account because 331310 cannot become Payable: the two salary
withholding taxes post there, and a tax cannot post to a Payable account. GEO Payroll posts both pension shares
on 332010 and salary advances on 150310 Payroll Advances, 332011 and 331311.

**Treasury Code** (contact, **Invoicing** or **Accounting** tab, every contact without a parent
company): a budget recipient such as the State Treasury is paid by this code instead of a bank
account, and the bank sends a treasury transfer. The single code for taxes is **101001000**.

---

## 7. Taxes this module adds

Odoo's own Georgian taxes cover VAT 18% / 12% / 5% / 0%, exports, exemptions, imports and
reverse charge for VAT payers. The taxes below sit next to them. Fiscal positions never replace
them, except 18% Fixed Assets, which follows "Georgia (VAT Registered)" like Odoo's 18%: choose
them on the product, as a contact default, or by hand. Withholding, turnover and
CIT amounts stay out of the VAT closing entry.

### VAT and scope

| Tax | Rate | Where the tax goes | Use it for |
|---|---:|---|---|
| Out of Scope (Sale) | 0% | nothing is posted | A sale that is not a supply for VAT |
| Out of Scope (Purchase) | 0% | nothing is posted | A purchase that is not a supply for VAT |
| VAT Exempt (Purchase) | 0% | nothing is posted | A vendor that is not VAT registered |
| VAT 18% Non-Deductible (Purchase) | 18% | into the cost of the line | VAT you pay but cannot deduct |
| 18% Fixed Assets | 18% | deductible VAT on 334011 Input VAT Local Purchases - Fixed Assets | A purchase of fixed assets with deductible VAT. Reaches the VAT Report like the standard 18% purchase (tags 24(B), 24(T)) |
| Reverse Charge 18% Non-Deductible (III-19) | 18% | into the cost, and owed on 333060 Reverse Charge VAT Payable | A buyer that is not VAT registered: VAT is due, nothing is deducted. Reaches the VAT Report, Annex A Part II, line 1 |

Examples, bill line 1,000.00:

| Tax | Cost of the line | Owed to the vendor | 333060 |
|---|---:|---:|---:|
| VAT 18% Non-Deductible (Purchase) | 1,180.00 | 1,180.00 | |
| Reverse Charge 18% Non-Deductible (III-19) | 1,180.00 | 1,000.00 | 180.00 |

### Turnover and profit tax

| Tax | Rate | Posts to | Notes |
|---|---:|---|---|
| Small Business 1% Turnover (Sale) | 1% | 339090 Other Tax Liabilities | Included in the price |
| Small Business 3% Turnover (over GEL 500,000) | 3% | 339090 Other Tax Liabilities | Included in the price |
| CIT 15% - Distributed Profit (gross-up ÷0.85) | 15% | Dr 910010 Corporate Income Tax, Cr 331110 Corporate Income Taxes | Journal entries only; the entry total does not change |

Examples: a sale at 1,000.00 with the 1% tax → revenue 990.00, tax 10.00; with the 3% tax →
revenue 970.00, tax 30.00. CIT on a journal item of 85.00 → 15.00 debit on 910010 and 15.00
credit on 331110.

### Withholding (taken at payment)

"Form 30" says whether the Form 30 declaration module fills **Form 30 Income Type** on the
tax; set it yourself where it says "no".

Non-residents, post to **331212 Withholding Tax (WHT) Transition Account**:

| Tax | Form 30 |
|---|---|
| WHT 5% - Non-resident Dividends | yes |
| WHT 5% - Non-resident Interest | yes |
| WHT 5% - Non-resident Royalties | yes |
| WHT 10% - Non-resident Mgmt/Technical Fees | yes |
| WHT 20% - Non-resident GE Property Rent | yes |
| WHT 15% - Offshore Royalties | yes |
| WHT 15% - Offshore Interest | yes |
| WHT 15% - Offshore Services/Other | yes |
| WHT 10% - Non-resident Other GE-source Income | no |
| WHT 10% - Non-resident Int'l Telecom/Transport | no |
| WHT 4% - Non-resident Oil & Gas Subcontractor | no |

Resident individuals, post to **331210 Withholding Tax (WHT) Accrued**:

| Tax | Form 30 |
|---|---|
| WHT 5% - Resident Individual Dividends | yes |
| WHT 5% - Resident Individual Interest | yes |
| WHT 5% - Resident Individual Residential Rent | yes |
| WHT 5% - Resident Individual Services (5% regime) | yes |
| WHT 20% - Resident Individual Royalties | yes |
| WHT 20% - Resident Individual Services (unregistered) | yes |
| WHT 20% - Resident Individual Commercial Rent | yes |
| WHT 20% - Stipend | yes |
| WHT 20% - Gift to Individual (>GEL 1,000/yr) | no |
| WHT 3% - Goods from Individual without Waybill | no |

Salaries, post to **331310 Employee Personal Income Tax (PIT) Accrued**:

| Tax | Form 30 |
|---|---|
| WHT 20% - Salary (PIT) | yes |
| WHT 20% - Non-resident Employment Income | yes |

---

## 8. Withholding at payment

Nothing is withheld on the bill; the tax is taken when you pay.

1. Post the vendor bill with the withholding tax on the line (from the product, the contact's
   **Default Purchase Tax**, or by hand). The bill total does not change; under it the bill
   shows **Withhold Due** and **Net Due**.
2. Click **Pay**. The dialog opens on **Withhold and Pay**.
3. Open the **Withholdings** tab and check tax, base and amount. All three can be changed.
4. Click **Create Payment**. The withholding line gets the company's next certificate number.

Example: bill 1,000.00 with **WHT 10% - Non-resident Mgmt/Technical Fees**:

| Account | Debit | Credit |
|---|---:|---:|
| Vendor payable | 1,000.00 | |
| Bank | | 900.00 |
| 331212 Withholding Tax (WHT) Transition Account | | 100.00 |

The payment also carries a **WH Base** / **WH Base Counterpart** pair of 1,000.00 each, on the
**Withholding Tax Base** account from **Accounting > Configuration > Settings** (or on the bill
line's account when that setting is empty). The pair nets to zero.

The other two choices in the dialog: **Withhold Only** posts the withholding without paying;
**Payment Only** pays without withholding. When you pay several bills at once, tick **Group
Payments**, or the **Withholdings** tab does not appear.

---

## 9. Default taxes per contact and Not Taxed products

**Default Sales Tax** and **Default Purchase Tax** (contact, **Sales & Purchase** tab, per
company) replace the product's taxes on quotations, sales orders, purchase orders, customer
invoices and vendor bills for that contact. **Not Taxed** (product) proposes no tax at all.

The rule, for each line with a product:

1. The product is **Not Taxed** → no tax. One can still be added by hand.
2. The contact (or its company) has a default tax for this direction → that tax replaces the
   product's taxes; the fiscal position still applies to it; withholding taxes on the product
   stay.
3. Otherwise Odoo's usual taxes (product, then fiscal position).

| Product taxes | Contact default | Fiscal position | Line gets |
|---|---|---|---|
| 18% (sale) | none | none | 18% |
| 18% (sale) | 0% Export | none | 0% Export |
| 18% (sale) | 18% | Non-Georgia | 0% Export: the position still maps it |
| none | 18% (sale) | none | 18% |
| 18% + WHT 20% - Resident Individual Services (unregistered) | VAT Exempt (Purchase) | none | VAT Exempt (Purchase) + the WHT 20% |
| anything, product Not Taxed | anything | anything | no tax |

A contact with country Georgia always gets one of Odoo's Georgian fiscal positions, and the
fiscal position still applies to a contact default. With this module a default **18%** stays
18% for Georgian customers with or without a Tax ID; for a foreign vendor, Odoo's Non-Georgia
position removes a purchase 18%, so give vendors of services from abroad **Default Purchase
Tax** = **18% Reverse Charge Services** (one reverse-charge tax). This module's own taxes (VAT Exempt, Out of
Scope, withholding ...) pass every fiscal position unchanged.

- A vendor that is not VAT registered: **Default Purchase Tax** = **VAT Exempt (Purchase)**.
- Contacts of a company take the company's values and cannot keep their own.
- **VAT Payer** (contact, shown next to Individual Entrepreneur / Small Business Status when
  Form 30 is installed): ticked, a withholding tax or "no withholding" label as **Default
  Purchase Tax** is added next to the product's 18% instead of replacing it. The contact needs
  a Tax ID, or Odoo's non-VAT fiscal position removes the 18% first. Bills pulled from rs.ge set
  their own taxes (only the 18%): add the label on those lines by hand; Form 30 warns when it is missing.
- **Default Sales Tax** offers no withholding taxes; **Default Purchase Tax** does, and a
  withholding tax chosen there replaces the product's VAT, unless the contact is a VAT Payer.
- Use **Not Taxed** only for things that are not a supply (deposits, penalties, pass-through
  costs). Never use it for exempt or zero-rated goods: a line without tax never reaches the VAT
  Report; those need Odoo's 0% exempt or 0% Export taxes.

---

## 10. Profit Distribution (CIT)

**Accounting > Accounting > Profit Distribution (CIT)** turns a net dividend into one posted
entry.

| Field | What to enter |
|---|---|
| Journal | A Miscellaneous journal of the company |
| Date, Shareholder | Entry date; the shareholder goes on the distribution and payable lines, the State Treasury on the CIT and withholding lines; both are required |
| Net Distribution | What the shareholder is due before dividend withholding |
| Withhold Dividend Tax (5%), Dividend WHT %, Dividend WHT Account (Cr) | Tick for an individual or a non-resident shareholder; the rate starts at 5. Leave it off for a resident company. The account starts at 331210: pay the tax to the State Treasury by a bank entry and match it with this account (accountant, 2026-11-12) |
| Distribution Account (Dr) | Usually 530110 Retained Earnings |
| CIT Payable Account (Cr) | Usually 331110 Corporate Income Taxes |
| Shareholder Payable Account (Cr) | Usually 340120 Accrued Dividends Payable |

```text
Gross = Net ÷ 0.85            CIT 15% = Gross − Net
Dividend WHT = Net × rate     Shareholder = Net − Dividend WHT
```

**Post Distribution** posts the entry at once and opens it. Example, net 850.00 to a resident
individual with 5% withholding on 331210 (331212 for a non-resident):

| Account | Debit | Credit |
|---|---:|---:|
| 530110 Retained Earnings | 1,000.00 | |
| 331110 Corporate Income Taxes | | 150.00 |
| 331210 Withholding Tax (WHT) Accrued | | 42.50 |
| 340120 Accrued Dividends Payable | | 807.50 |

Net 1,000.00 with the same settings → gross 1,176.47, CIT 176.47, withholding 50.00,
shareholder 950.00. Amounts are rounded to the tetri.

---

## 11. Bank name and BIC from a Georgian IBAN

Type the IBAN in **Account Number** and leave **Bank Name** and **BIC/SWIFT** empty. After
saving, both are filled from the two letters after the check digits (GE29 **TB** 0000...).
A value you type in the same save wins. Changing an IBAN to another Georgian bank replaces both,
unless you type them in that save. Basis, BOG and TBC Bank Integration recognise a journal's
bank by this BIC.

| IBAN code | Bank | BIC |
|---|---|---|
| BG | Bank of Georgia | BAGAGE22 |
| BS | BasisBank | CBASGE22 |
| BT | Silk Bank | DISNGE22 |
| CR | Cartu Bank | CRTUGE22 |
| HB | Halyk Bank Georgia | HABGGE22 |
| KS | Terabank | TEBAGE22 |
| LB | Liberty Bank | LBRTGE22 |
| PC | ProCredit Bank | MIBGGE22 |
| TB | TBC Bank | TBCBGE22 |
| VT | VTB Bank Georgia | UGEBGE22 |
| ZB | Ziraat Bank Georgia | TCZBGE22 |
| PB | Pasha Bank Georgia | PAHAGE22 |
| IS | Isbank Georgia | ISBKGE22 |
| CD | Credo Bank | JSCRGE22 |
| PS | Paysera Bank Georgia | PSRAGE22 |
| HS | HASH Bank | HAJSGE22 |
| PV | Pave Bank Georgia | PAVEGE22 |
| MB | Microbank MBC | MOMBGE22 |
| BC | Microbank Crystal | BCRYGE22 |

---

## 12. Contact Categories

1. **Contacts > Contact Categories**: add a category with a name and a color. Archive one you no
   longer use; the **Archived** filter shows it again.
2. On a company or an individual without a parent company, pick categories in **Contact
   Categories**, after Tags.
3. The contacts under a company show the company's categories, read-only.
4. In the contact list or kanban, the **Contact Categories** side panel filters by one or more
   categories.

Every internal user can create, change and delete categories. All companies share them.

---

## 13. When Odoo refuses

| Message starts with | Why | What to do |
|---|---|---|
| Net distribution must be greater than zero. | **Net Distribution** is 0 or negative | Enter the net amount due to the shareholder |
| Select a Dividend WHT account, or turn off dividend withholding. | **Withhold Dividend Tax (5%)** is ticked without an account | Choose 331210 or 331212, or untick it |
| These open amounts are owed to somebody but cannot be routed by this flow (**Pay Salaries**) | A payslip has income tax on 331310 while 331310 allows reconciliation | Switch off **Payment Reconciliation** on 331310 ([section 4](#4-set-it-up-once), step 3) |
| Withholding On Payment taxes cannot use the 'Group of Taxes' or the 'Percentage Tax Included' computations. | The computation of a withholding tax was changed | Keep **Percentage** as the computation of withholding taxes |

---

## 14. Rules to remember

- **Changing the customer or vendor on a draft re-proposes every line's taxes.** Taxes edited by
  hand on those lines are replaced.
- **The fiscal position applies after the contact default**, so exports and reverse charge keep
  working ([section 9](#9-default-taxes-per-contact-and-not-taxed-products)).
- **No tax is not "exempt".** A line without tax never reaches the VAT Report.
- **Withholding is taken at payment**, never on the bill ([section 8](#8-withholding-at-payment)).
- **Upgrades never rewrite this module's accounts and taxes.** Your edits stay; records added
  in a later version are created. One exception: the first upgrade after 2026-10-23 renamed the
  taxes once (new English and Georgian names, descriptions and labels) and removed
  `WHT 5% - Resident Individual Residential Rent (company pays)`; edits made after that stay.
- **Bank name and BIC appear after saving**, not while typing.
- **A Georgian personal number makes a contact a person.** Tax ID 01008057135 (11 digits, with
  country Georgia, a GE prefix, or no country) → person; 206322102 (9 digits) → company. Form 30
  then splits a person's first and last name. Other countries keep Odoo's rule: any Tax ID
  means a company, so give a foreign contact its country, or an 11-digit foreign number is
  read as a Georgian person.

---

## 15. Common questions

**Why does an invoice to a VAT-registered customer show several 18% taxes?** That comes from
Odoo's Georgian data, not from this module; see [Known limitations](#16-known-limitations).

**Can a contact default remove the product's withholding tax?** No. Remove it on the line by
hand, or take it off the product.

**Does a second company get its own certificate numbers?** Yes, from the moment its Georgian
chart loads. A branch uses its parent company's accounts, taxes and counter.

**Where do I lock a closed VAT period?** **Accounting > Accounting > Closing > Lock Dates…**

---

## 16. Known limitations

| Limitation | Workaround |
|---|---|
| Odoo's Georgian taxes are corrected only in companies that load the chart with this module installed, or that had the chart when the module was installed; an upgrade never corrects an existing company | On such a company, check the taxes on the first invoices: a VAT-registered customer must get one 18% |
| A foreign vendor's bill gets no VAT tax unless the vendor has a Default Purchase Tax (no automatic reverse charge) | Before filing VAT, review the month's foreign bills without a tax |
| An import VAT amount booked as a journal entry with **18% Import** is doubled (journal entries ignore Included in Price) | Book customs VAT as a vendor bill |
| **Accounting > Accounting > Closing > Tax Returns** has no Georgian VAT return: no deadline card, no automatic lock | Lock the period by hand in **Lock Dates…** |
| Installing on a company that already has the Georgian chart leaves 331310 reconcilable | [Section 4](#4-set-it-up-once), step 3 |
| Default taxes are not applied to expenses, invoices made from an rs.ge waybill, purchase orders made by replenishment, Point of Sale and eCommerce, or drafts that existed before the install | Set the taxes on those lines by hand |
| A company that still holds the old 4-digit chart with postings does not move to Odoo's chart by installing this module | Moving it is a separate migration |
| Contact Categories are shared by all companies | Name them so every company can use them |

---

## 17. Glossary

| Term | Meaning |
|---|---|
| WHT | Withholding tax: tax the payer keeps from a payment and pays to the budget |
| CIT | Corporate income tax, due in Georgia when profit is distributed |
| Gross-up | Net ÷ 0.85: the distribution before 15% CIT |
| Treasury Code | The State Treasury code a budget payment goes to, instead of a bank account |
| Personal number | The 11-digit ID of a Georgian individual; as a Tax ID it makes the contact a person |
| III-19 | Reverse charge for a buyer that is not VAT registered |
| Non-trade | A payable that is not owed to a supplier; reports show it apart from trade payables |

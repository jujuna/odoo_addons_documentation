# Taxes on Lines — Quick Guide (Sales Order, Purchase Order, Invoice, Bill, Journal Entry)

> **Modules:** `account`, `sale`, `purchase`, `l10n_ge`, our `gec_localization` | **Deep reference:** [`taxes.md`](taxes.md) | **Georgian taxes, positions and their defects:** [`l10n_ge.md`](l10n_ge.md)
> Live data quoted below is from `gec20_prod1` on 2026-10-02.

## What It Does & Why It Exists

Every line of a sales order, purchase order, invoice, bill or journal entry has a **Taxes** field. Odoo fills it in two moves: it proposes the product's taxes, then the document's **fiscal position** replaces or removes them. One engine on `account.tax` then turns price, quantity, discount and those taxes into untaxed amount, tax and total. Orders, invoices, the totals box and the browser all run the same code, so the numbers agree everywhere. Orders only show amounts. Invoices, bills and journal entries post: each tax becomes a journal item on the tax's account, and the tags on those items feed the VAT Report.

Use this file to answer two questions: "why does this line have this tax?" and "where does this amount come from?".

---

## The Big Picture

```
1. PROPOSE   product Sales Taxes / Purchase Taxes (for the document's company)
             no product: the account's default taxes, or the company default sales tax
                 |
2. ADAPT     gec_localization: product "Not Taxed" -> no tax
             contact "Default Sales/Purchase Tax" -> replaces the product's VAT
                 |
3. MAP       fiscal position of the document -> each tax is replaced, kept or removed
                 |
4. LINE      Taxes field on the line (still editable by hand)
                 |
5. COMPUTE   base = unit price x (1 - discount) x quantity -> tax per tax -> rounding -> totals
                 |
6. POST      invoice / bill / entry only: product line + one journal item per tax account,
             with tags -> VAT Report
```

### Key Decision Points
- **The fiscal position of the document.** It decides more than the product does. A position pinned on the contact wins; otherwise Odoo takes the first auto-applied position (by sequence) whose country and Tax ID rules match; a contact without a country gets none.
- **Tax Excl. / Tax Incl. badge on the document** (new in 20). Says whether the typed unit price already contains the tax.
- **Rounding method** of the company: Round per Tax (prod1) or Round per Line.

---

## Step 1-4 — Which taxes land on the line

| Line | Starting taxes | (Re)proposed when | Code |
|---|---|---|---|
| Sales order line | product Sales Taxes; a line without product gets the company default sales tax | product or company changes; the Fiscal Position field changes in the form (all lines); the customer changes (ours) | [sale_order_line.py:707](../addons/sale/models/sale_order_line.py#L707), [sale_order.py:1351](../addons/sale/models/sale_order.py#L1351) |
| Purchase order line | product Purchase Taxes | product chosen; Fiscal Position or company changes (all lines); vendor changes (ours); a line imported without taxes gets them through the same product onchange | [purchase_order_line.py:192](../addons/purchase/models/purchase_order_line.py#L192), [purchase_order.py:530](../addons/purchase/models/purchase_order.py#L530), [purchase_order_line.py:797](../addons/purchase/models/purchase_order_line.py#L797) |
| Invoice / bill line | product taxes, else the account's default taxes; a customer-invoice line typed without product gets the company default sales tax; a bill line never gets the company default purchase tax | product changes; customer/vendor changes (ours); a Fiscal Position change only shows **Update Taxes and Accounts** | [account_move_line.py:1293](../addons/account/models/account_move_line.py#L1293), [:1302](../addons/account/models/account_move_line.py#L1302), [:1324](../addons/account/models/account_move_line.py#L1324), [account_move.py:2809](../addons/account/models/account_move.py#L2809) |
| Journal entry line | none | only what you pick | [account_move_line.py:1330](../addons/account/models/account_move_line.py#L1330) |
| Invoice from an order, bill from a PO | the order line's taxes, copied as they are | at creation; nothing is re-proposed | [sale_order_line.py:2067](../addons/sale/models/sale_order_line.py#L2067), [purchase_order_line.py:787](../addons/purchase/models/purchase_order_line.py#L787) |

A new product's taxes come from **Settings > Accounting > Taxes > Default Taxes** ([product.py:79](../addons/account/models/product.py#L79), [:86](../addons/account/models/product.py#L86)). Changing a product's or contact's taxes later changes nothing on existing lines.

### The fiscal position step (`map_tax`)

The link lives on the **tax**, not on the position. Two fields on the tax form decide it: **Fiscal Position** (where the tax may be used; empty means "all") and **Replaces** (which domestic tax it stands in for) ([account_tax.py:81](../addons/account/models/account_tax.py#L81), [:87](../addons/account/models/account_tax.py#L87)). For each tax on the line, [`map_tax`](../addons/account/models/partner.py#L161) applies three rules:

1. A tax of this position **Replaces** it → swapped for every such tax (one tax can become several).
2. Otherwise it is kept if its **Fiscal Position** field lists this position or is empty.
3. Otherwise it is removed.

**How the document gets its position** ([_get_fiscal_position](../addons/account/models/partner.py#L259)): the position pinned on the contact (Sales & Purchase tab > Fiscal Information > **Fiscal Position**) wins ([partner.py:279](../addons/account/models/partner.py#L279)); a contact without a country gets none ([partner.py:286](../addons/account/models/partner.py#L286)); otherwise the first auto-applied position by sequence whose country, state, ZIP and Tax ID rules match ([partner.py:220](../addons/account/models/partner.py#L220)). Sales orders and invoices test the delivery address ([sale_order.py:609](../addons/sale/models/sale_order.py#L609), [account_move.py:1080](../addons/account/models/account_move.py#L1080)); purchase orders test the vendor ([purchase_order.py:506](../addons/purchase/models/purchase_order.py#L506)).

**What the positions do with `gec_localization`** (since 2026-10-22):

| Contact | Position picked | Sales `18%` becomes | Purchase `18%` becomes |
|---|---|---|---|
| Georgian, with a Tax ID | Georgia (VAT Registered) | `18%` | `18%` |
| Georgian, no Tax ID | Georgia (non-VAT Registered) | `18%` | removed: a non-registered vendor charges no VAT |
| Any other country | Non-Georgia | `0% Export`: export, VAT Report line I.14 | removed: no automatic reverse charge; Default Purchase Tax `18% Reverse Charge Services` on the vendor gives one |
| No country | none | `18%` | `18%` |
| Pinned "Domestic non-registered individual" | that one | `18%` | removed |

Core `l10n_ge` as shipped gives six taxes on a Tax-ID sale, no VAT without a Tax ID and three reverse-charge taxes on a foreign bill; how the module corrects that: [`l10n_ge.md`](l10n_ge.md#corrections-to-l10n_ges-vat-taxes). Documents posted before the correction keep their taxes: on prod1 `INV/2026/00001` is 1,000 + 540 = 1,540.

### Our layer (`gec_localization`)

[`_ge_partner_product_taxes`](../custom_addons/gec_odoo_modules/gec_localization/models/account_tax.py#L48) runs after core's pick on sales order lines, purchase order lines and invoice/bill lines:

1. Product **Not Taxed** → no tax proposed.
2. The contact (its company) has a **Default Sales Tax** / **Default Purchase Tax** in this company → that one tax replaces the line's taxes. A VAT default goes through the same fiscal position; a withholding tax or 0% label default does not. Products never carry withholding taxes. Exception: for a contact ticked **VAT Payer**, a withholding tax or label default is added to the line's taxes (the product's 18% stays).
3. Otherwise core's result is kept.

It also re-proposes all line taxes when the customer or vendor changes on a draft. Full rules and decisions: [`l10n_ge.md`](l10n_ge.md#default-taxes-per-contact-and-not-taxed-products).

---

## Step 5 — How the amounts are computed

Each line becomes a "base line" and goes through the same engine: [_prepare_base_line_for_taxes_computation](../addons/account/models/account_tax.py#L1571), [_add_tax_details_in_base_line](../addons/account/models/account_tax.py#L1723), [_get_tax_details](../addons/account/models/account_tax.py#L1118). Sales lines ([sale_order_line.py:1069](../addons/sale/models/sale_order_line.py#L1069)), purchase lines ([purchase_order_line.py:152](../addons/purchase/models/purchase_order_line.py#L152)) and invoice lines ([account_move_line.py:1253](../addons/account/models/account_move_line.py#L1253)) all call it.

1. **Base** = unit price × (1 − discount %) × quantity ([account_tax.py:1749](../addons/account/models/account_tax.py#L1749), [:1211](../addons/account/models/account_tax.py#L1211)).
2. **Included or excluded**, per tax, in this order ([_is_price_included](../addons/account/models/account_tax.py#L881)): reverse-charge taxes are always excluded; then the tax's own **Included in Price**; then the document's **Tax Excl. / Tax Incl.** badge ([sale_order.py:191](../addons/sale/models/sale_order.py#L191), [account_move.py:641](../addons/account/models/account_move.py#L641)), which is set from **Settings > Accounting > Taxes > Prices** when the document is created and is editable while draft. prod1: Tax Excluded.
3. **Order**: taxes sorted by sequence; a group tax is replaced by its children ([account_tax.py:853](../addons/account/models/account_tax.py#L853)). Fixed taxes first, then included taxes are taken out of the price, then excluded taxes are added on top ([account_tax.py:1233-1244](../addons/account/models/account_tax.py#L1233)).
4. **Formulas** ([account_tax.py:1063-1116](../addons/account/models/account_tax.py#L1063)):

| Tax Computation | Price excluded | Price included | Example, price 100 |
|---|---|---|---|
| Percentage | base × rate | price × rate ÷ (1 + rates) | 18%: excluded → tax 18.00, total 118.00; included → tax 15.25, base 84.75 |
| Percentage Tax Included | base × rate ÷ (1 − rate) | price × rate | `Small Business 1% Turnover (Sale)` (included): tax 1.00, base 99.00 |
| Fixed | amount × quantity | the same, taken out of the price | 5 GEL × 3 units = 15.00 |
| Group of Taxes | each child, in sequence | | |

5. **Tax on tax.** A tax with **Affect Base of Subsequent Taxes** adds its amount to the base of later taxes. Example: fixed 10 (affects base) then 18% on 100 → VAT base 110 → VAT 19.80, total 129.80.
6. **Rounding** (**Settings > Accounting > Taxes > Rounding Method**, [company.py:132](../addons/account/models/company.py#L132)). Three lines of 10.03 at 18%: Round per Line gives 1.81 × 3 = 5.43; Round per Tax (prod1) gives 30.09 × 18% = 5.4162 → 5.42, and the cent difference is spread over the lines ([_round_base_lines_tax_details](../addons/account/models/account_tax.py#L2204)).
7. **Totals**: untaxed, tax per tax group, total ([_get_tax_totals_summary](../addons/account/models/account_tax.py#L2746)); orders: [sale_order.py:726](../addons/sale/models/sale_order.py#L726), [purchase_order.py:32](../addons/purchase/models/purchase_order.py#L32).
8. **Foreign currency**: computed in the document currency; company-currency amounts are those divided by the rate ([account_tax.py:1772](../addons/account/models/account_tax.py#L1772)).
9. **Withholding taxes** (our WHT taxes) are skipped here, so they never change the bill total; they are computed when the payment is registered ([account_tax.py:74](../addons/l10n_account_withholding_tax/models/account_tax.py#L74), [`l10n_ge.md`](l10n_ge.md#withholding-at-payment)).

---

## Step 6 — From line to journal items (invoice, bill, entry)

Orders post nothing. On a draft invoice, bill or entry, every change re-runs [_sync_tax_lines](../addons/account/models/account_move.py#L3346), which creates, updates or deletes the tax journal items:

- **Product line** = untaxed amount: credit on a customer invoice, debit on a bill. It carries each tax's **base** tags ([account_tax.py:2431](../addons/account/models/account_tax.py#L2431)).
- **Tax line** = one per tax distribution line, account and tags. Amount = tax × the distribution %. Account = the distribution line's account, or the product line's account when that is blank ([account_tax.py:2457](../addons/account/models/account_tax.py#L2457)). Tags = the distribution line's tags. A line with a zero amount is not created ([account_tax.py:3142](../addons/account/models/account_tax.py#L3142)), so a 0% tax only tags the base.
- **Credit notes** use **Distribution for Refunds** instead of **Distribution for Invoices** ([account_tax.py:2412](../addons/account/models/account_tax.py#L2412)).
- **Receivable / payable** = total.
- **Journal entries**: the amount on a line is the base (tax excluded) and Odoo adds the tax lines ([account_move.py:1681](../addons/account/models/account_move.py#L1681)).

The VAT Report adds up the **tags** on posted items, not tax names ([`l10n_ge_vat_report.md`](l10n_ge_vat_report.md)).

**`BILL/2026/09/0002`** — local vendor, purchase `18%`:

| Account | Debit | Credit | Tags |
|---|---|---|---|
| 749000 General & Administrative - Others | 100.00 | | 24(B) |
| 334010 Input VAT Local Purchases | 18.00 | | 24(T) |
| 310110 Accounts Payable Trade and Services | | 118.00 | |

**`BILL/2026/10/0001`** — foreign vendor, `18% Reverse Charge Services` (distribution +100% / −100%, so the vendor is owed 100 and the VAT nets to zero):

| Account | Debit | Credit | Tags |
|---|---|---|---|
| 749000 General & Administrative - Others | 100.00 | | 21(B), 27(B) |
| 334040 Input Reverse Charge VAT | 18.00 | | 27(T) |
| 333060 Reverse Charge VAT Payable | | 18.00 | 21(T) |
| 310110 Accounts Payable Trade and Services | | 100.00 | |

**A customer invoice with plain `18%`** (contact without country, so no position): debit 140110 118.00; credit 611101 100.00 tagged 1(B); credit 333002 VAT Output 18.00 tagged 1(T).

---

## When Odoo re-proposes taxes

| You do this | Sales order | Purchase order | Invoice / bill |
|---|---|---|---|
| Pick or change the product | that line | that line | that line |
| Change the customer / vendor | all lines (core when the position changes, ours always) | all lines (core when the position changes, ours always) | all lines (ours); core alone only shows **Update Taxes and Accounts** |
| Change the Fiscal Position field by hand | all lines, at once, hand edits lost | all lines, at once | nothing until you click **Update Taxes and Accounts** ([account_move.py:6611](../addons/account/models/account_move.py#L6611)) |
| Change price, quantity or discount | taxes kept, amounts recomputed | same | same |
| Change taxes on the product or the contact | only lines proposed afterwards | same | same |
| Create the invoice / bill from the order | | | the order's taxes, copied |

---

## Real-World Scenario: why `S00010` shows 0%

**Situation.** `S00010` sells 1 × "Bershka" ჩანთა - 2 at 1.00 to Emma Granger. The product's Sales Taxes are `18%`. The order line has `0% Export`; untaxed 1.00, tax 0.00, total 1.00.

**What Odoo did:**
1. Propose: the product's `18%`.
2. Ours: Emma's **Default Sales Tax** is also `18%`, so nothing changes.
3. Map: Emma's country is the United States, she has no Tax ID and no pinned position. "Georgia (VAT Registered)" and "Georgia (non-VAT Registered)" require Georgia; "Non-Georgia" accepts any country. In it, `0% Export` **Replaces** `18%`, so `18%` becomes `0% Export`.
4. Compute: 1 × 1.00 = 1.00, tax 0.
5. The invoice would post: debit 140110 1.00, credit 611101 1.00 tagged 17(B), so the VAT Report shows a 1.00 export on line I.14. No tax line, because the amount is zero.

Setting `18%` on the product or on the contact cannot change this: both go through step 3.

**What to do:**
- **The goods leave Georgia (real export):** `0% Export` is the intended result. Keep it.
- **The sale is taxable in Georgia:** for this order, clear Other Info > Invoicing > **Fiscal Position**; the lines switch to `18%` at once. For every order of this customer, a domestic position must be pinned on her, but none of the shipped ones keeps `18%` (table above). Apply fix 2 from [`l10n_ge.md`](l10n_ge.md#gotchas--non-obvious-behavior) first (add both non-registered positions to the **Fiscal Position** field of `18%`), then pin "Domestic non-registered individual".

---

## Configuration & Settings

- **Default Taxes** (Settings > Accounting > Taxes): the taxes a new product starts with. prod1: `18%` sale, `18%` purchase.
- **Prices** (same place): the default of the Tax Excl. / Tax Incl. badge on new documents ([company.py:294](../addons/account/models/company.py#L294)). Existing documents keep their own badge.
- **Rounding Method** (same place): Round per Tax (prod1) or Round per Line. See Step 5.
- **Fiscal positions** (Accounting > Configuration > Accounting > Fiscal Positions): **Detect Automatically**, **Country**, **Tax ID required** and sequence decide which one a contact gets. The tax swap itself is set on the taxes (**Fiscal Position**, **Replaces**).

---

## Gotchas & Non-Obvious Behavior

- **The fiscal position beats the product and our contact default.** Most "wrong tax" questions are answered by the document's **Fiscal Position** field.
- **No tax is not "exempt".** A line without tax never reaches the VAT Report; exempt and export sales need their 0% exempt / `0% Export` taxes.
- **Existing lines never follow configuration changes.** Re-pick the product, change the position on the order, or click **Update Taxes and Accounts** on a draft invoice.
- **Price-included swaps change the unit price.** When a position replaces a price-included tax, a unit price taken from the product is recalculated: a product priced 118 with `18%` included sells at 100 under `0% Export` ([account_tax.py:1320](../addons/account/models/account_tax.py#L1320)). A price typed by hand stays.
- **A position without taxes is not "no position".** Such a position keeps only taxes whose **Fiscal Position** field is empty and removes the rest; an empty Fiscal Position field on the document keeps every tax ([partner.py:161](../addons/account/models/partner.py#L161)).

### Troubleshooting order for a wrong tax
1. The document's **Fiscal Position** (Other Info tab).
2. The contact: pinned **Fiscal Position**, country, Tax ID; ours: **Default Sales/Purchase Tax**.
3. The taxes' **Fiscal Position** and **Replaces** fields.
4. The product: Sales/Purchase Taxes for this company; ours: **Not Taxed**.
5. Was the line created before you changed 1-4? Then it still has the old taxes.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`taxes.md`](taxes.md) — the full engine reference: every computation type, cash basis, closing, POS, lock dates
- [`l10n_ge.md`](l10n_ge.md) — Georgian taxes, fiscal positions, their three defects with fixes, our contact default taxes
- [`l10n_ge_vat_report.md`](l10n_ge_vat_report.md) — how tagged journal items become the Georgian VAT declaration (Georgian)

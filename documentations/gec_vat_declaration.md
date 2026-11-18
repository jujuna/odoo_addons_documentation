# VAT Declaration (rs.ge) — `gec_vat_declaration`

> **Module:** `gec_vat_declaration` | **Path:** [`custom_addons/gec_odoo_modules/gec_vat_declaration/`](../custom_addons/gec_odoo_modules/gec_vat_declaration/)
> **Status:** Phase 1 of [`vat_declaration_build_plan.md`](../dev_notes/plans/vat_declaration_build_plan.md), built 2026-10-22, commits `4daad73` + `8759c4a` (grid, Georgian),
> 12 tests pass on a scratch DB (incl. a browser test of the grid). Tab 4 (annex ბ I, `b888439`) and tab 5 (annex ბ II,
> `cd2d81a`) added 2026-10-26; neither has tests of its own yet. Installed on gec20_prod1 since 2026-10-22, upgraded with
> tab 4 on 2026-10-26 and with tab 5 on 2026-10-27. Tab 17 (III-19⁶) proposed from sold margin-scheme fixed assets
> since 2026-10-28 (8 tests of its own, 20 in total). Tab 6 (annex ბ III, customs PDFs) added 2026-11-02 with the
> optional bridge `gec_vat_declaration_documents`. Drill-down (search icon → what made Odoo's figure) and formula
> tooltips added 2026-11-04, commit `a76b67f`. Go-live review fixes 2026-11-10, commit `e6d09d3` (78 tests on a scratch
> copy), and corrections booked in the acceptance month, commit `440f495` (rs_einvoice). gec20_prod1 not upgraded to them.

## What It Does & Why It Exists

Georgian VAT payers file a monthly declaration on the rs.ge portal by the 15th. The portal form has 18 tabs; five of them
are cell forms whose numbers come from the books: ა I (taxable operations), ა II (reverse charge), ა III (creditable
VAT), Part III (the final calculation) and III-19⁶ (margin scheme). This module rebuilds those five tabs inside Odoo as
a **VAT Declaration** record per company and month: Odoo proposes every cell it can from its own VAT Report, applies the
portal's own formulas to the locked cells, and keeps what the accountant types. The accountant compares the result with
the portal, copies the cells, and marks the month as filed. Tabs 4 and 5 (annexes ბ I and ბ II) list the month's issued and
received tax invoices as rs.ge sees them, to compare with the portal's own lists. Tab 6 (annex ბ III) lists the
customs declarations (regular and Form 4), one row per PDF; tabs 7 and 8 (ბ IV, ბ V) and tabs 10 and 11 (ბ VIII, ბ IX) are typed. The other 4 tabs
(ბ VII, ბ X, tourist) come in later phases. Tabs 13 and 14 (petroleum tax invoices, ნსაფ, issued and received) are filled by
`rs_spec_invoice` when it is installed (added 2026-11-07).

---

## The Big Picture — How It Works

```
New declaration (company, month)  -->  Generate  -->  type the manual cells, Save  -->  copy to the portal  -->  Mark as Filed
                                       (Odoo proposals    (locked cells recomputed           (locked on the server, tax lock
                                        + portal formulas)  on every Save)                     date set; Reset to Draft to change it)
```

1. **Generate** reads the month's totals from core's Georgian VAT Report (`l10n_ge.tax_report_ge`) through the report
   API, the way Odoo's own tax returns do: posted entries only, the company plus its branches with the same VAT number.
   The report's numbers are stored on each cell as **Odoo** (`odoo_value`).
2. Each cell is one of three kinds, copied from Form 30:
   - **Computed** (locked on the portal): always the portal formula, e.g. VAT = base × 18 %, Part III 17 / 18.
   - **Proposed** (editable on the portal, Odoo has a source): follows Odoo until the accountant types something else;
     after that Generate never overwrites it. Part III row 12 is proposed from other cells, not from the report
     (Scenario 3a).
   - **Typed** (no Odoo source): never touched.
3. **Save** recomputes every locked cell after typing, so Part III always shows the result the portal will show.
4. Warnings are listed on the form and never block. The cell checks (duplicates, Odoo VAT vs 18 %, negative cells,
   December rows, branches, cell 7 vs row 1, ბ I and tab 13 vs ა I, ბ II and tab 14 vs ა III, ბ III, ბ IV / ბ V caps) are computed live on
   every form load and Save; the invoice, bill and margin-scheme scans, the Documents pull (unreadable customs PDFs) and
   rs_spec_invoice (tabs 13 / 14) write their warnings once at Generate (`scan_warnings`, since 2026-11-06).
5. **Mark as Filed** asks for confirmation, then locks the declaration on the server (header except the Portal Number, cells and every annex row refuse changes; a bill or
   invoice it lists cannot be deleted) and sets the **Tax Return Lock Date** of the company and its same-VAT branches to
   the month end when that is later, after revoking active tax-lock exceptions, as core's tax return does
   ([account_return.py:1571](../enterprise/account_reports/models/account_return.py#L1571)). Reset to Draft lifts the
   declaration lock only; the lock date stays (core does the same). It is refused until the month has ended (the day
   after its last day): a lock date in the future would move or refuse every taxed posting of the month; core's own
   lock wizard refuses a future date too. Filing also locks the month for branches with their own Tax ID, because Odoo
   reads every parent's lock date ([company.py:761](../addons/account/models/company.py#L761)); a draft lists those
   branches in a warning: file theirs first. It is also refused while an earlier month of the company has a declaration
   and no filed one: the lock would close that month, and core's tax return refuses the same
   ([account_return.py:1535-1545](../enterprise/account_reports/models/account_return.py#L1535)); an adjusted draft of a month already filed does not block (2026-11-13). The
   **Portal Number** stays editable on a filed declaration: rs.ge gives it only after submitting (2026-11-13).

### Key Decision Points
- **ა III fixed assets (decided 2026-10-22, column 5 proposed since 2026-11-04):** Odoo's report has one VAT total per
  row. Column 5 (fixed assets) is proposed from the company setting **Fixed-asset accounts (VAT declaration)**
  (Accounting > Settings, accounts from the accountant's chart; the company and its branches): the VAT of tax lines whose
  base line sits on one of those accounts, plus VAT booked to 334011 by the tax "18% Fixed Assets", at most the row
  total. The setting is filled once with the accountant's 7 asset accounts (211210, 211310, 211510, 211420, 211410,
  216990, 210120) on the first upgrade and on every new Georgian chart. Column 4 (goods/services) = Odoo's row total − column 5;
  column 3 = 4 + 5, so the row total stays Odoo's number. Row 2 (import VAT: core's import taxes are 100 % tax-included,
  so the base line is 0 and cannot be split), row 4¹ (no tax behind it) and rows 6 / 6¹ (December only) keep column 5
  typed. An empty setting proposes 0, as before.
- **Corrections (Q9, decided 2026-10-22; 2026-11-10):** a correction counts in the month the buyer accepts it, and ა I
  row 1 is Odoo's net figure (Part III cell 7 only for decreases not booked in Odoo). rs_einvoice books both halves of a
  correction in the acceptance month: a seller's Correct & Reissue copy is sent to rs.ge as a draft and posted, dated
  that day, when the buyer accepts (posting it by hand is refused); a supplier's copy is dated that day and posted by
  Accept, or stays a draft when the acceptance arrives by import or Check Status. The gross row 1 + cell 6 / 7 idea of
  the build plan (item 5) is replaced. ბ I / tab 13 warn when a correction is accepted on rs.ge but still a draft in Odoo.
- **Primary or adjusted:** several declarations of one month are allowed. A new declaration starts as **Adjusted** when
  the month already has a filed one (editable, as on the reverse-charge form, 2026-11-10); the form warns about other
  declarations of the same month **and type**. **Duplicate** of a filed declaration gives an Adjusted draft carrying the
  cells (typed values, proposals and Odoo's figures) and every annex row; the next Generate replaces only the rows Odoo
  linked, so typed paper invoices, advances, customs and stock rows stay (2026-11-13).

---

## Real-World Scenarios

### Scenario 1: September, one sale and one purchase
**Situation:** Sales of 5,420 + 18 % VAT to a VAT-registered customer, a purchase with 500 VAT.
**What they do:** Accounting > Reporting > **VAT Declaration (rs.ge)**, New, month September, **Generate**.
**What happens:** ა I row 1 = 5,420 with VAT 975.60; ა III row 1 = 500; Part III 1 = 975.60, 2 = 5,420, 11 = 500,
17 = **475** (975.60 − 500, rounded down to whole lari as the portal does). Same numbers as the portal capture.

### Scenario 2: Part of the input VAT is a fixed asset
**Setup (once):** Accounting > Settings > VAT Declaration > **Fixed-asset accounts (VAT declaration)**: the accountant's
fixed-asset accounts, e.g. 211420 Furniture and Fixtures.
**What they do:** A bill has a 2,000 shelf on 211420 and 500 of goods on an expense account, both with 18 %; Generate.
**What happens:** ა III row 1: column 5 = 360 (the shelf's VAT), column 4 = 90, column 3 = 450 (Odoo's total). Typing
another column 5 keeps the typed value; column 4 follows (total − column 5), Part III does not change.

### Scenario 3: A turnover decrease typed by hand
**When:** only for a decrease that is **not booked in Odoo**. A credit note or an rs.ge correction posted in Odoo already
lowers ა I row 1 (Odoo's VAT Report sums the tagged lines, credit notes negative); typing it in cell 7 as well counts it
twice. A warning names this case: cell 7 is typed, row 1 is Odoo's figure, and the month has ბ I decreases or credit
notes. Row 1 is net (Odoo's figure): decided 2026-11-10 after the accountant's answer.
**What they do:** Part III, type 54 in cell 7, Save.
**What happens:** Cell 16 = 554, cell 17 = 421. With 1,000 instead: cell 17 = 0, cell 18 = 524 (refund side).

### Scenario 3a: Supplier credit notes above the month's bills
**When:** the month's supplier credit notes carry more VAT than its bills, so ა III column 4 of a row is negative. The
portal reads a negative cell as 0 and the excess would be lost. Accountant's rule (2026-11-12): it goes to Part III
row 12, the decrease of deducted VAT.
**What happens:** bill VAT 90, credit-note VAT 180: ა III row 1 column 4 = −90 (read as 0), cell 11 = 0, row 12 is
proposed 90 and cell 15 rises by 90. A warning names the row. Row 12 sums the negative column 4 of rows 1, 2, 3, 5, 7
and 8; a row 12 amount the accountant typed is kept, with Odoo's proposal shown beside it.
The ბ II warning still shows in such a month when the credit note has no rs.ge document (ბ II lists only rs.ge
invoices: "received invoices carry 90.00 VAT, A III row 1 claims -90.00"); it compares with row 1 before the portal's
floor, so an rs.ge correction that lowers an earlier bill raises no difference.
**Not included:** rows 4 and 4¹ (reverse charge). A reverse-charge credit note lowers ა II and ა III row 4 by the same
amount; both are read as 0 and cancel, so adding row 4 to row 12 would raise the VAT to pay. Open question to the
accountant: is such a reduction typed in ბ IX?

### Scenario 4: December
**What happens:** ა III rows 6 and 6¹ (own-built building, own repairs), columns 4 and 5, can be typed only in a
December declaration; the portal unlocks them only then (Order 996 Art. 75 §5). Other months show them locked at 0.

---

## The pages (rebuilt 2026-10-22 to look like rs.ge)

Each page is a grid drawn by the `gec_vat_grid` widget, laid out like the portal page:

| Tab | Green bar (full portal title) | Columns | Rows |
|---|---|---|---|
| 1 · ა-I დასაბეგრი | დანართი "ა" ნაწილი I დღგ-ით დასაბეგრი ოპერაციები | დასაბეგრი ბრუნვა · 18% | 22 |
| 2 · ა-II უკუდაბეგვრა | დანართი "ა" ნაწილი II უკუდაბეგვრის წესით დარიცხული დღგ | უკუდაბეგვრას დაქვემდებარებული ბრუნვა · 18% | 4 |
| 3 · ა-III ჩასათვლელი | დანართი "ა" ნაწილი III დღგ-ის ჩასათვლელი თანხა | ჯამი · საქონელზე/მომსახურებაზე · ძირითად საშუალებაზე | 11 |
| 16 · III გაანგარიშება | დღგ-ის საერთო თანხის გაანგარიშება | დასაბეგრი ოპერაციები · გადასახდელი · შესამცირებელი (numbered 1 · 2 · 3) | 20 |
| 17 · III-19⁶ მარჟა | the portal's III-19⁶ title | შესყიდვის ფასი · მიწოდების ფასი · დღგ | 5 |

- One row per portal row; a cell sits in the column where the portal has its input (catalog fields `line`,
  `line_label`, `slot`, taken from the portal capture). Part III pairs (6)/(7), (9)/(10), (12)/(13), (15)/(16) share a row.
- Lock = calculated by the portal (read-only; hover it for the portal formula); wand = proposed by Odoo (editable,
  follows Odoo until typed); no icon = typed. Click an editable cell to type; Save recomputes the locked cells.
- A faded search icon beside a value = Odoo has a source for it: click it to see what made Odoo's figure (next section).
- A grey "Odoo x" under a cell shows Odoo's figure when it differs: Odoo's proposal on a proposed cell, Odoo's own report
  figure on a locked cell (e.g. Odoo's real VAT beside the portal's 18 %).
- Georgian interface: `i18n/ka_GE.po` (house terms: გენერირება, მონახაზზე დაბრუნება, ჩაკეტილი, შემოთავაზებული).
- Proof: the browser test renders the grid (22 rows, lock icons, no OWL error); screenshots of all 5 pages in
  `Claude outputs/vat_phase1_20261022/screens_ka/`.

## Where each number comes from (checked against `a76b67f`, 2026-11-05)

Four kinds of source: **Tax** = core's Georgian VAT Report (tax tags), **Bill** = built line by line from invoices and
bills, **Formula** = the portal's own formula, **Other** = PDFs, assets or typed. `DECL` =
[`gec_vat_declaration.py`](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py),
`RC` = [`gec_vat_rc_declaration.py`](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_rc_declaration.py).

| Tab / row | Source | Exact source | Rule | Code |
|---|---|---|---|---|
| ა I rows 1-14³, base | Tax | report lines `ge_1`, `ge_3`…`ge_20` (tags `-1(B)`…`-20(B)`) | posted, accounting date, company + same-VAT branches | DECL:19-48, 340-362 |
| ა I VAT column | Formula | base × 18 %; Odoo's own VAT only feeds warnings | recomputed on every Save | DECL:151 |
| ა I row 1¹ | Other | = tab 17 total (margin scheme) | | DECL:149 |
| ა II rows 1-3 | Tax | `ge_21`…`ge_23` (tags `21(B)`…`23(B)`); VAT = base × 18 % | | DECL:49-54, 154 |
| ა III column 3 (row total) | Tax | `ge_24`…`ge_33` tax (tags `24(T)`…`33(T)`); shown as column 4 + 5 | | DECL:55-62, 157 |
| ა III column 5 (fixed assets) | Tax + account | VAT of `NN(T)` tax lines whose base line is on a fixed-asset account, or booked to 334011 | capped at the row total; typed value kept | DECL:364-401 |
| ა III column 4 (goods) | Formula | Odoo's row total − column 5 | | DECL:403-409 |
| ა III row 3 | Other | `ge_26` exists in core's report, but no tax in core l10n_ge or gec_localization carries `26(B)` / `26(T)`, so Odoo proposes 0 (checked 2026-11-13) | type the import VAT charged by a tax-authority decision | DECL:ODOO_SOURCE |
| ა III row 4¹ | Other | `ge_28` is a manual value in core's report, no journal items | | DECL:59 |
| ა III rows 6 / 6¹ | Other | typed in December, locked to 0 otherwise | | `gec_vat_cell.py`:96-101 |
| Part III (tab 16) | Formula | portal formulas over ა I-III; 17 / 18 rounded down to whole lari; 12 cells typed, row 12 proposed | | DECL:161-172 |
| Tab 17 (III-19⁶) | Bill + asset | sale = posted invoice lines with a Sold Asset; purchase = the asset's Asset Value | VAT = (sale − purchase) ÷ 1.18 × 0.18, at least 0 | DECL:627-713, 147 |
| ბ I | Bill | `out_invoice` with rs.ge status 2 / 3 / 8 (cancelled included); VAT = tax lines of category S | invoice date; a correction counts in its reversal's month | DECL:454-546 |
| ბ II | Bill | `in_invoice` with rs.ge status 2 / 3 / 8, any Odoo state (a draft only warns) | accounting date | DECL:557-625 |
| ბ III | Other | customs / Form 4 PDFs, uploaded or pulled from Documents (to the 15th of M+1) | the date inside the PDF is in the month | DECL:715-793 |
| ბ IV, ბ V | Other | typed only; compared with ა III rows 8 / 7 | | DECL:884-889 |
| III-19 Part I | Bill | posted vendor bill lines: vendor country set and not GE, product type Service, amount > 0, no E / Z / O tax; the RC tax on the line is not required | accounting date; VAT = 18 % of the amount (`VAT_RATE`) | RC:14-19, 195-211 |
| III-19 Part II rows 4 / 5 | Bill | proposed from the month's "Reverse and Create Invoice" groups; a typed value is kept with a warning | | RC:219-269 |
| III-19 Part III / IV | Other | goods (collateral) typed; rows 3-9 are the portal formulas | | RC:90-117 |

Column 5 uses the same core pieces as the enterprise Tax Report's "Account > Tax" grouping (`_get_report_query`,
`_get_query_tax_details`, `tax_exigible`) but groups by tag; it is not a copy of
[`account_generic_tax_report.py:390-413`](../enterprise/account_reports/models/account_generic_tax_report.py).

**Examples (gec20_vat_rc_test, the accountant's checklist DB):**

| Source | Record | Where it lands |
|---|---|---|
| Tax | November 2026 invoices: tag `1(B)` balance −3,481.00, `1(T)` −626.58 | ა I row 1 base 3,481.00, VAT 3,481 × 18 % = 626.58; Part III 1 = 626.58, 2 = 3,481 |
| Tax + account | BILL/2026/01/0001: shelf 2,000 on 211420 + 500 on 749000, one VAT line 450 (`24(T)`) | ა III row 1: column 3 = 450, column 5 = 360, column 4 = 90; Part III 11 = 450 |
| Tax + account | BILL/2026/02/0001: 1,000 on 749000 with "18% Fixed Assets", VAT 180 on 334011 | ა III row 1: column 5 = 180, column 4 = 0 |
| Bill | BILL/2025/01/0001: TEST Foreign Consulting GmbH, IT consulting 1,000, "Reverse Charge 18% Non-Deductible" | III-19 Part I row 1,000 / 180; Part II 3 = 180, 8 = 180; დარიცხვა 180 |
| Other (typed) | November 2026, ა III row 1 column 5 typed 52,000 (Odoo 52,201.44) | typed value kept; column 4 = 52,579.44 − 52,000 = 579.44; Part III 18 = 51,952 |

The reverse-charge bill also carries tags `21(B)` / `21(T)`: for a VAT payer the same VAT lands in ა II row 1 of this
declaration instead, and the company's VAT Payer flag decides which form applies.

## Drill-down — click a number, see what made it (added 2026-11-04, `a76b67f`)

Like Odoo's Tax Report audit: the search icon beside a value opens the journal items (or records) behind **Odoo's
figure** for that cell. Clicking the number itself still edits it. The form is saved first; the list is read from the
**current books** (live), so a filed month can show more or less than what was filed.

| Cell | Icon opens | Built by |
|---|---|---|
| The 46 cells mapped to the l10n_ge VAT report (`ODOO_SOURCE`: proposed bases, Odoo's VAT beside the 18 %, ა III totals) | core's own audit list of that report line, same month and companies as Generate | core `action_audit_cell` ([account_report.py:5232](../enterprise/account_reports/models/account_report.py#L5232)) with `_gec_report_options()` |
| ა III row 4¹ (`ge_28`) | core's **Manual values** list: that report line is typed into the report (engine `external`), it has no journal items; filtered to the declaration's companies | same, plus a company filter core leaves out |
| ა III column 5 (6 rows) | the tax journal items the column-5 query summed; when their balance differs from the cell (an item shared with a non-asset line, capped, typed, changed since Generate) the title says "the tax items differ from the cell" | `_gec_fixed_asset_tax_lines()` |
| ა III column 4 (8 rows) | the row's report items minus column 5's tax items, while column 5 equals the balance of those items; otherwise the whole row, titled "(column 5 differs from its tax items: the whole row)" | core audit, minus the ids above |
| III-19⁶ purchase / sale price (8 cells) | the assets whose Asset Value counted / the sold invoice lines | third result of `_gec_margin_scan()` |
| Locked (formula) cells | no list: the padlock's tooltip shows the portal formula in portal row / column numbers | catalog column `formula` |
| Typed cells (15: ა I 13.1, ა III column 5 of rows 2 and 4¹, Part III 4-4⁵, 6, 7, 9, 13-14¹) | nothing: no Odoo source | — |
| Part III row 12 | nothing: proposed from the negative ა III column 4 cells, not from journal items | — |

Which cells get the icon: `AUDIT_CODES` ([gec_vat_declaration.py:99](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L99)) = the four source maps, so a cell added to a map gets
its icon and list without other code. Entry point: `gec.vat.declaration.line.action_gec_audit()`
([gec_vat_cell.py:91](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_cell.py#L91)): read access on the cell is checked before the sudo report and scans; the
scans only return ids, and the list opens with the user's own rights.

**Signs:** core's audit list shows the journal items as booked. For report lines with a minus formula (ა I bases
`-1(B)`…, VAT `-NN(T)`), the items' balance is minus the cell, exactly as in Odoo's Tax Report.

## Tab 4 — annex ბ I, issued tax invoices (added 2026-10-26)

Nothing on this page goes to rs.ge: the portal attaches confirmed invoices to the declaration by itself. The page shows
what Odoo expects the portal's ბ I to hold, so the accountant can compare before filing.

**Which invoices become rows** (`_gec_b1_scan`, [gec_vat_declaration.py:531](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L531)): customer
invoices of the company and its same-VAT branches with an rs.ge number and an rs.ge status of confirmed (2), corrected
original (3) or confirmed correction (8), posted or cancelled. Cancelled ones are included: when a correction is
accepted in the same month, rs_einvoice cancels the original in Odoo, but rs.ge keeps listing it as status 3. Drafts
are not rows: an accepted correction still in draft gets a warning instead.

**Which month a row belongs to** (`_gec_b1_month`, [:509](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L509)): its invoice date, except a correction,
which counts in the month the buyer accepted it. When the original sits in an earlier VAT month, rs_einvoice reverses it
on acceptance with a credit note marked Skip rs.ge, reason "replacement", dated that day
([account_move_cancel.py:140](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_cancel.py#L140)); that date
is the month.

| Column | From |
|---|---|
| სერია, ნომერი | the invoice's rs.ge series and number |
| დასაბეგრი ოპერაციის თვე | invoice date (shown as the first day of the month) |
| მყიდველის ს/ნ | buyer Tax ID as sent to rs.ge (`rs_einv_buyer_tin`) |
| დღგ: გადასახდელი / შესამცირებელი | an invoice: its VAT; a correction: its VAT minus the corrected invoice's VAT, an increase on the left, a decrease on the right. VAT counts only tax lines whose tax has Tax Category Code S, the same VAT rs_einvoice sends (`_gec_rs_vat`); City Tax, Small Business turnover and 0% taxes add nothing |
| კორექტირებული ფაქტურის სერია, ნომერი | the corrected invoice (corrections only) |

Example (prod1, October 2026): original `ეა-87 0060685` VAT 3,600, correction `ეკ 15610312` to 2,700 → two rows,
3,600 payable and 900 reduced; the page's net equals the 2,700 Odoo books.

The sub-grid lists advance offsets from rs_einvoice's native advance settlements that rs.ge accepted (status 200):
delivery invoice, advance invoice, VAT. Rows linked to an Odoo invoice or settlement are rebuilt on every Generate;
typed rows (a paper invoice) are kept and shown shaded.

**The page** is drawn by the `gec_vat_rows` widget
([gec_vat_rows.js](../custom_addons/gec_odoo_modules/gec_vat_declaration/static/src/components/gec_vat_rows/gec_vat_rows.js)),
copied from the portal's ბ I HTML: green title, two-row header ("დღგ-ს თანხა" and "ანგარიშ ფაქტურა რომლის
კორექტირებაც წარმოებს" over their two columns), the portal's column widths (12/15/15/15/10/10/12/11 %), the "?"
help text, a totals row (fields `b1_amount`, `b1_reduce_amount`, `b1_advance_amount`), month shown as `10.2026`. Per
row: an open icon for Odoo rows, a delete icon for typed rows; **Add a row** adds a typed row. Not copied: the portal's
filter row, page-size selector, export and import (export is plan Phase 6).

**Companies:** the same as the VAT report, the declaring company and its own branches with the same Tax ID
(`_get_branches_with_same_vat` limited to `child_of` the company).

**Warnings** (never block): invoices to a contact with a Tax ID that are missing from rs.ge or not accepted (grouped by
rs.ge status, first 20 names), a correction counted in another month, an invoice cancelled in Odoo but still confirmed
on rs.ge, ბ I plus tab 13 VAT above ა I rows 1-3 (the portal requires rows 1-3 to cover the month's invoices; tab 13
counts since 2026-11-13, because petroleum sales VAT also sits in ა I; whether the portal's own control counts tab 13 is
not confirmed), and four
correction and date warnings (2026-11-10):

| Warning | When | Why it matters |
|---|---|---|
| Accepted on rs.ge, still a draft | a Correct & Reissue copy with rs.ge status 8 that Odoo did not post (lines changed after sending, or posting failed: the copy has a To-Do) | its VAT is in no month until it is posted |
| Correction posted, not accepted yet | a replacement posted while its original is still posted (corrections of the old flow, before `440f495`); when rs.ge already accepted it: run Check Status, unreconcile payments first | Odoo's VAT counts both invoices until the buyer accepts; rs.ge counts only the change |
| Correction and reversal in different months | shown in the month of the original's `replacement` reversal | the replacement's VAT and the original's reversal sit in two months' ა I row 1 |
| Booked this month, dated earlier on rs.ge | posted, rs.ge-accepted invoices whose accounting date is in the month but invoice date earlier (core moves the date past a tax lock, [account_move.py:6314](../addons/account/models/account_move.py#L6314)) | their VAT is in this month's ა I and on the earlier month's ბ I: file an adjusted declaration for that month |

Code: `_gec_correction_warnings` (shared with tab 5), the late-invoice search at the end of `_gec_b1_scan`.

## Tab 5 — annex ბ II, received tax invoices (added 2026-10-26)

Same page as tab 4, with the supplier's Tax ID and the creditable VAT (`ჩასათვლელი`). It lists what Odoo expects the
portal's ბ II to hold. The buyer side differs from the seller side in three ways, and each rule follows from it.

| Point | Rule | Why |
|---|---|---|
| Which bills | vendor bills with an rs.ge number and status 2 / 3 / 8, in any Odoo state | the portal lists rs.ge-accepted invoices; a draft or cancelled bill gets a warning |
| Which month | the bill's **accounting date** | that is where Odoo's VAT report credits the VAT (ა III); core moves a late bill into the first open month when the tax lock date covers its invoice date |
| VAT | the bill's standard-rate tax lines only (Tax Category Code S), as annex ბ I does for sales | a bill can carry withholding or a non-VAT tax next to VAT; neither is VAT rs.ge holds |
| Correction | a bill linked to the bill it replaces (`rs_einv_replaces_id`); the row is the change against it | rs_einvoice imports a supplier correction as a new bill ("fresh" mode) and cancels the original once the correction is accepted, reversing it in an earlier VAT month ([account_move_buyer.py:399](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L399)) |

Code: `_gec_b2_scan` ([gec_vat_declaration.py:637](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L637)), `_gec_rs_vat` ([:517](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L517)).
Rows are `gec.vat.invoice.line` with `part = purchase` (ბ I rows have `part = sale`). rs_einvoice keeps no advance links
for bills, so the ბ II advance sub-grid holds typed rows only.

**Petroleum bills (2026-11-07):** a bill with `rs_einv_is_spec` is not a ბ II row, it belongs to tab 14 (section below).
`_gec_b2_scan` leaves it out of the rows and of the "left out, rs.ge status" warning
([gec_vat_declaration.py:645](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L645), `_gec_b2_scan` starts at [:637](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L637))
and of the "not linked to an rs.ge invoice" warning ([:693](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L693)).
In `_gec_warnings` ([:915](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L915)) the "A III row 1 holds VAT
without an rs.ge tax invoice in ბ II" check counts tab 14 rows as ბ II rows ([:979](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L979)),
and the ბ II vs A III row 1 comparison adds the tab 14 VAT ([:970](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L970)).

Example (prod1 copy, September 2026): bill `ეა-86 7706173` VAT 500.80 (posted) and `ეა-86 7674590` VAT 49.27 (accepted
on rs.ge, still a draft in Odoo), total 550.07; warnings for the draft and three bills still pending on rs.ge.

**Warnings:** accepted on rs.ge but a draft in Odoo (VAT not credited); cancelled in Odoo but confirmed on rs.ge; a
correction whose original, in an earlier month, was cancelled (bills of the old flow); a correction whose original still
counts in Odoo, or whose original's reversal is in another month (shown in both months: a supplier correction pulled
before acceptance takes the rs.ge operation date, and with a monthly bill sequence core books it on that month's last
day, [account_move.py:7530](../addons/account/models/account_move.py#L7530); since `440f495` it is re-dated to the day
the acceptance is recorded, so this warning is mainly for bills of the old flow); bills waiting on rs.ge (grouped by status; from 1 October 2026 they
must be accepted or rejected before the 5th); posted bills with VAT from Georgian suppliers not linked to rs.ge; ბ II
VAT differs from ა III row 1.

**Original of a supplier correction:** when the correction is accepted, a posted original in an earlier VAT month is
reversed with a credit note dated that day; only an original of the same month is cancelled
([account_move_cancel.py:99-104](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_cancel.py#L99)), so a
declared month never loses VAT afterwards.

Warning (2026-11-05): **"A III row 1 holds VAT without an rs.ge tax invoice in ბ II"** names each posted bill of the
month whose row-1 VAT tag (`ge_24` tax) is on a bill that is not a ბ II row, with its VAT. It catches a deductible tax
picked by hand on a foreign or non-VAT supplier's bill (Odoo proposes it only for VAT Registered suppliers). Vendor
bills only: a supplier credit note with that tag is never listed (accountant decision 2026-11-06; its VAT reaches ბ II
through the correction row of the original invoice).

## Tab 6 — annex ბ III, customs declarations on import (added 2026-11-02)

The portal's ბ III lists the customs declarations whose import VAT the company credits. On the portal the accountant
types only the number; the portal looks it up in the customs system and fills code, date and VAT itself. In Odoo the
tab is filled from PDFs: **one PDF is one row**, nothing is booked. Two PDF types go here (accountant, 2026-11-02): the
regular customs declaration and **Form 4** (simplified import declaration with no assessment box; ბ III takes its
declaration number instead — portal help, [research §4b](../dev_notes/reference/vat_declaration_research_2026.md)).
The type is detected per file and shown in the ტიპი column.

| Column | Regular customs declaration | Form 4 |
|---|---|---|
| შეფასების ნომერი | right of "შეფასების": `A147622` (as printed; the portal help says "digits only") | below box 6 "დეკლარაციის რეგისტრაციის": `20010/2395611` |
| საბაჟოს კოდი | right below box A "გაფორმების საგადასახადო ორგანო": `11111` | the treasury code on the VAT line: `101001000` (user's mapping; the portal may show the office `20010`) |
| შეფასების თარიღი | `dd/mm/yyyy` right of "თარ." | below box 10 "რეგისტრაციის თარიღი": `01.08.2026` (time dropped) |
| დღგ-ის თანხა | right of "გადახდილია სულ": the total paid, **includes duty and excise** when present (user decision) | the line `დღგ -სახაზ. კოდი 101001000 374.04` |

**Why by position:** the PDF's text order glues neighbouring boxes: "იმ 4" and the code "11111" come out as `411111`.
The parser records where each text is drawn (at the `Tj` / `TJ` operator, because pypdf 5 on Python 3.13+ reports the
text only when its block ends) and picks, per anchor, the nearest item on the same line or right below that matches the
value's pattern; a value not found stays empty, never its neighbour ("თარ.", "ლარი", the treasury code). Both real
samples give the same values under PyPDF2 2.12.1 and pypdf 5.4.0. Code: `action_gec_customs_upload`
([gec_vat_declaration.py:829](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L829)), `_gec_customs_row_vals` ([:851](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L851)), `_gec_parse_pdf`
([:856](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L856)).

**Flow:** Upload PDFs (draft only) saves the declaration first, uploads the files, creates one `gec.vat.customs.line`
per PDF and links each PDF to the declaration (with its company). A file that is not a readable PDF stops the upload
and nothing is created; a PDF of neither type gives an empty row and a warning, and a PDF whose date cannot exist (31/02/2026) gives a row with an empty date to type. Rows stay editable; Generate keeps them.

**Documents app (optional), two ways:** with `gec_vat_declaration_documents` (installs itself with `documents`):

| Direction | What happens |
|---|---|
| VAT → Documents | every PDF uploaded on tab 6 becomes a document in **Finance / საბაჟო დეკლარაციები** or **Finance / ფორმა 4** (by type), with the declaration's company, view-only for internal users, no public link |
| Documents → VAT | **Generate** of month M also takes PDFs dropped into those two folders (or their subfolders) in the Documents app when: the PDF's own date is in M; it was uploaded from the 1st of M to the 15th of M+1 (user's time zone); it was uploaded by a user working in the declaration's company; it is not already on this declaration, also not as an earlier version. A PDF in those folders that cannot be read or shows no date is named in a ბ III warning (type its row by hand; 2026-11-10); one dated in another month is left out silently |

Example on 10 November: customs PDF dated 16.10 uploaded 3 Nov → October; Form 4 dated 01.08 → no (August, window
closed); customs dated 04.11 → November's declaration; customs dated 28.10 uploaded 17 Nov → no (after the 15th).
The folders hold all months; there are no month subfolders: the month comes from inside each PDF.

**Warnings:** ბ III total differs from ა III row 2 (import VAT, filled from bills with `18% Import` / tag 25(T)); a value
was not found in a PDF; the same number twice; a date outside the month.

Example: sample PDF `A147622`, office 11111, 16.10.2026, 827.75 + 1,433.65 (two goods items, tax type 28 at 18 %) =
2,261.40 paid. With no customs bill booked, Odoo's ა III row 2 is 0 and the first warning shows the gap.

## Tabs 7 and 8 — annex ბ IV (auction / enforcement purchases) and ბ V (barter before 2021), typed (added 2026-11-02)

Typed rows only (user decision), model `gec.vat.ref.line` with `grid` b4 / b5 (one model for the simple reference
grids, technical design T6). Columns as on the portal: ბ IV document number, seller TIN and name, owner TIN and name,
purchase date, VAT; ბ V declaration number, supplier TIN and name, period (month and year), VAT. Warnings (never
blocking, from the portal note that these annexes cap ა III): ა III row 8 above the ბ IV total; row 7 above the ბ V
total. Tab 9 (ბ VII, authority decisions) comes later with its own source document.

## Tabs 10 and 11 — annex ბ VIII (turnover corrections) and ბ IX (reverse-charge corrections), typed (added 2026-11-12)

Both annexes list reductions under Tax Code Art. 179 of an operation declared in an earlier month: ბ VIII a taxed
operation that had no tax invoice, ბ IX a reverse-charged operation. Columns as on the portal: declaration number,
reporting period, VAT amount. Same model as tabs 7 and 8 ([`gec.vat.ref.line`](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_invoice_line.py), `grid` b8 / b9).

- **The user types the number, Odoo fills the month.** When a VAT declaration of the same company has that
  **Portal Number**, the row's period becomes that declaration's month (`_compute_period`). On ბ IX a reverse-charge
  calculation (III-19) with that number is looked up next, as the portal accepts both there. No match: the period is
  empty and the user types it, which is the normal case for declarations filed before Odoo.
- **The month follows the number.** Changing the number of a ბ VIII / ბ IX row recomputes the period (and empties it
  when the new number matches nothing). A period typed in the same save is kept.
- **The amount is typed.** It is the size of this month's reduction, which Odoo cannot know.
- **ბ IX total = Part III cell 10**, as on the portal (its tab 11 script writes the grid total into `COL_10`). The cell
  is locked and is refreshed when the tab is saved and at Generate. ბ VIII feeds no cell: on the portal it only caps
  cell 7 together with ბ I, and Odoo has no warning for that cap.

Example: November 2026, ბ IX row `76497385`, a declaration filed in Odoo for 09.2026 with that Portal Number: the
period shows 09.2026; amount typed 40.00. Part III cell 10 = 40.00, cell 16 rises by 40.00, cell 17 falls by 40.

## Tabs 13 and 14 — petroleum tax invoices (ნსაფ), added 2026-11-07

Tab 13 lists the petroleum invoices the company issued, tab 14 the ones it received. `gec_vat_declaration` draws the
grids and owns the models; **`rs_spec_invoice` fills them at Generate**. Without that module the tabs hold typed rows
only: Generate in `gec_vat_declaration` never touches them.
Petroleum invoices are excluded from ბ I ([:539](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L539)) and, for bills, from ბ II (tab 5).

**Rows:** `gec.vat.invoice.line` with `part = spec_sale` (tab 13) or `spec_purchase` (tab 14)
([gec_vat_invoice_line.py:3](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_invoice_line.py#L3)), the ბ I / ბ II columns plus seven new fields
([:30-36](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_invoice_line.py#L30-L36); `korect_series` and `korect_number` exist since tab 4):

| Column | Field |
|---|---|
| Operation date | `operation_date` |
| Corrected invoice series / number / date | `korect_series`, `korect_number`, `korect_date` (`korect_date` is new) |
| Departure / destination station code | `station_from`, `station_to` |
| Product code (4 digits) | `product_code` |
| Litres / kilograms | `quantity_l`, `quantity_kg` |

The advance sub-grids (`spec13_advance`, `spec14_advance`) hold typed rows only: no ნსაფ advance link exists.
Grid layouts: `GRID_LAYOUT` `spec13` ([gec_vat_rows.js:128](../custom_addons/gec_odoo_modules/gec_vat_declaration/static/src/components/gec_vat_rows/gec_vat_rows.js#L128)),
`spec14` ([:141](../custom_addons/gec_odoo_modules/gec_vat_declaration/static/src/components/gec_vat_rows/gec_vat_rows.js#L141)), advance grids
([:137](../custom_addons/gec_odoo_modules/gec_vat_declaration/static/src/components/gec_vat_rows/gec_vat_rows.js#L137), [:150](../custom_addons/gec_odoo_modules/gec_vat_declaration/static/src/components/gec_vat_rows/gec_vat_rows.js#L150)).
Totals: `b13_amount`, `b13_reduce_amount`, `b13_advance_amount`, `b14_*`.

| Point | Rule | Why |
|---|---|---|
| Tab 13: which invoices | customer invoices (`out_invoice`) with `rs_einv_is_spec`, an rs.ge number and rs.ge status 2 / 3 / 8 | the portal lists accepted invoices; same status set as ბ I |
| Tab 13: which month | `_gec_b1_month`: the invoice date, a correction in the month the buyer accepted it | copies ბ I (assumption below) |
| Tab 13: VAT | category S tax lines (`_gec_rs_vat`); a correction row is the change against `rs_einv_replaces_id` | what rs.ge receives, as ბ I |
| Tab 13: other columns | buyer Tax ID (`rs_einv_buyer_tin`); stations from `rs_spec_start_site_id` / `rs_spec_end_site_id` (site code); litres and kg from the invoice header (`rs_spec_quantity_l`, `rs_spec_quantity_kg`) | the ნსაფ header holds them |
| Tab 14: which bills | vendor bills (`in_invoice`) with `rs_einv_is_spec` imported from the Received Petroleum Invoices inbox, rs.ge status 2 / 3 / 8 | the portal lists accepted invoices; same status set as ბ II |
| Tab 14: which month | the bill's accounting date (`date`) | copies ბ II (assumption below) |
| Tab 14: VAT | category S tax lines (`_gec_rs_vat`); a correction is the change against `rs_einv_replaces_id` | as ბ II |
| Tab 14: other columns | supplier Tax ID (`rs_einv_seller_tin`); stations from the bill's sites; litres and kg from the bill's first rs.ge line snapshot (`rs_einv_pulled_line_ids`: `g_number`, `rs_g_number_alt`) | a bill has no litre / kg fields of its own |
| Product code | `rs_spec_ssf_code` of the product on the invoice's fuel line | filled by Sync Petroleum Products |
| Typed rows | kept at Generate, as in ბ I / ბ II | a paper invoice has no Odoo document |

Code: `rs_spec_invoice` overrides `action_generate` ([rs_spec_invoice/models/gec_vat_declaration.py:7](../custom_addons/gec_odoo_modules/rs_spec_invoice/models/gec_vat_declaration.py#L7), super first)
and rebuilds the rows that have a `move_id` for both parts by running `_gec_b1_scan(spec=True)` and `_gec_b2_scan(spec=True)`
([`_gec_b1_scan`](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L531),
[`_gec_b2_scan`](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L637): the flag flips
the `rs_einv_is_spec` term of their domains, nothing else) and adding the ნსაფ columns per row
(`_gec_spec_row`, [:21](../custom_addons/gec_odoo_modules/rs_spec_invoice/models/gec_vat_declaration.py#L21)).

**Warnings:** the same set as ბ I / ბ II, prefixed `13:` / `14:` (not on rs.ge; left out by rs.ge status; cancelled in Odoo
but confirmed on rs.ge; a correction counted in its acceptance month; accepted but still a draft; a cross-month correction).
The ბ II "bills not linked to an rs.ge invoice" warning stays on ბ II only: an unlinked bill cannot be told petroleum or not.

Example (prod1, 2026-11-07): tab 13 for 2026-11 lists ეს 1400033 (code 0110, 1 L, VAT 270.00), ეს 1400034 (code 2709,
VAT 216.00) and ეს 1400354 (code 0110, VAT 18.00). Tab 14 for 2024-10 lists ეა 8442582 (code 0270, 1 L / 1 kg, VAT 0.15,
stations 1110177 → 1110177) after Accept.

**Assumption [not confirmed]:** the month rule copies ბ I (tab 13) and ბ II (tab 14); the accountant has not confirmed it yet.

**Gotcha:** the product code and the stations come from the product (`rs_spec_ssf_code`, filled by Sync Petroleum
Products) and from the site records. An invoice made before the sync shows an empty code until the next Generate after a sync.

## Tab 15 — petroleum stock balances (annex III-10 part III), added 2026-11-11

Tab 15 ("ფაქტიურად დარიცხული ნაშთები") is the monthly stock register of ნსაფ products: what was on hand at the start of
the month, what came in, and how it was sold. As with tabs 13/14, `gec_vat_declaration` owns the grid and the row model
`gec.vat.stock.line`; **`rs_spec_invoice` fills it at Generate** (`_gec_spec_stock_rows`, called from its `action_generate`
override). Generate deletes the rows that have products (`product_ids`) and keeps typed rows.

One row per 4-digit code (user 2026-11-11): the ნსაფ products (`rs_spec_rs_id` set, archived products included) that share
`rs_spec_ssf_code` are added into one row, which links them in `product_ids`; a product without a code gets its own row.
The key is one line, `row_of` in `_gec_spec_stock_rows`: returning `product` instead of the code gives one row per product,
with no other change. A row is shown only when one value is not zero.
Every column has a kg and a litre half; a row fills only the half of the product's unit (kg when the unit converts to kg
and not to litres, else litres, the rule of `_compute_rs_spec_quantities`). Annex III-10 part III has one unit per row
("კგ/ლ"), so the other half stays 0.

| Col | Fields | Source | Why |
|---|---|---|---|
| 1 | `product_code` | `rs_spec_ssf_code` | the portal takes the 4-digit code |
| 3 | `opening_*` | done `stock.move.line` up to the end of the day before the month (company time zone): into stock plus, out of stock minus (stock = internal locations and transit locations of a company) | works for fuel not tracked in stock too (no quants there, so core's `qty_available` at a date goes negative); shape of the Romanian SAF-T stock export |
| 4 | `received_*` | done lines in the month from a vendor location (or the company-less inter-company transit) into stock, minus returns | the law says "actually received"; same locations as column 3, so this month's closing is next month's opening |
| 5 | `spec_sold_*` | the tab 13 rows of the same Generate: `rs_spec_quantity_kg` / `_l`; a correction counts its change against `rs_einv_replaces_id` | same invoices and months as tab 13 |
| 6 / 7 | `sold_*`, `sold_amount_*` | posted `out_invoice` / `out_refund` product lines of ნსაფ products with `rs_einv_is_spec` off, accounting date in the month, line discount 0; amount = `price_total` in GEL (`_rs_amount_to_gel`) | invoices only, user 2026-11-11 (POS: see Gotchas); amount with VAT = what the customer paid |
| 8 / 9 | `discount_sold_*`, `discount_amount_*` | the same lines with a line discount above 0 | the line discount % is the only discount rs.ge accepts (negative discount lines are refused at send) |
| 10-12 | `own_use_*`, `processed_*`, `closing_*` | never filled (user 2026-11-11); `closing_*` read-only as on the portal | typed on the portal |

Credit notes count only when their `reversed_entry_id` is an ordinary invoice: a refund of a ნსაფ invoice belongs to tab 13,
and a fuel credit note with no original is left out with the warning "… a petroleum credit note without an original invoice
is not in tab 15".

Grid: `GRID_LAYOUT.stock15` carries an explicit `header` (5 rows of label / colspan / rowspan, as the portal prints it);
the template draws `layout.header` when present and the one-level `headTop` / `headSub` header otherwise.

Example (scratch copy of the demo DB, 2026-11-11, October 2026): diesel in litres, 10,000 received and 3,000 delivered in
September, 5,000 received and 200 returned in October, ნსაფ 1,000, plain invoice 300 L (885.00), discounted invoice 200 L
at 10 % (531.00), a credit note of 50 L on the plain invoice → row 0110: opening 7,000, received 4,800, ნსაფ 1,000, sold 250 / 737.50,
discount 200 / 531.00. Bitumen in kg, not tracked in stock, 500 received in September and 100 in October → row 2713:
opening 500, received 100.

**Gotchas:**
- Every posted fuel customer invoice becomes a ნსაფ (rs_spec_invoice `_rs_spec_mark_before_post`) unless it skips rs.ge or was
  sent as an ordinary e-invoice, so columns 6-9 mostly hold credit notes and invoices posted outside the form (a POS order
  invoice, auto-post: both go through `_post`, which skips the marking).
- POS session closing posts an `out_invoice` / `out_refund` with `_post` (addons/point_of_sale/models/pos_session.py:1001-1004,
  :1116), but by default its lines carry no product (closing lines are grouped by account unless the POS setting
  "Closing Entry by Product" is on, pos_order.py:1282-1327), so till sales are not counted. With that setting on, fuel till
  sales would count as sales without discount (the closing line has no discount %), and a refund session move would be
  left out with the "no original invoice" warning.
- A transit location without a company (core "Inter-company transit", the delivery and receipt location of sister
  companies) is treated as outside stock: a delivery to it lowers the opening, a receipt from it counts as received.
- Inventory adjustments and scrap are in no column: column 12 would not equal the stock.
- Two products can share one 4-digit code (two SSN codes, prod1 has 7 such codes); they share one row. A kg product and a
  litre product with one code fill the kg and litre halves of that row.

## Tab 17 — III-19⁶, the margin scheme (rebuilt 2026-10-28 on fixed assets)

A VAT payer that resells second-hand goods, works of art, collectors' items or antiques pays VAT on the margin only:
per row, VAT = (sale price − purchase price) ÷ 1.18 × 0.18, a loss row counting 0. The row total goes to ა I row 1¹ and
Part III. The four categories exclude each other in the law (Tax Code Art. 157: "secondary goods" are used goods other
than art, collectibles and antiques). The accountant books these goods as **fixed assets** (decided 2026-10-28), so
the category is on the asset.

**The accountant's flow**

| Step | Where | What Odoo keeps |
|---|---|---|
| 1. Buy | Vendor bill, description-only line on a fixed-asset account (one line per item, quantity 1), usually no tax | Core creates the asset; its **Asset Value** (`original_value`) is the purchase price |
| 2. Classify | Asset form: **Margin Scheme** = Second-hand Goods / Work of Art / Collectors' Item / Antique; model "No depreciation"; Confirm | `gec_margin_scheme` ([account_asset.py](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/account_asset.py)) |
| 3. Sell | Customer invoice, description-only line, no tax; post it | — |
| 4. Link | Asset → Modify Depreciation → **Sell**, pick that invoice line; post the draft "Sale" entry core creates | The invoice line's **Sold Asset** (`gec_sold_asset_id`), written by our extension of core's `set_to_close` |
| 5. Declare | VAT Declaration → Generate | Tab 17 proposes purchase and sale price per category |

Core keeps no link from a sold asset to its invoice line (the Sell action only writes chatter,
[account_asset_variant.py:711-758](../enterprise/account_asset/models/account_asset_variant.py#L711)), hence step 4's
field. A new Sell or Dispose of the same asset (after Set to Running) moves the link; an invoice that was credited keeps
it, so its credit note still shows a warning. Sell refuses an invoice line that already sold another asset that is still
closed (one asset per line; since 2026-11-06). When the wrong asset was sold and then set back to running, selling the
right asset on the same line moves the link to it (2026-11-13). The column is on customer invoice lines (not credit notes), hidden by
default; Margin Scheme shows on assets of Georgian companies only.

**What Generate proposes** (`_gec_margin_scan`, [gec_vat_declaration.py](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py)):
posted invoice lines of the month (accounting date, as ა I) linked to an asset with a category, summed per category.
Sale price = the lines' amount in GEL as booked; purchase price = the asset's Asset Value, counted once: in the month of
the asset's first non-credited invoice line, or together with a sale that was later credited (goods returned and sold
again count the purchase price again in the resale month). The 8 price cells are proposed (wand) and follow Odoo until typed.

Example (scratch DB test): assets 1,000 / 500 / 300 / 200 sold for 1,180 / 618 / 354 / 500 → rows 27.46 / 18.00 / 8.24
/ 45.76, ა I row 1¹ = 99.46.

**Warnings** (never block):

| Warning | Meaning |
|---|---|
| sold with a tax | The line carries a tax: the sale price leaves it out and a VAT tax also reaches Odoo's VAT report (the core "18% Margin Scheme" charges 18% of the full price) |
| no longer closed | The asset was set to running after its sale (sale undone) |
| credit notes cancel margin-scheme sales | Correct the row by hand |
| without a purchase price | Asset Value 0: VAT on the full sale price |
| without VAT and without a category | A sold asset that looks like a margin sale but has no category |
| purchase price already counted | The same asset sold through invoices of two months; only the sale price counts here |
| sold or disposed without a posted invoice line | Core's Sale/Disposal entry of the month has no linked invoice (receipt, Point of Sale, cancelled invoice): type the row if it was a margin sale |
| sold this month on an invoice of another month | Sell done after the invoice's month: the sale belongs to the invoice's month (regenerate or adjust that declaration) |

**Setup rules:** one bill line per item (core makes one asset per line and Sell closes the whole asset) and one asset
per customer invoice line (Sell refuses a line that already sold another closed asset); confirm
the asset before selling (Modify Depreciation shows on running assets only); sell on a customer invoice (the Sell picker
offers invoices only); "No depreciation" model for goods held for resale. If `gec_property_tax_report` (Form 15) is
installed, tick "Exempt from Property Tax" on margin assets, otherwise they enter the property-tax base.

**Not covered / open:** whether rs.ge expects a tax invoice for margin sales and how the margin VAT is booked to
333002 (accountant question #30); assets bought with deductible VAT (the margin scheme normally excludes them; no
warning).

## Reverse-charge VAT calculation — annex III-19 (added 2026-11-04, `5e38484`; locks 2026-11-05)

**What it is:** a separate rs.ge form, "უკუდაბეგვრის წესით დარიცხული დღგ-ის თანხის გაანგარიშება", filed by a
company **not registered for VAT** that buys services from a foreign (non-resident) supplier: it owes 18 % VAT on those
services and pays it by the 15th of the next month, with no deduction (Order 996 Art. 65). A VAT payer declares the
same reverse charge inside the monthly declaration instead (ა II row 1 ← report line `ge_21`), so it does not use this
form: the company contact's **VAT Payer** flag (`gec_vat_payer`) says which one applies, and Generate warns when it is
ticked. Menu: Accounting > Reporting > **Reverse-charge VAT (rs.ge)**; model `gec.vat.rc.declaration`, rows
`gec.vat.rc.line` ([gec_vat_rc_declaration.py](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_rc_declaration.py)).

**Which tax on the bill (accountant 2026-11-04):** VAT payer → "18% Reverse Charge Services" (owed and deducted, net 0);
non-payer → **"Reverse Charge 18% Non-Deductible"** (gec_localization, owed on 333060, cost for the rest). The form
selects bill lines by supplier, product and tax category, not by this tax. Row VAT is 18 % of the amount, as the
portal locks it and as on the VAT declaration (`VAT_RATE`, 2026-11-13; before, the tax's current rate). The tax is read
by its xmlid only for two warnings: it is missing, or a bill declared in Part I carries neither reverse-charge tax, so
Odoo books no VAT for it.

| Part | Content | Source |
|---|---|---|
| I | One row per bill line: foreign supplier, service type, date, amount, VAT | **Generate**: posted vendor bills of the month (accounting date), supplier's country set and not Georgia, product of type Service, amount = line amount in GEL before withholding, VAT = 18 % of the amount; lines with a tax of category E, Z or O (VAT Exempt, 0 %, Out of Scope) are left out (exempt services, Order 996 Art. 65(2); Out of Scope: accountant 2026-11-05). Service type = the line's **Service Type** (optional bill-line column) or the product name. Rows can also be added by hand |
| II | Rows 3-9 for Part I | 3 = Σ VAT; 4 / 5 VAT before / after a correction, proposed by Generate from the month's corrections and editable (a typed value is kept); 6 = 5 − 4 when 5 > 4; 7 = 4 − 5 when 4 > 5; 8 = 3 + 6 − 7, or 0 when 7 > 3; 9 = 7 − 3 when 7 > 3. A search icon beside rows 4 / 5 lists the qualifying lines of the month's corrected bills / replacement bills (live, from `_gec_rc_corrections`); row 3 has none, the Part I table above is its detail. Padlocks show the formula on hover |
| III | Goods transferred to a creditor as collateral (Tax Code Art. 161(1)(b)) | Typed only; VAT = price × rate |
| IV | Rows 3-9 for Part III | as Part II |

Header: **დარიცხვა** = row 8 of II + IV, **შემცირება** = row 9 of II + IV. Primary / Adjusted, Draft / Filed as on the
main declaration. Duplicate copies neither the rows nor rows 4 / 5 of Parts II and IV (they belong to one month); the
next Generate proposes them again. A Duplicate of a filed calculation starts as Adjusted (2026-11-13).

**Locks (2026-11-05):** a Filed calculation and its rows refuse every change on the server (import and API too) until
Reset to Draft, except the Portal Number (2026-11-13); a bill listed on a Filed calculation cannot be deleted (draft calculations just lose the row); typed
amounts cannot be negative (a partial credit note is corrected in rows 4 / 5 or on the portal). Until 2026-11-13
Generate and Mark as Filed re-read the tax's rate for every row and filing was refused while the tax was missing;
since then the rate is fixed at 18 % and only Generate warns. Mark as Filed is refused while an earlier month has a
calculation and no filed one, as on the VAT declaration (2026-11-13).
Since 2026-11-10 Mark as Filed also sets the Tax Return Lock Date of the company and its same-VAT branches, as the
VAT declaration does (shared `res.company._gec_lock_tax_month`), and both forms refuse a month that has not ended yet.
Since 2026-11-11 these checks and the lock run on any save that sets Filed (`_gec_file`, called from `write`; a record created as Filed is created as draft, then filed), the calculation shows the same "not the main branch" warning as the VAT declaration (`res.company._gec_vat_branch_warning`), and a bill listed on a filed calculation cannot be reset to draft.

**Cancellation vs correction (accountant 2026-11-04):**

| Case | In Odoo | On the form |
|---|---|---|
| **Cancellation** (an error: the bill is fully reversed, no new bill) | Credit note, any date | The bill leaves its own month's Part I. If that month is earlier, the credit note's month warns: file an adjusted calculation for it |
| **Correction** (the amount changes) | "Reverse and Create Invoice": open month → dated its last day; closed month → accounting date in the current month, bill date = the original's | The original stays in its own month's Part I; the new bill is never a Part I row; **Generate fills Part II rows 4 / 5** in the credit note's month (VAT before / after, still editable) |

Odoo recognises a correction because core creates the credit notes and the new bills of one "Reverse and Create
Invoice" click in the same transaction (equal `create_date`, same supplier; [models.py:4292](../odoo/orm/models.py#L4292));
core stores no link ([account_move_reversal.py:157](../addons/account/wizard/account_move_reversal.py#L157)). One click
on several bills of a supplier is one group: rows 4 / 5 get the group's totals, and a chain in one month (bill → new bill
→ newer bill) nets to the first and the last VAT. Only **posted** credit notes and new bills count: while the new bill
is still a draft the original looks cancelled, so post it before Generate. Rows 4 / 5 follow Odoo's proposal only while
nobody typed over them (the main declaration's rule); a typed value is kept, with a warning when it differs from
Odoo's figure; a vanished correction resets an untouched value to 0. A replacement later cancelled in full drops out of row 5. Known limit: a script or import that creates, in
one transaction, a supplier's credit note and an unrelated new bill of the same supplier is read as a correction.
Generate reads all companies of the declaration (the company and its same-VAT branches) whatever the company switcher
shows.

**Warnings (never block):** one "Left out of Part I" list with the reason per bill (supplier has no country, no
product, product is not a service, zero or negative amount); partial or unlinked supplier credit notes of the month;
the VAT Payer flag; cancellations (file an adjusted calculation); rows 4 / 5 filled from corrections; other
calculations of the same month; bills declared in Part I without a reverse-charge tax (2026-11-13). A new calculation starts as **Adjusted** when the month already has a filed one.

**Law note [Certain]:** Order 996 Art. 65(5) says Part II is used when, in the reporting period, an amount declared in an
earlier calculation is corrected; the accountant's practice for a cancellation (adjusted original month) differs. Kept
as the accountant decided; see `dev_notes/plans/vat_reverse_charge_declaration_plan_20261104.md` section 5.

## How Things Work Under the Hood

- **Catalog** `gec.vat.cell`: 109 cells (ა I 32, ა II 7, ა III 33, Part III 24, III-19⁶ 13), code = portal input id
  without `control_` (`355_1_5`, `353_43_1`, `358_17`), Georgian label and portal tooltip. Generated from the portal
  capture by `Claude outputs/vat_portal_20261021/tools/gen_cell_csv.py`, which fails unless the counts match. Column
  `formula` (added 2026-11-04 by hand, not by that script): the portal formula of the 49 locked cells, written from
  `compute_cells()` — change both together.
- **Values** `gec.vat.declaration.line`: `value`, `proposed_value` (last proposal), `odoo_value` (Odoo's figure).
- **Row lock** `gec.vat.declaration.row` ([gec_vat_declaration_row.py](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration_row.py)),
  an AbstractModel without fields inherited by the cell lines, the ბ I-V rows and the III-19 rows: create, write and
  delete call `declaration_id._check_draft()`, so a filed declaration refuses every row change on the server (import and
  API too). The declarations' own `write` refuses every key but `state` when filed.
- **Warnings**: `generation_warnings` is computed (cell checks, live) plus `scan_warnings` (the ბ I, ბ II and margin
  scans, written once at Generate). `VAT_RATE` (18) is named once and used by `compute_cells()`; the III-19 form reads
  its rate from the reverse-charge tax.
- **`_gec_report_options()` / `_gec_report_totals()`** ([gec_vat_declaration.py:380](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L380)) — report options with
  `period_type: 'month'` and `tax_unit: 'company_only'` on a sudo report object scoped to the company tree, as core's
  return does ([account_return.py:1951](../enterprise/account_reports/models/account_return.py#L1951)). A `return_period` date would raise: Georgia has no VAT return type.
- **`ODOO_SOURCE`** ([gec_vat_declaration.py:18](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L18)) — portal cell → core line: ა I bases from `ge_1`, `ge_3`…`ge_20`
  (row 1¹ comes from tab 17, not from `ge_2`), ა II from `ge_21`…`ge_23`, ა III totals from `ge_24`…`ge_33`; Odoo's own VAT
  per row is kept beside the portal's 18 % for comparison.
- **`compute_cells()`** ([gec_vat_declaration.py:165](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L165)) — the portal JavaScript formulas in dependency order (margin
  scheme, ა I, ა II, ა III, Part III 1-11, 15 / 16, 17 / 18). Half-up rounding to 2 decimals; 17 / 18 floored. The portal
  reads a negative input as 0 (`parseFloat('0' + value)`), so negatives count as 0 in the formulas, are kept as typed and
  produce a warning.
- **`_gec_fixed_asset_tax_lines()` / `_gec_fixed_asset_vat()`** ([gec_vat_declaration.py:437](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L437)) — the first runs the query and
  returns the VAT and the tax item ids per cell (the drill-down lists those ids), the second caps it. ა III column 5 at Generate: core's
  per-line tax details (`_get_query_tax_details`, [account_move_line_tax_details.py:35](../addons/account/models/account_move_line_tax_details.py#L35)) over the report's own query,
  tax items carrying the row's `NN(T)` tag, base line on a listed account, exigible only — the shape of the generic Tax
  Report's "Account > Tax" grouping ([account_generic_tax_report.py:390](../enterprise/account_reports/models/account_generic_tax_report.py#L390)). Capped at Odoo's row total. Cells in
  `FIXED_ASSET_SOURCE` (:78).
- **`_gec_sync_cell_lines()`** ([gec_vat_declaration.py:483](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_declaration.py#L483)) — proposals first, column 5 before column 4
  (column 4 reads it), then formulas on the merged values; runs on create, Generate and every Save of a draft. Form 30's
  order (formulas before proposals) would leave the cells one save behind.

### Guards
- Company or month cannot change once a cell has a value; a filed declaration, its cells and its annex rows refuse every
  change until Reset to Draft, and no row can be moved into a filed declaration (`declaration_id` write, import, API); a filed declaration cannot be deleted; a bill or invoice listed on a filed declaration
  (ბ I, ბ II, advance offsets, III-19 rows) cannot be deleted; catalog cells cannot be deleted while used
  (`ondelete='restrict'`): never delete a row from `data/gec.vat.cell.csv`, the upgrade fails while any declaration
  holds that cell's line.

---

## Gotchas
- **[Certain] Odoo's VAT Report and this form differ by design** where the portal differs: VAT is base × 18 % (Odoo's own
  VAT per row is shown beside it, with a warning when they differ), and a correction counts when the buyer accepts it.
- **[Certain] Old prod1 invoices sit on tag 2 (`18% S`)** from before the Phase 0 tax fix: a prod1 Generate of those months
  shows ა I row 1 empty and a margin-scheme warning.
- **[Likely] Rounding:** the portal's `round_2` body is not in the capture; half-up is assumed (a 0.01 difference is possible
  on exact half-tetri values).
- **[Certain] A margin-scheme row sold below cost counts 0**, as on the portal (`control_359_sum` builds `'0' + value`),
  so it never lowers Part III.
- **[Certain] The portal itself is inconsistent on ა III row 4¹:** its page-load sum of Part III cell 11 leaves `353_43_1`
  out, its edit-time sum (`control_353_sum`) includes it. The form follows the edit-time sum; check cell 11 on the
  portal when row 4¹ has a value.
- **Cell warnings are live, scan warnings are as of the last Generate.** The ა I / ა II "Odoo VAT ≠ 18 %" warning appears
  only for rows whose base still equals Odoo's. A bill posted after Generate changes the drill-down list, not the stored
  scan warnings, until the next Generate.
- **Recompute runs through the form** (the tab fields). A line written directly by import or RPC is not recomputed until
  the next Save or Generate.
- **[Likely] A correction row carries only the change** (900 reduced, not the new 2,700), and **[Guessing] its month
  column shows the correction's own date**; neither is confirmed against a portal month that holds a correction.
- **[Likely] Final invoices in native advance mode:** rs.ge receives only the regular lines (full VAT), while the row
  takes Odoo's VAT, which nets the down-payment line, and the sub-grid subtracts the advance again. None exist yet on
  prod1; the rule is open.
- **[Certain] ბ III PDFs and deletes:** deleting a ბ III row keeps its PDF on the declaration (and in Documents);
  deleting a declaration deletes its PDFs (core unlinks a record's attachments; with Documents a copy waits 30 days in
  the trash). A Documents "new version" re-links the declaration to the new file while the row keeps the old one.
- **[Certain] ბ III does not book anything:** the uploaded PDFs never reach ა III row 2. Import VAT is credited only by
  a vendor bill with `18% Import` (tag 25(T)); a journal entry doubles it ([l10n_ge.md](l10n_ge.md)).
- **[Likely] Other customs PDF layouts** (export, deferred payment, English prints) were not seen; a layout without the
  four labels gives empty cells and a warning, not wrong values.
- **[Certain] Parser limits:** text drawn with the PDF operators `'` or `"` (next line + show) gets the previous line's
  position in both PyPDF2 and pypdf; the customs PDFs use `Tj` only. A decimal comma ("2261,40") is not read (cell
  empty, warning); commas count only as thousand separators.
- **[Certain] Typing during an upload is lost:** the form is saved before the file dialog opens and reloaded after the
  upload, so anything typed while the files upload is discarded.
- **The acceptance month is the day Odoo learns it:** the reversal, the seller's posted copy and the supplier's copy
  date are all set when Check Status (or the cron, or Accept) runs, not when the buyer clicked on rs.ge. A late Status
  Update moves the correction into the next month. A seller copy whose lines changed after sending, or that fails to
  post, stays a draft with a To-Do and its original stays posted; fix it and click Check Status again.
- **[Certain] ა III column 5 follows the base line's account only.** A tax line shared by an asset line and a minus line
  (down payment, discount) gives the asset its full share, so column 5 is capped at the row total. Core leaves some VAT
  unsplit and it falls into column 4: a journal entry whose tax and base signs differ, tax and base on different partners
  or currencies, a tax that affects the next tax's base, a T tag typed by hand on a non-tax line. A declaration whose
  column 4 was typed with column 5 left empty now adds Odoo's column 5 on the next Generate: re-check such months.
- **Drill-down lists are live, the cells are not:** the cells hold what the last Generate read; the icon reads the
  books now. A bill posted, reset or reversed after Generate makes the list differ from the cell until the next
  Generate. A month filed since 2026-11-06 carries the tax lock date, so tax-affecting postings into it are refused or
  moved by core; a month filed before that, or one with a lock exception, shows today's books in the list.
- **[Certain] Drill-down and branches:** the cells count the company and its same-VAT branches; the list shows a
  branch's items only when that branch is ticked in the company switcher (the list opens with the user's rights, as
  core's own audit and tax return do).
- **[Certain] Drill-down of a shared tax line:** core books one tax item for all base lines of a bill with the same tax
  and tax account (account_tax.py:2363), so a bill with an asset line and an expense line on 18 % has one VAT item.
  Column 5 counts only the asset's share; its list shows the whole item (titled "the tax items differ from the cell"),
  and column 4 then lists the whole row (titled "column 5 differs from its tax items"). Verified 2026-11-04: cell 180,
  item 270.
- **Formula tooltips are text, not code:** the catalog column `formula` repeats `compute_cells()` in portal notation; a
  changed portal formula needs both edits, nothing checks that they agree.
- **Not modelled:** the portal's "18 %" checkbox on ა I (VAT always computed), December cells 19-20 (not in the
  captured form).
- **[Certain] Filing the reverse-charge calculation locks the month for core's manual values:** core's VAT Report then
  refuses a new manual value of ა III row 4¹ (`ge_28`, engine `external`) for that month
  ([account_report.py:8456-8459](../enterprise/account_reports/models/account_report.py#L8456)). It happens only when one
  company files both forms for the same month; III-19 is for companies not registered for VAT, so only in the month of
  registration [Likely, rare]. Type ა III row 4¹ column 4 (cell `353_44_1`) on this form instead.
- **[Likely] A ბ III PDF pulled from Documents stays unlinked:** the row points to the Documents file, whose attachment has
  no `res_model`. Deleting that document and emptying the Documents trash removes the attachment, and the row, filed or
  not, silently loses its PDF link (`attachment_id` is `ondelete='set null'`,
  [gec_vat_invoice_line.py:69](../custom_addons/gec_odoo_modules/gec_vat_declaration/models/gec_vat_invoice_line.py#L69));
  the typed number, date and VAT stay. Do not clean the Finance / საბაჟო დეკლარაციები and ფორმა 4 folders after filing.
- **ბ VIII / ბ IX month lookup is by Portal Number only:** a declaration that gets its Portal Number after the row was
  typed does not fill the month (retype the number); a negative ბ IX amount lowers cell 10 as typed (the portal's
  handling of a negative grid amount is not confirmed).

## Related
- [`vat_declaration_build_plan.md`](../dev_notes/plans/vat_declaration_build_plan.md) · [`vat_declaration_technical_design.md`](../dev_notes/plans/vat_declaration_technical_design.md) ·
  [`vat_declaration_rs_portal_pages.md`](../dev_notes/reference/vat_declaration_rs_portal_pages.md) · [`l10n_ge.md`](l10n_ge.md) (the VAT Report and the tax fixes) ·
  [`gec_income_tax_report.md`](gec_income_tax_report.md) (Form 30, the pattern)

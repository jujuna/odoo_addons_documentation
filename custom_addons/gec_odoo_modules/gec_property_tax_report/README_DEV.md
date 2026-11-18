# gec_property_tax_report: Developer Guide

Odoo 20. Technical name and xmlid prefix `gec_property_tax_report`. rs.ge form **15**,
annex **V-01** — the annual enterprise property tax declaration.

> **In one minute.** One declaration per company and year. `action_generate()` reads
> `account.asset` and the land plot register at click time and builds two sets of lines;
> manual lines survive. Part III is **aggregated by property type × territorial unit ×
> acquisition year**, because the portal offers column 3 as a dropdown, not a free name.
> A model constraint refuses any land row whose rate disagrees with the rs.ge matrix, so
> generation fails as a whole with the list of offenders. `action_export()` runs the
> completeness checks and writes one SpreadsheetML file per part into a Binary field.
> No cron, no journal entries, nothing written back to assets.

Deliberately modelled on `gec_income_tax_report` (rs.ge form 30), which lives in the
separate repo `Gec-Business/odoo-modules`. Read that module's `README_DEV.md` first if
you have not: the classifier mixin, the two-layer validation, the snapshot-line rule and
the grid widget all come from there.

| You want to | Read |
|---|---|
| Find your way around | 1, 2 |
| Understand how a row is built | 4, 5 |
| Understand validation and the export | 6, 7 |
| Understand the trace | 8 |
| Reload the classifiers, extend the module | 9, 11 |
| Know what is still unverified | 10 |

---

## 1. Map of the module

```
__manifest__.py                        depends: account_asset (Enterprise)
models/rs_form15_classifier.py         mixin + 8 classifier models, BASE_NON_AGRI_RATE,
                                       DEFAULT_BUILDING_RATE
models/res_company.py                  rs_form15_is_leasing_company
models/account_asset.py                9 fields + _rs_form15_book_value / _exemption /
                                       _coefficient_exempt, LEASING_RATE_CAP
models/rs_form15_land_plot.py          land master data, _declared_area()
models/rs_form15_declaration.py        PART3/PART4 HEADERS + STYLES, DIFFERENCE_USES_PRORATED,
                                       _number(); declaration + both line models
models/rs_form15_declaration_xlsx.py   second class on the declaration: the workbook
wizard/rs_form15_explain.py            the per-row explanation dialog
data/*.csv                             classifier data; xmlids property_type_<code>,
                                       territory_<code>, exemption_<code>,
                                       land_territory_<code>, land_type_<code>,
                                       land_rate_<terr>_<type>, revaluation_<band>
security/                              ACL csv + 3 multi-company record rules
static/src/components/rs_form15_grid/  base widget (js, xml, scss)
static/src/components/rs_form15_part3_grid/, rs_form15_part4_grid/   two subclasses
tools/generate_classifier_csv.py       regenerates the CSVs from the rs.ge workbooks
tests/test_form15.py                   4 classes, 26 tests
```

### The classifiers

All year-versioned (`valid_from` / `valid_to` as `YYYY` integers, `0` = open) through
`rs.form15.classifier.mixin`. `code` is the ID written into the import file.

| Model | Rows | Source |
|---|---|---|
| `rs.form15.property.type` | 20 | `15_data_1.xlsx` sheet 1. `display_code` (`1.1`) parsed out; `is_immovable`, `is_leasing`. |
| `rs.form15.territory` | 78 | `15_data_1.xlsx` sheet 2, part III |
| `rs.form15.exemption.basis` | 6 | `15_data_1.xlsx` sheet 3; validity parsed from the free-text notes |
| `rs.form15.land.territory` | 263 | `15_data_5.xlsx` sheet 1; `region` / `municipality` split out of the path |
| `rs.form15.land.type` | 11 | `15_data_5.xlsx` sheet 2; `unit`, `uses_base_rate`, `base_rate` |
| `rs.form15.land.rate` | **2 893** | `15_data_5.xlsx` sheet 3. 263 × 11 exactly, so the matrix is **dense** — it is a lookup, not a permission check. |
| `rs.form15.revaluation.coefficient` | 4 | hand-written; `code` is what column 7 carries, including `-` |
| `rs.form15.building.rate` | user | **rs.ge publishes none.** See 5.3. |

---

## 2. Architecture

```
account.asset ──┐
                ├── action_generate() ──> rs.form15.part3.line ──┐
land.plot ──────┘                         rs.form15.part4.line ──┤
                                                                 ├─ _check_matrix (constrains)
rs.form15.land.rate ─────────────────────────────────────────────┘
                                          action_export() ─ _check_lines ─> SpreadsheetML
```

**Two periods, on purpose.** `date_from` is the first day of the reporting year and
computes `date_to` and `tax_year`; `land_reference_date` is a separate required Date,
defaulting to 1 April of the same year, and computes `land_year`. Part III reads
`tax_year`, part IV reads `land_year` — for its rate lookup, its classifier validity and
its export filename. Order 996 art. 88 §4 gives part III the past tax year and §5(კ)
gives part IV the current one as at 1 April, so a single year cannot serve both. The
default keeps them equal; an `onchange` moves 1 April with the period.

`UNIQUE(company_id, date_from)`: a correction is the same record re-generated and
re-flagged `შესწორებული`, never a second record — two records for one year would let two
different files exist for one filing.

Classifier links on a line are **stored snapshots**, never related fields, with
`ondelete='restrict'`. A filed row must stay as filed when a plot or an asset changes.
Archive a classifier, never delete it.

---

## 3. Dependencies: what we read, what breaks

| Module | We rely on | If it changes |
|---|---|---|
| `account_asset` (Enterprise) | `original_value`, `salvage_value`, `already_depreciated_amount_import`, `acquisition_date`, `disposal_date`, `children_ids`, `depreciation_move_ids.depreciation_value`, `state`; view `account_asset.view_account_asset_form`, `view_account_asset_tree` | The book-value reader mirrors core's `_compute_value_residual`; a change to how depreciation is posted changes column 6. |
| `account` | `res.company.currency_id`, `currency.round` | rounding of every money column |
| `base` | view `base.view_company_form` anchored on `currency_id` | the leasing-company flag |
| `web` | `X2ManyField`, `Field`, `Pager`, the `action` service | the grid widgets |
| rs.ge | `15_data_<n>.xlsx`, `temp_15_1_2.xml`, `temp_15_2.xml`, `15_inst_635.pdf` | a new data version: regenerate the CSVs (9) |

---

## 4. Lifecycle

```
draft --action_generate()--> draft        unlink source != 'manual', rebuild
draft --action_export()----> exported     _check_lines() passes, two files stored
exported --action_draft()--> draft
```

`action_generate()` is the only entry point; there is no cron and no `create`/`write`
override anywhere. The generator reads the database as it is at the click, so late data
is picked up only by the next run and hand edits on generated rows are lost at that run.
Everything happens in one transaction: if a constraint fails, the earlier `unlink` rolls
back too.

---

## 5. How rows are built

### 5.1 Part III: `_part3_line_vals()`

Assets read: `state in ('open', 'paused', 'close')`, `parent_id = False`,
`rs_form15_excluded = False`. Gross-increase children are folded into their parent's book
value, exactly as core's `book_value` does, so only parents need tagging.

**Group key**: `(property_type, territory, acquisition_year, object)`. The art. 202(2)
flag is decided per declared object: an immovable row is exempt only when all its assets
are, and a mixed object gets a warning. The acquisition year is in the key because one
row carries one coefficient; it is forced to `0` for a movable type. A missing year option
(2000 and later) is created by `RsForm15Year._for_year(year, create=True)` under the xmlid
`year_<YYYY>` with `noupdate`, so a later CSV row for that year finds it; the row carries a
warning.

**Column 6** is `AccountAsset._rs_form15_average(year)`, the one reader the generator and
the explanation share. For a leasing company's leased-out asset with a base value it is
`base × (dates of {1 Jan, 31 Dec} on which the asset existed) / 2`, existence read from the
acquisition and disposal dates (`_rs_form15_exists_on`), not from the value; otherwise the mean of
`AccountAsset._rs_form15_book_value(date)`:

```
original_value - already_depreciated_amount_import - Σ depreciation_value of posted moves ≤ date
```

plus children recursively; `0` before `acquisition_date` and from
`_rs_form15_disposal_date(variant)` on (the last entry that is not cancelled: a restrictive
audit trail keeps cancelled later entries on the variant, a hashed journal keeps reversed
ones; both are skipped). Archived assets are read (`active_test=False`): Odoo archives only
closed assets. A closed asset whose core `disposal_date` is before the year is not read at
all, and an asset linked to a land plot is never read, whatever its exclusion flag. This
mirrors core's `_compute_value_residual` rather than calling the enterprise helper
`_get_residual_value_at_date`, which returns **0** when no depreciation move precedes the
date and deliberately ignores reversals — not acceptable for a legal filing. A reversal
posts its own move with a negative `depreciation_value`, so summing posted moves nets it
out.

**Column 8**, `_rs_form15_exemption(average)`: an explicit amount wins; otherwise the
international-company months pro-rate the average (`120000 / 12 × 8 = 80000`).

**Column 10**: `rs.form15.building.rate._rate_for(territory, year)` returns
`(rate, from_table)`; a miss falls back to `DEFAULT_BUILDING_RATE = 1.0` and the row gets
a warning. Capped at `LEASING_RATE_CAP = 0.6` when the type is `is_leasing` and the
company is a leasing company.

**Column 12**, `_part3_previous_advances()`: last year's declaration, summed by
`(property_type, territory)`, taking **column 11** — the full-year figure. Order 996
art. 88 is explicit that the next year's current payment is computed on column 11 even
when column 15 applied.

### 5.2 Part IV: `_part4_line_vals()`

One row per plot for which `plot._is_owned_on(land_reference_date)` holds:
`date_acquired <= day < date_sold`, empty bounds open. Both dates are stored computes,
`readonly=False`: a linked `asset_id` supplies `acquisition_date` and
`_rs_form15_disposal_date(main variant)`; an unlinked plot keeps what was typed. Linking an
asset sets its `rs_form15_excluded`, so the land is never valued again in part III;
relinking, unlinking or deleting the plot releases an asset no other plot links. An
archived plot without `date_sold` is left out (the old way of removing a plot). `_rates_for(year)` loads the whole matrix once.
`RsForm15LandType._unit_rate(table_rate)` is the only place the two meanings of the rate
column are reconciled:

```python
return self.base_rate * table_rate if self.uses_base_rate else table_rate
```

Only land type `33` has `uses_base_rate`. Verified against rs.ge's own template row
(`1000 × 0.24 × 1.5 = 360`) and the five rows of a submitted declaration.

### 5.3 Why the building rate table is user data

rs.ge ships 2 893 land rates and **no** part III rates: each municipality introduces its
own, capped at 1% by Tax Code art. 202(1). A hard error on a missing rate — the Form 30
behaviour — would block every filing on data rs.ge does not publish. The fallback is the
cap, which can only overstate the liability, plus a warning. `_seed_year(year)` creates a
capped row for every territorial unit at once.

---

## 6. Validation

Two layers, two moments, as in Form 30.

| Layer | When | Checks | Effect |
|---|---|---|---|
| Matrix | every line save, and when the year changes | classifier valid for the year; a rs.ge rate exists for the pair; the stored rate equals it | `ValidationError` naming every offender; nothing is stored |
| Completeness | export only | territory and type set, area > 0, taxable ≤ area, taxable needs a basis, column 6 non-zero, immovable needs column 5 | `UserError` with up to 40 entries; no file |

Plus two constraints that exist because of what the portal hides or caps:

- `_check_immovable_columns` — a movable type must carry no acquisition year and no
  coefficient, so they go out **empty** rather than as `0` or `1`.
- `_check_rate` — 0 to 1%, or 0 to 0.6% for a leasing company's leased-out property.

Why the matrix runs at save and again at export: line values can be imported, and a rate
rule can be edited after generation. Why completeness runs only at export: an unfinished
manual row must stay saveable.

---

## 7. Export

`_build_xml(lines)` is shared; it asks the recordset for `_rs_form15_headers()`,
`_rs_form15_styles()` and the three style IDs. Adding a part means a model plus one `if`.

| Part | Field | Filename | Columns | Template |
|---|---|---|---|---|
| III | `export_file_3` | `form15_part3_<company tax ID>_<year>.xml` | 15 | `temp_15_1_2.xml` |
| IV | `export_file_4` | `form15_part4_<company tax ID>_<year>.xml` | 9 | `temp_15_2.xml` |

Excel 2003 SpreadsheetML. Rules, all taken from the rs.ge templates:

| Rule | Reason |
|---|---|
| element tags namespace-qualified, `ss:` on attributes | lxml then serialises like the portal's own files |
| every cell `ss:Type="String"` | leading zeros in IDs survive |
| empty cells written as one space | the portal's own export does it; an empty `<Data/>` is untested |
| numbers through `_number()`: `250`, `250.5`, `0` | dot decimal, no trailing zeros |
| **style IDs differ per part** | `temp_15_2.xml` uses s65 table / s64 header / s63 data; `temp_15_1_2.xml` swaps s63 and s64 |
| ID **and** name are both sent | unlike Form 30, which sends IDs only |
| `HEADERS` copied verbatim | columns are read **by position**: change `HEADERS` and `_export_values` together |

---

## 8. The trace

`line._explain()` on both line models returns `{title, formula, steps, sources, warning}`.
The explanation dialog (`rs.form15.explain`, rendered through the QWeb template
`row_explanation`) and the workbook's **Row details** sheet both render that one dict, so
the story and the stored values come from one code path and cannot disagree. For part III
the `sources` list re-reads each asset's book value at 1 January and 31 December, which is
the question an auditor actually asks.

`action_export_explanation()` builds an `xlsxwriter` workbook — Read me, Part III, Part IV,
Row details — into `explanation_file` and returns an `ir.actions.act_url`, so the browser
downloads at once and the file stays on the form. Every click rewrites the slot; there is
no history.

---

## 9. Classifier data and updates

```bash
python3 tools/generate_classifier_csv.py ~/Downloads/15_data_1.xlsx ~/Downloads/15_data_5.xlsx
```

Expected: 20 / 78 / 6 / 263 / 11 / 2893 rows. Sheets are read **by position**, not by
name: rs.ge ships them with typos and stray spaces (`ტერიტორი ულიერთეული(ქონება) `).

Two constants in the script encode judgements, not data:
`IMMOVABLE_TYPE_CODES = {18, 19, 22}` and `LEASING_TYPE_CODES = {21, 22}`.

`RsForm15LandRate.write()` flips the record's `ir.model.data` to `noupdate=True` outside
install mode, so a manager's dated edit survives a future CSV reload.

---

## 10. Take into account

- **Odoo 20 rules that already bit this module.** A non-stored compute cannot appear in a
  search domain — `warning_count` and the four totals had to be `store=True`. `<list>` not
  `<tree>`; `models.Constraint`; `Command`; `env._("text %s", value)`; search views take a
  bare `<group>` around group-by filters.
- **An x2many list defaults to 40 rows.** Both grids set `limit="1000"`; past that, the pager shows and filters and totals cover one page.
- **The portal derives, we cross-check.** Part III columns 11/13/15 and part IV columns
  7/8 are recomputed on import. They are marked `locked` in the widgets (padlock, grey,
  readonly) and a disagreement is a warning, not a blocked export.
- **Part III is aggregated.** Line count is bounded by 20 types × 78 units, whatever the
  asset count.
- **Regeneration deletes generated rows.** Corrections belong at the source.
- **The grid header is data-driven.** A column carrying `group:` merges into a spanning
  header; everything else spans both rows. That is why both parts share one template,
  where Form 30 has one per annex.
- **Georgian text in Python lives in constants, not in `_()`.** `PART3_HEADERS` and
  `PART4_HEADERS` are the portal's own strings and must never be translated.

### Assumptions recorded on 2026-09-21, not verified against a portal upload

| # | Assumption | Where | How to settle it |
|---|---|---|---|
| 0 | `land_reference_date` defaults to 1 April of the year **after** the period | `_onchange_date_from` | Settled by Tax Code art. 205(2) (matsne, version of 2026-10): property for the past year, land for the current tax year. |
| 1 | Column 13 uses column 15 when the year is incomplete | `DIFFERENCE_USES_PRORATED = True` | Type `10` into column 14 on the portal and watch column 13. Order 996 art. 88 §4 ლ says column 15; rs.ge's own sample row in `temp_15_1_2.xml` computes `8 = 9 − 1`, i.e. column 11. |
| 2 | Property type group 5 is leased-out property | `LEASING_TYPE_CODES`, `is_leasing` | Read the parent label of `5.1 მოძრავი` on the portal. Inferred from the group 1 label, „გარდა ლიზინგით გაცემულისა". It drives the 0.6% cap. |
| 3 | `3 დაუმთავრებელი მშენებლობა` is immovable | `IMMOVABLE_TYPE_CODES` | Pick it on the portal and see whether columns 5 and 7 stay visible. |
| 4 | The advance is one payment of the full column 11 total by 15 June | `_compute_next_advance` | Settled by Tax Code art. 205(3), (4), (9). The 25% + 50% and 50/50 splits in older notes are wrong. |

---

## 11. Extension recipes

**Another part.** Add a line model with `_rs_form15_headers()`, `_rs_form15_styles()` and
the three style getters, an `_export_values()`, a `_check_lines()`, an `_explain()`, and one
`if` in `action_export`. The builder needs no change.

**Another generated source for part III.** Add a `source` value, write
`_<thing>_line_vals()` returning dicts with the same keys, add it to the list in
`action_generate_part3`, and set `warning` whenever something is guessed.

**A new grid.** Subclass `RsForm15Grid`, override `columns`, `gridTitle`, `gridSubtitle`,
`gridIcon`, `gridHint`, `explainPart`, and optionally `isCellHidden` and `sourceRecord`.
Register it and use it as a `widget=` on the x2many. No template needed.

**Keep an edited generated row across regeneration.** Add a `keep` Boolean to the line
and exclude it from the `unlink` filter in `action_generate_part3` / `_part4`.

---

## 12. Tests

```bash
odoo-bin -d <disposable db> -i gec_property_tax_report \
  --test-enable --test-tags /gec_property_tax_report --stop-after-init
```

| Class | Covers |
|---|---|
| `TestForm15Classifiers` | row counts of all six generated CSVs, the coefficient-vs-amount split on land type 33, exemption validity windows, the four revaluation bands |
| `TestForm15Land` | the five part IV rows of a submitted declaration, rs.ge's own template row, exemption reducing the taxed area, the matrix constraint, the SpreadsheetML shape |
| `TestForm15Property` | the three part III rows of a submitted declaration, the instruction's partial-year example (1050 → 875), the coefficient, the movable-columns constraint, the 1% cap, untagged assets aborting generation, the book-value reader, the international-company exemption |
| `TestForm15Declaration` | one declaration per year, months bounds, the building-rate fallback and cap, `_seed_year` |

The fixtures are the numbers from `Print.pdf`, `temp_15_2.xml` and the two worked
examples in `15_inst_635.pdf`, so a failure means a real regression, not a changed
opinion.

---

## 13. Questions developers ask

**Why not one row per asset?** Column 3 is a dropdown of 20 property types on the portal,
not a free name. A per-asset row cannot be submitted.

**Why is land not an `account.asset`?** Part IV taxes area × the rate of a zone and land
type, which an asset has nowhere to put. The plot is the tax record; the land's accounting,
when it exists, is the optional `asset_id`, which also supplies the ownership dates.

**Why is the period a Date when the form prints a year?** Odoo house style, and it is
what `gec_income_tax_report` does with `date_from`. The Date is the input; `tax_year` and
`land_year` are stored computes, so every lookup still compares integers. It also makes
the two reference periods expressible, which a single year could not.

**Why `Integer` for classifier validity?** `YYYY` compares correctly and `0` is a natural
"open" value; the classifiers are published per reporting year, not per date.

**Why are classifier links stored and not related?** A related field would rewrite filed
rows when a plot or asset changes. Filed rows must stay as filed.

**Why does the export send both the ID and the name?** Because rs.ge's own templates do.
Form 30 sends IDs only; form 15 does not.

**Why write a space into empty cells?** The portal's own export does it; an empty
`<Data/>` is untested against its importer.

**Why is the tax written at all, if rs.ge recomputes it?** So a mismatch is visible before
you upload, and so the explanation workbook has something to explain.

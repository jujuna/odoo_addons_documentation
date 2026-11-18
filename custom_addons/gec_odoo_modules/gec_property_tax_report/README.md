# Property Tax in Odoo: Guide for Accountants

The annual enterprise property tax declaration, **annex V-01**, built from Fixed Assets
and a land plot register and exported as the two files eservices.rs.ge imports.

> **In one minute.** One declaration per company and year. **Generate** reads your fixed
> assets and your land plots and builds the rows; **Export** writes one file per part.
> Part III is grouped by property type and territorial unit, not one row per asset,
> because the portal offers that column as a dropdown. rs.ge recomputes the tax columns
> itself, so what the module writes there is a cross-check — the numbers that matter are
> the values, the areas and the rates.

---

## 1. What the module does

| Part | Source | What it contains |
|---|---|---|
| **III** | `account.asset` | Property other than land: buildings, machinery, vehicles, computers, construction in progress |
| **IV** | the land plot register | Land, as at 1 April of the filing year (the year after the period) |

Parts I and II of the paper form — your identification, the declaration type and the tax
office's own block — are filled on the portal, not here.

### What it does not do

- It does not submit anything. You upload the two files on eservices.rs.ge.
- It does not post any journal entry. It shows next year's advance (the full column 11
  total, due 15 June, Tax Code art. 205(3)) but does not book it.
- It does not touch your assets or your accounting. Generation only reads.

---

## 2. One-time setup

### 2.1 Tag every asset

**Accounting ▸ Assets**, open an asset, **Property Tax** tab:

| Field | Why |
|---|---|
| **Property Type** | Declaration column 3. A dropdown on the portal, so an untagged asset stops generation by name. |
| **Territorial Unit** | Column 4. It selects the rate. |
| **Exempt from Property Tax** | Ticks the asset out of the declaration entirely — use it for land, which belongs in part IV. |

Optional, on the same tab:

- **Exemption Basis** and **Exemption Amount** — column 9 and column 8.
- **International Company Months** — the exemption is then the average annual value
  pro-rated over the months the status was held. Status granted on 5 May counts from
  1 May, so that year has 8 months.
- **IFRS Revaluation Model** + **Last Audit Date** — while the audit is less than four
  calendar years old, the revaluation coefficient of column 7 does not apply.
- **Leased Out** + **Value at Lease-Out** — see 2.4.

### 2.2 Set the building tax rates

**Accounting ▸ Configuration ▸ rs.ge Property Tax (Advanced) ▸ Building Tax Rates.**

rs.ge publishes no rate table for part III — each municipality sets its own, capped at
1% by Tax Code art. 202(1). A territorial unit with no row **falls back to 1%** and the
declaration line says so in its warning. That can only overstate the tax, never
understate it, but confirm the real rate before filing.

### 2.3 Register your land plots

**Accounting ▸ Configuration ▸ Land Plots.** One record per plot:

| Field | Note |
|---|---|
| Territorial Unit | region / municipality / zone, as rs.ge splits it. The zone decides the rate. |
| Land Type | agricultural kinds are declared in hectares, non-agricultural in square metres |
| Area | column 4 |
| Exemption Basis | leave empty for "შეღავათით არ ვსარგებლობ" |
| Taxable Area | **only** when an exemption applies. Empty means the whole area is taxed. |
| Asset | optional: the same land as booked in Fixed Assets. Its dates are then read from the asset, and the asset is ticked **Exempt from Property Tax** so it is not taxed again in part III. |
| Acquired On / Sold On | the plot is declared only if it was owned on the declaration's **Land as at** date. Bought on 1 April counts; sold on 1 April does not. Empty means owned. Read-only when an asset is linked. |

### 2.4 If you are a leasing company

Tick **Leasing Company** on the company record. Property you lease out is then valued at
its book value when first leased out — type it into **Value at Lease-Out** — and the rate
is capped at **0.6%** instead of 1%, for the whole lease period. The value counts only for
the part of the year the asset existed: nothing after it is sold, half in the year it is
sold or put into use. Without the company flag, Value at Lease-Out is ignored.

For an ordinary company that leases something out, nothing changes: Odoo already carries
the value the asset would have had if it had not been leased out, which is what the law
asks for.

---

## 3. Every year

1. **Accounting ▸ Reporting ▸ Property Tax Declaration (Form V-01)** → **New**.
2. Set **Period** — the first day of the reporting year, 1 January. **Land as at**
   follows it automatically: 1 April of the next year, the year you file in (see below). For a company that existed only part of the year, set
   **Months of Existence** — 1 to 11. A month counts in full when registration falls on or before the
   15th, or deregistration after the 15th. Leave it at 0 for a full year.
3. **Generate**. Both parts are rebuilt. Rows you typed by hand survive.
4. Review the yellow rows. Every one carries a reason.
5. **Export**. One file per part, ready to upload.
6. Optionally **Explanation Workbook** — every row, every step, in one spreadsheet.

**Regenerating deletes the generated rows.** Corrections belong at the source: the asset
tag, the plot, the building rate. A row you typed by hand is kept. Column 12 typed on a
generated row is kept too when Odoo holds no declaration for the previous year.

**Archived assets and plots still count** for the year they had a value or were owned. A
plot archived without a **Sold On** date is treated as removed.

A correction to a filed year is the **same** declaration: reset it to draft, switch
**Declaration Type** to `შესწორებული`, regenerate, export.

---

## 4. Where the numbers come from

### 4.1 Part III

One row per **property type × territorial unit × year acquired**, so several assets of one
kind in one municipality become a single row.

| Col. | Value |
|---|---|
| 3, 4 | the asset's property type and territorial unit |
| 5 | year acquired — **immovable property only**; the portal hides it otherwise |
| 6 | (value at 1 January + value at 31 December) ÷ 2, from the posted depreciation entries, summed over the assets in the row |
| 7 | 3× before 2000, 2× 2000-2003, 1.5× in 2004, `-` from 2005. Unknown year takes 3×. Immovable property only. |
| 8, 9 | the exemption and its legal ground |
| 10 | the building tax rate of that territorial unit, as a percent number (`1`, not `0.01`) |
| 11 | (col. 6 × col. 7 − col. 8) × col. 10% |
| 12 | **last year's column 11** — always the full-year figure, never column 15 |
| 14, 15 | filled only for an incomplete year: col. 11 ÷ 12 × col. 14 |
| 13 | column 15 when it exists, otherwise column 11, minus column 12 |

### 4.2 Part IV

One row per plot owned on the **Land as at** date (see Acquired On / Sold On in 2.3).

| Col. | Value |
|---|---|
| — | the rate and the classifiers are read for the year of **Land as at**, not the period |
| 2, 3 | the plot's territorial unit and land type |
| 4 | the area |
| 5 | the taxable area — **only** when an exemption applies |
| 6 | the exemption basis |
| 7 | the rs.ge table value for that unit and type |
| 8 | taxable area × the rate |

**The trap in column 7.** For non-agricultural land the table value is a **municipal
coefficient**, not an amount: 200 m² at coefficient 1.5 is `200 × 0.24 × 1.5 = 72 GEL`,
and the form shows `1.5`, not `0.36`. For every agricultural kind the value is an
absolute amount in GEL per hectare. The module handles both; you only need to know it
when you check a figure by hand.

---

## 5. Warnings

A yellow row is informative, never blocking.

| Warning | What to do |
|---|---|
| No building tax rate is configured for this territorial unit | Add the row under Building Tax Rates. 1% was used. |
| No rs.ge rate covers this territorial unit and land type | Check the plot's type. The tax is 0. |
| The rs.ge rate for this pair is zero | That is what rs.ge publishes. Usually correct; confirm for an unusual land kind. |

## 6. Errors that stop you

| Message | Cause |
|---|---|
| These assets have no property tax type or territorial unit | Tag them, or tick **Exempt from Property Tax**. The asset form no longer forces the tags, so other asset work is never blocked. |
| Reset the declaration to draft before changing the months of existence | The file is exported; reset to draft first. |
| … rate … does not match the rs.ge table value | Someone edited a rate by hand. Regenerate. |
| … is movable property: the acquisition year and the revaluation coefficient must stay empty | The portal hides both columns for that type. |
| The building tax rate must be between 0 and 1 percent | Tax Code art. 202(1). |
| Column 14 is filled only for an incomplete year | 1 to 11, or 0 for a full year. |
| … has a taxable area but no exemption basis | The portal fills column 5 only with an exemption. |

## 7. Rules worth remembering

- **Part III is by type, not by asset.** Twelve computers in Poti are one row.
- **Column 12 is last year's column 11**, even when last year was a partial one.
- **The portal recomputes** part III columns 11, 13, 15 and part IV columns 7 and 8.
  They carry a padlock on screen.
- **Land is declared from the plot register, by area.** If you also book it in Fixed
  Assets, link that asset on the plot: the dates follow the asset and it stays out of part III.

## 8. Questions

**Why are there two dates on the declaration?**
Because the form reports two different periods. Tax Code art. 205(2): property is
reported for the **past** year, land for the **current** year, the year you file in,
as at 1 April. **Period** drives part III, **Land as at** drives part IV. For the 2025
declaration filed in 2026, Period is 1 January 2025 and Land as at is 1 April 2026.

**Why is my part III row's value not what the asset card shows?**
Column 6 is an average of two dates, not today's book value. The Explanation Workbook
shows both dates per asset.

**An asset was sold in June. What happens?**
Its value at 31 December is zero, so the average halves. That is what the law asks for.

**Can I edit a generated row?**
Yes, while the declaration is in draft — but **Generate** rebuilds it. Fix the source
instead, or add a manual row.

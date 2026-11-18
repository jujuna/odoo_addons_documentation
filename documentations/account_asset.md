# account_asset — Fixed Assets & Depreciation

> **Module:** `account_asset` (enterprise, `auto_install: True`) | **Path:** [`enterprise/account_asset/`](../enterprise/account_asset/)
> Verified against Odoo 20 source on 2026-09-24.

---

## The Core Idea — What Problem Does This Solve?

You buy a laptop for $1,200. It will last 3 years. Should that $1,200 hit your expenses all in January when you bought it? No — because you're going to use it for 36 months. Putting the full cost in January would make January look horribly expensive and the next 35 months look artificially cheap.

The solution: **spread the cost across the months you actually use it.** $1,200 ÷ 36 months = $33.33/month. That's depreciation.

```
WITHOUT depreciation:           WITH depreciation:
Jan:  −$1,200.00                Jan:  −$33.33
Feb:       $0.00                Feb:  −$33.33
Mar:       $0.00                Mar:  −$33.33
...                             ...every month for 3 years
```

**The accounting principle behind this:** match expenses to the period in which they were used (the "matching principle").

---

## Asset or Expense? A Decision Guide

The rule is simple: **will you use it beyond the current accounting period?** If yes → asset. If no → expense.

| Purchase | Decision | Reason |
|---|---|---|
| Laptop, desktop computer | Asset | Lasts 3–5 years |
| Company car or van | Asset | Lasts many years |
| Office furniture | Asset | Lasts many years |
| Building renovation | Asset | Capital improvement, long life |
| Perpetual software license | Asset | Long-term intangible |
| Land | Asset, **`no_depreciation`** model | You own it forever; it does not wear out |
| Printer paper | Expense | Used up immediately |
| Annual software subscription | Expense | Already a monthly/yearly cost |
| Phone bill | Expense | Monthly service, consumed now |

---

## The Two-Level Model — Asset vs Variant

This is the single most important thing to understand about 20.0.

```
account.asset  ──  "the laptop"
  name, company, fixed asset account, asset group, acquisition date,
  original_value, non_deductible_tax_value, the bill lines it came from,
  analytic distribution, Properties
       │
       ├── account.asset.variant  (main variant)   ← Statutory / local GAAP
       │      model_id, state, journal, prorata, salvage, book_value,
       │      value_residual, the depreciation board (depreciation_move_ids)
       │
       ├── account.asset.variant  (ledger variant) ← e.g. IFRS ledger
       │      its own model + its own board, posting only the DIFFERENCE
       │
       └── account.asset.variant  (gross increase child)
              created by a re-evaluation upward; parent_id → main variant
```

`account.asset` ([account_asset.py:11](../enterprise/account_asset/models/account_asset.py#L11)) keeps only the facts that are true regardless of how you depreciate: what it is, what it cost, which bill it came from, which fixed-asset account holds it.

Everything a depreciation schedule needs — the method, the journal, the state machine, the board itself — lives on `account.asset.variant` ([account_asset_variant.py:24](../enterprise/account_asset/models/account_asset_variant.py#L24)).

### How the form still looks like one record

The asset form shows variant data through a **context-selected** variant:

- `main_variant_id` ([account_asset.py:88](../enterprise/account_asset/models/account_asset.py#L88)) — the first variant with no ledger, i.e. the statutory schedule.
- `current_selected_variant_id` ([account_asset.py:102](../enterprise/account_asset/models/account_asset.py#L102)) — reads `variant_id` from the **context**, falling back to the main variant.
- `state`, `method`, `book_value`, `value_residual`, `salvage_value`, `journal_id`, `prorata_date`, `depreciation_move_ids`, `parent_id`, `model_id` on `account.asset` are all **related** to `current_selected_variant_id` ([account_asset.py:108-146](../enterprise/account_asset/models/account_asset.py#L108)).

So opening the asset with `context = {'variant_id': <id>}` shows that ledger's schedule in the same form. The **Main Asset** / **Asset Variants** stat buttons do exactly that ([account_asset.py:609](../enterprise/account_asset/models/account_asset.py#L609), [:633](../enterprise/account_asset/models/account_asset.py#L633)).

### Writes are split automatically

`create()` and `write()` on `account.asset` route each value to the right model via `_split_assets_variants_vals()` ([account_asset.py:446](../enterprise/account_asset/models/account_asset.py#L446)): keys that match a writable, non-related variant field go to `current_selected_variant_id`; the rest stay on the asset. Creating an `account.asset` with no `main_variant_id` implicitly creates its main variant ([account_asset.py:410-437](../enterprise/account_asset/models/account_asset.py#L410)).

> **Practical consequence:** `self.env['account.asset'].create({'name': ..., 'original_value': ..., 'model_id': ..., 'salvage_value': ...})` still works — `model_id` and `salvage_value` silently land on the freshly created variant. But `asset.method_number` does **not** exist; duration lives on `asset.model_id.method_number`.

---

## The Three Numbers That Matter

```
You buy a laptop for $1,200. You estimate it'll be worth $200 as scrap at the end.
Only $1,000 will actually be "used up" over its life.

Original Value        = $1,200   ← what you paid (on account.asset)
Not Depreciable Value = $200     ← salvage (on the variant)
Depreciable Value     = $1,000   ← original − salvage = what gets expensed over time

After 6 months of depreciation ($500 posted):
Depreciable Value (remaining) = $500   ← what's still left to expense
Book Value                    = $700   ← $500 remaining + $200 salvage
```

**Book Value = what your balance sheet shows. It decreases every time a depreciation entry is posted.**

| Name in Odoo | Field | Where it lives | Changes when? |
|---|---|---|---|
| Asset Value | `original_value` | `account.asset` ([:40](../enterprise/account_asset/models/account_asset.py#L40)) | Set at creation from the bill lines + non-deductible tax; editable in Draft only |
| Not Depreciable Value | `salvage_value` | variant ([:120](../enterprise/account_asset/models/account_asset_variant.py#L120)) | Manually, or computed as `original_value × model.salvage_value_percent` |
| Depreciable Value | `value_residual` | variant ([:119](../enterprise/account_asset/models/account_asset_variant.py#L119)) | `original − salvage − already_depreciated_import − Σ posted depreciation_value` |
| Book Value | `book_value` | variant ([:113](../enterprise/account_asset/models/account_asset_variant.py#L113), stored, recursive) | `value_residual + salvage + Σ children.book_value`; the salvage is **released** once the variant closes with every move posted |
| Total Depreciable | `total_depreciable_value` | variant ([:125](../enterprise/account_asset/models/account_asset_variant.py#L125)) | `original_value − salvage_value` |
| Gross Increase Value | `gross_increase_value` | variant ([:127](../enterprise/account_asset/models/account_asset_variant.py#L127)) | `Σ children.original_value` |

> **Important:** `value_residual` and `book_value` only move when entries are **posted**. Draft rows in the board have zero effect. `_compute_value_residual` filters on `state = 'posted'` ([account_asset_variant.py:258](../enterprise/account_asset/models/account_asset_variant.py#L258)).

---

## Asset Lifecycle — From Purchase to Disposal

```
STEP 1: Asset Created
  ┌─────────────────────────────────────────────────────┐
  │  Draft                                              │
  │  Asset + main variant exist, no schedule yet.        │
  │  You can still edit everything.                      │
  └─────────────────────────────────────────────────────┘
                          │
                   Click "Confirm"  (validate)
                          │
                          ▼
STEP 2: Asset Running
  ┌─────────────────────────────────────────────────────┐
  │  Running (open)                                     │
  │  Full board generated as account.move records.      │
  │  Past-dated moves posted now; future moves flagged  │
  │  auto_post='at_date' and posted by the 2 AM cron.   │
  └─────────────────────────────────────────────────────┘
       │          │            │              │
    Pause      Sell        Dispose      New Depreciation
       │          │            │        (adds a ledger variant)
       ▼          ▼            ▼
STEP 3: Paused  Closed      Closed
  Depreciation  Asset sold. Asset scrapped.
  frozen.       Gain/loss.  Loss if book value > 0.
       │
    Resume  →  back to Running
```

| Status | Technical | Meaning |
|---|---|---|
| Draft | `draft` | Created, not started. Everything editable |
| Running | `open` | Active. The board exists; entries post on schedule |
| On Hold | `paused` | Frozen. Paused days accumulate and shift future entries |
| Closed | `close` | Fully depreciated, sold, or disposed |
| Cancelled | `cancelled` | Posted entries reversed/cancelled, drafts deleted, `asset_paused_days` reset |

`state` is defined on the variant ([account_asset_variant.py:59](../enterprise/account_asset/models/account_asset_variant.py#L59)): `draft` / `open` / `paused` / `close` / `cancelled` — templates never appear as a `state` value, since they are separate `account.depreciation.model` records. The asset-level `state` is a computed mirror of the selected variant ([account_asset.py:108](../enterprise/account_asset/models/account_asset.py#L108)); `main_variant_state` ([:94](../enterprise/account_asset/models/account_asset.py#L94)) is what the list view colors on.

### Confirm cascades across variants

`account.asset.validate()` ([account_asset.py:508](../enterprise/account_asset/models/account_asset.py#L508)):

- On the **main** variant: confirms **every draft variant** of the asset at once (unless the asset is itself a gross-increase child), logs "Asset created", and posts a note on each source bill.
- On a **ledger** variant: refuses unless the main variant is already `open` — *"Cannot confirm current asset while main asset is not running"*.

Then `variant.validate()` ([account_asset_variant.py:660](../enterprise/account_asset/models/account_asset_variant.py#L660)) sets `state = 'open'`, builds the board if empty and the method is not `no_depreciation`, re-runs `_check_depreciations`, and posts everything not yet posted.

---

## The Depreciation Board Tab

The board is a **pre-generated set of `account.move` records**, one per period, created the moment you confirm. Think of a loan amortization table in reverse.

| Column | Field on `account.move` | Meaning |
|---|---|---|
| Depreciation Date | `date` | Last day of the period this entry covers |
| Ref | `ref` | `"<asset name>: Depreciation"` |
| Depreciation | `depreciation_value` ([account_move.py:24](../enterprise/account_asset/models/account_move.py#L24)) | Expense recognized **this period only**. Editable while draft, on the main variant |
| Cumulative Depreciation | `asset_depreciated_value` ([:18](../enterprise/account_asset/models/account_move.py#L18)) | Running total from start through this row |
| Remaining Value | `asset_remaining_value` ([:17](../enterprise/account_asset/models/account_move.py#L17)) | What's left to depreciate **after** this row. Hidden on ledger variants |
| Journal Entry | `name` | Link to the actual move |

Visual cues: blue = draft, normal = posted, muted = cancelled. Source: [account_asset_views.xml:143-158](../enterprise/account_asset/views/account_asset_views.xml#L143).

Both cumulative fields are computed together in `_compute_depreciation_cumulative_value` ([account_move.py:51](../enterprise/account_asset/models/account_move.py#L51)) by walking the variant's moves in date order — they are **not stored**.

### Draft vs. Posted

**Draft row** = planned, not yet in your books. Zero effect on P&L, balance sheet, or the header values.

**Posted row** = recorded:
```
Debit   Depreciation Expense (P&L)      $1,000
Credit  Accumulated Depreciation (BS)   $1,000
```

### The Board In Action

**Machine: $12,000, 12 monthly periods, no salvage, starting Jan 1**

```
Row  | Date     | Depreciation | Cumulative | Remaining | Status
-----|----------|-------------|------------|-----------|-------
1    | Jan 31   | $1,000      | $1,000     | $11,000   | Posted  ← date passed
2    | Feb 28   | $1,000      | $2,000     | $10,000   | Posted
3    | Mar 31   | $1,000      | $3,000     |  $9,000   | Posted
4    | Apr 30   | $1,000      | $4,000     |  $8,000   | Draft   ← auto_post='at_date'
...
12   | Dec 31   | $1,000      | $12,000    |      $0   | Draft
```

### Prorata — Partial First Period

**Laptop $1,000, 10 monthly periods, starting March 10**

```
Date       | Amount  | Cumulative | Remaining
-----------|---------|------------|----------
Mar 31     |  $71.00 |    $71.00  |  $929.00   ← partial month (Mar 10–31)
Apr 30     | $100.00 |   $171.00  |  $829.00
...
Dec 31     | $100.00 |   $971.00  |   $29.00
Jan 31     |  $29.00 | $1,000.00  |    $0.00   ← asset closes
```

**Why 11 rows for 10 periods?** The partial first month plus the leftover in January together make one full $100 month. The total is always exactly $1,000.

### The Last Row Must Reach Zero

Enforced by `_check_depreciations` ([account_asset_variant.py:332](../enterprise/account_asset/models/account_asset_variant.py#L332)), and the rule now differs by variant kind:

- **Main variant**: the last move's `asset_remaining_value` must be 0 — *"The remaining value on the last depreciation line must be 0"*.
- **Ledger / child variant**: the last move's `asset_depreciated_value` must be 0 — *"The depreciated value on the last depreciation line for variant must be 0"* (its board holds differences, which must net out).

### What Happens Every Night (Auto-Posting)

`compute_depreciation_board()` ([account_asset_variant.py:463](../enterprise/account_asset/models/account_asset_variant.py#L463)) creates the moves and calls `_post()` on all of them for `open` variants. `account.move._post(soft=True)` posts anything dated up to today and, for future-dated moves, sets `auto_post = 'at_date'` instead of posting ([account_move.py:6244-6250](../addons/account/models/account_move.py#L6244)).

The nightly job is **`account.ir_cron_auto_post_draft_entry`** ([service_cron.xml:3](../addons/account/data/service_cron.xml#L3)), scheduled daily at 02:00, running `model._autopost_draft_entries()`. `account_asset` ships **no cron of its own**.

### How the Board Is Computed

1. `compute_depreciation_board(date=False)` ([account_asset_variant.py:463](../enterprise/account_asset/models/account_asset_variant.py#L463)) — unlinks draft moves (from `date` onward if given), then per variant:
2. `_recompute_board(start_depreciation_date)` ([:476](../enterprise/account_asset/models/account_asset_variant.py#L476)) loops from `paused_prorata_date` to the asset's last day, one period at a time:
   - `_get_end_period_date()` ([:537](../enterprise/account_asset/models/account_asset_variant.py#L537)) — month end for `method_period = '1'`, fiscal-year end for `'12'`.
   - `_compute_board_amount()` ([:394](../enterprise/account_asset/models/account_asset_variant.py#L394)) — the amount for that period, per method.
   - `already_depreciated_amount_import` is consumed out of the first rows before any move is emitted.
   - `_prepare_move_for_asset_depreciation()` ([account_move.py:319](../enterprise/account_asset/models/account_move.py#L319)) builds the 2-line move vals.
3. The collected vals are `create()`d, then `_post()`ed for `open` variants.

Note the **ordering gotcha**: `compute_depreciation_board` deletes drafts for the *whole recordset* first, then recomputes per variant — so calling it on a multi-variant recordset is safe, but calling it on a ledger variant whose main variant has no moves yet raises *"Cannot generate depreciation board for ledger variant before main asset variant"* ([account_asset_ledger_variant.py:128](../enterprise/account_asset/models/account_asset_ledger_variant.py#L128)).

---

## Depreciation Methods

`method` lives on the depreciation model ([account_depreciation_model.py:38](../enterprise/account_asset/models/account_depreciation_model.py#L38)).

### `linear` — Straight Line

Equal amounts every period, proportional to days.

```
Monthly expense = Total to depreciate ÷ Number of months
$1,000 over 10 months = $100/month
```

`_get_linear_amount()` ([account_asset_variant.py:380](../enterprise/account_asset/models/account_asset_variant.py#L380)) computes it by **cumulative subtraction** — "what should be depreciated by the end of this period" minus "what should have been depreciated before it" — so rounding never drifts and the last row still lands on zero.

**Duration or rate.** New in 20.0: `method_mode` ([:54](../enterprise/account_asset/models/account_depreciation_model.py#L54)) is `duration` or `rate`. In `rate` mode you type an annual/monthly **percentage** into `method_rate`, and the inverse stores `method_number = 1 / rate` ([:238](../enterprise/account_asset/models/account_depreciation_model.py#L238)). Because `1/0.0278 = 35.9712`, the display logic in `_get_rounded_duration()` ([:382](../enterprise/account_asset/models/account_depreciation_model.py#L382)) hunts for the shortest rounding that still renders as the rate you typed — so "2.78 % per month" shows as **36 periods**, not 35.97.

**When to use:** furniture, buildings, equipment — anything that ages evenly.

### `degressive` — Declining Balance

A fixed **percentage of whatever's left** (`method_progress_factor`), so more expense early.

```
Rate = 30% per year
Year 1: $1,000 × 30% = $300 → $700 remaining
Year 2: $700  × 30% = $210 → $490 remaining
Year 3: $490  × 30% = $147 → $343 remaining
...never reaches zero on its own
```

The implementation prorates the factor across the fiscal year (`days in period / days in fiscal year`), so monthly periods under a yearly factor come out smooth rather than lumpy.

**When to use:** vehicles, computers, technology.

### `degressive_then_linear` — Declining then Straight Line

`max(degressive, linear)` each period, so it switches to straight line the moment straight line becomes larger. This guarantees the asset reaches exactly zero. `_degressive_linear_amount()` ([account_asset_variant.py:1030](../enterprise/account_asset/models/account_asset_variant.py#L1030)).

Gross-increase children of a `degressive_then_linear` parent get a derived depreciable base so they **switch at the same moment as the parent** ([account_asset_variant.py:437-458](../enterprise/account_asset/models/account_asset_variant.py#L437)).

**When to use:** required by law in some countries (France, Belgium…).

### `no_depreciation` — new in 20.0

The asset is tracked but never depreciated: land, works of art, assets parked pending capitalization. Selecting it zeroes `method_number`, `method_progress_factor`, `salvage_value_percent` and forces `prorata_computation_type = 'constant_periods'` ([account_depreciation_model.py:267](../enterprise/account_asset/models/account_depreciation_model.py#L267)). `validate()` skips board generation entirely, and the Journal / Prorata fields are hidden on the form.

To start depreciating it later, use the wizard's **Activate Depreciation** action (below).

---

## Prorata Computation

`prorata_computation_type` ([account_depreciation_model.py:6-10](../enterprise/account_asset/models/account_depreciation_model.py#L6)), copied onto the variant and overridable there.

| Value | Label | How it works |
|---|---|---|
| `daily_computation` | Based on days per period | Real calendar days: `(end - start).days + 1` |
| `constant_periods` | Constant Periods | Every month = 30 days, every year = 360 days |
| `none` | No Prorata | `prorata_date` is snapped to the **fiscal year start**, so the first period is always full |

`_get_delta_days()` ([account_asset_variant.py:551](../enterprise/account_asset/models/account_asset_variant.py#L551)) implements the 30-day arithmetic:

```
start_prorata = (days_in_start_month - start_day + 1) / days_in_start_month
end_prorata   = end_day / days_in_end_month

delta = start_prorata × 30
      + end_prorata   × 30
      + (end_year  - start_year)      × 360
      + (end_month - start_month - 1) × 30
```

`prorata_date` is computed from `acquisition_date` ([:233](../enterprise/account_asset/models/account_asset_variant.py#L233)) and is `readonly=False` — you can override it. `paused_prorata_date` ([:242](../enterprise/account_asset/models/account_asset_variant.py#L242)) is `prorata_date` shifted forward by `asset_paused_days`, and it is what the board actually counts from.

---

## Multi-Ledger Depreciation (new in 20.0)

If your company runs more than one book — local GAAP plus IFRS, or a separate tax book — you can depreciate the same asset differently in each without duplicating the asset.

A **ledger** in 20.0 is an `account.journal.group`, set on a journal via `journal_id.journal_group_id` (labelled **Ledger**, [account_journal.py:257](../addons/account/models/account_journal.py#L257)). `company.has_ledger` is True as soon as any journal group exists ([company.py:592](../addons/account/models/company.py#L592)); that's what drives `asset.is_multi_ledger_company`.

### How it works

- A variant becomes a **ledger variant** purely because its journal belongs to a journal group — `is_ledger_variant = bool(journal_id.journal_group_id)` ([account_asset_ledger_variant.py:37](../enterprise/account_asset/models/account_asset_ledger_variant.py#L37)). There is no separate model; [`account_asset_ledger_variant.py`](../enterprise/account_asset/models/account_asset_ledger_variant.py) is an `_inherit` extension of `account.asset.variant`.
- A ledger sub-variant's board holds **only the difference** against the main variant. `_mirror_main_variant_moves()` ([:111](../enterprise/account_asset/models/account_asset_ledger_variant.py#L111)) adds a counter-entry for every main-variant move: merged into the sub-variant's own move when the dates match, otherwise emitted as a standalone move posted to the **recovery account**.
- So `book_value` on a ledger variant is `main_variant.book_value − its own posted depreciation` ([:68](../enterprise/account_asset/models/account_asset_ledger_variant.py#L68)), and `_get_own_value_residual()` ([:222](../enterprise/account_asset/models/account_asset_ledger_variant.py#L222)) adds the countered main-variant depreciation back to recover the sub-asset's own depreciable base.
- One variant per ledger per asset, enforced by `_check_unique_ledger_per_asset` ([:86](../enterprise/account_asset/models/account_asset_ledger_variant.py#L86)).

### The recovery account

`recovery_account_id` ([account_asset_ledger_variant.py:19](../enterprise/account_asset/models/account_asset_ledger_variant.py#L19), income type) absorbs the reversal of excess depreciation when the statutory book catches up, or when the asset is disposed of. It is **required** on any depreciation model whose journal belongs to a ledger — `_check_ledger_recovery_account` ([account_depreciation_model.py:251](../enterprise/account_asset/models/account_depreciation_model.py#L251)).

### Adding a ledger schedule

The **New Depreciation** button (`action_depreciation_ledger`, [account_asset.py:646](../enterprise/account_asset/models/account_asset.py#L646)) opens [`depreciation.ledger.wizard`](../enterprise/account_asset/wizard/depreciation_ledger_wizard.py). It requires at least one journal linked to a ledger (otherwise a `RedirectWarning` sends you to Journals) and refuses if the main variant uses `no_depreciation`. `apply()` creates the variant via `asset._create_variants()` and confirms it.

Accounts default from the depreciation model's `ledger_*` accounts, falling back to whatever the main variant posts to ([depreciation_ledger_wizard.py:48](../enterprise/account_asset/wizard/depreciation_ledger_wizard.py#L48)).

### Closing

A ledger sub-variant **cannot be disposed of on its own** — *"A ledger sub-asset is closed together with its asset. Dispose of the asset instead."* Closing the main variant closes them via `_close_with_main_variant()` ([account_asset_ledger_variant.py:192](../enterprise/account_asset/models/account_asset_ledger_variant.py#L192)), which checks each sub-variant's own journal lock date and unwinds its entries against the recovery account rather than booking a sale.

---

## Depreciation Models (Templates)

`account.depreciation.model` ([account_depreciation_model.py:13](../enterprise/account_asset/models/account_depreciation_model.py#L13)) is the template record — the depreciation configuration that one or many assets point to via `model_id`. It inherits `mail.thread`, and `company_id` is **optional** — leave it empty and the model is available to every company.

**Menu:** Accounting → Configuration → **Accounting** → Depreciation Models ([account_depreciation_model_views.xml:189](../enterprise/account_asset/views/account_depreciation_model_views.xml#L189)).

### What it stores

| Field | Purpose |
|---|---|
| `method` | `linear` / `degressive` / `degressive_then_linear` / `no_depreciation` |
| `method_mode` | `duration` or `rate` (linear only) |
| `method_number` (Float) | Number of periods |
| `method_period` | `'1'` = monthly, `'12'` = yearly |
| `method_rate` | Non-stored percentage input; inverse writes `method_number = 1/rate` |
| `method_progress_factor` | Declining factor |
| `prorata_computation_type` | Default prorata mode for assets using this model |
| `salvage_value_percent` | Default salvage as a fraction of original value |
| `journal_id` | **`company_dependent`** — one model shared across companies posts to each company's own journal |
| `ledger_depreciation_account_id` / `ledger_expense_account_id` / `ledger_recovery_account_id` | Accounts used when this model drives a ledger variant (all `company_dependent`) |

### Auto-generated names

`name` is computed from the configuration unless you type your own (`is_name_custom`), via `_get_default_name()` ([:207](../enterprise/account_asset/models/account_depreciation_model.py#L207)) — e.g. `30%, 5 Year Declining then Linear Daily Computation, 10% salvage (IFRS Journal)`. Typing a name that happens to equal the generated one clears the custom flag again.

### Models freeze once used

`write()` ([:289](../enterprise/account_asset/models/account_depreciation_model.py#L289)) only allows a small editable set (`active`, `name`, `journal_id`, `prorata_computation_type`, `salvage_value_percent`, the three ledger accounts). Changing anything else while an asset in this company is `open`/`paused`/`close` raises *"Cannot update a depreciation model that has non-draft or non-cancelled assets."* — or, if another company is the one holding those assets, *"Cannot update a depreciation model being used by another company."*

`has_locking_assets` ([:95](../enterprise/account_asset/models/account_depreciation_model.py#L95)) exposes that state to the UI.

> **Consequence for re-evaluation:** because models are frozen, the Re-evaluate wizard cannot edit the model. It searches for an existing model matching the new duration, and if none exists **copies** the model with `active = False` ([asset_modify.py:279-300](../enterprise/account_asset/wizard/asset_modify.py#L279)). Expect a population of archived, single-use depreciation models in any database that re-evaluates assets.

### Pre-loaded models

[`data/account.depreciation.model.csv`](../enterprise/account_asset/data/account.depreciation.model.csv) ships five: `no_depreciation`, and 3 / 5 / 10 / 20 year linear (yearly periods). `_post_init_hook` ([__init__.py:10](../enterprise/account_asset/__init__.py#L10)) then loads chart-template-provided values for `account.account.depreciation_model_id` / `asset_depreciation_account_id` / `asset_expense_account_id` and for the models themselves.

---

## Creating Assets From Vendor Bills

This is the main flow. **20.0 removed the `create_asset` selection** — configuration is now "does this account have a depreciation model?", and the answer is binary.

### Setup on the fixed asset account

Chart of Accounts → edit the account ([account.py:9](../enterprise/account_asset/models/account.py#L9)):

| Field | Effect |
|---|---|
| `depreciation_model_id` | **The switch.** Set it and bills posted on this account create assets. Domain excludes ledger-journal models |
| `asset_depreciation_account_id` | Accumulated Depreciation account. **Required** unless the model is `no_depreciation` |
| `asset_expense_account_id` | Depreciation Expense account. Same requirement |
| `ledger_depreciation_model_ids` | Extra models, one per ledger — each creates an additional ledger variant on every auto-created asset |
| `asset_properties_definition` | `PropertiesDefinition`; the per-asset custom fields shown as `asset_properties` |
| `can_create_asset` | Computed. **True only for `account_type == 'asset_fixed'`** (not `asset_non_current`) |

`_check_unique_ledger_depreciation` ([account.py:59](../enterprise/account_asset/models/account.py#L59)) rejects `ledger_depreciation_model_ids` entries whose journal has no ledger, and rejects two models pointing at the same ledger.

### The automatic flow

`account.move._post()` → `_auto_create_asset()` ([account_move.py:216](../enterprise/account_asset/models/account_move.py#L216)):

```
Post an invoice/bill
  ↓
For each line: account.can_create_asset AND account.depreciation_model_id
               AND price_total > 0, not a tax line, no asset yet
  ↓
Create account.asset (Draft) with the line's name, analytic distribution,
  acquisition_date = invoice_date, model_id = line.depreciation_model_id
  ↓
_create_variants(account.ledger_depreciation_model_ids)   ← one variant per ledger
  ↓
asset.validate()      ← ALWAYS. No "create in draft" option
  ↓
Chatter note on both the asset and the bill; non-deductible tax note if any
```

**When auto-creation does NOT trigger:**

- Account type isn't `asset_fixed` (so **not** `asset_non_current`)
- The account has no `depreciation_model_id`
- `price_total` is zero or negative
- The line is a tax line (`tax_line_id`)
- The line already has assets
- It's a customer invoice/refund whose account is in the `asset` internal group
- The move isn't an invoice, or isn't posted

**Two hard errors worth knowing:**

- A line with no `name` and no product → *"Journal Items of \<account\> should have a label in order to generate an asset"*.
- A depreciating model without both asset accounts set → *"Account \<x\> should have accumulated depreciation and depreciation expense accounts set in order to generate an asset"*.

### Per-line model override

`account.move.line.depreciation_model_id` ([account_move.py:442](../enterprise/account_asset/models/account_move.py#L442)) defaults from the account but is editable on the bill line (shown when the account has a model and the move is an invoice). So one bill can create a 3-year asset and a 5-year asset from two lines on the same account.

### Editing the bill afterwards

`_auto_update_asset()` ([account_move.py:276](../enterprise/account_asset/models/account_move.py#L276)) re-syncs name, company, currency, analytic distribution, acquisition date and model onto **draft or cancelled** assets, then re-validates them. Assets whose line moved to a non-fixed-asset account get cancelled. Running assets are **not** touched — the form shows a warning to that effect ([account_asset.py:313](../enterprise/account_asset/models/account_asset.py#L313)).

### Manual: Turn a Journal Item Into an Asset

Journal Items list → Action → **Turn as an asset** (`turn_as_asset`, [account_move.py:454](../enterprise/account_asset/models/account_move.py#L454)). It requires one company, one account, all lines posted, `can_create_asset`, and the account fully configured — otherwise a `RedirectWarning` sends you to the account.

---

## Pause and Resume

**Pause** (`pause()` on the wizard, [asset_modify.py:446](../enterprise/account_asset/wizard/asset_modify.py#L446) → variant `pause()`, [account_asset_variant.py:818](../enterprise/account_asset/models/account_asset_variant.py#L818)):

1. `_create_move_before_date(pause_date)` posts a partial depreciation for the days used in the current period and drops the future drafts.
2. `state = 'paused'`.

**Resume** (`resume_after_pause()` → the wizard in `resume` mode → `modify()`):

1. Counts days between the last depreciation date (or acquisition date) and the resume date, **minus one** — pausing and resuming the same day is zero days.
2. Adds them to `asset_paused_days`, sets `state = 'open'`.
3. `paused_prorata_date` shifts by that total, so the whole remaining board slides forward.
4. Resuming on or before the pause date raises *"You cannot resume at a date equal to or before the pause date"*.

Resuming the **main** variant resumes every paused variant of the asset ([asset_modify.py:307-322](../enterprise/account_asset/wizard/asset_modify.py#L307)).

---

## Selling or Disposing

Both go through `set_to_close(invoice_line_ids, date, message)` ([account_asset_variant.py:690](../enterprise/account_asset/models/account_asset_variant.py#L690)). Dispose passes no invoice lines; Sell passes the customer invoice line(s).

Guards: the disposal date must be after `company._get_user_fiscal_lock_date(variant.journal_id)`, and you cannot **sell** an asset that still has a running gross increase — *"Please use 'Dispose' on the increase(s)"*.

The variant **and its gross-increase children** are closed together, then `_get_disposal_moves()` ([:945](../enterprise/account_asset/models/account_asset_variant.py#L945)) builds one closing move each. `_get_disposal_line_datas()` ([:997](../enterprise/account_asset/models/account_asset_variant.py#L997)) produces the (amount, account) pairs:

```
(original_value,      fixed asset account)
(depreciated_amount,  accumulated depreciation)
(invoice amounts,     per invoice-line account)     ← sale only
(difference,          company.gain_account_id or loss_account_id)
```

`difference = -original_value - depreciated_amount - invoice_amount`; positive → gain account, negative → loss account.

### Disposing (scrapping)

```
1. Final partial depreciation entry up to the disposal date
2. Closing entry:
   DR  Accumulated Depreciation    (all depreciation posted so far)
   DR  Loss on Disposal            (remaining book value)
   CR  Fixed Asset Account         (original cost)
```

### Selling

```
1. Final partial depreciation entry up to the sale date
2. Closing entry:
   DR  Accumulated Depreciation
   CR  Fixed Asset Account         (original cost — off the books)
   CR  Sale proceeds account(s)    (from the invoice line)
   CR  Gain on Sale                (sold above book value)
   -- or --
   DR  Loss on Sale                (sold below book value)
```

`net_gain_on_sale` ([account_asset_variant.py:138](../enterprise/account_asset/models/account_asset_variant.py#L138)) is stored as `|Σ invoice line balances| − book_value`.

**Example:** cost $1,200, accumulated $900, book value $300, sold for $400 → gain $100.

Gain/loss accounts live on `res.company` ([res_company.py:10](../enterprise/account_asset/models/res_company.py#L10)) and are editable inside the wizard, which writes them back to the company via inverse ([asset_modify.py:114](../enterprise/account_asset/wizard/asset_modify.py#L114)).

`disposal_date` ([account_asset_variant.py:133](../enterprise/account_asset/models/account_asset_variant.py#L133)) is stored on close as the latest move date.

---

## Re-evaluating an Asset

**Modify Depreciation** button → `asset.modify` wizard, action `modify` ([asset_modify.py:263](../enterprise/account_asset/wizard/asset_modify.py#L263)). You can change duration/rate, `value_residual`, `salvage_value`, and the fixed asset account.

Guards: the date must be after the journal's lock date, and there must be **no unposted depreciation dated on or before** the operation date — *"There are unposted depreciations prior to the selected operation date, please deal with them first."*

### Value goes UP

1. `_create_move_before_date(date)` posts depreciation up to the operation date.
2. A model matching the new duration is found or copied (archived).
3. A **positive_revaluation** move is posted, dated `date + 1 day`: debit the fixed asset account, credit `account_asset_counterpart_id`.
4. A **new `account.asset`** is created for the increase, whose main variant has `parent_id = the original variant` — the gross-increase child. It depreciates over the parent's **remaining** days (`_compute_lifetime_days`, [account_asset_variant.py:208](../enterprise/account_asset/models/account_asset_variant.py#L208)).
5. The parent's board is recomputed for the remaining life.

The child shows under the **Gross Increase** stat button; the child itself shows a **Parent Asset** button.

### Value goes DOWN

1. Depreciation posted up to the date.
2. A **negative_revaluation** move reduces the book value now, flagged `asset_value_change = True`.
3. Future amounts are recomputed lower. `_get_linear_amount()` explicitly spreads each recorded decrease across the remaining lifetime so the curve stays smooth.

### Activate Depreciation (new in 20.0)

For an asset held on a non-depreciating footing (`no_depreciation` model, or parked on the wrong account). `activate_depreciation()` ([asset_modify.py:473](../enterprise/account_asset/wizard/asset_modify.py#L473)):

1. Validates that `new_account_asset_id` is itself configured to create assets (else `RedirectWarning` to the account).
2. Posts a transfer move: debit the **new** fixed asset account, credit the old one, for the full book value.
3. Closes the old variant and links that move to it.
4. Creates a **new `account.asset`** with `origin_asset_id` = the old asset, `original_value` = the transferred book value, and confirms it.

The old asset gets an **Active Asset** button (`derived_asset_ids`), the new one an **Original Asset** button (`origin_asset_id`) — [account_asset.py:53-65](../enterprise/account_asset/models/account_asset.py#L53).

---

## Non-Deductible Taxes and Asset Cost

Some jurisdictions disallow part of a tax (Belgium: 50% of car-related VAT). The non-deductible portion must be capitalized.

```
Car purchase: $10,000 + $2,100 VAT (50% non-deductible)
Non-deductible portion: $2,100 × 50% = $1,050
original_value = $10,000 + $1,050 = $11,050
```

`_compute_non_deductible_tax_value()` ([account_asset.py:244](../enterprise/account_asset/models/account_asset.py#L244)) converts each line's `non_deductible_tax_value` to the asset currency at the line's date and scales it by `deductible_percentage`. `_compute_value()` ([:201](../enterprise/account_asset/models/account_asset.py#L201)) adds it to `related_purchase_value`, and `_post_non_deductible_tax_value()` ([:678](../enterprise/account_asset/models/account_asset.py#L678)) posts a chatter note explaining the gap. The form also shows the tax-excluded figure inline next to Asset Value.

`_compute_value()` raises *"All the lines should be posted"* if any source bill line sits on a draft move.

---

## Migrating From Another System

Use `already_depreciated_amount_import` ([account_asset_variant.py:127](../enterprise/account_asset/models/account_asset_variant.py#L127)) for assets that were already partly depreciated elsewhere.

**Example:** $1,000 asset, $800 already depreciated in the old system.

- Set `already_depreciated_amount_import = 800`
- `value_residual` starts at `1000 − salvage − 800`
- `_recompute_board()` consumes the 800 out of the leading periods (skipping whole rows if needed) so no entry is emitted for already-expensed time
- Only the remaining $200 generates new journal entries

For creation-time imports there are two write-only helpers on `account.asset`, `import_account_depreciation_id` and `import_account_depreciation_expense_id` ([account_asset.py:149-156](../enterprise/account_asset/models/account_asset.py#L149)), which seed the main variant's accounts when the fixed-asset account cannot supply them.

---

## Asset Groups

`account.asset.group` ([account_asset_group.py:4](../enterprise/account_asset/models/account_asset_group.py#L4)) — a name, an optional company, and the assets pointing at it. Purely organizational; no effect on depreciation.

> **Note:** there is **no menu and no `ir.actions.act_window`** for asset groups in this module. You reach them only through the `asset_group_id` field on the asset form (quick-create from the dropdown), or via the group's own `action_open_linked_assets()`.

`asset_group_id` is tracked and indexed ([account_asset.py:37](../enterprise/account_asset/models/account_asset.py#L37)), and it works as a groupby/filter in the asset list.

---

## Where to Find Everything in Odoo

| Menu / Location | Purpose |
|---|---|
| Accounting → **Accounting → Assets & Liabilities → Assets** | The asset list ([account_asset_views.xml:322](../enterprise/account_asset/views/account_asset_views.xml#L322)) |
| Asset form → **Asset** tab | Values, fixed asset account, group, depreciation model, prorata, journal, analytic, Properties |
| Asset form → **Depreciation Board** tab | Every scheduled entry, past and future (hidden until entries exist) |
| Asset form → **Bills** tab | The source journal items (`original_move_line_ids`) |
| Asset form → **Modify Depreciation** | Dispose / Sell / Re-evaluate / Pause / Activate Depreciation |
| Asset form → **New Depreciation** | Add a ledger variant (multi-ledger companies only) |
| Asset form → stat buttons | Main Asset, Asset Variants, Linked Assets, Journal Items, Depreciation entries, Gross Increase, Original Asset, Active Asset, Parent Asset |
| Accounting → Configuration → **Accounting → Depreciation Models** | Create/edit templates |
| Accounting → Configuration → **Accounting → Multi-Ledger** | `account.journal.group` records = ledgers |
| Chart of Accounts → edit account | `depreciation_model_id` + the two asset accounts = the auto-creation switch |
| Accounting → Reporting → **Statement Reports → Depreciation Schedule** | The asset report ([assets_report.xml:4](../enterprise/account_asset/data/assets_report.xml#L4), [menuitems.xml:3](../enterprise/account_asset/data/menuitems.xml#L3)) |
| Journal Items list → Action → **Turn as an asset** | Manually convert posted items |
| Asset list → Action → **Confirm** / **Compute Depreciation** | Server actions for bulk work ([account_asset_views.xml:324-346](../enterprise/account_asset/views/account_asset_views.xml#L324)) |

---

## Common Mistakes and How to Avoid Them

**"No asset was created when I posted the bill"**
→ The account must be type **Fixed Asset** (`asset_fixed` — `asset_non_current` is not enough in 20.0) **and** have `depreciation_model_id` set **and** have both asset accounts set. Also check the line has a label and a positive amount.

**"I'm looking for the Save as Model button"**
→ Gone. Create the template directly under Configuration → Accounting → Depreciation Models.

**"I can't edit the depreciation model — Odoo says it has assets"**
→ Models freeze once any asset in your company is open/paused/closed. Create a new model, or use Modify Depreciation on the asset (which copies the model for you).

**"The Depreciable Value in the header isn't changing"**
→ It only moves on **posted** entries. Drafts don't count.

**"I have 10 periods but 11 rows in the board"**
→ Normal with prorata. The partial first period plus the leftover last period make one full period.

**"Book Value is 0 even though I set a salvage value"**
→ Once the variant is closed with every move posted, `_compute_book_value` subtracts the salvage — it was released at disposal.

**"I can't sell this asset"**
→ Dispose its gross-increase children first, or the wizard refuses to automate the entry.

**"I can't confirm the IFRS variant"**
→ Confirm the main (statutory) variant first. Ledger variants mirror it and cannot run ahead of it.

**"I can't dispose of just the IFRS schedule"**
→ By design. Dispose the asset; the ledger sub-assets close with it.

**"I can't delete the asset"**
→ Only `draft` / `cancelled` assets with no posted entries can be deleted. Note that plain `unlink()` on an `account.asset` actually deletes the **selected variant** unless you pass `context = {'delete_asset': True}` ([account_asset.py:374](../enterprise/account_asset/models/account_asset.py#L374)).

**"I changed the accumulated depreciation account and the board didn't follow"**
→ Only `analytic_distribution` propagates to draft entries ([account_asset_variant.py:370](../enterprise/account_asset/models/account_asset_variant.py#L370)); account or journal changes do not. The accounts come from the fixed-asset account, not from the asset.

---

## The Journal Entries Behind the Scenes

**Every depreciation period** — `_prepare_move_line_for_asset_depreciation()` ([account_move.py:372](../enterprise/account_asset/models/account_move.py#L372)) builds exactly two lines:
```
Debit   Depreciation Expense (P&L)          $100    ← account_depreciation_expense_id
Credit  Accumulated Depreciation (BS)       $100    ← account_depreciation_id
```
The analytic distribution of the asset is copied onto both lines when set.

**Your balance sheet:**
```
Assets:
  Equipment (original cost)          $1,200
  Less: Accumulated Depreciation      ($300)
  Net Book Value                       $900
```

**At disposal (scrapping):**
```
Debit   Accumulated Depreciation     $1,000
Debit   Loss on Disposal               $200
Credit  Equipment Account            $1,200
```

**At sale (sold for $250, book value $200):**
```
Debit   Accumulated Depreciation     $1,000
Credit  Equipment Account            $1,200
Credit  Sale proceeds (AR)             $250
Credit  Gain on Sale                    $50
```

Every asset move carries `asset_move_type` ([account_move.py:33](../enterprise/account_asset/models/account_move.py#L33)): `depreciation`, `purchase`, `sale`, `disposal`, `positive_revaluation`, `negative_revaluation`.

### Reversing a posted depreciation entry

`_reverse_moves()` ([account_move.py:147](../enterprise/account_asset/models/account_move.py#L147)):

- If a draft entry still exists → its `depreciation_value` **increases** by the reversed amount.
- If none exists and the variant isn't closing → a new draft entry is created one period after the last date.
- The reversal move inherits `asset_variant_id` and a negated `asset_number_days`, and the asset chatter logs it.

### Resetting the bill to draft

`button_draft()` ([account_move.py:196](../enterprise/account_asset/models/account_move.py#L196)) cancels `open` assets linked to the move and **unlinks** draft ones. `button_cancel()` ([:190](../enterprise/account_asset/models/account_move.py#L190)) archives (`active = False`) every asset created from the move's lines.

---

## Technical Reference

### `account.asset` — the header

| Field | Type | Notes |
|---|---|---|
| `name` | Char | Computed from the first bill line, stored, editable; tracked, translatable |
| `company_id` | Many2one | Required |
| `is_multi_ledger_company` | Boolean | Related `company_id.has_ledger` — drives the New Depreciation button |
| `account_asset_id` | Many2one | Fixed Asset Account. Computed from the bill lines; **form domain requires `depreciation_model_id != None`** |
| `asset_group_id` | Many2one | Optional grouping, tracked, indexed |
| `original_value` | Monetary | `related_purchase_value + non_deductible_tax_value`; editable in Draft |
| `related_purchase_value` | Monetary | `Σ line.balance × line.deductible_percentage`, excluding tax lines |
| `non_deductible_tax_value` | Monetary | Capitalized non-deductible tax, stored readonly |
| `acquisition_date` | Date | `min(invoice_date or date)` over the bill lines, else today |
| `original_move_line_ids` | Many2many | The source journal items (`asset_move_line_rel`) |
| `asset_properties` | Properties | Definition from `account_asset_id.asset_properties_definition` |
| `origin_asset_id` / `derived_asset_ids` | M2o / O2m | Set by Activate Depreciation: old asset ↔ new asset |
| `linked_assets_ids`, `count_linked_asset`, `warning_count_assets` | computed | Other assets sharing the same bill lines; the warning turns the button red when one is already confirmed |
| `variant_ids`, `variant_count`, `variant_ledger_names`, `warning_sub_assets` | O2m / computed | The schedules and their ledger labels |
| `main_variant_id`, `is_main_variant`, `main_variant_state`, `main_variant_model_name`, `main_variant_parent_id` | | The statutory schedule and shortcuts to it |
| `current_selected_variant_id` | computed + `search=` | Context-driven (`variant_id`); the source of every related field below |
| `state`, `method`, `model_id`, `book_value`, `value_residual`, `salvage_value`, `gross_increase_value`, `already_depreciated_amount_import`, `prorata_date`, `prorata_computation_type`, `journal_id`, `parent_id`, `depreciation_move_ids`, `*_count` | related | All proxy `current_selected_variant_id` ([account_asset.py:108-146](../enterprise/account_asset/models/account_asset.py#L108)) |
| `import_account_depreciation_id` / `import_account_depreciation_expense_id` | M2o, `store=False` | Creation-time seeds for the main variant's accounts |

`_inherit = ['mail.thread', 'mail.activity.mixin', 'analytic.mixin']` — so `analytic_distribution` is an asset-level field, computed from the bill lines weighted by balance ([:263](../enterprise/account_asset/models/account_asset.py#L263)).

### `account.asset.variant` — the schedule

| Field | Notes |
|---|---|
| `model_id` | Required, `ondelete='restrict'`. Computed from the bill line's or account's model while Draft |
| `method`, `method_mode`, `method_number`, `method_period`, `method_progress_factor`, `salvage_value_percent` | All **related** to `model_id` — read-only on the variant |
| `state` | `draft` / `open` / `paused` / `close` / `cancelled` |
| `journal_id` | Computed from `model_id._get_journal(company)`, stored, readonly |
| `name` | `asset.name` for the main variant, `"<asset> - <journal>"` otherwise |
| `prorata_computation_type`, `prorata_date`, `paused_prorata_date` | See [Prorata Computation](#prorata-computation) |
| `account_depreciation_id` / `account_depreciation_expense_id` | From the fixed asset account; ledger variants fall back to the model's `ledger_*` accounts, then the main variant's |
| `recovery_account_id` | Ledger variants only |
| `book_value` (stored, recursive), `value_residual`, `salvage_value`, `total_depreciable_value`, `gross_increase_value` | See [The Three Numbers](#the-three-numbers-that-matter) |
| `already_depreciated_amount_import` | Migration seed |
| `asset_lifetime_days` (computed, recursive), `asset_paused_days` | Total schedule length in days; accumulated pause |
| `disposal_date` | Stored on close = latest move date |
| `net_gain_on_sale` | Stored at sale |
| `parent_id` / `children_ids` | Gross-increase hierarchy, **variant → variant** |
| `depreciation_move_ids` | The board (`account.move.asset_variant_id`) |
| `is_ledger_variant`, `journal_group_name` | From `journal_id.journal_group_id` |
| `depreciation_entries_count` (posted), `total_depreciation_entries_count` (all), `gross_increase_count` | Stat button counters |

### `account.move` fields added by this module

| Field | Purpose |
|---|---|
| `asset_variant_id` | `account.move.asset_id` does not exist in 20.0; this is its replacement. `ondelete='cascade'` |
| `depreciation_value` | Expense for this period; computed + inversable |
| `asset_depreciated_value` / `asset_remaining_value` | Non-stored cumulative columns, computed together |
| `asset_depreciation_beginning_date` | Start of the period this entry covers |
| `asset_number_days` | **Marked deprecated in the source** — don't build on it |
| `asset_value_change` | True for revaluation entries |
| `asset_move_type` | Computed, stored: depreciation / purchase / sale / disposal / positive_revaluation / negative_revaluation |
| `asset_ids`, `count_asset`, `asset_id_display_name`, `draft_asset_exists` | Assets created from this move's lines |

On `account.move.line`: `asset_ids` (M2m), `non_deductible_tax_value`, `depreciation_model_id`, `display_depreciation_model`.

### Key methods

| Method | File | What it does |
|---|---|---|
| `validate()` | [account_asset.py:508](../enterprise/account_asset/models/account_asset.py#L508) | Confirms; cascades to all draft variants from the main one |
| `validate()` | [account_asset_variant.py:660](../enterprise/account_asset/models/account_asset_variant.py#L660) | `state='open'`, build board, check, post |
| `compute_depreciation_board()` | [account_asset_variant.py:463](../enterprise/account_asset/models/account_asset_variant.py#L463) | Drops drafts, regenerates, posts |
| `_recompute_board()` | [account_asset_variant.py:476](../enterprise/account_asset/models/account_asset_variant.py#L476) | The period loop; returns move vals |
| `_compute_board_amount()` | [account_asset_variant.py:394](../enterprise/account_asset/models/account_asset_variant.py#L394) | Amount for one period, all four methods |
| `_get_linear_amount()` | [account_asset_variant.py:380](../enterprise/account_asset/models/account_asset_variant.py#L380) | Cumulative-subtraction linear amount (no rounding drift) |
| `_degressive_linear_amount()` | [account_asset_variant.py:1030](../enterprise/account_asset/models/account_asset_variant.py#L1030) | `max(degressive, linear)` |
| `_get_end_period_date()` | [account_asset_variant.py:537](../enterprise/account_asset/models/account_asset_variant.py#L537) | Month end or fiscal-year end |
| `_get_delta_days()` | [account_asset_variant.py:551](../enterprise/account_asset/models/account_asset_variant.py#L551) | Day count (actual or 30-day month) |
| `_get_last_day_asset()` | [account_asset_variant.py:577](../enterprise/account_asset/models/account_asset_variant.py#L577) | End of the full schedule (parent's, for children) |
| `_get_residual_value_at_date()` | [account_asset_variant.py:1053](../enterprise/account_asset/models/account_asset_variant.py#L1053) | Interpolated theoretical value at any mid-period date |
| `_create_move_before_date()` | [account_asset_variant.py:850](../enterprise/account_asset/models/account_asset_variant.py#L850) | Partial depreciation up to a date (pause / sell / dispose / re-evaluate) |
| `_cancel_future_moves()` | [account_asset_variant.py:929](../enterprise/account_asset/models/account_asset_variant.py#L929) | Deletes drafts, reverses posted entries after a date |
| `_get_disposal_moves()` | [account_asset_variant.py:945](../enterprise/account_asset/models/account_asset_variant.py#L945) | Builds the closing entry |
| `set_to_close()` | [account_asset_variant.py:690](../enterprise/account_asset/models/account_asset_variant.py#L690) | Sell or dispose |
| `set_to_cancelled()` | [account_asset_variant.py:739](../enterprise/account_asset/models/account_asset_variant.py#L739) | Reverse/cancel posted, delete drafts, reset paused days, log a full audit note |
| `set_to_draft()` / `set_to_running()` | [account_asset_variant.py:796](../enterprise/account_asset/models/account_asset_variant.py#L796) | Back to draft; reopen a closed asset (re-running `modify()` if the board doesn't end at zero) |
| `pause()` | [account_asset_variant.py:818](../enterprise/account_asset/models/account_asset_variant.py#L818) | Partial entry + freeze |
| `_mirror_main_variant_moves()` | [account_asset_ledger_variant.py:111](../enterprise/account_asset/models/account_asset_ledger_variant.py#L111) | Counter-entries that make a ledger board hold only differences |
| `_auto_create_asset()` | [account_move.py:216](../enterprise/account_asset/models/account_move.py#L216) | Creates + confirms assets from a posted invoice |
| `_auto_update_asset()` | [account_move.py:276](../enterprise/account_asset/models/account_move.py#L276) | Re-syncs draft/cancelled assets when the bill changes |
| `asset.modify.modify()` | [asset_modify.py:263](../enterprise/account_asset/wizard/asset_modify.py#L263) | Re-evaluate and resume |
| `asset.modify.sell_dispose()` | [asset_modify.py:466](../enterprise/account_asset/wizard/asset_modify.py#L466) | Calls `set_to_close()` with or without invoice lines |
| `asset.modify.activate_depreciation()` | [asset_modify.py:473](../enterprise/account_asset/wizard/asset_modify.py#L473) | Transfer account + close old + create new depreciating asset |
| `depreciation.ledger.wizard.apply()` | [depreciation_ledger_wizard.py:62](../enterprise/account_asset/wizard/depreciation_ledger_wizard.py#L62) | Adds and confirms a ledger variant |

### Constraints

| Constraint | Model | Rule |
|---|---|---|
| `_check_depreciations` | variant ([:332](../enterprise/account_asset/models/account_asset_variant.py#L332)) | Open main variant: last move's `asset_remaining_value == 0`. Open sub-variant: last move's `asset_depreciated_value == 0` |
| `_check_state` | variant ([:326](../enterprise/account_asset/models/account_asset_variant.py#L326)) | An archived variant must be `close` |
| `_check_active` | asset ([:344](../enterprise/account_asset/models/account_asset.py#L344)) | Cannot archive unless the main variant **and every variant** is `close` |
| `_check_related_purchase` | asset ([:355](../enterprise/account_asset/models/account_asset.py#L355)) | Bill lines must net non-zero and all come from one account |
| `_constrains_check_asset_state` | move ([account_move.py:125](../enterprise/account_asset/models/account_move.py#L125)) | Cannot post an entry whose variant is still draft |
| `_unlink_if_draft` | asset ([:366](../enterprise/account_asset/models/account_asset.py#L366)) / variant ([:345](../enterprise/account_asset/models/account_asset_variant.py#L345)) | No deletion in `open`/`paused`/`close`, and none with posted entries. The variant's version is also run explicitly before an asset delete, because `ondelete='cascade'` would otherwise bypass it |
| `_check_unique_ledger_per_asset` | ledger variant ([:86](../enterprise/account_asset/models/account_asset_ledger_variant.py#L86)) | One variant per ledger per asset |
| `_check_ledger_recovery_account` | model ([:251](../enterprise/account_asset/models/account_depreciation_model.py#L251)) | A ledger-journal model must name a recovery account |
| `_check_unique_ledger_depreciation` | account ([account.py:59](../enterprise/account_asset/models/account.py#L59)) | `ledger_depreciation_model_ids` must all have ledger journals, one per ledger |
| Model freeze | model `write()` ([:289](../enterprise/account_asset/models/account_depreciation_model.py#L289)) | Config changes blocked once a non-draft asset uses it |
| Lock date | `set_to_close`, `modify`, `_close_with_main_variant` | Cannot dispose / re-evaluate before `company._get_user_fiscal_lock_date(journal)` |
| Unposted priors | `modify()` ([asset_modify.py:351](../enterprise/account_asset/wizard/asset_modify.py#L351)) | No draft depreciation dated ≤ the operation date |
| Sell with children | `set_to_close` / `_onchange_action` | Dispose gross increases before selling the parent |

### Security ([`ir.access.csv`](../enterprise/account_asset/security/ir.access.csv))

| Group | `account.asset` / `account.asset.variant` | `account.depreciation.model` | `account.asset.group` |
|---|---|---|---|
| `account.group_account_readonly` | read | read | read |
| `account.group_account_invoice` | create + read | — | — |
| `account.group_account_user` | full | full | — |
| `account.group_account_manager` | — | — | full |

Multi-company domains: `[('company_id','in',company_ids)]` for assets and variants; `parent_of` for asset groups; `['|',('company_id','=',False),('company_id','parent_of',company_ids)]` for depreciation models (company-less models are shared).

---

## Related Docs

- [`deferred_expenses_revenue.md`](deferred_expenses_revenue.md) — the same machinery applied to deferrals
- [`accounting_fixed_costs_guide.md`](accounting_fixed_costs_guide.md) — account types, lock dates, analytic distribution
- [`account_analytic_account.md`](account_analytic_account.md) — the analytic side of `analytic.mixin` on assets
- [`accounting_reports.md`](accounting_reports.md) — where the Depreciation Schedule fits

# bsc_strategy — Balanced Scorecard for Odoo 20

Strategy management with the Balanced Scorecard: perspectives, strategic
objectives, a strategy map, KPIs with periodic manual measurement, an
initiative portfolio, and the periodic review that turns all of it into
decisions.

Companion modules:
**bsc_project** — links an approved initiative to an Odoo project or task;
installs automatically when Project is present.
**bsc_demo** — a worked example that installs and then runs a full year.


## What changed in 20.0.1.5.0 (security review)

Rules the access-rights table cannot express now live in
`models/bsc_security.py` and are covered by `tests/test_security.py`. Each was
found by trying the action as the user concerned, through the ORM (what an
RPC client can do), not through the screens.

- A contributor could change the **target** of their own figure, **validate**
  it themselves, and change it after a manager had validated it. Now only the
  figure, the Reported switch, the comment and draft/submitted state are
  theirs; the views show the target read-only for them.
- The closed-period lock and the "automated figure" marker trusted a context
  key, which any client can send: anyone could edit a closed period or make a
  typed figure look automated. Both are now honoured only for code running as
  superuser.
- A manager could reopen a closed period by writing its state directly; only
  an Administrator can now.
- A contributor could approve their own initiative and write "approved by".
  Contributors now propose only; approval is recorded by the system; an
  approved budget is changed by a manager only.
- A manager could flag a real scorecard as demo, so that "Remove demo data"
  would delete it.
- A KPI filter on a data source (read with elevated rights) could count
  records its author may not open; the filter is now refused in that case.
- Cause-effect links, perspective weights and initiative stages had no
  multi-company rule.
- Contributors can comment in the chatter of scorecards, objectives, KPIs,
  initiatives and reviews (read access is enough to post).

## What changed in 20.0.1.4.0

**Project execution (initiative -> project / task)**

- Progress now follows the tasks the moment one changes, not once a night.
- A task dragged into the Done column counts as done. Odoo itself does not
  change a task's state when its card is moved, so before this the initiative
  never saw it. Cards dropped into the scorecard's Done / Cancelled columns are
  given the matching task state; dragged back out, they open again.
- Cancelled tasks are left out instead of counting as done, and a task with
  subtasks counts through its subtasks.
- Creating the project or task switches "Track Progress from Project" on. An
  empty project does not overwrite a progress figure somebody typed.

**KPIs filled from Odoo data**

- "Connect to Odoo data" on the KPI opens a guided window: pick a ready-made
  measure, optionally narrow it ("Only count records where"), choose thousands
  or millions, see what it would report for the current period, connect.
- 16 ready-made measures (`models/bsc_kpi_recipes.py`) for Sales, Accounting,
  CRM, Purchase, Inventory, Manufacturing, Point of Sale and Project, offered
  only when the app is installed. Money is read from Odoo's reporting models,
  in the company currency; revenue is net of credit notes. Each was checked
  against Odoo's own totals on a database with demo data.
- Data sources can now compute a share of records (%) and include archived
  records (a lost opportunity is archived).
- Fixed: a figure typed in before the KPI was connected was overwritten by the
  source. Clearing an automated figure now hands the row back to the source
  instead of locking it as "manual" for good. The nightly job read period
  boundaries in the server's time zone; it now uses the scorecard owner's.

**Icons**

- Odoo 20 replaced Font Awesome with Material Symbols. Every icon of the module
  (buttons, stat buttons, dashboard, strategy map) was converted; before, they
  showed as a dash or nothing.

## What changed in 20.0.1.3.0

**Odoo 20 compatibility**

* `ir.config_parameter.get_param()` no longer exists in Odoo 20; every score
  computation raised `AttributeError`. Settings are now read with
  `get_float()` (with a fallback for older versions).
* Access rights moved from `ir.model.access` + `ir.rule` to Odoo 20's
  `ir.access` (`security/ir.access.csv`). The Odoo 19 files are kept, unused, in
  `security/odoo19/`.
* Odoo 20 runs Owl 3: the strategy map now declares its props with `useProps()`,
  uses `proxy()` instead of `useState()`, and its templates address the
  component through `this.` explicitly.

**Bugs fixed**

* Scores can be read for any period (`with_context(bsc_period_id=...)`). The
  strategy review froze the score of the period containing *today* - usually the
  next, empty one - so a Q1 review prepared in April showed 0 %. The review, the
  period-close message, the board pack printed from a review and the dashboard
  now all use the period they are about.
* Activation creates rows for every period that has already started, not only
  the current one. A cycle activated in October no longer loses January-September,
  and those periods no longer close as "complete" with nothing in them.
* Data Entry's two default filters (*Mine to Report*, *Open Period*) were ORed,
  so closed periods showed up too. They are now ANDed.
* Quarterly and half-year periods are named after the calendar when the cycle is
  aligned with it (a cycle starting in April no longer calls April-June "Q1").

**Easier to fill in**

* KPIs carry their own **Target** (`default_target`), copied onto every new row.
  Before, the first period's target was 0 and a reported figure showed *No Data*.
* A **setup checklist** on the scorecard, in the order the method wants, naming
  what is missing.
* Objectives, KPIs and cause-effect links are typed straight into editable
  tables (scorecard Objectives tab, objective KPIs tab, *Strategy → KPIs*,
  *Strategy → Cause-Effect Links*).
* Activation lists every problem at once instead of one error per attempt.
* Data Entry is leaner, shows the previous figure, and has *Submit* / *Validate*
  for the selected rows. The review form shows the figures of its period.

**New**

* **Dashboard** (managers): scorecard and period selector, index, completion,
  KPI status, initiative portfolio and budget, perspectives, the index over the
  cycle, what needs attention, the period's review.
* **Demo data**: *Configuration → Demo Data* loads a full worked year (in the
  user's language, Georgian or English) and removes it again with one button.
* **User Guide**: *User Guide* in the menu, served by `/bsc_strategy/guide` in the
  reader's language (`static/guide/guide_ka.html`, `guide_en.html`).
* `i18n/ka.po` covers every new string.

91 tests pass on Odoo 20 (`tests/test_usability.py`, `tests/test_integration.py` and `tests/test_security.py` cover the items above).

---

## Why it is built this way

This is not a KPI dashboard with extra fields. Three design choices follow
directly from what is known about how Balanced Scorecards fail in practice
(see `../TZ_BSC_Odoo_v0.1.md` §2.4 and the Madsen 2025 review in the parent
folder):

1. **Objectives and the strategy map are the core.** A KPI cannot exist
   without an objective (`bsc.kpi.objective_id` is required). Scorecards
   filled with measures that serve no stated objective are documented to
   *reduce* organisational performance, not improve it.
2. **Cause-effect links are stored as hypotheses, not facts.** Each link on
   `bsc.objective.link` carries a written hypothesis, a believed strength and
   a `validated` flag. The most persistent criticism of this method is that
   these links are assumed and never checked; the data model makes the
   assumption visible and falsifiable.
3. **The review is a first-class model.** `bsc.review` records findings,
   decisions, strategy adjustments and the corrective initiatives that come
   out of them. Without it, a scorecard gets filled in every quarter and
   changes nothing.

Perspectives are ordinary records, not a hard-coded selection: they get
adapted by industry and sector, and in public or non-profit organisations
their order changes. `bsc.perspective.sequence` drives the layering of the
strategy map, bottom to top.

## Installation

```bash
# copy both modules into your addons path, then
odoo-bin -d <database> -i bsc_strategy --without-demo=all
```

Requires a standard Odoo 20 (`base`, `mail`, `web`, `project`). Works on Community.
No Studio, no enterprise-only views.

The installing administrator is granted *Balanced Scorecard / Administrator*.
Everyone else is assigned explicitly — a strategy is not automatically
everybody's business.

## First run, in the intended order

1. **Configuration → Perspectives** — four are pre-loaded. Rename, reorder,
   or add an ESG or health-and-safety perspective.
2. **Strategy → Scorecards → New** — name, cycle dates, review frequency,
   strategy owner.
3. Add **objectives** per perspective. Owners are required; weights are not.
4. On each objective, open the **Strategy Map** tab and say which objective
   drives which, in one sentence each. Do this before choosing measures.
5. Add **KPIs** — one or two per objective. Set the unit, the direction, and
   the data owner (the person who will be asked for the figure).
   An objective that does not become a number goes to
   *Qualitative assessment* instead and needs no KPI.
6. Add **initiatives** and link them to the objectives they serve.
7. **Activate**. Periods are generated and the first one is opened with an
   empty row per KPI.
8. Every period: data owners fill in **Data Entry**; then close the period and
   hold a **Strategy Review**.

## Access levels

| Group | Can |
|---|---|
| Contributor | Read the strategy; report figures for their own KPIs; propose initiatives |
| Manager | Design objectives, KPIs and initiatives; validate figures; run reviews |
| Administrator | Configure perspectives and stages; reopen a closed period; delete |

Closed periods are protected in `write()`/`unlink()`, not only in the views —
the API is blocked too. The administrator bypass is explicit
(`bsc_bypass_period_lock` in the context) and every reopening is written to
the chatter.

## The arithmetic

| Direction | Achievement |
|---|---|
| Higher is better | `actual / target × 100` (no target → no data) |
| Lower is better | `target / actual × 100`; `actual = 0` → 100 % |
| Inside a range | 100 % inside; proportional outside |

Achievement is capped (default 150 %) so one over-performing measure cannot
hide two failing ones. Rollup is a weighted average that **drops** unreported
KPIs from both sides of the fraction — an unreported measure is not a zero.
With every weight left at zero, everything is weighted equally.

Configurable through `ir.config_parameter`:

| Key | Default |
|---|---|
| `bsc.achievement_cap` | 150 |
| `bsc.objective_threshold_green` | 95 |
| `bsc.objective_threshold_amber` | 80 |
| `bsc.qualitative_score_green` / `_amber` / `_red` | 100 / 85 / 50 |

Per-KPI green and amber thresholds live on the KPI itself.

## Known deviations from the specification

* **Scores are computed, not stored.** The spec proposed stored scores with a
  nightly recompute. Scores depend on which period is "current", which is a
  function of today's date and cannot be expressed in `@api.depends` — a
  stored value would go stale silently. They are therefore computed on read,
  and frozen only where a frozen number belongs: `bsc.review.score_snapshot`.
  Filtering still works: the `status` fields carry an explicit `search=`
  method that evaluates in Python (see `computed_selection_search`), so
  "Off Track" filters behave normally. What is *not* available is sorting,
  grouping and pivoting by score or status on these three models. Fine up to
  a few dozen KPIs per scorecard; if you ever need to rank scorecards by
  score, store a snapshot per period rather than making these fields stored.
* **The visual strategy map was folded back in** at v19.0.3.0.0. It was built as
  a separate module precisely so the core would not be hostage to the most
  version-fragile layer of Odoo; that separation has been traded for having one
  module to install. If an Odoo upgrade breaks the OWL component, the map is the
  first place to look, and `static/src/` is self-contained enough to drop.
* **`i18n/ka.po` is partial on purpose** — it fixes the vocabulary of the
  method, where a wrong word changes the meaning. Complete it from
  Settings → Translations → Export Translation.

## Verified

Installed and tested against a real Odoo 19.0 checkout (PostgreSQL 16), not
only syntax-checked:

* `bsc_strategy` installs on a clean database, with no warnings in the log;
* `bsc_project` installs on top of `project`;
* 32 tests pass;
* an end-to-end run was exercised in a live database: activation generates
  four quarterly periods and the empty rows, figures roll up
  (KPI -> objective -> perspective -> scorecard), off-track filters return
  the right records, the review freezes its snapshot and lists the off-track
  objectives, an initiative creates its project and pulls progress back from
  the tasks, the board pack renders, and a closed period rejects writes.


---

# Automation

Merged in from the former `bsc_automation` module (v19.0.2.0.0). Automates three
things and deliberately nothing else: the **figures**, the **proposed target**,
and **opening the review**. The judgement stays human.

## 1. Figures from Odoo data

`bsc.kpi.data_source` has two values. A **manual** KPI is asked of its owner
every period. A **computed** one is filled from a vetted query.

A **source** (`bsc.kpi.source`) is a vetted query: model, filter, aggregate,
and — most importantly — the date field that decides which period a record
belongs to. An administrator writes it once under
*Configuration → KPI Data Sources*, presses **Test**, and from then on whoever
designs a KPI just picks it from a dropdown.

That indirection is the design, not an accident:

* the people who set strategy never write a search domain;
* a query is reviewed and tested once instead of retyped per KPI;
* `ir.model` is readable only by ERP managers in Odoo 19, so a raw model picker
  on the KPI form would raise `AccessError` for a BSC Manager anyway.

Filters are read with `literal_eval`. A domain is data; it can never be code.

### Guards

| Situation | What happens |
|---|---|
| Query matched **no records** (sum/avg/min/max) | Left empty, flagged *No Records Matched*. **Never published as zero.** |
| Query matched no records (**count**) | Written as 0 — for a count, zero is a real answer |
| Figure differs from last period by more than the KPI's limit (default 50 %) | **Held back**, not published. The owner is asked to confirm or reject |
| Period is closed | Never written to, by anyone, cron included |
| Figure already `validated` | Never overwritten |
| Somebody edited the row by hand | That row becomes manual permanently |
| Source raised an error | Recorded on the row and the KPI; the cron does not fail |

Every published figure carries its own audit trail: which source, how many
records, which date field, which window.

### The red-figure rule

`bsc_strategy` raises `ValidationError` when a red figure has no explanation.
Writing an automated value recomputes the status, so that rule would make the
cron fail outright. It is therefore **deferred, not dropped**: automated rows
are exempt at write time, and `action_close()` refuses to close the period
while an automated red figure carries no comment. *Close Anyway* still
overrides it, exactly as it does for missing figures.

### Automate only what is unambiguous

Revenue, record counts, closed tasks, headcount. Anything judgement-based —
satisfaction, quality, capability — should stay manual. Expect roughly half
your KPIs to remain manual; that is the correct outcome, not a gap.

Note: sources read with elevated rights on purpose, so a KPI does not change
value depending on who is looking at it. The consequence is that anyone who can
see the scorecard sees an aggregate over records they may not be able to open —
which is why sources are administrator-defined.

## 2. Proposed targets

Core always carries the previous target forward. Each KPI can now say how its
next target is proposed:

| Rule | Basis |
|---|---|
| Same as last period | Core behaviour, still the default |
| Last period actual, plus a percentage | Previous **actual** × (1 + growth) |
| Baseline, plus a percentage | `baseline_value` × (1 + growth) — the field core stores but never uses |
| Leave empty | For a target that is negotiated, not derived |

Applied once, when the row is created, and always editable afterwards. A target
is a commitment, not a calculation.

## 3. The review opens itself

Closing a period creates its `bsc.review` as a **prepared draft** — score and
completion frozen, off-track objectives listed — and puts a to-do on the
strategy owner. The meeting, the findings and the decisions remain entirely
manual. Switch it off per scorecard with *Open the Review Automatically*.

---


---

# The strategy map

Merged in from the former `bsc_strategy_map` module (v19.0.3.0.0). One OWL
client action, inline SVG, one SCSS file - no charting library and no external
asset.

## What you see

* **Perspectives are horizontal layers**, ordered by their own `sequence` —
  bottom to top, the way a strategy map is read: learning drives process,
  process drives the customer, the customer drives the financial result.
* **Objectives are cards**, with a coloured stripe for their traffic-light
  status, their score, their KPI count and their owner.
* **Links are arrows**, from cause up to effect. Thickness shows how strongly
  the link is believed. **A dashed arrow is a hypothesis nobody has checked
  against data.**

That last convention carries the whole module. The most persistent criticism of
the Balanced Scorecard is that its causal chain is assumed and never tested. In
a table of links, that is invisible. On a map where half the arrows are dashed,
it is the first thing anyone sees — and the header tells you the count
outright: *"12 links · 9 unproven"*.

## How to read it

Find the red card near the top. Follow the arrows down. You are now looking at
the causes **your own strategy nominated** for that failure — which is exactly
the conversation a strategy review is supposed to have, and the one a list of
KPIs cannot start.

## The inspector panel

The map keeps its natural width, and the space to its right is an inspector.
Clicking a card no longer throws you out of the map — it loads the detail
beside it, so you keep your place.

| Selected | The panel shows |
|---|---|
| An **objective** | Score, status, owner, weight · every KPI with target, actual, achievement and trend for the current period · variance comments · automation flags (*automated*, *held for confirmation*, *source problem*) · what drives it and what it drives, each marked proven or assumed · its initiatives with progress · an *Open objective* button |
| A **link** | The two objectives it joins, the hypothesis in full, how strongly it is believed, and a one-click validate button |
| **Nothing** | A briefing: perspective scores, off-track objectives as a clickable list, and how many of the cause-effect links have actually been checked against data |

Selecting an objective also lights up its own arrows on the map and steps the
rest back, so the chain around it is readable at a glance.

**Hide details** in the top bar collapses the panel and gives the map the full
window — worth roughly 1.5 extra cards per row, which is the difference between
panning sideways and not on a 1600px laptop. Clicking a card while it is hidden
brings it straight back, so a click never appears to do nothing.

Below 1100px the panel moves underneath the map instead of beside it.

## What you can do on it

| Action | Result |
|---|---|
| Click a card | Loads it into the inspector; click again to close |
| Click an arrow | Loads the hypothesis into the inspector |
| Hover an arrow | Tooltip with the hypothesis, strength and proof state |
| **Highlight proven links** | Fades every unchecked assumption, leaving only what the data supports |
| Click *not yet* / *yes* in the table | Validates a hypothesis without leaving the map, and logs it to the scorecard chatter |
| Scorecard dropdown | Switches between scorecards; the current period's scores are used |

Below the map, every link is listed as a written claim — cause, effect,
hypothesis, belief, validated. That table is the map in words, and it prints.

A footer warns about **unconnected objectives**: an objective that neither
drives nor is driven by another is not part of a strategy yet, it is a
standalone intention.

## Where it lives

* **Balanced Scorecard → Strategy → Strategy Map**
* A **Strategy Map** stat button on the scorecard form, once it has objectives.

## Technical notes

One OWL client action, inline SVG, one SCSS file. **No charting library, no
external asset, nothing pinned to a version** — which is the whole reason this
lives outside `bsc_strategy`: the interactive layer is the most upgrade-fragile
part of Odoo, and the core must not be hostage to it.

The whole map arrives in a single `get_strategy_map()` call. Scores are computed
and never stored, so reading them record by record from the browser would cost
one recompute per objective.

Layout is computed in the component: perspectives become bands, objectives wrap
at six per row, and arrows pick their anchor edges from the relative position of
the two cards — upward links leave the top edge, sideways links inside one
perspective leave the sides.

### Limits

* Layout is automatic; cards cannot be dragged to fixed positions. For the
  objective counts a scorecard should have (tens, not hundreds) that is a
  feature — the map cannot drift out of date with the data.
* Arrow routing does not avoid overlapping other cards. With a very dense map
  some arrows will cross; the hypotheses table below is the unambiguous record.
* Not printable as PDF from here. The board pack in `bsc_strategy` prints the
  same links as a table.

---

## Tests

```bash
odoo-bin -d <database> -i bsc_strategy --test-enable --stop-after-init
```

`tests/test_automation.py` covers the automation guards: an empty result set is
never published as a zero, a plain count of zero is, a deviating figure is held
and then confirmed, a closed period and a validated figure are never written to,
a human edit wins permanently, a red automated figure does not raise on write but
does block the close, and a domain is data rather than code.
`tests/test_scoring.py` covers cases T1–T12 of the specification (including
the ones that used to be division-by-zero bugs elsewhere: zero targets, zero
actuals on a lower-is-better measure, all-zero weights).
`tests/test_workflow.py` covers activation gates, reporting, the "zero is a
real figure" case, the red-needs-a-reason rule, period closing, the closed
period lock, initiative approval gates and the review loop.

## Upgrading to Odoo 20

The core depends on `base` and `mail` only, overrides no other module's
methods, inherits no other module's views and contains no JavaScript. What
will need attention is listed in `../TZ_BSC_Odoo_v0.1.md` §13 and §20. Run
the test suite first: it is the cheapest map of what broke.

## Licence

LGPL-3.

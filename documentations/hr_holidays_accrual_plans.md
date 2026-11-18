# Time Off — Accrual Plans

> **Updated 2026-09-22 for Odoo 20.0.** Module: `hr_holidays`. Models: [`hr.leave.accrual.plan`](../addons/hr_holidays/models/hr_leave_accrual_plan.py), [`hr.leave.accrual.level`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py) (the file name still says `..._plan_level.py`). Engine: [`hr_leave_allocation.py`](../addons/hr_holidays/models/hr_leave_allocation.py). Public-holiday interaction: [`public_holidays_flow.md`](public_holidays_flow.md).

> **Changed in 20.0 — `hr.leave.type` no longer exists.** The whole module now hangs off [`hr.work.entry.type`](../addons/hr_holidays/models/hr_work_entry_type.py). Everywhere v19 had `holiday_status_id` / "Time Off Type", 20.0 has `work_entry_type_id` / **"Time Type"**. The accrual plan itself now carries a `work_entry_type_id` ([`plan:19`](../addons/hr_holidays/models/hr_leave_accrual_plan.py#L19)) and it is effectively **required**: an allocation cannot use a plan without one ([`allocation:165`](../addons/hr_holidays/models/hr_leave_allocation.py#L165)), and the plan's time type must equal the allocation's ([`allocation:170`](../addons/hr_holidays/models/hr_leave_allocation.py#L170)).

## What It Does

An accrual plan makes an employee's time-off balance **grow gradually over time** instead of granting a fixed lump of days. You attach the plan to an allocation (Time Off ▸ Allocations ▸ pick an **Accrual Plan**). A nightly scheduled action then tops up the balance according to the plan's rules.

A plan is just a template: rules live in the plan header (**Configuration**) plus one or more **Milestones (levels)**.

**Changed in 20.0:** the `allocation_type` field (*Regular* / *Accrual Allocation*) is **gone**. An allocation is an accrual allocation purely because `accrual_plan_id` is set. On the form the field is rendered with the placeholder *"Regular allocation"* ([`allocation_views:156`](../addons/hr_holidays/views/hr_leave_allocation_views.xml#L156)) — leave it empty for a regular allocation, fill it for an accrual one. It is hidden entirely when no plan exists for the chosen time type (`hide_accrual_plan_id`).

## How It Works (flow)

1. Build the plan: pick its **Time Type**, set the Configuration options, add milestones.
2. Give an employee an allocation on the same time type and select the plan.
3. The accrual cron (`_update_accrual`) repeatedly adds `added_value` at each `frequency` occurrence, promotes the employee through milestones by seniority, caps the balance, and carries over / resets unused days on the carry-over date.

## Plan Configuration Fields

| Field (UI) | Model field | What it does |
|---|---|---|
| **Time Type** | `work_entry_type_id` | **New in 20.0.** The `hr.work.entry.type` this plan accrues. Limited to types that require an allocation and are time-off selectable, in the company's country. Source: [`:19`](../addons/hr_holidays/models/hr_leave_accrual_plan.py#L19) |
| **When the time is accrued?** | `accrued_gain_time` | `start` = days granted up-front at the period start; `end` = granted after the period is worked (default). Source: [`:33`](../addons/hr_holidays/models/hr_leave_accrual_plan.py#L33) |
| **It is based on worked time?** (only if accrued at *end*) | `is_based_on_worked_time` | `Yes` = accrual is proportional to time actually worked (unpaid time off reduces it); `No` = full accrual for the whole calendar period regardless of absences. Source: [`:30`](../addons/hr_holidays/models/hr_leave_accrual_plan.py#L30) |
| **What should happen to the unused accrued time?** | `can_be_carryover` | Yes/No radio: *"They should be carried over"* vs *"They should be lost (reset)"*. Source: [`:38`](../addons/hr_holidays/models/hr_leave_accrual_plan.py#L38), label at [`views:195`](../addons/hr_holidays/views/hr_leave_accrual_views.xml#L195) |
| **When should unused accrued time be reset/carried over?** | `carryover_date` | `year_start` (Jan 1), `allocation` (allocation's anniversary), or `other` = custom day/month (`carryover_day` / `carryover_month`). Source: [`:39`](../addons/hr_holidays/models/hr_leave_accrual_plan.py#L39) |
| **Switch employees to the new accrual level** (only if >1 milestone) | `transition_mode` | When an employee reaches a higher milestone: `immediately` apply it, or `end_of_accrual` wait until the current period finishes. Source: [`:25`](../addons/hr_holidays/models/hr_leave_accrual_plan.py#L25) |

**Changed in 20.0 — the carry-over wording was rewritten, and this matters.** In v19 the switch read *"Do you need a carry-over of the accrued days from one year to another?"* and the reset date was hidden when you answered No, which is what made the year-end wipe invisible (see below). In 20.0 the question is *"What should happen to the unused accrued time?"* with an explicit **"They should be lost (reset)"** option, and the date question — now *"When should unused accrued time be reset/carried over?"* — stays visible in both cases ([`views:203`](../addons/hr_holidays/views/hr_leave_accrual_views.xml#L203)). The behaviour did not change; the UI stopped hiding it.

## Milestones (Levels)

Each milestone is a seniority tier. An employee sits on the highest milestone their tenure qualifies for, and accrues at that tier's rate.

| Card text (UI) | Model field(s) | Meaning |
|---|---|---|
| **After X day(s)/year(s)** | `start_count` + `start_type` (+ `milestone_date`) | Seniority threshold, measured from the allocation start, at which this milestone activates. `start_count = 0` → "At allocation creation". Source: [`level:25`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L25) |
| **Accrual frequency: 1 day(s) every year on the 1 of January** | `added_value` + `added_value_type` + `frequency` (+ day/month detail fields) | How much is granted and how often (hourly … yearly). Source: [`level:41`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L41), [`level:47`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L47) |
| **After a year, unused accrued time will be: Lost (Reset) / Carried over** | `action_with_unused_accruals` + `carryover_options` + `max_carriedover_duration` | `all` = carried over (`unlimited`, or `limited` = "Up to N"); `lost` = reset to 0 at the carry-over date. Source: [`level:119`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L119) |
| **Define a carry over validity?** | `accrual_validity` + `accrual_validity_count` / `accrual_validity_type` | Carried-over days expire N days/months after the carry-over date. Drives `carried_over_days_expiration_date` on the allocation, which is its own cron event. Source: [`level:143`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L143) |
| **A balance cap is set to 100 day(s)** | `cap_accrued_time` + `maximum_leave` | Hard ceiling: the allocation balance never exceeds this. (`cap_accrued_time_yearly` / `maximum_leave_yearly` cap the amount accrued per year.) Source: [`level:106`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L106) |

**Changed in 20.0:** `postpone_max_days` was renamed **`max_carriedover_duration`** ([`level:139`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L139)); the `lost` label became **"Lost (Reset)"**; and `action_with_unused_accruals` gained `readonly=False`, so it is directly editable rather than purely computed.

`accrued_gain_time` and (new in 20.0) `is_based_on_worked_time` are shared from the plan onto every level as related fields ([`level:23-24`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L23)), so all milestones grant with the same timing and proration policy.

**New in 20.0 — `yearly_gain`.** The milestone form now shows a read-only *"Gain for the year"* (or *"Maximum gain for the year"* when based on worked time): frequency × `added_value` extrapolated over a year, using the company calendar for hourly/daily frequencies ([`level:273`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L273)). It is a display aid only — caps are not applied to it, and the form says so.

## What the "accrual period" is

It is **not a separate field** — the accrual period is **one cycle of the milestone's Frequency**, computed by `_get_next_date` ([`level:302`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L302)) and `_get_previous_date` ([`level:345`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L345)).

The cron does **not** always advance a whole frequency cycle: each iteration moves `nextcall` to the *earliest* of the next accrual date, the next level transition, the carry-over date, and the carried-over expiry date ([`allocation:711-730`](../addons/hr_holidays/models/hr_leave_allocation.py#L711)). A cycle can therefore be interrupted mid-way by a carry-over or a milestone change.

| Frequency | One accrual period = |
|---|---|
| Daily | 1 day |
| Weekly | 1 week |
| Twice a month | ~half a month (between the two chosen days) |
| Monthly | 1 month |
| Twice a year | ~6 months |
| Yearly | 1 year |

So "**At the start / end of the accrual period**" just means: grant the days at the beginning or the end of each such cycle.

## Start vs End — advance vs arrears

The setting does not change **how much** is granted, only **which period the grant belongs to**:

- **At the start** = paid **in advance**. On 1 March the employee receives March's days, before March is worked.
- **At the end** = paid **in arrears**. On 1 March the employee receives February's days, because February is now over.

Both modes therefore fire on the *same calendar dates* (the milestone's accrual dates). The balance under `start` is permanently **one full period ahead** of the same plan under `end`.

15 h monthly on the 1st, allocation starting 1 January:

| Date | At the start (advance) | At the end (arrears) |
|---|---|---|
| 1 Jan | +15 → 15 (for January) | 0 (January not worked yet) |
| 1 Feb | +15 → 30 (for February) | +15 → 15 (for January) |
| 1 Mar | +15 → 45 | +15 → 30 |
| … | … | … |
| 1 Dec | +15 → 180 (12th grant) | +15 → 165 (for November) |

Same plan, yearly frequency on 1 January, employee hired 1 January: **start** gives the full year immediately; **end** gives nothing until 1 January of the *following* year — the employee waits 12 months for a balance.

Two consequences of choosing `start`:

1. **Worked-time proration becomes impossible** and the option disappears from the form ([`plan:111`](../addons/hr_holidays/models/hr_leave_accrual_plan.py#L111)) — Odoo cannot prorate on hours worked in a period that has not happened yet.
2. **Over-granting risk on leavers and long absences** — days are on the balance before they are earned, so a mid-year leaver holds more than they accrued.

**Changed in 20.0 — the `already_accrued` flag is gone.** v19 pre-granted the next period at the end of a run and set `already_accrued = True` so the loop would skip that date later. 20.0 has no such field: `start` and `end` are two separate code paths, `_process_accrual_start` ([`allocation:582`](../addons/hr_holidays/models/hr_leave_allocation.py#L582)) and `_process_accrual_end` ([`allocation:599`](../addons/hr_holidays/models/hr_leave_allocation.py#L599)), each of which only grants when `nextcall` is genuinely a period boundary for that mode. Double-granting is prevented structurally instead of by a flag.

## The Engine — what the nightly cron actually does

Cron **"Accrual Time Off: Updates the number of time off"**, every 1 day, runs `model._get_to_update_accrual_allocations()._update_accrual()` ([`ir_cron_data.xml:4`](../addons/hr_holidays/data/ir_cron_data.xml#L4)). **Changed in 20.0:** the selection of allocations moved out of `_update_accrual` into its own method, so `_update_accrual` can be called on an arbitrary recordset (the batch wizard and the form onchange both do this).

`_get_to_update_accrual_allocations` ([`allocation:794`](../addons/hr_holidays/models/hr_leave_allocation.py#L795)) picks up allocations that have a plan, are **`state = validate` (approved)**, have already started (`date_from <= today`), are not past `date_to`, and whose `nextcall` is empty or `<= today`. A draft or to-approve allocation accrues nothing.

Each allocation carries its own cursor ([`allocation:151-158`](../addons/hr_holidays/models/hr_leave_allocation.py#L151)):

| Field | Meaning |
|---|---|
| `lastcall` | last accrual **event** processed (accrual, carry-over, level transition, carried-over expiry) |
| `nextcall` | next date the engine must act on — the earliest of those four event kinds |
| `last_accrual` | **new in 20.0** — last date on which days were actually added; the start anchor of the next `end`-mode period |
| `yearly_accrued_days` | **renamed in 20.0** (was `yearly_accrued_amount`) — running total for the **yearly cap**, reset on every carry-over date |
| `previous_carryover_number_of_days` | **new in 20.0** — balance snapshot at the last carry-over, used to work out which days expire |
| `carried_over_days_expiration_date` | **new in 20.0** — when carried-over days die, if the milestone sets a carry-over validity |

`_process_accrual_plans` ([`allocation:669`](../addons/hr_holidays/models/hr_leave_allocation.py#L669)) loops `while nextcall <= today`, so a cron that has been down for months catches up in one pass. Each loop: pick the milestone valid at `nextcall`, expire carried-over days if due, apply the carry-over policy if the date is a carry-over date, add the period's days, apply caps, then move `lastcall`/`nextcall` forward.

**Changed in 20.0 — the loop is now side-effect-free.** It works entirely on an in-memory `allocation_data` dict and writes back once, at the end, in `_update_accrual` ([`allocation:775`](../addons/hr_holidays/models/hr_leave_allocation.py#L775)). That is what lets the same code answer "how many days will this employee have on date X" without touching the database (`_get_additionnal_future_leaves_on`, [`allocation:805`](../addons/hr_holidays/models/hr_leave_allocation.py#L805)). The class docstring tags methods "accrual inconsistent" to mark the ones that must read the dict rather than the record.

Setting `accrued_gain_time = start` also force-clears `is_based_on_worked_time` ([`plan:111`](../addons/hr_holidays/models/hr_leave_accrual_plan.py#L111)) — you cannot prorate by worked time when you pay up-front, and the option disappears from the form.

**Milestone transitions.** `_get_lvls_boundaries` ([`allocation:644`](../addons/hr_holidays/models/hr_leave_allocation.py#L644)) turns the plan's milestones into a list of start dates. With `transition_mode = immediately` that is simply `date_from + start_count`; with `end_of_accrual` each boundary is pushed forward to the next accrual date of the incoming level.

## Carry-over OFF does not mean "balance keeps growing"

**Still true in 20.0.** The behaviour is unchanged; only the UI got honest about it.

- `can_be_carryover` = No → the milestone's **Carry Over Options** group is hidden ([`views:75`](../addons/hr_holidays/views/hr_leave_accrual_views.xml#L75)) **and** `action_with_unused_accruals` is force-computed to **`lost`** ([`level:244`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L244)).
- The carry-over **date** is still computed and still hit by the engine — `_get_next_carryover_date` never checks `can_be_carryover` ([`allocation:397`](../addons/hr_holidays/models/hr_leave_allocation.py#L397)), and the main loop pulls `nextcall` onto it unconditionally ([`allocation:726`](../addons/hr_holidays/models/hr_leave_allocation.py#L726)). `carryover_date` still defaults to **`year_start` = 1 January**.
- On that date `_process_carryover_date` runs `allocated_duration = leaves_taken` ([`allocation:564`](../addons/hr_holidays/models/hr_leave_allocation.py#L564)) — i.e. **the unused balance is wiped to zero**; only already-taken time stays accounted for. 20.0 made the guard *stricter*, not looser: it now fires on `action_with_unused_accruals == 'lost'` **or** `not can_be_carryover`.

So carry-over = No is strict **use-it-or-lose-it on 31 December**, not "unlimited accumulation". `test_unused_accrual_lost` ([`tests:2170`](../addons/hr_holidays/tests/test_accrual_allocations.py#L2170)) shows the balance going 20 → reset → 1 across 31 Dec / 1 Jan.

**Changed in 20.0 — the trap is now signposted.** The plan form asks *"What should happen to the unused accrued time?"* and spells out the No branch as **"They should be lost (reset)"**, and the follow-up question — *"When should unused accrued time be reset/carried over?"* — is no longer hidden when you answer No. In v19 both the wording and the reset date were hidden, which is what made this a surprise. If you are migrating a v19 plan, nothing about the stored behaviour changes.

Order on 1 January with gain at start: wipe first, then the new period's grant, **both inside the same loop iteration** ([`allocation:723-740`](../addons/hr_holidays/models/hr_leave_allocation.py#L723)) — so the employee starts 1 January with exactly one fresh period's worth. The yearly-cap counter is also zeroed between the two steps.

## The first period is prorated

`_get_period_added_duration` ([`allocation:545`](../addons/hr_holidays/models/hr_leave_allocation.py#L545)) computes `period_prorata = days / period_days` whenever the accrual window does not cover the whole period ([`:551`](../addons/hr_holidays/models/hr_leave_allocation.py#L551)). It is skipped when the plan is based on worked time, because worked-time proration already handles it.

Monthly-on-the-1st plan, allocation starting 24 August → first grant = `(1 Sep − 24 Aug) / (1 Sep − 1 Aug) = 8/31` of the monthly amount. A yearly-on-1-January plan started on 24 August gives `130/365` of the yearly amount for the stub year, then the full amount on 1 January.

This proration is **calendar-day based**, not worked-time based (worked-time proration is a separate switch and is unavailable with `start`).

To avoid a partial first period, set the allocation's **Start Date to the first day of a period** (e.g. the 1st of the hire month for a monthly-on-the-1st plan) — then `start_period == start_date` and the employee gets the full amount.

## Testing accruals

In normal use the balance only moves when the **daily cron** runs. (Two places call the engine directly: the batch allocation wizard when you leave the duration at 0, and the allocation form's own simulation onchange.) Two traps when testing:

- **A neutralized database has all crons disabled** — `neutralize.sql` runs `UPDATE ir_cron SET active = false` for everything except `autovacuum_job` ([`neutralize.sql:14`](../odoo/addons/base/data/neutralize.sql#L14)). On a DB showing the red *"Database neutralized for testing"* banner, accruals never run until you re-activate "Accrual Time Off: Updates the number of time off" in Settings ▸ Technical ▸ Scheduled Actions and trigger it manually.
- **Only approved allocations accrue** (`state = validate`). A record sitting in *To Approve* shows a simulated figure — `_onchange_process_accrual_plans` ([`allocation:1095`](../addons/hr_holidays/models/hr_leave_allocation.py#L1095)) resets the accrual cursors and replays the plan up to today purely in the form — but the cron ignores it until it is approved.

## Backdating `date_from` now DOES back-pay

**Changed in 20.0 — this is the opposite of v19 behaviour.** v19 had `_add_lastcalls`, which on create anchored `lastcall` at `max(previous period boundary relative to today, allocation start)`, so every period completed before creation was silently skipped. **That method no longer exists.**

20.0 initialises the cursors lazily, the first time the engine sees the allocation, in `_init_accrual_calls` ([`allocation:623`](../addons/hr_holidays/models/hr_leave_allocation.py#L623)): `lastcall = date_from + first milestone offset`, full stop. The catch-up loop then runs from there to today.

The rule that follows: **every period between `date_from` and today is granted.** `test_accrual_period_start_past_start_date` ([`tests:2733`](../addons/hr_holidays/tests/test_accrual_allocations.py#L2733)) creates a monthly gain-at-start allocation on 1 March 2024 with `date_from` = 1 January 2024 and asserts **3 days**, not 1.

| Plan created today (24 Aug) with `date_from` = 1 Jan | v19 | 20.0 |
|---|---|---|
| Monthly on the 1st, 15 h | 15 h (August only) | 120 h (Jan–Aug, 8 grants) |
| Yearly on 1 Jan, 180 h | 180 h | 180 h (unchanged) |

Practical consequence when migrating: **do not carry over v19 habits of creating a compensating regular allocation for the skipped months** — you will double-pay. Conversely, a backdated `date_from` is now a real liability, so set it deliberately.

Note also that the v19 log note *"This allocation have already ran once, any modification won't be effective…"* is **gone in 20.0**. It no longer holds: because the engine recomputes from `date_from` rather than from a frozen anchor, an allocation whose cursors are reset (form onchange, batch wizard) replays the plan from scratch.

## Hours are stored as days

`number_of_days` is always the storage unit. A milestone encoded in hours is divided by the employee's `hours_per_day` in `_convert_duration` ([`allocation:427`](../addons/hr_holidays/models/hr_leave_allocation.py#L427)); the same conversion applies to `maximum_leave`, `maximum_leave_yearly` and `max_carriedover_duration`.

**Changed in 20.0:** the rate is no longer frozen at the allocation start. `_get_employee_hours_per_day` ([`allocation:182`](../addons/hr_holidays/models/hr_leave_allocation.py#L182)) resolves the calendar at the **current `nextcall`**, falling back to `date_from` only before the first run — so an employee who switches from full-time to part-time mid-plan converts subsequent grants at the new rate.

15 h/month with an 8 h/day calendar = 1.875 days/month. **An employee on a fully flexible calendar uses 24 h/day** ([`hr_employee.py:830`](../addons/hr_holidays/models/hr_employee.py#L830)) — 15 h would become 0.625 days. Always check the calendar before encoding an hour-based plan. See [`hr_holidays_time_off_units.md`](hr_holidays_time_off_units.md).

## Yearly cap vs balance cap

| Option (UI) | Field | Semantics |
|---|---|---|
| **Define a yearly cap?** — "Accrual will stop until next carry-over date if accrued time's reach N" | `cap_accrued_time_yearly` / `maximum_leave_yearly` | Limits how much is **granted between two carry-over dates**. Counter `yearly_accrued_days` is reset to 0 on the carry-over date ([`allocation:738`](../addons/hr_holidays/models/hr_leave_allocation.py#L738)); the grant is trimmed by the remaining headroom ([`allocation:442`](../addons/hr_holidays/models/hr_leave_allocation.py#L442)). |
| **Define a balance cap?** — "The plan will be on hold if the balance reach N" | `cap_accrued_time` / `maximum_leave` | Limits the **standing balance**: `added = min(added, leaves_taken + maximum_leave − allocated_duration)` ([`allocation:447`](../addons/hr_holidays/models/hr_leave_allocation.py#L447)). Taking time off frees the ceiling again; accrual resumes automatically. |

Ordering detail: the yearly cap is applied **before** the balance cap, and both trim the same grant.

A yearly cap equal to `frequency count × added_value` (e.g. 12 × 15 h = 180 h) never binds — it is only a safety net against future edits to the frequency.

## Worked Example — two ways to give 180 hours a year

Both plans below use `accrued_gain_time = start`, carry-over = *lost (reset)*, one milestone reached "At allocation creation". Re-verified against the 20.0 engine — every number below still holds.

| | **Monthly**: 15 h every month on the 1st, yearly cap 180 h | **Annual**: 180 h every year on 1 January |
|---|---|---|
| Grant events per year | 12 | 1 |
| Balance on 1 February | 30 h | 180 h |
| Balance on 1 December | 180 h | 180 h |
| Can the employee take 3 weeks in February? | No — only what has accrued | Yes — the full year is available on day 1 |
| Allocation with `date_from` = 24 Aug | 8/31 × 15 h ≈ 3.9 h now, then 15 h per month | 130/365 × 180 h ≈ 64 h now, 180 h on 1 Jan |
| 1 January | balance wiped, 15 h granted | balance wiped, 180 h granted |
| Leaver in June | has earned ~6 × 15 h = 90 h | still holds 180 h (over-granted) |
| Risk | employee cannot take a long holiday early in the year | company over-grants to leavers and to unpaid-leave absences |

The proration figures come straight from `_get_period_added_duration`: for the monthly plan the period is 1–31 Aug (31 days) and the accrual window 24–31 Aug (8 days); for the annual plan the period is 1 Jan – 31 Dec (365 days) and the window 24 Aug – 31 Dec (130 days). The 180 h yearly cap on the monthly plan never binds, since 12 × 15 h lands exactly on it — it is only a safety net against a later edit to the frequency.

Monthly = pay-as-you-earn, matches severance/settlement math. Annual = simple entitlement, front-loaded risk. If the balance must survive year-end, **the plan must answer "They should be carried over"** and the milestone must be set to *Carried over* — otherwise both plans reset every 1 January.

**20.0 caveat:** if you create these allocations today but backdate `date_from` to 1 January, the engine now back-pays the whole elapsed stretch rather than just the current period. See the backdating section above.

## Assigning a Plan to an Employee

The plan does nothing on its own — it is applied through an **allocation**:

1. **Time Off ▸ Management ▸ Allocations ▸ New**.
2. Pick the **Time Type** (`work_entry_type_id`). **Changed in 20.0:** there is no Allocation Type selector any more.
3. Pick the **Accrual Plan** — the dropdown is filtered to plans whose own `work_entry_type_id` matches, and the field is hidden entirely when no such plan exists ([`allocation_views:156`](../addons/hr_holidays/views/hr_leave_allocation_views.xml#L156)). Leaving it empty (placeholder *"Regular allocation"*) keeps the allocation a regular one.
4. Pick the **Employee** and a **Start Date** (`date_from`) — milestone seniority ("After X years") is counted from this date, and so is the whole accrual history (see backdating).
5. Confirm / Approve. The nightly accrual cron then tops up the balance automatically.

**Batch assignment:** allocations are still per-employee (no multi-employee field on the allocation). To grant a plan to many people at once use the **"Generate time off allocations for multiple employees"** wizard ([`hr_leave_allocation_generate_multi_wizard.py:96`](../addons/hr_holidays/wizard/hr_leave_allocation_generate_multi_wizard.py#L96)).

**Changed in 20.0 — the wizard got narrower and more automatic:**

- The `allocation_mode` selector and its **department** and **employee-tag** targets were **removed**. You now either list employees explicitly or leave the list empty to hit everyone in the chosen company.
- `allocation_type` is gone here too — setting `accrual_plan_id` is what makes the generated allocations accrual ones.
- Leaving **Allocation** (`duration`) at 0 makes the wizard reset the accrual cursors and immediately run `_update_accrual` on the new records, so they are created already caught up rather than waiting for the nightly cron ([`wizard:106`](../addons/hr_holidays/wizard/hr_leave_allocation_generate_multi_wizard.py#L106)).
- The wizard now approves what it creates, as far as the running user's rights allow.

**Unit of the grant:** each milestone grants in **Day(s) or Hour(s)** (`added_value_type`, [`level:42`](../addons/hr_holidays/models/hr_leave_accrual_plan_level.py#L42)). An accrual allocation *displays* in the milestone's unit rather than the time type's own unit of measure — `_get_request_unit` returns `accrual_plan_id.added_value_type` whenever a plan is set ([`allocation:381`](../addons/hr_holidays/models/hr_leave_allocation.py#L381)) — so for an hour-based type, grant hours to keep every screen in hours. See [`hr_holidays_time_off_units.md`](hr_holidays_time_off_units.md).

## Regular vs Accrual Allocation

Both give an employee a balance of a time-off type, but the way days arrive differs:

| | Regular Allocation | Accrual Allocation |
|---|---|---|
| How days are granted | A **fixed** number, **all at once** | **Grows over time** via an accrual plan |
| Needs an accrual plan? | No | Yes (`accrual_plan_id`, [`allocation:149`](../addons/hr_holidays/models/hr_leave_allocation.py#L149)) |
| Starting balance | The full amount you type | Usually 0, then the cron adds days |
| Typical use | "Give everyone 20 vacation days for 2026", one-off bonus days, manual top-up | "Earn 2 days/month", seniority leave, part-time proportional, pay-as-you-work |

**Changed in 20.0 — the `number_of_days > 0` SQL constraint is gone.** v19 enforced a positive duration on regular allocations at the database level. 20.0 replaces it with a Python check, `_check_negative_allocation` ([`allocation:347`](../addons/hr_holidays/models/hr_leave_allocation.py#L347)): negative allocations are now a supported feature, permitted when the time type sets `allows_negative`, and bounded by its `max_allowed_negative` across the validity period. Useful for clawing back over-granted accrual instead of editing history.

## "Eligible for Accrual Rate?" (on the Time Type)

**Changed in 20.0:** this field moved with the model. It is `elligible_for_accrual_rate` on **`hr.work.entry.type`**, help: *"this time type will be taken into account for accruals computation."* Source: [`hr_work_entry_type.py:105`](../addons/hr_holidays/models/hr_work_entry_type.py#L105).

It **only matters when an accrual plan is "based on worked time"**, where it decides whether time taken under this type still counts as **worked time** (so the employee keeps earning accrual during it):

- **Checked** → counts as worked → the employee **still accrues** while on this leave (for example, a paid leave type deliberately configured as eligible).
- **Unchecked** → does **not** count → that absence **reduces** the accrual (e.g. unpaid leave).

Default: anything whose `count_as` is not `absence` is auto-eligible; pure absences default to *not* eligible ([`hr_work_entry_type.py:406`](../addons/hr_holidays/models/hr_work_entry_type.py#L406)), and a `working_time` type may not be made ineligible at all. The worked-time proration adds eligible absence hours onto worked hours and divides by worked + ineligible hours ([`allocation:513`](../addons/hr_holidays/models/hr_leave_allocation.py#L513)). If the plan is **not** based on worked time (whole calendar days), this flag has no effect — except for `hourly` frequency, which always consults the calendar.

Public holidays use the similarly named field on `resource.calendar.leaves` ([`resource_calendar_leaves.py:18`](../addons/hr_holidays/models/resource_calendar_leaves.py#L18)), whose stock default is **False** and whose normal Public Holidays UI does not expose it. Therefore stock public holidays reduce worked-time-based accrual unless customization/data explicitly marks them eligible. **New in 20.0:** the public-holiday loading wizard copies the flag down from the source work entry type when it creates calendar leaves ([`load_public_holiday_wizard.py:145`](../addons/hr_holidays/wizard/load_public_holiday_wizard.py#L145)), so holidays generated that way inherit the type's setting rather than the `False` default. Decide and audit the Georgian policy separately from the holiday's payroll work-entry type.

## Use Cases

- **Seniority plan** (the screenshot): from day 1 → 1 day/year; after 4 years → 2 days/year; after 8 years → 3 days/year. Rewards tenure; carry-over capped at 100 days.
- **Monthly build-up**: e.g. ~1.67 days every month, capped at 20/year — statutory vacation accrued across the year rather than granted up front.
- **Worked-time based**: part-timers / hourly staff accrue in proportion to hours actually worked (`is_based_on_worked_time = Yes`).
- **Use-it-or-lose-it**: `action_with_unused_accruals = lost` (or simply carry-over = *"They should be lost (reset)"* on the plan) so any unused balance resets on the carry-over date.
- **Carry over, but with an expiry**: carry over unlimited, then set *Define a carry over validity?* to e.g. 3 months — the carried-over days survive 1 January but die on 1 April, tracked via `carried_over_days_expiration_date`.

## Related Docs

- [`INDEX.md`](INDEX.md)

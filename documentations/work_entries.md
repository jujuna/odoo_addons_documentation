# Work Entries — The Time→Money Engine

> **Module:** `hr_work_entry` (community) | **Path:** [`addons/hr_work_entry/`](../addons/hr_work_entry/)
> Live integrations: [`hr_attendance`](../addons/hr_attendance/), [`hr_holidays`](../addons/hr_holidays/),
> [`hr_holidays_attendance`](../addons/hr_holidays_attendance/), [`hr_payroll`](../enterprise/hr_payroll/),
> [`hr_payroll_attendance`](../enterprise/hr_payroll_attendance/)
> **Verified against Odoo 20 source 2026-09-22.** Related docs: [`public_holidays_flow.md`](public_holidays_flow.md),
> [`payroll_wage_types.md`](payroll_wage_types.md), [`attendance_work_entry.md`](attendance_work_entry.md),
> [`hr_payroll.md`](hr_payroll.md).

---

## Read This First — Odoo 20 Removed the `hr.work.entry` Model

**`hr.work.entry` does not exist in Odoo 20.** There is no work-entry table, no work-entry
calendar view, no work-entry state machine, no conflict engine, no generation cron and no
regeneration wizard. The only models left with "work entry" in the name are
`hr.work.entry.type` ([hr_work_entry_type.py:10](../addons/hr_work_entry/models/hr_work_entry_type.py#L10))
and the vestigial calendar filter `hr.user.work.entry.employee`
([hr_user_work_entry_employee.py:9](../addons/hr_work_entry/models/hr_user_work_entry_employee.py#L9)).

The whole bridge-module family is **deleted**: `hr_work_entry_holidays`,
`hr_work_entry_attendance`, `hr_work_entry_planning`, `hr_work_entry_planning_attendance`,
`hr_work_entry_enterprise`, `hr_work_entry_holidays_enterprise`, all `hr_work_entry_contract_*`,
`hr_payroll_holidays` and `hr_payroll_planning`. Those directories still exist in this checkout
but contain **nothing but stale `__pycache__`** left over from the v19 tree copy — `git ls-tree 20.0`
returns zero tracked files for every one of them. Do not import from them.

**Planning is no longer a payroll time source at all.** `planning.slot` has no work entry type
and no payroll bridge in v20.

**`hr.leave.type` is also gone.** Time-off types *are* work entry types now: `hr.leave.work_entry_type_id`
([hr_leave.py:167](../addons/hr_holidays/models/hr_leave.py#L167)), and `hr_holidays` bolts the
old leave-type fields (`requires_allocation`, `request_unit`, `leave_validation_type`,
`allows_negative`, …) onto `hr.work.entry.type`
([hr_work_entry_type.py:31](../addons/hr_holidays/models/hr_work_entry_type.py#L31)).

| Odoo 19 | Odoo 20 |
|---|---|
| `hr.work.entry` records, stored, with a lifecycle | **Nothing stored.** Real records (`hr.attendance`, `hr.leave`) carry the classification |
| `hr.work.entry.state` (draft / validated / conflict / cancelled) | `hr.attendance.state` (draft / validated / refused), `hr.leave.state`, plus `hr.payroll.warning` rows on the pay run |
| 4-check conflict engine, `_check_if_error` | Gone. Attendance overlap constraint + attendance validation policy + pay-run warnings |
| Cron "Generate Missing Work Entries" | Gone. Nothing is generated ahead of time |
| `date_generated_from` / `date_generated_to`, delta generation | Gone. Every consumer recomputes from scratch |
| Regeneration wizard | Gone |
| `hr.version.work_entry_source` (calendar / attendance / planning) | `hr.version.attendance_based` boolean ([hr_version.py:10](../addons/hr_attendance/models/hr_version.py#L10)) |
| `hr.work.entry.type.is_leave` / `is_work` | `count_as` = `working_time` \| `absence` ([hr_work_entry_type.py:36](../addons/hr_work_entry/models/hr_work_entry_type.py#L36)) |
| `hr.leave.type` | merged into `hr.work.entry.type` |
| `hr.attendance.overtime` + overtime rulesets | `hr.time.rule` ([hr_time_rule.py:110](../addons/hr_work_entry/models/hr_time_rule.py#L110)) |
| `struct.unpaid_work_entry_type_ids` | removed |
| Codes `WORK100` / `LEAVE100` everywhere | numeric codes: `002.00` Work, `006.00` Public holiday, `000.00` Out of contract ([hr_work_entry_type_data.xml](../addons/hr_work_entry/data/hr_work_entry_type_data.xml)) |

---

## What It Does & Why It Exists

A work entry is still the unit that sits between "time" (schedules, attendances, leaves) and
"money" (payslips): *this employee, this day, this many hours, of this type*. What changed is
**where it lives**. In v20 it is never a record. It exists in two forms:

1. **As a classification on a real record.** An `hr.attendance` and an `hr.leave` each carry a
   `work_entry_type_id`. That field *is* the work entry type of those hours. Payroll rates,
   absence-vs-working-time semantics and the payslip line all follow from it.
2. **As a transient dict, produced at the moment someone asks for it.**
   `hr.version.generate_work_entries(date_from, date_to)` returns a plain `list[dict]` of
   `{date, duration, work_entry_type_id, employee_id, version_id, company_id}`
   ([hr_version.py:303](../addons/hr_work_entry/models/hr_version.py#L303)). It creates nothing.
   The payslip calls it, consumes the list, and throws it away.

The piece that makes this work is the new **time rule engine** (`hr.time.rule`). Where v19 solved
"these 3 hours are overtime at 150%" by generating an extra work-entry record, v20 solves it by
**splitting the attendance or leave record itself** and stamping the overtime type on the split-off
part. The overtime is a real `hr.attendance` row you can see on the employee's attendance list,
not a shadow record in a separate table.

Who uses it: HR/Payroll managers configure Time Types and Time Rules once; attendance officers and
time-off approvers work with ordinary attendance and leave records; the payslip reads the
projection at compute time.

---

## The Big Picture — How It Works

```
CONFIG (once)
  hr.work.entry.type  ("Time Type": code, count_as, amount_rate)
  hr.time.rule        ("Automatic Rules": condition -> excess/deficit -> output type)
  resource.calendar.attendance.work_entry_type_id   (per schedule line)

LAYER 1 — classification, on real records, as they are saved
  hr.attendance (validated) ──┐
  hr.leave      (validated) ──┤─> hr.time.rule._evaluate_rules()
                              │     builds _Iv interval pipeline per employee
                              │     each rule, in sequence order, reclassifies slices
                              └─> _apply_output(): WRITES BACK
                                    - source record's own work_entry_type_id / end trimmed
                                    - new child records (source_attendance_id / source_leave_id)
                                    - optional leave allocation credit + log row

LAYER 2 — projection, at payslip time only
  hr.version.generate_work_entries(date_from, date_to)
      calendar theoretical attendance   (resource.calendar.attendance -> its own type)
    - resource.calendar.leaves          (public holidays + validated hr.leave)
    - days knocked out by attendances   (hr_holidays_attendance)
    + hr.attendance segments            (their own work_entry_type_id)
      -> split at local midnight, convert to (date, duration), merge per key
      -> list[dict]   <-- nothing persisted

CONSUMPTION
  hr.payslip._compute_worked_days_line_ids()
      -> version.get_work_hours() sums duration per (type, category options)
      -> one hr.payslip.worked_days line per type
      -> amount = hourly_rate x hours x type.amount_rate
```

### Key Decision Points

- **`hr.version.attendance_based`** ([hr_version.py:10](../addons/hr_attendance/models/hr_version.py#L10)) —
  the replacement for `work_entry_source`. `False` (default, from
  `res.company.attendance_based`): the theoretical schedule supplies the baseline hours.
  `True`: the schedule contributes nothing and badge records are the entire baseline
  ([hr_version.py:15](../addons/hr_holidays_attendance/models/hr_version.py#L15)).
  It is only a *baseline* switch — see the gotcha below: attendances win on days they exist either way.
- **A record's `work_entry_type_id`** decides the payslip line it lands on, its `amount_rate`,
  and whether it counts as working time or absence.
- **A time rule's `sequence`** ([hr_time_rule.py:119](../addons/hr_work_entry/models/hr_time_rule.py#L119)) —
  rules fire in order and each one sees what the previous ones already classified. Lowest
  sequence wins a contested interval.
- **`hr.work.entry.type.count_as`** — `absence` types are subtracted from working time by the
  resource engine ([resource_calendar.py:38](../addons/hr_work_entry/models/resource_calendar.py#L38));
  `working_time` types add to it.

---

## Layer 1 — The Time Rule Engine

This is the genuinely new machinery and the reason this doc exists.

### What a rule is

`hr.time.rule` ([hr_time_rule.py:110](../addons/hr_work_entry/models/hr_time_rule.py#L110)) is
*condition → effect* over time intervals. UI: **Attendances → Configuration → Automatic Rules**
or **Time Off → Configuration → Automatic Rules**
([hr_attendance_view.xml:649](../addons/hr_attendance/views/hr_attendance_view.xml#L649),
[hr_time_rule_views.xml:59](../addons/hr_holidays/views/hr_time_rule_views.xml#L59)).

| Part | Fields | What it does |
|---|---|---|
| **Scope** | `company_id`, `country_id`, `employee_domain` | Which employees the rule can touch ([_get_applicable_employees](../addons/hr_work_entry/models/hr_time_rule.py#L336)). Attendance narrows it further to employees with a calendar when `calendar_source='employee'` ([hr_time_rule.py:13](../addons/hr_attendance/models/hr_time_rule.py#L13)) |
| **Input filter** | `condition_work_entry_type_ids` (required) | Only intervals currently carrying one of these types are considered. This is what lets rules chain: rule 2 can match the output type of rule 1 |
| **Threshold** | `threshold_operator` (`exceed`/`less_than`), `working_hours_mode` | `schedule_day` / `schedule_week` compare against the calendar; `day` / `week` compare against a flat `expected_hours` ([hr_time_rule.py:130-163](../addons/hr_work_entry/models/hr_time_rule.py#L130)) |
| **Baseline** | `calendar_source` (`employee`/`reference`), `resource_calendar_id` | Whose schedule is "expected". `reference` falls back to company calendar then `env.company`'s ([_get_schedule_calendar](../addons/hr_work_entry/models/hr_time_rule.py#L364)) |
| **Timing window** | `apply_monday…apply_sunday`, `apply_on_public_holidays`, `timing_start`/`timing_stop` | Restricts the rule to certain weekdays and hours of the day. `timing_start > timing_stop` inverts the window, i.e. a night-shift band ([_build_hour_window_intervals](../addons/hr_work_entry/models/hr_time_rule.py#L485)) |
| **Tolerance** | `employer_tolerance` (exceed), `employee_tolerance` (less_than) | Excess/deficit below tolerance produces nothing ([hr_time_rule.py:798](../addons/hr_work_entry/models/hr_time_rule.py#L798), [:831](../addons/hr_work_entry/models/hr_time_rule.py#L831)) |
| **Effect: type** | `work_entry_type_id` ("Set Excess/Deficit to") | The type stamped on the matched portion. **Leave it empty** and the rule keeps the source type but still credits allocation / premium-pay categories |
| **Effect: pay** | `amount_rate` (read-only mirror of the output type's rate, [hr_time_rule.py:211](../addons/hr_work_entry/models/hr_time_rule.py#L211)), `premium_pay_category_ids` (payroll, [hr_time_rule.py:10](../enterprise/hr_payroll/models/hr_time_rule.py#L10)) | Rate lives on the **type**, not the rule. Premium-pay categories are pushed onto the output record as `category_options_ids` |
| **Effect: time off** | `leave_compensation_rate`, `allocation_type_id` (holidays, [hr_time_rule.py:26](../addons/hr_holidays/models/hr_time_rule.py#L26)) | Convert excess hours into a leave allocation (or claw back on deficit) |

Ships with 24 rules in [hr_time_rule_data.xml](../addons/hr_work_entry/data/hr_time_rule_data.xml):
one generic "Employee Schedule Rule" (anything beyond the daily schedule → Overtime) plus
localised stacks for ID, AE, EG, IQ, JO, OM, SA.

### The pipeline

`_evaluate_rules(records, start_dt, end_dt)`
([hr_time_rule.py:862](../addons/hr_work_entry/models/hr_time_rule.py#L862)) is the heart.

1. **Build the pipeline.** Each source record becomes one or more `_Iv` tuples
   ([hr_time_rule.py:21](../addons/hr_work_entry/models/hr_time_rule.py#L21)) —
   `(start, end, work_entry_type, source, classifying_rule, acc, pp)` in the employee's local
   naive time. `classifying_rule=None` means "untouched".
   Absence-type leaves are clipped to the working schedule first so lunch breaks and overnight
   gaps do not count toward thresholds
   ([_get_pipeline_intervals_local](../addons/hr_holidays/models/hr_leave.py#L1692));
   attendances keep their raw span.
2. **Each rule, in `sequence` order, over the whole pipeline.** The rule filters to intervals
   whose current type is in `condition_work_entry_type_ids`, clips them to its weekday/hour
   window, groups by day or week, and calls `_evaluate_period`
   ([hr_time_rule.py:744](../addons/hr_work_entry/models/hr_time_rule.py#L744)).
3. **`_evaluate_period` does the arithmetic.** Expected = schedule hours in the window (or flat
   `expected_hours`). Worked = union of the record intervals **minus a prorated share of the
   attendance's `break_duration`** — a 2 h break inside an 8 h attendance contributes 1 h to a
   4 h timing window ([hr_time_rule.py:772-790](../addons/hr_work_entry/models/hr_time_rule.py#L772)).
   On `exceed`, the excess is taken from the **end** of the day's intervals. On `less_than`, the
   deficit is materialised in the **gap** between schedule and worked time.
4. **Reclassify.** Matched slices are split at the excess boundaries and get the rule's output
   type. The previously classifying rule is pushed onto `acc` so its premium-pay categories and
   its allocation credit survive being displaced
   ([hr_time_rule.py:991-1014](../addons/hr_work_entry/models/hr_time_rule.py#L991)).
   A rule with no output type and no schedule threshold short-circuits: it tags everything it
   matched without loading schedule data ([hr_time_rule.py:940](../addons/hr_work_entry/models/hr_time_rule.py#L940)).
5. **Extract.** Anything left with `rule is not None` is the excess set.

### What "applying" a rule does to your data

`_apply_output` ([hr_time_rule.py:582](../addons/hr_work_entry/models/hr_time_rule.py#L582)) is
where it stops being a computation and starts being writes. This is the part to internalise:

- **The source record is mutated in place** when the first output slice starts at or before the
  source's own start: its `work_entry_type_id`, `time_rule_id` and end datetime are overwritten
  ([hr_time_rule.py:690-707](../addons/hr_work_entry/models/hr_time_rule.py#L690)). The original
  8 h attendance literally becomes the 8 h "Work" part.
- **Later slices become new child records** of the same model —
  `hr.attendance` with `source_attendance_id`, or `hr.leave` with `source_leave_id`
  ([hr_attendance.py:103](../addons/hr_attendance/models/hr_attendance.py#L103),
  [hr_leave.py:284](../addons/hr_holidays/models/hr_leave.py#L284)).
  Generated attendance children are auto-validated on create
  ([hr_attendance.py:689](../addons/hr_attendance/models/hr_attendance.py#L689)); generated leave
  children are created directly in `state='validate'`
  ([hr_time_rule.py:66](../addons/hr_holidays/models/hr_time_rule.py#L66)).
- **Deficit output goes into free slots**, not on top of existing records:
  `_get_time_rule_deficit_occupied` returns what is already there and the engine fills the
  complement, deducting hours already covered by a previous run so repeats are idempotent
  ([hr_time_rule_source_mixin.py:71](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L71)).
- **Allocation credit** (holidays): excess hours × `leave_compensation_rate` ÷ `hours_per_day`
  are added to an open-ended allocation of `allocation_type_id`, creating and approving one if
  none exists; every credit is logged in `hr.time.rule.allocation.log`
  ([hr_time_rule.py:76](../addons/hr_holidays/models/hr_time_rule.py#L76),
  [hr_time_rule_allocation_log.py:6](../addons/hr_holidays/models/hr_time_rule_allocation_log.py#L6)).
  Before a batch is re-evaluated, prior credits for those sources are **reversed** from the log
  ([_reverse_allocation_credits](../addons/hr_holidays/models/hr_time_rule.py#L245)) — and if the
  employee has already *spent* that balance, the reversal raises a `ValidationError` naming the
  employee, the type and the manager to talk to. Deficit is pre-filtered so an over-draw drops
  the deficit output entirely rather than pushing a balance negative
  ([_filter_deficit_exceeding_allocation](../addons/hr_holidays/models/hr_time_rule.py#L160)).

### When rules run

Triggered by ordinary CRUD on the source models, via the mixin's `create`/`write`
([hr_time_rule_source_mixin.py:330](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L330)):

| Trigger | Which rules |
|---|---|
| Attendance/leave create, or write to span / employee / type / state / break | `_trigger_time_rules` → `_trigger_time_rules_for_affected` ([:297](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L297)): **past days** get all day rules; **today** gets only `exceed` day rules; **past weeks** get only `exceed` week rules |
| Cron "Process daily time rules" (daily, on `hr.attendance` and `hr.leave`) | Yesterday's records, `less_than` day rules only ([:182](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L182)) |
| Cron "Process weekly time rules" | The week that ended yesterday, only rules whose `week_start` matches ([:195](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L195)) |

The split exists so undertime is never charged while the employee is still working the day or
the week. Only **validated** sources are eligible:
`[('state','=','validated')]` for attendance
([hr_attendance.py:660](../addons/hr_attendance/models/hr_attendance.py#L660)) and
`[('state','=','validate')]` for leaves
([hr_leave.py:1711](../addons/hr_holidays/models/hr_leave.py#L1711)).

`skip_time_rules=True` in the context disables the whole trigger path — the engine sets it on
its own writes, and you must set it on any bulk data fix you do not want re-evaluated.

---

## Layer 2 — The Payslip-Time Projection

`generate_work_entries` ([hr_version.py:303](../addons/hr_work_entry/models/hr_version.py#L303))
is a pure function from versions + a date range to a list of vals dicts. Nothing is written,
nothing is cached, and there is no notion of a "generated window" — it always recomputes.

### The algorithm

`_get_version_work_entries_values` ([hr_version.py:122](../addons/hr_work_entry/models/hr_version.py#L122)):

1. **Theoretical attendance** from `resource.calendar.attendance` for each version
   ([_get_attendance_intervals](../addons/hr_work_entry/models/hr_version.py#L72)). Fully flexible
   versions get the whole span as one interval.
2. **Subtract `resource.calendar.leaves`** in range. Each calendar leave is routed by its own
   `count_as`: `absence` reduces working time, `working_time` (e.g. paid training booked as a
   leave) replaces it ([hr_version.py:172](../addons/hr_work_entry/models/hr_version.py#L172)).
3. **Resolve each leave interval to a type**
   ([_get_interval_leave_work_entry_type](../addons/hr_work_entry/models/hr_version.py#L44),
   overridden in [hr_version.py:264](../addons/hr_holidays/models/hr_version.py#L264)). Priority:
   a country "bypass" code (`_get_bypassing_work_entry_type_codes`, non-empty only in BE and HK)
   > **global calendar leave** (public holiday) > employee leave > the generic
   `generic_work_entry_type_leave` fallback.
4. **Postprocess** ([_generate_work_entries_postprocess](../addons/hr_work_entry/models/hr_version.py#L412)):
   split every interval at local midnight, convert `(date_start, date_stop)` to `(date, duration)`,
   drop zero-duration, and **merge** everything sharing the merge key into one dict. The key is
   `(date, work_entry_type_id, employee_id, version_id, company_id)`
   ([:386](../addons/hr_work_entry/models/hr_version.py#L386)), extended with
   `category_options_ids` when payroll is installed
   ([hr_version.py:713](../enterprise/hr_payroll/models/hr_version.py#L713)).

Absence-type intervals get their duration from the calendar's theoretical hours rather than the
raw clock difference — that is what `_generate_work_entries_postprocess_adapt_to_calendar`
selects ([:405](../addons/hr_work_entry/models/hr_version.py#L405)).

### The schedule line chooses the type

Every `resource.calendar.attendance` row ("Monday morning", "Saturday shift") carries its own
`work_entry_type_id` ([resource_calendar_attendance.py:13](../addons/hr_work_entry/models/resource_calendar_attendance.py#L13)),
restricted to types flagged `resource_calendar_selectable` (auto-true for `working_time` types,
[hr_work_entry_type.py:112](../addons/hr_work_entry/models/hr_work_entry_type.py#L112)).
Generation reads it ([_get_interval_work_entry_type](../addons/hr_work_entry/models/hr_version.py#L91));
fallback is the structure type's `default_work_entry_type_id`
([hr_version.py:609](../enterprise/hr_payroll/models/hr_version.py#L609)), then the country's
`002.00` type, then the generic Work type
([_get_default_work_entry_type_id](../addons/hr_work_entry/models/hr_version.py#L18)).

So a schedule can emit **custom types automatically and with no rule at all** — a Saturday slot
configured as "Site Day" produces that type every week. A schedule line whose type is an
`absence` is excluded from `hours_per_week` / `days_per_week` / `hours_per_day` and from
`_is_work_period` ([resource_calendar_attendance.py:64](../addons/hr_work_entry/models/resource_calendar_attendance.py#L64),
[resource_calendar.py:11](../addons/hr_work_entry/models/resource_calendar.py#L11)) — but the day
still counts in full toward `_get_reference_hours_per_day`
([resource_calendar.py:23](../addons/hr_work_entry/models/resource_calendar.py#L23)).

### Attendances override the schedule

`hr_holidays_attendance` is `auto_install` with `hr_attendance` + `hr_holidays`, so on any
database with both, it rewrites generation
([hr_version.py:35](../addons/hr_holidays_attendance/models/hr_version.py#L35)):

- Validated attendances with a check-out are pulled in and become work-entry vals in their own
  right, carrying their own `work_entry_type_id`
  ([:115](../addons/hr_holidays_attendance/models/hr_version.py#L115)). `break_duration` is cut
  off the end ([:94](../addons/hr_holidays_attendance/models/hr_version.py#L94)).
- For a **calendar-based** version, every local day that has an attendance is "knocked out" of
  the theoretical schedule wholesale
  ([:88](../addons/hr_holidays_attendance/models/hr_version.py#L88) →
  [_get_real_attendances:143](../addons/hr_holidays_attendance/models/hr_version.py#L143)).
  **Consequence: one badge record replaces the entire scheduled day.** `attendance_based`
  therefore only changes what happens on days with *no* attendance.
- `working_time` leaves and attendances that overlap are resolved by **work entry type
  sequence**, lowest wins, via `resolve_intervals_by_sequence`
  ([:103](../addons/hr_holidays_attendance/models/hr_version.py#L103),
  [hr_time_rule.py:31](../addons/hr_work_entry/models/hr_time_rule.py#L31)). Absence leaves lose
  to any worked time that overlaps them
  ([_get_valid_leave_intervals:165](../addons/hr_holidays_attendance/models/hr_version.py#L165)).

---

## Validation & State — What Replaced the Conflict Engine

There is no conflict state and nothing blocks a payslip on "missing work entries". Validity is
now enforced on the real records, at three different places.

**1. Attendance state machine** ([hr_attendance.py:95](../addons/hr_attendance/models/hr_attendance.py#L95)):
`draft` → `validated` → `refused`. What creates a draft is the company's
`attendance_validation` policy ([res_company.py:37](../addons/hr_attendance/models/res_company.py#L37)):

| Policy | Effect on create |
|---|---|
| `no_validation` (default) | Everything is created `validated` |
| `tolerance_validation` | `_update_tolerance_state` auto-validates only if worked hours are within `attendance_validation_tolerance` of the day's expected hours; otherwise the record stays `draft` and waits for approval ([hr_attendance.py:669](../addons/hr_attendance/models/hr_attendance.py#L669)) |
| (any) | Records the engine itself creates (`time_rule_id` or `source_attendance_id` set) always auto-validate ([hr_attendance.py:692](../addons/hr_attendance/models/hr_attendance.py#L692)) |

Draft and refused attendances are invisible to both layers. The old "overlap" check survives as a
hard SQL-level constraint: `_check_validity` forbids overlapping or double-open attendances for
an employee ([hr_attendance.py:198](../addons/hr_attendance/models/hr_attendance.py#L198)) —
bypassed under `skip_time_rules` so the engine can split records.

**2. The `source_stale` flag** — the closest thing left to a conflict badge. Editing or deleting
a source attendance marks its surviving rule outputs stale
([_STALE_TRIGGER_FIELDS:243](../addons/hr_attendance/models/hr_attendance.py#L243),
[_mark_outputs_stale_on_delete:264](../addons/hr_attendance/models/hr_attendance.py#L264)). The
attendance list/kanban shows a warning and a **Mark Reviewed** button
([hr_attendance_view.xml:41](../addons/hr_attendance/views/hr_attendance_view.xml#L41),
[action_mark_reviewed:269](../addons/hr_attendance/models/hr_attendance.py#L269)). It is advisory
— it blocks nothing.

**3. Pay-run warnings** — `_get_start_payrun_warnings`
([hr_payslip_run.py:428](../enterprise/hr_payroll/models/hr_payslip_run.py#L428)) surfaces
"Time Offs to Review" (unapproved or deferred leaves in the period) and "No Time Offs"
(nothing recorded at all) before the run starts. `hr_payroll_attendance` adds an
"Attendance Discrepancies" warning for employees who have attendances but are not
`attendance_based`
([hr_payroll_attendance_warning_data.xml:4](../enterprise/hr_payroll_attendance/data/hr_payroll_attendance_warning_data.xml#L4)).
These pre-run warnings are dashboard guidance and block nothing by themselves. The hard gate is
`hr.payslip.run.action_validate`: a user who is not a Payroll Officer (or system/superuser)
cannot validate a run whose slips still carry warnings or errors
([hr_payslip_run.py:376](../enterprise/hr_payroll/models/hr_payslip_run.py#L376)).

**Leave deferral** survives, moved from the deleted `hr_payroll_holidays` into `hr_payroll`
itself: a leave overlapping an already-validated payslip gets `payslip_state='blocked'`
([hr_leave.py:17](../enterprise/hr_payroll/models/hr_leave.py#L17)) and its
`resource.calendar.leaves` are filtered out of generation entirely
([hr_version.py:707](../enterprise/hr_payroll/models/hr_version.py#L707)).

---

## How the Payslip Consumes Them

1. `_compute_worked_days_line_ids` ([hr_payslip.py:2162](../enterprise/hr_payroll/models/hr_payslip.py#L2162))
   collects every version overlapping the slip (including mid-period version swaps) and calls
   `all_versions_to_generate.generate_work_entries(date_from - 1, date_to + 1)` **once for the
   whole batch** ([:2217](../enterprise/hr_payroll/models/hr_payslip.py#L2217)), then splits the
   resulting vals per version. Refund slips copy and negate the origin's lines instead.
2. `get_work_hours` ([hr_version.py:559](../enterprise/hr_payroll/models/hr_version.py#L559) →
   [_get_work_hours:580](../enterprise/hr_payroll/models/hr_version.py#L580)) filters the list to
   this version and this date range and sums `duration` keyed by
   `(work_entry_type_id, category_options_ids)`. Pure Python over the dicts — no query, no state
   filter, nothing to exclude.
3. `_get_worked_day_lines_values` ([hr_payslip.py:1374](../enterprise/hr_payroll/models/hr_payslip.py#L1374))
   makes one worked-days line per key. `number_of_days = hours / hours_per_day`, rounded per
   `work_entry_type.round_days_type` unless the type's `request_unit` is `hour`
   ([_round_days:1344](../enterprise/hr_payroll/models/hr_payslip.py#L1344)); the rounding
   remainder is dumped on the biggest line. **Hours produced by a time-rule split
   (`trimmed_duration`) are excluded from rounding** and keep their exact fraction
   ([hr_payslip.py:1385-1400](../enterprise/hr_payroll/models/hr_payslip.py#L1385),
   tagged at [hr_version.py:721](../enterprise/hr_payroll/models/hr_version.py#L721)).
4. An **Out Of Contract** line (code `000.00`, `amount_rate` 0) is appended for stretches of the
   period outside the contract ([hr_payslip.py:1462](../enterprise/hr_payroll/models/hr_payslip.py#L1462)).
5. `hr.payslip.worked_days._compute_amount` prices it:
   `amount = hourly_rate × number_of_hours × work_entry_type.amount_rate`, zero when
   `amount_rate == 0` ([hr_payslip_worked_days.py:123](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L123),
   [:51](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L51)). Types in the
   `EXTRA_HOURS` salary-rule category are `is_extra_hours` and stay out of the fixed-wage
   denominator ([hr_work_entry_type.py:37](../enterprise/hr_payroll/models/hr_work_entry_type.py#L37),
   [hr_payslip_worked_days.py:108](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L108)).
   Full pricing chain: [`payroll_wage_types.md`](payroll_wage_types.md) §2.

Because the projection is recomputed on every `_compute_worked_days_line_ids`, a draft slip
picks up new attendances or leaves as soon as it is refreshed —
`action_refresh_from_work_entries` ([hr_payslip.py:1326](../enterprise/hr_payroll/models/hr_payslip.py#L1326))
drops the lines and recomputes; `_recompute_payslips` does it automatically when wage fields
change ([hr_version.py:683](../enterprise/hr_payroll/models/hr_version.py#L683)). There is still
**no staleness detection** for time data changing after a slip was computed.

There is **no state choreography between payslip and time records** any more. Validating a
payslip does not lock, validate or archive anything; cancelling it releases nothing. The only
back-pressure is `payslip_state` on the leave and the `_unlink_except_valid_payslips` guard on
the version ([hr_version.py:649](../enterprise/hr_payroll/models/hr_version.py#L649)).

---

## Time Type Anatomy (`hr.work.entry.type`)

Labelled **"Time Type"** in the UI now, and it is the single classification table for worked time,
absence *and* time-off types.

| Field | Where | What it controls |
|---|---|---|
| `code` | base | Payroll code referenced by salary rules. Unique per country (NULL country included), enforced with a readable error ([_check_code_unicity](../addons/hr_work_entry/models/hr_work_entry_type.py#L52)). Core types now use numeric codes |
| `count_as` | base | `working_time` \| `absence`. Replaces `is_work`/`is_leave`. Drives the resource engine, the pipeline clipping and `_is_work_period` |
| `amount_rate` | base | The pay multiplier, read at pay time. 0 = unpaid, 1.5 = 150% |
| `display_code` / `color` | base | 3-char badge and colour on attendance/leave/calendar views |
| `external_code` | base | Third-party payroll provider code, consumed by the export wizard |
| `resource_calendar_selectable` | base | Whether the type can be put on a schedule line. Defaults to `count_as == 'working_time'` |
| `country_id` | base | Scopes the type. Leave empty for your own types; a company with **any** localised type sees only that country's types ([res_company.py:23](../addons/hr_work_entry/models/res_company.py#L23)) |
| `requires_allocation`, `time_off_selectable`, `request_unit`, `leave_validation_type`, `allows_negative`, `include_public_holidays_in_duration`, … | `hr_holidays` | The whole former `hr.leave.type` surface ([hr_work_entry_type.py:31](../addons/hr_holidays/models/hr_work_entry_type.py#L31)) |
| `category_ids` / `optional_category_ids` | `hr_payroll` | Salary rule categories. `EXTRA_HOURS` in `category_ids` computes `is_extra_hours` ([hr_work_entry_type.py:24](../enterprise/hr_payroll/models/hr_work_entry_type.py#L24)) |
| `round_days_type`, `display_hours` | `hr_payroll` | Day rounding on the payslip line |
| `modified_by_user` | `hr_payroll` | Set when a user edits a critical field of a system-created type; it then stops being overwritten by data reloads, and **Reset** restores it ([hr_work_entry_type.py:106](../enterprise/hr_payroll/models/hr_work_entry_type.py#L106)) |

With payroll installed, types can only be archived, never deleted
([_unlink_except_work_entry_type](../enterprise/hr_payroll/models/hr_work_entry_type.py#L98)).
Duplicating one auto-suffixes the code with a uuid fragment
([hr_work_entry_type.py:104](../addons/hr_work_entry/models/hr_work_entry_type.py#L104)).

Generic types shipped ([hr_work_entry_type_data.xml](../addons/hr_work_entry/data/hr_work_entry_type_data.xml)):
Work `002.00`, Overtime 150% `040.00`, Out Of Contract `000.00` (rate 0), Generic Time Off
`LEAVE100`, Compensatory `LEAVE105`, Work from home `002.08`, Leave without pay `158.00`,
Illness `013.00`, Legal leave `016.00`, Public holiday `006.00`.

**Different rates still require different types** — `amount_rate` is read from the type at pay
time and there is no per-record rate override. That is why the shipped overtime rule stacks map
each rate band to its own type.

---

## The Sources in Depth

### Attendances (`hr_attendance`)

`hr.attendance` inherits the source mixin
([hr_attendance.py:26](../addons/hr_attendance/models/hr_attendance.py#L26)) with
`check_in`/`check_out` as the span. `work_entry_type_id` is **required**, defaulting to
`res.company.attendance_work_entry_type_id` — itself computed from the company country's
`002.00` type ([res_company.py:46](../addons/hr_attendance/models/res_company.py#L46)).
So plain presence is no longer hardcoded to one xmlid; it is a per-company setting
(**Attendances → Configuration → Settings → Attendance Time Type**).

Rule outputs appear as child attendances on a "Rules Outputs" page of the source form
([hr_attendance_overtime_views.xml:12](../addons/hr_holidays_attendance/views/hr_attendance_overtime_views.xml#L12)).
Open attendances (no check-out) contribute nothing — the source domain requires a non-false
span end ([hr_time_rule_source_mixin.py:117](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L117)).

### Time off (`hr_holidays`)

`hr.leave` inherits the mixin with `date_from`/`date_to` as the span
([hr_leave.py:74](../addons/hr_holidays/models/hr_leave.py#L74)). A leave feeds the payslip
through two different paths that must not be confused:

- **As a `resource.calendar.leaves` row** — created by `_create_resource_leave()` on validation,
  carrying `holiday_id`. This is what Layer 2 reads and subtracts from the schedule.
- **As a time-rule source** — the leave record itself, which rules can split and reclassify.

A rule splitting a day-unit leave sets `is_time_rule_trimmed`
([hr_leave.py:286](../addons/hr_holidays/models/hr_leave.py#L286)) so that
`_compute_date_from_to` does not snap the trimmed end back to the schedule boundary; the form
then shows a `HH:MM → HH:MM` range instead of a whole day
([_compute_time_rule_time_range:297](../addons/hr_holidays/models/hr_leave.py#L297)).
The `_time_rule_write_ctx` on `hr.leave`
([hr_leave.py:81](../addons/hr_holidays/models/hr_leave.py#L81)) is a long list of skip flags —
that is the engine writing leaves without re-firing approvals, date checks or the overlap
constraint. Whenever you write leaves programmatically near this engine, you need the same flags.

After applying leave output, `_create_resource_leave()` is re-run on sources *and* new records so
the calendar view of Layer 2 stays consistent
([hr_time_rule.py:242](../addons/hr_holidays/models/hr_time_rule.py#L242)).

### Public holidays / global time off

A `resource.calendar.leaves` with no `resource_id` gets its type computed to the country's
`006.00` "Public holiday", falling back to the generic one
([resource_calendar_leaves.py:18](../addons/hr_work_entry/models/resource_calendar_leaves.py#L18)).
In type resolution, a global calendar leave beats an employee leave for the same interval unless
a country bypass code applies
([hr_version.py:288](../addons/hr_holidays/models/hr_version.py#L288)). Rules can be told to
ignore public holidays with `apply_on_public_holidays=False`, which subtracts the holiday days
from the rule's window ([_build_rule_day_intervals:534](../addons/hr_work_entry/models/hr_time_rule.py#L534)).
Balance-side treatment (`include_public_holidays_in_duration`) and the company/timezone matrix
are in [`public_holidays_flow.md`](public_holidays_flow.md) — **note that doc still describes the
v19 architecture.**

### Overtime → time off (`hr_holidays_attendance`)

This is where "extra hours become leave" now lives. The attendance flavour of
`_apply_attendance_output` pre-filters over-drawing deficits and then applies the allocation
credits ([hr_time_rule.py:9](../addons/hr_holidays_attendance/models/hr_time_rule.py#L9)).
Configure it on the rule: **Allocate <rate>% to <Time Off Type>**
([hr_time_rule_views.xml:43](../addons/hr_holidays/views/hr_time_rule_views.xml#L43)). The
allocation target must `requires_allocation` and be `time_off_selectable`; the *output* type must
be the opposite — `requires_allocation = False`
([hr_time_rule.py:22](../addons/hr_holidays/models/hr_time_rule.py#L22)).

---

## Export

`hr.export.work.entries` ([hr_export_work_entries.py:11](../addons/hr_work_entry/wizard/hr_export_work_entries.py#L11))
exports a month of the Layer-2 projection to a semicolon-separated file for external payroll
providers: date, company, company external code, type name/code/external code, employee name and
external code, duration in hours
([_get_columns:84](../addons/hr_work_entry/wizard/hr_export_work_entries.py#L84)). It calls
`generate_work_entries` directly ([:199](../addons/hr_work_entry/wizard/hr_export_work_entries.py#L199)) —
no stored data involved. Reached from the Employees list cog menu
([export_cog_menu.js](../addons/hr_work_entry/static/src/export_cog_menu/export_cog_menu.js)) or
the list action ([hr_employee_views.xml:16](../addons/hr_work_entry/views/hr_employee_views.xml#L16)),
downloaded through `/hr_work_entry/download/<company>/<export>`
([main.py:7](../addons/hr_work_entry/controllers/main.py#L7)).

---

## Security & UI

**Access** ([ir.access.csv](../addons/hr_work_entry/security/ir.access.csv)):

| Model | Who | Notes |
|---|---|---|
| `hr.work.entry.type` | HR Officer read; HR Manager CRUD; Payroll Manager CRUD ([hr_payroll ir.access.csv:19](../enterprise/hr_payroll/security/ir.access.csv#L19)); Time Off Manager CRUD, Time Off Employee read ([hr_holidays ir.access.csv:63](../addons/hr_holidays/security/ir.access.csv#L63)) | Restriction row limits visibility to types of the user's companies' countries plus country-less ones |
| `hr.time.rule` | Attendance Officer CRUD ([hr_attendance ir.access.csv:7](../addons/hr_attendance/security/ir.access.csv#L7)); Time Off Manager CRUD, Time Off Officer read ([hr_holidays ir.access.csv:92](../addons/hr_holidays/security/ir.access.csv#L92)) | Restriction: own-company rules, or company-less rules of a matching country |
| `hr.time.rule.allocation.log` | Time Off Manager CRUD, Officer read | Audit trail for allocation credits |
| `hr.export.work.entries(.employee)` | HR Officer CRUD | Company restriction on the export |

Note there is no `hr.time.rule` permission row for a pure payroll user — the rules are reachable
only through the Attendance or Time Off groups.

**Menus:**
- Employees → Configuration → Working Schedules → **Time Types**
  ([menuitems.xml:4](../addons/hr_work_entry/views/menuitems.xml#L4))
- Payroll → Configuration → **Time Management** → Time Types / Working Schedules / Public Holidays
  ([hr_payroll_menu.xml:79](../enterprise/hr_payroll/views/hr_payroll_menu.xml#L79))
- Attendances → Configuration → **Automatic Rules** (Attendance Manager)
- Time Off → Configuration → **Automatic Rules** (Time Off Manager)

**There is no Work Entries screen.** You look at attendances and at time off. The rule form
([hr_time_rule_views.xml:10](../addons/hr_work_entry/views/hr_time_rule_views.xml#L10)) is a
sentence-shaped builder — "Exceed [8:00] the daily schedule ± [0:30] based on Employee Schedule,
Mon–Fri, from 00:00 to 24:00 → Set Excess to Overtime, Allocate 100% to Compensatory".
The Worked Days tab on the payslip remains a read-only projection
([hr_payslip_views.xml:150](../enterprise/hr_payroll/views/hr_payslip_views.xml#L150)).

---

## Gotchas & Non-Obvious Behavior

- **Rules mutate your source data, permanently.** An `exceed` rule rewrites the attendance's own
  `work_entry_type_id` and end time, then creates children. There is no "cancel rule" button and
  no archive of what the record looked like before. Test a rule on a copy of production data.
- **Only validated sources are seen.** A draft attendance or an unapproved leave is invisible to
  both the rule engine and the payslip. With `attendance_validation='no_validation'` (the
  default) everything is validated on create, so this bites only on databases that turned
  validation on.
- **Attendances beat the schedule on any day they exist**, even for a calendar-based version,
  because `hr_holidays_attendance` knocks the whole local day out of the theoretical schedule.
  One 2-hour badge on an 8-hour scheduled day produces 2 paid hours, not 8.
  `attendance_based` only governs days with no attendance at all.
- **No generation cron, no pre-generated data.** Nothing exists until a payslip (or the export
  wizard) asks. Correspondingly there is nothing to "regenerate" and nothing to fix after the
  fact — you fix the attendance or the leave.
- **Week rules are cron-only for undertime.** `_trigger_time_rules_for_affected` deliberately
  runs only `exceed` week rules on save, because charging a weekly deficit while the user is
  still entering the week's data would create spurious records
  ([hr_time_rule_source_mixin.py:326](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L326)).
- **Reversing an allocation credit can raise.** If a rule granted compensatory days and the
  employee already took them, editing the originating attendance raises a `ValidationError`
  naming the record, the employee and the manager
  ([hr_time_rule.py:267](../addons/hr_holidays/models/hr_time_rule.py#L267)). Expect this to
  surface as "I can't fix a typo in an old attendance".
- **Rule order is global, not per-source.** Rules are evaluated in `sequence, id` order across
  the whole applicable set, and each one sees the previous ones' output. Localisation data uses
  this deliberately (Indonesia: the ">9 h at 200%" rule has the lower sequence so it wins the
  overlap with ">8 h at 150%"). Inserting a rule in the middle of a shipped stack changes the
  meaning of the rules after it.
- **`condition_work_entry_type_ids` is required and defaults to the company's attendance type**
  ([hr_time_rule.py:9](../addons/hr_attendance/models/hr_time_rule.py#L9)). A rule with the wrong
  input type silently matches nothing — there is no warning.
- **A rule with no output type is still a rule.** It does not reclassify, but it can still attach
  premium-pay categories and allocate leave. That is the `_get_source_annotation_vals` path
  ([hr_time_rule.py:667](../addons/hr_work_entry/models/hr_time_rule.py#L667)).
- **`hr.time.rule.amount_rate` is display only** — a stored mirror of the output type's rate
  ([hr_time_rule.py:305](../addons/hr_work_entry/models/hr_time_rule.py#L305)). Editing it on the
  rule changes no money. Change the type's rate, or point the rule at a different type.
- **`skip_time_rules` disables the entire engine.** Useful for migrations and bulk fixes,
  dangerous everywhere else — records written under it are never evaluated, and nothing re-queues
  them.
- **Breaks are prorated, not subtracted whole.** `break_duration` is spread across whatever
  fraction of the attendance falls inside the rule's timing window
  ([hr_time_rule.py:790](../addons/hr_work_entry/models/hr_time_rule.py#L790)) — a narrow night
  window on a long shift absorbs only its share.
- **Custom time sources are a real option again.** Because the classification lives on records
  implementing `hr.time.rule.source.mixin`, a custom model can plug in by declaring the four
  `_time_rule_*` attributes and implementing `_get_time_rule_output_vals`,
  `_get_time_rule_remainder_vals` and `_get_time_rule_deficit_occupied`
  ([hr_time_rule_source_mixin.py:21](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L21)).
  Getting hours onto the **payslip**, though, additionally means overriding
  `_get_version_work_entries_values` — the projection only knows about the calendar, calendar
  leaves and (via `hr_holidays_attendance`) attendances.
- **Multi-company generation is loose.** `_get_leave_domain` searches calendar leaves with
  `company_id in [False] + version.company_id.ids`
  ([hr_version.py:60](../addons/hr_work_entry/models/hr_version.py#L60)) without the resource
  engine's exact company/calendar pairing; a customisation that needs strict scoping must add its
  own filter.
- **`hr.user.work.entry.employee` is dead weight.** It survived the rewrite but nothing outside
  its own definition and ACL references it.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`attendance_work_entry.md`](attendance_work_entry.md) — the attendance source and the rule
  engine from the attendance side (also verified against v20)
- [`hr_payroll.md`](hr_payroll.md) — payslip lifecycle, pay-run warnings, accounting.
  **Its appendices (A/B/C, crons, key-methods map) still describe the v19 work-entry model.**
- [`payroll_wage_types.md`](payroll_wage_types.md) — how the aggregated lines become money.
  **Still written for v19: §3, §7.5–7.7, §8.2 and §10 describe removed modules and the
  conflict engine.**
- [`public_holidays_flow.md`](public_holidays_flow.md) — public holiday semantics.
  **Still written for v19: "Flow B", the work-entry source matrix and the safety-gap table
  describe removed machinery.**

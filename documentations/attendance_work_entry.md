# Attendance and Payroll Time — `hr_attendance` + Time Rules + Payslips

> **Modules:** `hr_attendance`, `hr_work_entry`, `hr_holidays_attendance`, `hr_payroll_attendance` | **Path:** [`addons/hr_attendance/`](../addons/hr_attendance/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

Employees check in and out (kiosk, systray, manual entry). Each clock record is an
`hr.attendance` with a **time type**. Payroll uses those records in two ways:

- **As the baseline** for employees whose version is *attendance based*: only clocked time is
  worked time.
- **As overrides of the schedule** for everybody else: a validated attendance replaces the
  scheduled hours of the day it falls on.

Overtime and missing time are handled by **time rules** (`hr.time.rule`), which split and
re-type the attendance records themselves. Nothing is generated or stored for payroll: when a
payslip is computed, `hr.version.generate_work_entries()` builds the day/duration values from
schedules, attendances and leaves. `hr.work.entry` records do not exist in 20.0; see
[`work_entries.md`](work_entries.md) for that projection.

---

## The Big Picture — How It Works

```
hr.attendance (check-in/out, break, time type, state)
    | validated + closed only
    v
hr.time.rule engine            splits / re-types the attendance, creates child records
    |                           (overtime, deficit), optional time-off allocation credit
    v
payslip compute: hr.version.generate_work_entries(date_from, date_to)
    schedule hours (not attendance-based versions)
  - days that have a validated attendance (whole local day)
  + attendance segments, each with its own time type, break cut off the end
  +/- leaves and public holidays (worked time wins over absence)
    v
worked-day lines per time type  ->  amount = rate x hours x type rate
```

### Key Decision Points

- **Attendance based or not** (`hr.version.attendance_based`,
  [hr_version.py:10](../addons/hr_attendance/models/hr_version.py#L10); company default
  "Default Tracking"). It only changes the days *without* a validated attendance: schedule hours
  (off) or nothing (on).
- **Validation policy** of the company: decides whether new attendances count at once.
- **Time rules**: which hours become overtime or missing time, and with which time type and rate.

---

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `hr_work_entry` | Time types, the `hr.time.rule` engine, the source mixin, the schedule/leave projection ([manifest](../addons/hr_work_entry/__manifest__.py)) |
| `hr_attendance` | Clock records, validation, breaks, kiosk/systray, crons; depends on `hr_work_entry` ([__manifest__.py:18](../addons/hr_attendance/__manifest__.py#L18)) |
| `hr_holidays_attendance` | Puts attendances into the payslip projection, resolves attendance/leave overlaps, allocation credits from rules; auto-installs with Attendances + Time Off ([__manifest__.py:9](../addons/hr_holidays_attendance/__manifest__.py#L9)) |
| `hr_payroll_attendance` | Payslip attendance count and button, payroll options on attendances, pay-run warnings; auto-installs with payroll ([__manifest__.py:8](../enterprise/hr_payroll_attendance/__manifest__.py#L8)) |
| `hr_attendance_gantt` | Gantt view of attendances (worked vs expected hours) |
| `hr_timesheet_attendance` | Timesheet vs attendance report only; no timesheet-to-payroll link |

---

## Attendance Records

Source: [`hr_attendance.py`](../addons/hr_attendance/models/hr_attendance.py).

| Field | Behavior |
|---|---|
| `check_in`, `check_out` | UTC timestamps; a record without check-out is open ([:47](../addons/hr_attendance/models/hr_attendance.py#L47)) |
| `date` | Check-in date in the employee's timezone |
| `worked_hours` | Check-out minus check-in minus `break_duration` ([:163](../addons/hr_attendance/models/hr_attendance.py#L163)); no automatic lunch deduction |
| `break_duration` | Extra unpaid break in hours: not negative, not longer than the attendance, only once checked out ([:176](../addons/hr_attendance/models/hr_attendance.py#L176)) |
| `work_entry_type_id` | Required time type, default = company's Attendance Time Type ([:87](../addons/hr_attendance/models/hr_attendance.py#L87)) |
| `state` | `draft` / `validated` / `refused` ([:95](../addons/hr_attendance/models/hr_attendance.py#L95)) |
| `time_rule_id`, `source_attendance_id`, `overtime_attendance_ids` | Which rule produced this record, from which source, and the outputs of a source ([:102](../addons/hr_attendance/models/hr_attendance.py#L102)) |
| `source_stale` | Warning on a rule output whose source was edited or deleted |
| `in_mode`, `out_mode` | Capture channel: kiosk, systray, manual, auto check-out, technical |

- **Validity** ([_check_validity](../addons/hr_attendance/models/hr_attendance.py#L198)): no
  overlapping attendances per employee and only one open record. The engine's own writes use
  `skip_time_rules`, which also skips this check, because splitting creates adjacent records.
- **Duplicating is blocked** ([copy](../addons/hr_attendance/models/hr_attendance.py#L272)).
  Moving an attendance to another employee is refused unless it is your own, you are that
  employee's attendance manager, or you are Attendance Administrator ([write](../addons/hr_attendance/models/hr_attendance.py#L245)).
- **Stale outputs.** Changing check-in/out, break, employee or time type of a source, or deleting
  it, marks its surviving outputs `source_stale` ([:243](../addons/hr_attendance/models/hr_attendance.py#L243),
  [:264](../addons/hr_attendance/models/hr_attendance.py#L264)). **Mark Reviewed** only clears the
  flag ([action_mark_reviewed](../addons/hr_attendance/models/hr_attendance.py#L269)); it does
  not rebuild anything.

---

## Validation

Company setting **Attendance Validation** ([res_company.py:37](../addons/hr_attendance/models/res_company.py#L37)):

| Value | New attendances |
|---|---|
| `no_validation` (default) | Created validated |
| `manual_validation` | Created draft; a manager validates |
| `tolerance_validation` | Created draft, then validated automatically when closed if the elapsed time is within **Validation Tolerance (Hours)** of the day's expected hours, or when no hours are expected ([_update_tolerance_state](../addons/hr_attendance/models/hr_attendance.py#L669)) |

- Records produced by a rule (`time_rule_id` or `source_attendance_id` set) are always created
  validated; an explicit `state` in the values wins ([create](../addons/hr_attendance/models/hr_attendance.py#L689)).
- The tolerance check compares **elapsed** time, not `worked_hours`, so a long break does not
  push a record out of tolerance.
- `action_validate`, `action_reset_to_draft` and `action_refuse` (rules skipped) set the state
  ([:704](../addons/hr_attendance/models/hr_attendance.py#L704)).
- **Only closed, validated attendances count** for time rules and for payroll. Draft, refused and
  open records supply nothing.

---

## Time Rules

Source: [`hr_time_rule.py`](../addons/hr_work_entry/models/hr_time_rule.py#L110), extended by
[`hr_attendance`](../addons/hr_attendance/models/hr_time_rule.py). Menu: Attendances →
Configuration → Automatic Rules. Rule anatomy and pipeline: [`work_entries.md`](work_entries.md).

| Setting | Purpose |
|---|---|
| `sequence`, `active`, `company_id` / `country_id`, `employee_domain` | Order and scope. A rule with no company, no country and an empty domain applies to every employee ([_get_applicable_employees](../addons/hr_work_entry/models/hr_time_rule.py#L336)) |
| `condition_work_entry_type_ids` | Which time types the rule looks at; defaults to the company's attendance type ([hr_time_rule.py:9](../addons/hr_attendance/models/hr_time_rule.py#L9)) |
| `threshold_operator` | `exceed` (overtime) or `less_than` (missing time) |
| `working_hours_mode`, `calendar_source`, `resource_calendar_id`, `expected_hours` | Compare with the daily or weekly schedule (employee's or a reference calendar), or with flat daily/weekly hours |
| `week_start` | Week boundary for weekly rules |
| Weekday flags, `apply_on_public_holidays` | Days the rule applies to |
| `timing_start`, `timing_stop` | Hour window inside a day; the database requires start < stop ([:226](../addons/hr_work_entry/models/hr_time_rule.py#L226)), so a 22:00–06:00 night band needs two rules |
| `employer_tolerance`, `employee_tolerance` | Excess or deficit below the tolerance produces nothing |
| `work_entry_type_id` ("Set Excess to") | Time type of the matched hours; may be empty when the rule only adds payroll options or time-off credit |
| `amount_rate` | Display mirror of the output type's rate; the money follows the type |

What applying a rule does: the source attendance is shortened and re-typed or kept as the first
output, further outputs and remainders become new attendance records, and deficit outputs are
placed in the free schedule time. Outputs carry payroll options (`category_options_ids`) from
`hr_payroll_attendance` ([hr_time_rule.py:10](../enterprise/hr_payroll_attendance/models/hr_time_rule.py#L10)),
and payroll groups hours by time type and those options.

**Shipped rules.** "Employee Schedule Rule" (anything beyond the daily schedule on the generic
Work type → Overtime `040.00`) has no company, country or domain, so it applies to every
company, Georgian ones included ([hr_time_rule_data.xml:4](../addons/hr_work_entry/data/hr_time_rule_data.xml#L4)).
The other shipped rules are limited to their countries.

---

## When Rules Run

Saving a source triggers them unless `skip_time_rules` is set
([_trigger_time_rules_for_affected](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L297)):

| Period of the saved record | Rules applied at save |
|---|---|
| A past day | Daily excess and daily deficit rules |
| Today or later | Daily excess only |
| A completed week | Weekly excess only |
| Weekly deficit | Never at save; cron only |

Crons ([hr_attendance_data.xml](../addons/hr_attendance/data/hr_attendance_data.xml)):

| Job | Interval | What it does |
|---|---|---|
| Automatic check-out | 4 hours | Closes open attendances in companies with Automatic Check Out: *tolerance* mode when open time plus the day's earlier worked hours exceeds expected hours plus the tolerance; *specific time* mode at a local cut-off ([_cron_auto_check_out](../addons/hr_attendance/models/hr_attendance.py#L451)) |
| Absence detection | 4 hours | With Absence Management: for each employee with no attendance yesterday, a one-second validated technical attendance, so deficit rules can create missing-time outputs; technical records without outputs are deleted ([_cron_absence_detection](../addons/hr_attendance/models/hr_attendance.py#L515)) |
| Daily time rules | 1 day | Yesterday's records, deficit day rules ([_cron_process_day_undertime_rules](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L182)) |
| Weekly time rules | 1 week | The week that ended yesterday, only rules whose `week_start` is today's weekday ([_cron_process_week_time_rules](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L195)) |

The weekly job's docstring calls it a daily cron, but it ships weekly. Weekly deficit rules
whose `week_start` differs from the cron's weekday are never processed; set the cron to daily if
you use them.

**Overtime balance.** Employee `total_overtime` sums `worked_hours` of all attendances that carry
a `time_rule_id`, without any state filter ([hr_employee.py:179](../addons/hr_attendance/models/hr_employee.py#L179)).
It is a display figure, not what the payslip pays.

---

## Attendance-Based Versus Schedule-Based Payroll

The projection lives in [`hr_holidays_attendance/models/hr_version.py`](../addons/hr_holidays_attendance/models/hr_version.py#L35):

- **Attendance based:** the schedule supplies nothing
  ([_get_attendance_intervals](../addons/hr_holidays_attendance/models/hr_version.py#L18)); closed
  validated attendances are the worked time. Leaves and public holidays still produce their
  scheduled hours.
- **Schedule based:** the schedule supplies ordinary days, but a validated attendance on a local
  day removes that **whole day** from the schedule and supplies its own intervals instead
  ([:88](../addons/hr_holidays_attendance/models/hr_version.py#L88)). One 2-hour badge on an 8-hour
  day gives 2 hours, not 8.

In both modes:

- The break is cut off the end of the attendance ([:94](../addons/hr_holidays_attendance/models/hr_version.py#L94)).
- Where an attendance and a working-time leave overlap, the time type with the lower sequence wins
  ([:103](../addons/hr_holidays_attendance/models/hr_version.py#L103)); worked time removes
  overlapping absence ([_get_valid_leave_intervals](../addons/hr_holidays_attendance/models/hr_version.py#L165)).
- Values are split at local midnight and merged per date, time type, employee, version and
  company. An 08:00–12:00 and a 13:00–17:00 attendance of the same type give one 8-hour value;
  an overnight attendance is split between the two dates in the version's timezone.

---

## Payroll Integration

[`hr.payslip`](../enterprise/hr_payroll/models/hr_payslip.py) calls the projection for its period
and prices one worked-day line per time type (and payroll options). `hr_payroll_attendance` adds:

- **Attendance count and button** on attendance-based payslips: validated attendances overlapping
  the period ([_get_attendance_by_payslip](../enterprise/hr_payroll_attendance/models/hr_payslip.py#L15));
  the button opens all of the employee's attendances, starting at the payslip date
  ([action_open_attendances](../enterprise/hr_payroll_attendance/models/hr_payslip.py#L56)).
- **`payslip_id` on attendance**: the latest non-draft, non-cancelled payslip whose period holds
  the local check-in date, computed on the fly ([_get_payslip_domain](../enterprise/hr_payroll_attendance/models/hr_attendance.py#L36)).
- **Payroll options** on attendances ([hr_attendance.py:9](../enterprise/hr_payroll_attendance/models/hr_attendance.py#L9))
  and `attendance_based` visible to payroll users ([hr_version.py:7](../enterprise/hr_payroll_attendance/models/hr_version.py#L7)).
- **Warnings**: "Attendance Discrepancies" for employees with attendances who are not attendance
  based ([warning data:4](../enterprise/hr_payroll_attendance/data/hr_payroll_attendance_warning_data.xml#L4)),
  and pay-run start warnings "Attendances to Review" and "No Attendance" for attendance-based
  versions ([hr_payslip_run.py:10](../enterprise/hr_payroll_attendance/models/hr_payslip_run.py#L10)).

---

## Configuration & Settings

Attendances → Configuration → Settings, all stored on the company
([res_config_settings.py](../addons/hr_attendance/models/res_config_settings.py)):

| Setting | Behavior |
|---|---|
| **Attendance Validation** + **Validation Tolerance** | See Validation. Draft attendances do not pay |
| **Attendance Time Type** | Type given to new attendances and read by rules; any working-time type ([res_company.py:46](../addons/hr_attendance/models/res_company.py#L46)) |
| **Default Tracking** | Default of `attendance_based` for new versions ([res_company.py:63](../addons/hr_attendance/models/res_company.py#L63)) |
| **Automatic Check Out** (tolerance, default 2 h, or specific time, default 20:00) | Arms the auto check-out cron |
| **Absence Management** | Arms absence detection |
| **Break Management on Checkout** | Lets employees enter their break when checking out |
| **Single Check-In** | One attendance per day |
| **Device & Location Tracking**, **Take Pictures on Check-In** | Store GPS/IP/browser and a picture |
| Kiosk mode, barcode source, PIN, systray | Capture channels only; they write the same record |

Setting an employee's **attendance manager** adds that user to the Officer group
([hr_employee.py:117](../addons/hr_attendance/models/hr_employee.py#L117)).

---

## Recipe — Georgian Client, Fixed Schedule + Paid Overtime

1. **Overtime type.** Create a working-time type per overtime rate, e.g. "Overtime 150%" with
   rate 1.5, and give it the salary category your structure adds to GROSS. Leave its country empty
   (see the one-country-type trap in [`public_holidays_flow.md`](public_holidays_flow.md)). The
   shipped `040.00` pays 100%.
2. **Versions.** Leave `attendance_based` off to keep schedule pay on days without a badge. If
   employees badge, they must badge every workday: a badge replaces the whole scheduled day.
3. **Rule.** Edit "Employee Schedule Rule" or add your own: exceed the daily schedule, condition =
   the attendance type, output = your overtime type, employer tolerance e.g. 0:15. Add a
   weekend-only and a holiday-only rule if those pay differently.
4. **Validation.** Use manual or tolerance validation so unapproved overruns do not pay.
5. **Monthly flow.** Punches → approve drafts (rules run at validation) → refresh draft payslips →
   confirm.

With `geo_payroll`, overtime can also come from approved overtime work logs; do not pay the same
hours through both channels ([`geo_payroll.md`](geo_payroll.md)).

---

## Access

Source: [`hr_attendance_security.xml`](../addons/hr_attendance/security/hr_attendance_security.xml)
and [`ir.access.csv`](../addons/hr_attendance/security/ir.access.csv).

| Group | Access to `hr.attendance` |
|---|---|
| Every internal user | Read own attendances ([ir.access.csv:4](../addons/hr_attendance/security/ir.access.csv#L4)) |
| Self Attendance Edit (default for new users) | Create/edit own attendances while not validated, or always when the company uses `no_validation` ([:5](../addons/hr_attendance/security/ir.access.csv#L5)) |
| Officer: Manage attendances | Full access to employees they manage ([:3](../addons/hr_attendance/security/ir.access.csv#L3)) |
| Officer: Manage all attendances / Administrator | Full access ([:2](../addons/hr_attendance/security/ir.access.csv#L2)) |

---

## Gotchas & Non-Obvious Behavior

- **Employees can edit validated attendances under `no_validation`** (the default), and those
  hours are payroll hours. Use manual or tolerance validation where pay follows the clock.
- **The generic overtime rule is live everywhere.** On a database with Attendances and payroll,
  every validated hour beyond the daily schedule becomes `040.00` Overtime and reaches the
  payslip at 100%. `gec20_prod1` has this rule active (checked 2026-09-24).
- **Absence detection can cut pay.** A surviving technical attendance knocks its scheduled day out
  of the payslip, and the deficit outputs land there with the rule's output type; a type with
  rate 0 removes that day's pay.
- **Rules rewrite attendance records.** There is no undo; the source record itself is shortened
  and re-typed. Test rules on a copy of production data.
- **"Attendances to Review" pay-run warning searches a field that does not exist.** It filters
  `hr.attendance` on `overtime_status` ([hr_payslip_run.py:19](../enterprise/hr_payroll_attendance/models/hr_payslip_run.py#L19)),
  a field `hr.attendance` does not define. Starting a pay run whose versions include an
  attendance-based employee should fail on that domain [Unverified].
- **Weekly deficit rules can silently never run** (weekly cron vs `week_start`, above).
- **Mark Reviewed is not a recalculation.** Fix the source or re-save it to re-run the rules.

| Symptom | Check |
|---|---|
| Clocked hours missing from the payslip | Attendance closed and validated; version dates and timezone; draft payslip refreshed |
| A scheduled day shrank after a punch | Schedule-based versions: a badge replaces the whole day |
| Overtime not classified | Rule active and in scope; condition type = the attendance's type; threshold, window, tolerance; day or week finished |
| Hours differ from clock time | Break, midnight split, overlap with a leave of lower sequence |
| Warning icon on a rule output | Source edited or deleted; review, then Mark Reviewed |
| Overtime balance differs from pay | `total_overtime` counts every rule output; payroll counts validated records per type |

---

## Related Docs

- [`work_entries.md`](work_entries.md) — the projection, time types and the rule engine
- [`hr_payroll.md`](hr_payroll.md) — payslips and pay runs
- [`hr_employee_versions.md`](hr_employee_versions.md) — versions, `attendance_based`, timezone
- [`resource_calendars.md`](resource_calendars.md) — schedules and expected hours
- [`public_holidays_flow.md`](public_holidays_flow.md) — attendance on public holidays
- [`payroll_wage_types.md`](payroll_wage_types.md) — how hours become money

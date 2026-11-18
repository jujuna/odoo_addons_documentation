# Time Off — Core Module (hr_holidays)

> **Module:** `hr_holidays` (community), payroll deferral in enterprise `hr_payroll` | **Path:** [`addons/hr_holidays/`](../addons/hr_holidays/), [`enterprise/hr_payroll/models/hr_leave.py`](../enterprise/hr_payroll/models/hr_leave.py)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

`hr_holidays` is the request/approval engine for absences. Employees file **time off requests** (`hr.leave`) against **time types**: `hr.work.entry.type` records flagged `time_off_selectable`, which `hr_holidays` extends with the time-off switches ([hr_work_entry_type.py](../addons/hr_holidays/models/hr_work_entry_type.py)). HR grants budgets through **allocations** (`hr.leave.allocation`); approvers move requests through a small state machine. A validated leave becomes a `resource.calendar.leaves` row. That row is the single handoff point every other module (work entries, planning, timesheets, accruals) consumes. The module also owns **public holidays** (company-wide `resource.calendar.leaves`, with bundled per-country data), **mandatory days** (days on which employees may not request leave), and the time-off side of **time rules** (`hr.time.rule`, which can turn over/undertime into leaves and allocation credits).

`hr.leave.type`, `holiday_status_id`, `hr_work_entry_holidays` and `hr_payroll_holidays` do not exist in 20.0; use `hr.work.entry.type`, `work_entry_type_id`, `hr_holidays` (it depends on `hr_work_entry` and maps leaves to work entries in [hr_version.py](../addons/hr_holidays/models/hr_version.py)) and `hr_payroll`.

---

## The Big Picture — Request Lifecycle

```
            create()                    action_approve()                 action_approve()
 employee ───────────► confirm ──────────────────────► validate1 ────────────────────► validate
                          │        (only if type is 'both')   │                            │
                          │                                    │                            ├─► resource.calendar.leaves created
                          │      action_refuse()               │                            ├─► calendar.event meeting (optional)
                          ├───────────────────────► refuse ◄───┘                            ├─► work entries regenerated (in-module)
                          │                                                                 │
                          │                              action_cancel() wizard             │
                          └────── (delete allowed) ◄──── cancel ◄───────────────────────────┘
                                                                     action_back_to_approval() → confirm
```

States: `confirm` (To Approve) → `validate1` (Second Approval) → `validate` (Approved), plus `refuse` and `cancel` ([hr_leave.py:158](../addons/hr_holidays/models/hr_leave.py#L158)). There is **no draft state**: a new request is born in `confirm` (a stale `'draft'` literal remains in one write-guard, [hr_leave.py:1604](../addons/hr_holidays/models/hr_leave.py#L1604)).

Step by step:

1. **Create** ([create:1529](../addons/hr_holidays/models/hr_leave.py#L1529)). `default_get` pre-picks the first *country-matching* time type (by `sequence`, `time_off_selectable=True`) that either needs no allocation or has a valid one ([hr_leave.py:95](../addons/hr_holidays/models/hr_leave.py#L95)). The user only enters `request_date_from/to` (+ half-day period or hour range); `date_from/date_to` and durations are computed from the employee's calendar ([_compute_date_from_to:712](../addons/hr_holidays/models/hr_leave.py#L712), [_get_durations:875](../addons/hr_holidays/models/hr_leave.py#L875)). `_check_validity` runs immediately: allocation coverage, negative cap, and mandatory-day checks ([hr_leave.py:1415](../addons/hr_holidays/models/hr_leave.py#L1415)). When it fails during a *multi*-employee generation, the offending leaves are unlinked and the user gets a bus notification instead of an exception; a single request raises.
2. **Auto-approval at create** ([_process_auto_approve_activities:1579](../addons/hr_holidays/models/hr_leave.py#L1579)). A leave is auto-approved in sudo if the type is `no_validation` **or the creating user is a Time Off Officer**. Either way a "The time off has been automatically approved" chatter note is posted. Otherwise `activity_update()` schedules an approval activity on the responsible ([hr_leave.py:2355](../addons/hr_holidays/models/hr_leave.py#L2355)).
3. **Approve** ([action_approve:1923](../addons/hr_holidays/models/hr_leave.py#L1923)). One button serves both steps: for a `both`-validation leave in `confirm` it writes `validate1` + `first_approver_id`; otherwise it calls `_action_validate`. The first-approval activity is marked done and a "Second approval request" activity is created for the HR responsible ([activity_update:2355](../addons/hr_holidays/models/hr_leave.py#L2355)).
4. **Validate** ([_action_validate:2059](../addons/hr_holidays/models/hr_leave.py#L2059)). Refuses to proceed if any leave falls entirely on non-working days/public holidays (`number_of_days == 0` → "not supposed to work during that period"). Sickness/incapacity types bypass this check; the list is inline in `_get_leaves_on_public_holiday` and matches work entry type **codes** (`013.00`, `128.00`, `123.00`, …, [hr_leave.py:1949](../addons/hr_holidays/models/hr_leave.py#L1949)). Writes `validate`, stamps first/second approver, then `_validate_leave_request` ([:1822](../addons/hr_holidays/models/hr_leave.py#L1822)) creates the `resource.calendar.leaves` row ([_create_resource_leave:1789](../addons/hr_holidays/models/hr_leave.py#L1789)) and, if the type has `create_calendar_meeting`, a `calendar.event` in the employee's calendar. The employee gets a "has been accepted" message.
5. **After validation** the leave is mostly frozen: a constraint blocks date/employee edits in `validate1/validate` ([_check_date_state:1393](../addons/hr_holidays/models/hr_leave.py#L1393)), and any state write away from `validate` deletes the linked `resource.calendar.leaves` first ([write:1613](../addons/hr_holidays/models/hr_leave.py#L1613)). Dates *can* be amended on a validated leave without a state round-trip: the write override then re-dates the resource leave in place (`_amend_resource_leave_dates`). The calendar drag path (`reschedule_from_calendar` / `can_reschedule`) uses this.

### Key Decision Points

- **Time type validation flow** (`leave_validation_type`): `no_validation` / `hr` / `manager` / `both` — decides who must click and how many times.
- **Requires allocation**: with it, the request is checked against granted days; without it (e.g. stock Sick Time Off), employees can request freely.
- **`count_as`** (`working_time` vs `absence`, from `hr.work.entry.type`): drives the overlap check bucket, the zero-duration rejection, the max-absence-per-day constraint and what lands on the resource leave.
- **What happens to a validated leave later** — refuse vs cancel vs delete — has three different guard sets (see the dedicated section below).

---

## Who Can Do What

### Groups ([hr_holidays_security.xml](../addons/hr_holidays/security/hr_holidays_security.xml))

| Group | xmlid | Gets |
|---|---|---|
| Employee | `group_hr_holidays_employee` | The baseline group: implied by `base.default_user_group` (the groups given to new users) and by `hr.group_hr_user`. All "own records" access rows are attached to it ([hr_holidays_security.xml:8](../addons/hr_holidays/security/hr_holidays_security.xml#L8)). It is declared a light group ([res_groups.py](../addons/hr_holidays/models/res_groups.py)): holding it does not lift a user out of the Light role |
| Time Off Responsible | `group_hr_holidays_responsible` | Team-approver role. Auto-granted/removed when a user is set/unset as someone's `leave_manager_id` ([hr_employee.py:316](../addons/hr_holidays/models/hr_employee.py#L316), [hr_employee.py:345](../addons/hr_holidays/models/hr_employee.py#L345), [res_users.py:14](../addons/hr_holidays/models/res_users.py#L14)) |
| Officer: Manage all requests | `group_hr_holidays_user` | See and manage everyone's requests; implies Responsible + HR Officer |
| Administrator | `group_hr_holidays_manager` | Everything, incl. configuration and deleting approved records |

Installing payroll widens this: **every payroll group implies Time Off Officer** (the Assistant group implies it and Officer/Administrator imply Assistant, [enterprise/hr_payroll/security/hr_payroll_security.xml:14](../enterprise/hr_payroll/security/hr_payroll_security.xml#L14)).

### Access — what a plain employee actually sees

All access is one [`security/ir.access.csv`](../addons/hr_holidays/security/ir.access.csv): an `operation` column (`c`/`r`/`u`/`d`) and an optional `domain` per row. `hr_holidays_security.xml` holds only the group definitions.

The class docstring claims a regular employee "can see all leaves" ([hr_leave.py:40](../addons/hr_holidays/models/hr_leave.py#L40)) — **that is stale**. The employee read row limits reads to *own* leaves (`hr_leave_rule_employee`); Responsible additionally reads their team's (`hr_leave_rule_responsible_read`); Officer reads all. Employees can create/write own non-`validate/validate1` leaves, and their `leave_manager_id` can write when the type's validation is manager/both/no_validation (`hr_leave_rule_employee_update`).

The officer row is a bare `crud` with **no domain** (`hr_leave_rule_user_read`): nothing in the access layer stops an officer writing their **own** validated leave. Only `_get_next_states_by_state`/`_check_approval_update` gate state changes, and they give officers `cancel` on their own leave.

The leave **description is private**: `name` is a compute over `private_name`; anyone who is not officer/owner/leave-manager sees `*****` ([_compute_description:556](../addons/hr_holidays/models/hr_leave.py#L556)), and the matching `_search_description` narrows non-officers to their own records.

### The approval matrix

Every button's availability comes from the `can_approve/can_validate/can_refuse/can_cancel/can_back_to_approve/can_reschedule` computes, all funneled through `_check_approval_update` → `_get_next_states_by_state` ([hr_leave.py:2255](../addons/hr_holidays/models/hr_leave.py#L2255), [:2209](../addons/hr_holidays/models/hr_leave.py#L2209)):

| Actor | Can do |
|---|---|
| Employee (own leave) | Cancel own `validate1/validate/refuse` leave — but only if it hasn't started yet (`is_in_past` blocks it; officers bypass) ([:2227](../addons/hr_holidays/models/hr_leave.py#L2227)) |
| Time-off manager (`leave_manager_id`) | `manager` and `both` types: refuse from `confirm`/`validate`. `manager` adds `confirm→validate` and `refuse→validate`; `both` adds `confirm→validate1` (first approval only) and `validate1→refuse`. Nothing on `hr` types ([:2242](../addons/hr_holidays/models/hr_leave.py#L2242)) |
| Officer | Everything: approve, validate, refuse, back-to-approval, resurrect cancelled (`cancel→confirm/validate/refuse`) ([:2232](../addons/hr_holidays/models/hr_leave.py#L2232)) |
| Anyone | Superuser bypasses all checks ([:2257](../addons/hr_holidays/models/hr_leave.py#L2257)) |

Double validation has an extra layer: `_check_double_validation_rules` — first approval (`validate1`) requires being the employee's leave manager or an officer; final `validate` on a `both` type requires the officer group; Administrators skip the whole check ([hr_leave.py:1515](../addons/hr_holidays/models/hr_leave.py#L1515)). So the intended split is *manager approves first, HR officer confirms second*.

**Who gets the approval activity** ([_get_responsible_for_approval:2336](../addons/hr_holidays/models/hr_leave.py#L2336)): `manager` type (or `both` in `confirm`) → the employee's `leave_manager_id`, falling back to the direct manager's user, then to `hr_responsible_id`; `hr` type (or `both` in `validate1`) → the employee's `hr_responsible_id`. The HR step is routed per *employee*, not per type: the time type has no "Notify HR" (`responsible_ids`) field, and `hr_responsible_id` only accepts users in the Time Off Officer group ([hr_version.py:22](../addons/hr_holidays/models/hr_version.py#L22)). Refused/cancelled leaves get their activities unlinked; validated ones get them marked done ([activity_update:2355](../addons/hr_holidays/models/hr_leave.py#L2355)).

---

## hr.work.entry.type — Configuration as Behavior Switches

A "time off type" is an `hr.work.entry.type` record that `hr_holidays` decorates with the time-off switches ([hr_work_entry_type.py](../addons/hr_holidays/models/hr_work_entry_type.py)). The consequence worth internalizing: **the leave type and the work entry type are one and the same record**, so a validated leave materializes as work entries of its own type.

Only the switches that change flow:

| Field | Behavior change |
|---|---|
| `time_off_selectable` ([:125](../addons/hr_holidays/models/hr_work_entry_type.py#L125)) | The gate that separates "a work entry type" from "a time off type". Off (e.g. overtime/shift-premium types) = never offered in the leave form and skipped by `_check_validity` |
| `country_id` ([:61](../addons/hr_holidays/models/hr_work_entry_type.py#L61)) | Types are country-scoped; `default_get` and the request domain filter on the employee's company country. A company's country cannot be changed while country-typed leaves exist ([res_company.py:9](../addons/hr_holidays/models/res_company.py#L9)) |
| `leave_validation_type` ([:66](../addons/hr_holidays/models/hr_work_entry_type.py#L66)) | `no_validation` = auto-approved at create (in sudo); `hr` = HR responsible; `manager` = employee's approver; `both` = manager first, HR second |
| `requires_allocation` ([:71](../addons/hr_holidays/models/hr_work_entry_type.py#L71)) | On: requests are checked against validated allocations (`_check_validity`), the type only appears in the request dropdown if `has_valid_allocation` ([:244](../addons/hr_holidays/models/hr_work_entry_type.py#L244)). Off: unlimited requests, no balance tracking. **Cannot be flipped once leaves of the type exist** ([:259](../addons/hr_holidays/models/hr_work_entry_type.py#L259)) |
| `employee_requests` ([:72](../addons/hr_holidays/models/hr_work_entry_type.py#L72)) | On: employees may file their own *allocation* requests for this type. Off: only officers allocate |
| `allocation_validation_type` ([:76](../addons/hr_holidays/models/hr_work_entry_type.py#L76)) | Same 4 options, but for the allocation approval chain |
| `allows_negative` + `max_allowed_negative` ([:114](../addons/hr_holidays/models/hr_work_entry_type.py#L114)) | Lets the balance go below zero up to N days/hours. `_check_validity` then only blocks past `-max_allowed_negative`; an allocation (any, even 0-remaining) must still exist ([hr_leave.py:1429](../addons/hr_holidays/models/hr_leave.py#L1429)). A SQL constraint forces `max_allowed_negative > 0` when the flag is on |
| `unpaid` ([:97](../addons/hr_holidays/models/hr_work_entry_type.py#L97)) | A pure flag in this module — payroll semantics live in the payroll layer; accrual plans "based on worked time" also exclude unpaid leave time |
| `request_unit` ([:88](../addons/hr_holidays/models/hr_work_entry_type.py#L88)) | Day / half-day / hour — full treatment in [`hr_holidays_time_off_units.md`](hr_holidays_time_off_units.md). For `day` types the computed duration is `ceil`'d to whole days ([hr_leave.py:1051](../addons/hr_holidays/models/hr_leave.py#L1051)) |
| `unit_of_measure` ([:94](../addons/hr_holidays/models/hr_work_entry_type.py#L94)) | Hours vs days — the unit the *balance* is allocated and displayed in, independent of `request_unit` |
| `count_days_as` ([:108](../addons/hr_holidays/models/hr_work_entry_type.py#L108)) | `working` (duration follows the employee's schedule) vs `calendar` (a full week costs 7). The calendar branch is a separate duration path that is not re-rounded ([hr_leave.py:953](../addons/hr_holidays/models/hr_leave.py#L953)). Frozen once leaves of the type exist ([:206](../addons/hr_holidays/models/hr_work_entry_type.py#L206)) |
| `include_public_holidays_in_duration` ([:98](../addons/hr_holidays/models/hr_work_entry_type.py#L98)) | UI label "Ignore Public Holidays". On: public holidays inside the request consume balance too (duration computed with `compute_leaves=False`). Guarded: cannot be toggled while current-year leaves overlap a public holiday ([:175](../addons/hr_holidays/models/hr_work_entry_type.py#L175)) |
| `count_as` (base field, [hr_work_entry/hr_work_entry_type.py:36](../addons/hr_work_entry/models/hr_work_entry_type.py#L36)) | `absence` vs `working_time`. Copied onto the `resource.calendar.leaves` row; also decides the overlap bucket, presence status, and whether a zero-hour span is rejected or padded |
| `elligible_for_accrual_rate` ([:105](../addons/hr_holidays/models/hr_work_entry_type.py#L105)) | Set on the type and copied down onto the resource row. Defaults to `count_as != 'absence'`; `working_time` types are *forced* eligible by a constraint ([:169](../addons/hr_holidays/models/hr_work_entry_type.py#L169)) |
| `allow_request_on_top` ([:102](../addons/hr_holidays/models/hr_work_entry_type.py#L102)) | Exempts the type from the overlap check (`dashboard_warning_message` → `_check_date` ValidationError). Forbidden on `count_as='absence'` types ([:163](../addons/hr_holidays/models/hr_work_entry_type.py#L163)) |
| `support_document` ([:101](../addons/hr_holidays/models/hr_work_entry_type.py#L101)) | Shows the attachment widget on the request |
| `create_calendar_meeting` ([:37](../addons/hr_holidays/models/hr_work_entry_type.py#L37)) | Off: no `calendar.event` on validation |
| `sequence` (base) / `hide_on_dashboard` ([:44](../addons/hr_holidays/models/hr_work_entry_type.py#L44)) / `color` ([:43](../addons/hr_holidays/models/hr_work_entry_type.py#L43)) | Ordering/default pick in the request form; hide from the dashboard cards while staying requestable. Each dashboard card takes the type's `color` (0 = neutral background, [time_off_card.js:225](../addons/hr_holidays/static/src/dashboard/time_off_card.js#L225)) |

`hr_holidays` creates no types of its own: it *writes time-off settings onto existing work entry types, matched by code* ([hr_work_entry_type_data.xml](../addons/hr_holidays/data/hr_work_entry_type_data.xml)): `016.00` Paid Time Off (`requires_allocation`, validation `both`), `013.00` Sick Time Off (no allocation, `support_document`, hidden on dashboard), `LEAVE105` Compensatory, `158.00` Unpaid. The rest of that file holds about 180 per-country records that mark payroll codes `time_off_selectable=False` or configure them as time off for that country.

Employees only get **read** on `hr.work.entry.type` (`access_hr_holidays_status_employee` in [ir.access.csv](../addons/hr_holidays/security/ir.access.csv)); Administrators get full `crud`.

---

## Allocations (hr.leave.allocation) — Basics

An allocation is the budget line: employee + type (`work_entry_type_id`) + `number_of_days` + validity window (`date_from`/`date_to`). An allocation is an accrual allocation exactly when `accrual_plan_id` is set; there is no allocation-type selector ([hr_leave_allocation.py:149](../addons/hr_holidays/models/hr_leave_allocation.py#L149); all accrual mechanics in [`hr_holidays_accrual_plans.md`](hr_holidays_accrual_plans.md)).

- **States**: `confirm → validate1 → validate / refuse` — no cancel state ([:87](../addons/hr_holidays/models/hr_leave_allocation.py#L87)). New records must be created in `confirm` ([create:903](../addons/hr_holidays/models/hr_leave_allocation.py#L903)); `no_validation` types auto-approve right after create.
- **Approval** mirrors leaves (`allocation_validation_type`, same `_get_next_states_by_state` shape, [:838](../addons/hr_holidays/models/hr_leave_allocation.py#L838)) with one extra rule: **nobody but an Administrator can approve/refuse their own allocation** ([:1041](../addons/hr_holidays/models/hr_leave_allocation.py#L1041)).
- **Shrink guard**: writing a smaller duration recomputes consumed leaves before/after and refuses if it would drop below what the employee already took (negative types get their cap respected) ([write:926](../addons/hr_holidays/models/hr_leave_allocation.py#L926)). It fires only when one of `number_of_days_display`/`number_of_hours`/`state`/`date_to` is written.
- **Delete guards**: only `confirm`/`refuse` can be unlinked, and never if validated leaves consumed from it ([:967](../addons/hr_holidays/models/hr_leave_allocation.py#L967), [:975](../addons/hr_holidays/models/hr_leave_allocation.py#L975)). The state guard — not the taken-leaves one — is bypassable with the `allocation_skip_state_check` context, which the departure cleanup uses.
- **Balance math** lives in `hr.employee._get_consumed_leaves(work_entry_types, …)` ([hr_employee.py:546](../addons/hr_holidays/models/hr_employee.py#L546)): leaves in `confirm/validate1/validate` are all "virtually taken" (pending requests reserve balance); allocations are consumed in `date_to`-ascending order (expiring first); excess beyond all allocations is reported as `excess_days` ([:615](../addons/hr_holidays/models/hr_employee.py#L615)). This one method feeds the dashboard, the type's remaining-days display, `_check_validity` and the payroll "no allocation" warning.

Batch tools for officers: **Generate allocations for multiple employees** wizard (by employee/company/department/tag; auto-approves what the caller may approve, [hr_leave_allocation_generate_multi_wizard.py:113](../addons/hr_holidays/wizard/hr_leave_allocation_generate_multi_wizard.py#L113)) and its leave twin (**generates already-validated leaves** when run by an officer, splitting/refusing conflicting existing requests — [hr_leave_generate_multi_wizard.py:59](../addons/hr_holidays/wizard/hr_leave_generate_multi_wizard.py#L59)). The leave wizard refuses the whole batch if any conflicting existing request is an *hourly* leave, because it cannot split those ([:106](../addons/hr_holidays/wizard/hr_leave_generate_multi_wizard.py#L106)).

---

## Refuse vs Cancel vs Delete vs Back-to-Approval

Four distinct exits with different guards and different payroll consequences:

| Action | Who / when | What happens | Guards |
|---|---|---|---|
| **Refuse** ([action_refuse:2093](../addons/hr_holidays/models/hr_leave.py#L2093)) | Officer; leave manager for non-`hr` types. From `confirm/validate1/validate` | State `refuse`, approver stamped, meeting archived, employee + leave manager notified ([_notify_manager:2114](../addons/hr_holidays/models/hr_leave.py#L2114)); resource leave removed via the write-override, and time-rule allocation credits reversed | **No payslip guard** — refusing still deactivates already-paid work entries; `hr_payroll` only recomputes draft slips afterwards ([hr_payroll/hr_leave.py:301](../enterprise/hr_payroll/models/hr_leave.py#L301)). The asymmetry is documented in [`work_entries.md`](work_entries.md) |
| **Cancel** ([action_cancel:1907](../addons/hr_holidays/models/hr_leave.py#L1907) → wizard [hr_holidays_cancel_leave.py](../addons/hr_holidays/wizard/hr_holidays_cancel_leave.py) → [_action_user_cancel:2135](../addons/hr_holidays/models/hr_leave.py#L2135)) | The employee themselves, on own future `validate1/validate/refuse` leave (reason asked in wizard) | `_force_cancel` posts the reason, notifies the responsibles who had approved, sets state `cancel` in sudo, archives the meeting, removes the resource leave ([:2142](../addons/hr_holidays/models/hr_leave.py#L2142)) | `hr_payroll` marks it `payslip_state='done'` and recomputes draft slips ([hr_payroll/hr_leave.py:315](../enterprise/hr_payroll/models/hr_leave.py#L315)) |
| **Delete** ([_unlink_if_correct_states:1664](../addons/hr_holidays/models/hr_leave.py#L1664)) | Employee: only `confirm/validate1/cancel` and not in the past; Officer: only `cancel/confirm`; Administrator: anything | `unlink()` first runs `_prepare_leave_unlink` in sudo — time-rule credits reversed, then `_post_leave_cancel` (meeting + resource leave removed) ([:1684](../addons/hr_holidays/models/hr_leave.py#L1684)) | `hr_payroll` adds a hard stop: cannot delete a leave whose period is covered by a validated/paid regular payslip *confirmed after the leave was created* ([_check_uncovered_by_validated_payslip:370](../enterprise/hr_payroll/models/hr_leave.py#L370)) |
| **Back to Approval** ([action_back_to_approval:1940](../addons/hr_holidays/models/hr_leave.py#L1940)) | Officer, on `validate` | Back to `confirm`, activities rescheduled, meeting + resource leave removed ([_move_validate_leave_to_confirm:1944](../addons/hr_holidays/models/hr_leave.py#L1944)) | `hr_payroll` hides the button when the leave overlaps a validated/paid slip ([_compute_can_back_to_approve:233](../enterprise/hr_payroll/models/hr_leave.py#L233)) and raises `AccessError` for non-officers who reach the method anyway |

Additional edit guards: non-officers cannot modify a leave that already began unless they are its leave manager, and only managers touch cancelled leaves ([write:1599](../addons/hr_holidays/models/hr_leave.py#L1599)); **duplication is blocked** unless every copied leave is cancelled/refused ([copy_data:1760](../addons/hr_holidays/models/hr_leave.py#L1760), bypassable with the `skip_copy_check` context).

---

## Public Holidays & Mandatory Days

### Public holidays

The `resource.*` extensions are split over [`resource_resource.py`](../addons/hr_holidays/models/resource_resource.py), [`resource_calendar.py`](../addons/hr_holidays/models/resource_calendar.py) and [`resource_calendar_leaves.py`](../addons/hr_holidays/models/resource_calendar_leaves.py). Links in this section point at the last one.

A public holiday is a `resource.calendar.leaves` row with **no `resource_id`** (company-wide), optionally scoped to one working calendar. `hr_holidays` extends the model with the back-pointer `holiday_id` and `elligible_for_accrual_rate`, which defaults false ([resource_calendar_leaves.py:17](../addons/hr_holidays/models/resource_calendar_leaves.py#L17)) — public holidays created by hand or by the monthly cron therefore reduce worked-time accrual unless explicitly marked eligible; only the loader wizard copies the flag from a time type. Two same-scope public holidays may not overlap, but the guard is Python-only and concurrent creates can race ([:21](../addons/hr_holidays/models/resource_calendar_leaves.py#L21)).

The important flow is **retroactive re-evaluation**: create/write/unlink triggers `_reevaluate_leaves` over every non-refused/cancelled leave in the company/time window, without an applicability filter for the specific calendar ([:61](../addons/hr_holidays/models/resource_calendar_leaves.py#L61), [:116](../addons/hr_holidays/models/resource_calendar_leaves.py#L116)). The scope keys on the leave's `employee_company_id`. Durations are recomputed, each leave is bounced through `confirm` and back, the employee may be notified, and an underfunded leave is **auto-refused** ([:97](../addons/hr_holidays/models/resource_calendar_leaves.py#L97)). Validated leaves get their resource rows recreated. Time-rule *output* leaves (`source_leave_id` set) are excluded: the rule engine re-runs them from their source instead ([:52](../addons/hr_holidays/models/resource_calendar_leaves.py#L52)).

Timezone handling: the conversion from wall time to the company timezone happens in the **loader wizard** (`convert_timezone(..., company.tz)`), and `create` honours a `convert_datetime` context flag. Direct writes on an existing public holiday skip it. See [`public_holidays_flow.md`](public_holidays_flow.md) before operating across timezones or paid periods.

By default a public holiday inside a request costs nothing because `include_public_holidays_in_duration=False`. When true, the employee leave consumes the holiday. A leave consisting only of excluded public holidays/non-working days validates to 0 days and is rejected (unless its code is on the sickness/incapacity bypass list). Toggling the flag does not reliably recompute existing past/future-year leaves, so a change on live data needs an explicit re-evaluation.

### Bundled public-holiday data, loader wizard and cron

`hr_holidays` ships real public-holiday calendars as CSVs under [`data/public_holidays/`](../addons/hr_holidays/data/public_holidays/) — 20 countries (AU, BE, CH, EG, HK, IN, JO, KE, LT, LU, MA, MX, MY, NL, PL, RO, SA, SK, TR, US), declared under `other_files` so they are read at runtime rather than loaded as records.

Three entry points consume them, all through `_prepare_public_holidays_data(start_date, end_date)` ([resource_calendar_leaves.py:152](../addons/hr_holidays/models/resource_calendar_leaves.py#L152)), which picks the CSV per `company.country_code`, skips dates already covered by an existing company holiday, and reports back three buckets: companies with no country, companies with no data file, and companies already fully covered.

1. **Load Public Holidays wizard** — `load.public.holiday.wizard` ([wizard/load_public_holiday_wizard.py](../addons/hr_holidays/wizard/load_public_holiday_wizard.py)), reachable from the Company Holidays list button. You pick a **year** (must be > 2025), the wizard previews one editable line per holiday (`load.public.holiday.wizard.line`) with a pre-filled **time type** — the `006.00` "Public Holiday" work entry type for the company's country, falling back to the country-less one — and refuses to create anything until every line has a type ([:62](../addons/hr_holidays/wizard/load_public_holiday_wizard.py#L62)). Each created `resource.calendar.leaves` row carries that type's `count_as` and `elligible_for_accrual_rate`.
2. **Monthly cron** "Time Off: Generate Public Holidays" — `_cron_generate_public_holidays` ([:231](../addons/hr_holidays/models/resource_calendar_leaves.py#L231)) silently creates the next rolling **12 months** of holidays for every company, and no-ops under tests.
3. **Company creation** fires the same method immediately ([res_company.py:27](../addons/hr_holidays/models/res_company.py#L27)), so a new company starts with a populated holiday calendar.

Operationally this means public holidays appear *without anyone asking*, as ordinary `resource.calendar.leaves` rows — so the retroactive `_reevaluate_leaves` path above runs on them like any manual edit.

### Mandatory days

`hr.leave.mandatory.day` is a tiny model: name, date range, company, optional working-calendar / departments / job positions scoping ([hr_leave_mandatory_day.py:7](../addons/hr_holidays/models/hr_leave_mandatory_day.py#L7)). Matching is done per employee in `_get_mandatory_days` (calendar + job + department parent-chain filters, [hr_employee.py:511](../addons/hr_holidays/models/hr_employee.py#L511)). Effect: `has_mandatory_day` is computed on the leave ([hr_leave.py:831](../addons/hr_holidays/models/hr_leave.py#L831)) and `_check_validity` raises *"You are not allowed to request time off on a Mandatory Day"* — **for non-officers only**, and only for leaves not in `cancel`/`refuse` ([hr_leave.py:1473](../addons/hr_holidays/models/hr_leave.py#L1473)). Employees have read-only access to the model; only Administrators configure it (menu Time Off → Configuration → Mandatory Days).

---

## Automatic Maintenance Around the Lifecycle

Five crons ([ir_cron_data.xml](../addons/hr_holidays/data/ir_cron_data.xml)):

| Cron | Interval | What it does |
|---|---|---|
| Accrual Time Off | daily | `_get_to_update_accrual_allocations()._update_accrual()` — see the accrual doc |
| Time Off: Cancel invalid leaves | daily | `_cancel_invalid_leaves` ([hr_leave.py:2525](../addons/hr_holidays/models/hr_leave.py#L2525)) — scans leaves starting within 31 days whose type is fed by accrual allocations and force-cancels (chatter reason: "the accruated amount is insufficient") any that exceed the projected balance beyond the negative cap |
| Time Off: Generate Public Holidays | monthly | `_cron_generate_public_holidays` — rolling 12 months of country holidays per company |
| Time Off: Process daily time rules | daily | `_cron_process_day_undertime_rules` — the `hr.time.rule` engine's day pass |
| Time Off: Process weekly time rules | weekly | `_cron_process_week_time_rules` |

- **Contract/version changes** ([hr_version.py:32](../addons/hr_holidays/models/hr_version.py#L32), [:81](../addons/hr_holidays/models/hr_version.py#L81)): creating or re-dating a version with a different working schedule splits overlapping leaves per version period, refusing/re-creating them (last split segment lands in `confirm`); a constraint blocks a single leave spanning versions with different calendars ([_check_contracts:679](../addons/hr_holidays/models/hr_leave.py#L679)). That constraint is skipped for time-rule-generated leaves and can be suppressed with the `skip_leave_version_check` context, which `hr.leave.write` sets automatically when the new dates stay inside the old span.
- **Employee/version calendar change:** the active path is version create/write, which splits/recomputes leaves across schedule periods and can reject insufficient allocations. The employee-write block is disabled by its own `no_leave_resource_calendar_update` context ([hr_employee.py:330](../addons/hr_holidays/models/hr_employee.py#L330)). Public holidays are not employee-owned: applicability follows the date-effective calendar dynamically.
- **Manager/department change** ([hr_employee.py:369](../addons/hr_holidays/models/hr_employee.py#L369)): pending/future leaves and pending allocations get their `department_id`/`manager_id` refreshed; `leave_manager_id` follows `parent_id.user_id` only when it pointed at the previous manager ([:266](../addons/hr_holidays/models/hr_employee.py#L266)).
- **Departure**: the cleanup hangs off `hr.employee.departure.action_register` ([hr_employee_departure.py:11](../addons/hr_holidays/models/hr_employee_departure.py#L11)). Leaves crossing the departure date are split at departure+1 (`_split_leaves`, [hr_leave.py:1981](../addons/hr_holidays/models/hr_leave.py#L1981)); post-departure approved leaves are force-cancelled; the remaining ones are **deleted, or refused instead** when a localization overrides `_check_refuse_future_leaves_condition` ([:92](../addons/hr_holidays/models/hr_employee_departure.py#L92)) — the default is delete. Running allocations get `date_to` = departure date, future ones deleted.
- **Presence/UX side effects**: validated current leaves flip `is_absent` and the presence icon (`presence_holiday_absent/present`, [hr_employee.py:114](../addons/hr_holidays/models/hr_employee.py#L114)). Every internal user reads a colleague's leave status (presence icon, avatar card), so the computation prefetches the employee's versions in sudo ([hr_employee.py:148](../addons/hr_holidays/models/hr_employee.py#L148)); a user without HR rights still sees "back on" dates. The Discuss `im_status` → `leave_*` mapping is computed client-side in the store patches (`static/src/core/common/im_status_patch.js`). The user display name gains "✈ Back on <date>" ([res_users.py:40](../addons/hr_holidays/models/res_users.py#L40)), where the return date is the **next working interval** after the leave, not `date_to` ([_get_first_working_interval_batch:126](../addons/hr_holidays/models/hr_employee.py#L126)); `res.partner.leave_date_to` mirrors it for multi-user partners ([res_partner.py:11](../addons/hr_holidays/models/res_partner.py#L11)). Department kanbans count absences and to-approve requests ([hr_department.py:22](../addons/hr_holidays/models/hr_department.py#L22)).
- **Reporting**: `hr.leave.report` (SQL union of leaves + allocations, [report/hr_leave_report.py](../addons/hr_holidays/report/hr_leave_report.py)), `hr.leave.report.calendar` (the calendar/dashboard view model, [report/hr_leave_report_calendar.py](../addons/hr_holidays/report/hr_leave_report_calendar.py)) and **`hr.leave.employee.report`** ([report/hr_leave_employee_report.py](../addons/hr_holidays/report/hr_leave_employee_report.py)) behind Reporting → *by Employee*. Both calendar-side models share `hr.leave.display.name.mixin` so leave labels read identically everywhere.

Pure-UI/support files not affecting flow: [hr_employee_public.py](../addons/hr_holidays/models/hr_employee_public.py) (mirrors employee computes for the public model), [calendar_event.py](../addons/hr_holidays/models/calendar_event.py) (no video call on leave meetings, plus an edit-permission compute), [mail_message_subtype.py](../addons/hr_holidays/models/mail_message_subtype.py) (auto-creates department-level subtypes), [mail_activity_type.py](../addons/hr_holidays/models/mail_activity_type.py) (registers the 4 approval activity types as non-unlinkable via `_get_model_info_by_xmlid`), [res_groups.py](../addons/hr_holidays/models/res_groups.py) (marks the Employee group as light), [hr_holidays_summary_employees.py](../addons/hr_holidays/wizard/hr_holidays_summary_employees.py) (PDF summary report launcher), [controllers/webmanifest.py](../addons/hr_holidays/controllers/webmanifest.py) (PWA share-target entry).

---

## Enterprise: the Defer Flow (inside hr_payroll)

Installing Payroll brings the defer flow; all of it lives in [enterprise/hr_payroll/models/hr_leave.py](../enterprise/hr_payroll/models/hr_leave.py). Everything pivots on one field:

| `payslip_state` ([hr_leave.py:17](../enterprise/hr_payroll/models/hr_leave.py#L17)) | Label |
|---|---|
| `normal` | "To compute in next payslip" (default) |
| `done` | "Computed in current payslip" |
| `blocked` | "Payslip to be corrected" — the leave's period is already closed by a validated/paid slip |

### How a leave becomes blocked

On validation, before the base logic runs, `_action_validate` searches the employee's **regular** payslips: if a `validated`/`paid` slip overlaps the leave **and no other, not-yet-validated regular slip also covers it**, `payslip_state='blocked'` ([hr_leave.py:247](../enterprise/hr_payroll/models/hr_leave.py#L247)). Afterwards `_recompute_payslips` refreshes the draft slips (empty ones recompute worked days, computed ones run `action_refresh_from_work_entries`, [:325](../enterprise/hr_payroll/models/hr_leave.py#L325)) — the same refresh runs after refuse, cancel, back-to-approval and delete.

### What blocked means for payroll correctness

- **Excluded from work-entry generation**: `hr.version._get_resource_calendar_leaves` filters blocked leaves out of calendar-based generation ([hr_payroll/hr_version.py:710](../enterprise/hr_payroll/models/hr_version.py#L710)). The already-paid attendance entries of the closed month stay untouched.
- **The error surface is configurable `hr.payroll.warning` records** ([hr_payroll_warning_data.xml](../enterprise/hr_payroll/data/hr_payroll_warning_data.xml)). A `warning`-level record *Leaves to defer* matches every `payslip_state='blocked'` leave and renders on the leave itself (`display_on_model`) as an `issues` JSON entry with a **"Correct Payslip"** action ([hr_leave.py:88](../enterprise/hr_payroll/models/hr_leave.py#L88)). `_issues_dependencies` ([:83](../enterprise/hr_payroll/models/hr_leave.py#L83)) makes that entry recompute when `payslip_state` changes. A second record flags leaves whose `excess_days` show no covering allocation.
- **Auto-approval is suppressed** for a `no_validation` leave created by a non-officer when any *danger*-level payroll warning applies; an HR-responsible approval activity is scheduled instead ([_process_auto_approve_activities:65](../enterprise/hr_payroll/models/hr_leave.py#L65)). This is the one place payroll can veto a self-service leave.
- **Guards on destructive paths** (all above in the refuse/cancel/delete table): delete is blocked when a validated/paid regular slip confirmed *after* the leave covers it ([:370](../enterprise/hr_payroll/models/hr_leave.py#L370)); Back-to-Approval is hidden and, if forced, raises for non-officers ([:233](../enterprise/hr_payroll/models/hr_leave.py#L233), [:306](../enterprise/hr_payroll/models/hr_leave.py#L306)). Refuse remains unguarded (community asymmetry).
- `compute_sheet` on regular slips marks every non-blocked, non-refused leave ending before the slip horizon as `done` ([hr_payslip.py:1322](../enterprise/hr_payroll/models/hr_payslip.py#L1322)), and refunding a slip flips the blocked leaves it covered back to `normal` ([_action_refund_payslips:1181](../enterprise/hr_payroll/models/hr_payslip.py#L1181)) — the "green" state is bookkeeping, nothing reads it for money.

### Resolution paths

There is no "Defer to Next Month" action in 20.0; a blocked leave is resolved one of two ways:

1. **Correct Payslip** — `action_adjust_corresponding_payslip` ([:281](../enterprise/hr_payroll/models/hr_leave.py#L281)) finds the most recent `validated`/`paid` slip of the employee's structure type overlapping the leave and delegates to `hr.payslip.action_adjust_payslip()`, i.e. the generic payslip-amendment mechanism. The work-entry correction is done by the payslip amendment, not by the leave.
2. **Mark as handled** — completing the "Leave to Defer" activity: `activity_feedback(['hr_payroll.mail_activity_data_hr_leave_to_defer'])` sets `payslip_state='done'` ([:345](../enterprise/hr_payroll/models/hr_leave.py#L345)); cancelling the leave does the same ([:315](../enterprise/hr_payroll/models/hr_leave.py#L315)).

The **Deferred Time Off Manager** company setting lives in `hr_payroll` ([res_company.py:71](../enterprise/hr_payroll/models/res_company.py#L71), [res_config_settings.py:16](../enterprise/hr_payroll/models/res_config_settings.py#L16)).

Deeper payslip-side context (warning records, adjustment slips, payroll statuses) is in [`hr_payroll.md`](hr_payroll.md).

---

## Configuration & Settings

- **Time Off Approver** (employee form, HR Settings tab → `leave_manager_id`) — who approves `manager`-step requests; setting it auto-adds the user to the Responsible group, unsetting removes it if they manage nobody else ([hr_employee.py:345](../addons/hr_holidays/models/hr_employee.py#L345), [res_users.py:14](../addons/hr_holidays/models/res_users.py#L14)).
- **HR Responsible** (`hr_responsible_id` on the employee/version) — who gets `hr`-step activities; the field's domain only accepts Time Off Officers ([hr_version.py:22](../addons/hr_holidays/models/hr_version.py#L22)). Empty = nobody is notified (approval still possible for any officer).
- **Deferred Time Off Manager** (Payroll → Settings → `deferred_time_off_manager`, [enterprise/hr_payroll/models/res_config_settings.py:16](../enterprise/hr_payroll/models/res_config_settings.py#L16)).
- **Menus** ([hr_holidays_views.xml](../addons/hr_holidays/views/hr_holidays_views.xml)): Configuration → **Time Types** (the `hr.work.entry.type` list), **Accrual Plans**, **Company Holidays** (= `resource.calendar.leaves` without resource, Administrator-only, carries the *Load Public Holidays* button), **Mandatory Days** (Administrator-only). Reporting → *by Employee* / *by Type* / *Balance*.

---

## Dependencies

The manifest declares three: `hr_work_entry`, `hr_calendar`, `resource`.

| Requires | Why |
|---|---|
| `hr_work_entry` | owns `hr.work.entry.type` (the time off type itself), `hr.work.entry`, and the `hr.time.rule` engine. Pulls in `hr` transitively |
| `hr_calendar` | pulls in `calendar` for the optional meeting created per validated leave, plus multi-employee calendar helpers |
| `resource` | working calendars; `resource.calendar.leaves` is the materialized-absence table |
| (`mail`, `hr`, `calendar`) | transitive: chatter, approval activities, notification subtypes, meetings |

| Works with | What it adds |
|---|---|
| `hr_payroll` (enterprise) | the defer flow above |
| `hr_holidays_attendance` | wires attendance into accruals (`worked_hours` frequency prorata, [hr_leave_allocation.py:13](../addons/hr_holidays_attendance/models/hr_leave_allocation.py#L13)) and into the time-rule allocation-credit path ([hr_time_rule.py](../addons/hr_holidays_attendance/models/hr_time_rule.py)). There is no `overtime_deductible` type flag in 20.0; extra hours reach time off through time-rule allocation credits |
| `hr_holidays_gantt`, `hr_holidays_contract_gantt` | Gantt/UI layers only |
| `hr_holidays_homeworking`, `project_timesheet_holidays`, `planning_holidays`, `l10n_fr_hr_holidays`, `l10n_in_hr_holidays` | work-location, analytic-line and Planning effects; full relation map in [`public_holidays_flow.md`](public_holidays_flow.md) |

### Time rules on leaves

`hr.time.rule` comes from `hr_work_entry`; `hr_holidays` extends it with two fields ([hr_time_rule.py:26](../addons/hr_holidays/models/hr_time_rule.py#L26)): **Allocate %** (`leave_compensation_rate`) and **Allocate to** (`allocation_type_id`, restricted to allocation-requiring, time-off-selectable types). A rule that fires on excess/deficit time can therefore (a) *split or trim a leave* into rule-typed output leaves — `hr.leave.source_leave_id` / `output_leave_ids` / `is_time_rule_trimmed` — and (b) *credit an open-ended allocation* at the configured rate, logged on `hr.time.rule.allocation.log` ([_apply_allocation_credits:76](../addons/hr_holidays/models/hr_time_rule.py#L76)). Credits are reversed whenever the source leave is rewritten, refused or deleted. Two of the crons drive the day/week passes.

---

## Gotchas & Non-Obvious Behavior

- **Refuse vs cancel asymmetry is the payroll-integrity hole**: refusing a validated leave deactivates already-paid work entries and regenerates attendance, with no payslip guard — only delete and back-to-approval are guarded. Details in [`work_entries.md`](work_entries.md); nothing in `hr_payroll` closes this either.
- **The class docstring is wrong about visibility**: regular employees see only their *own* leaves ([ir.access.csv](../addons/hr_holidays/security/ir.access.csv), `hr_leave_rule_employee`), not "all leaves" as the docstring at [hr_leave.py:40](../addons/hr_holidays/models/hr_leave.py#L40) claims.
- **An officer creating a leave auto-approves it.** `_process_auto_approve_activities` approves in sudo when `validation_type == 'no_validation'` **or** the creating user is in `group_hr_holidays_user` ([hr_leave.py:1590](../addons/hr_holidays/models/hr_leave.py#L1590)). An officer filing their own `both`-validation leave therefore never passes through an approval step at all.
- **Pending requests reserve balance**: `confirm` and `validate1` leaves count as "virtually taken" in every balance computation ([_get_consumed_leaves:546](../addons/hr_holidays/models/hr_employee.py#L546)) — a stack of unapproved requests can block new ones.
- **The overlap check is bucketed by `count_as`.** Two leaves only conflict if they share the same `count_as` value and **both** types have `allow_request_on_top=False`; time-rule-generated leaves are excluded entirely ([_compute_dashboard_warning_message:495](../addons/hr_holidays/models/hr_leave.py#L495) → [_check_date:1383](../addons/hr_holidays/models/hr_leave.py#L1383)). A `working_time` training and an `absence` leave can therefore coexist on the same day.
- **Two more hard constraints on `hr.leave`**: `_check_max_absence_per_day` caps hourly absence requests at the schedule's expected hours (24h/day on flexible calendars, [hr_leave.py:1348](../addons/hr_holidays/models/hr_leave.py#L1348)), and `_check_executive_employee_type` forbids **any** leave for employees of contract type "company executive" ([:1409](../addons/hr_holidays/models/hr_leave.py#L1409)).
- **Officers can resurrect cancelled leaves** (`cancel → confirm/validate/refuse` in the transition matrix, [hr_leave.py:2232](../addons/hr_holidays/models/hr_leave.py#L2232)) even though `_check_approval_update` blocks everyone else with "A cancelled leave cannot be modified".
- **Public-holiday edits rewrite history**: `_reevaluate_leaves` changes validated leave durations, may auto-refuse leave and indirectly deactivate validated work entries, while existing holiday work entries remain stale. The **monthly cron creates public holidays on its own**, so a company that never opens the wizard still gets its calendar rewritten. Block paid/validated intervals server-side.
- **A daily cron force-cancels future leaves** whose accrual balance no longer covers them ([_cancel_invalid_leaves:2525](../addons/hr_holidays/models/hr_leave.py#L2525)) — approved leaves can disappear overnight after an allocation/plan change.
- **Employee unlink row on allocations grants nothing**: its domain requires `state='draft'`, a state allocations never have (`hr_leav_allocation_rule_employee_unlink` in [ir.access.csv](../addons/hr_holidays/security/ir.access.csv)) — employees cannot delete even their own pending allocation requests (officers can).
- **Day-unit types round up**: `ceil(days)` on the computed duration ([hr_leave.py:1051](../addons/hr_holidays/models/hr_leave.py#L1051)) — a 4.5-working-day span costs 5 days, with an explanatory banner (`work_entry_type_increases_duration`, [:863](../addons/hr_holidays/models/hr_leave.py#L863)). `count_days_as='calendar'` types take a different branch and are **not** re-rounded.
- **Dead code in the defer flow**: `hr.leave.write` in `hr_payroll` guards on `vals.get('active')`, a field `hr.leave` does not have, and then calls `_check_uncovered_by_validated_payslip()` twice ([enterprise/hr_payroll/models/hr_leave.py:389](../enterprise/hr_payroll/models/hr_leave.py#L389)) — only the `unlink` guard is live.
- **`blocked` only triggers against *regular* payslips** (`is_regular`, [enterprise/hr_payroll/models/hr_leave.py:258](../enterprise/hr_payroll/models/hr_leave.py#L258)) — credit notes/refund slips over the period don't cause deferral.
- **Installing payroll promotes every payroll user to Time Off Officer** ([enterprise/hr_payroll/security/hr_payroll_security.xml:14](../enterprise/hr_payroll/security/hr_payroll_security.xml#L14)) — they can approve/refuse anyone's leave.
- **Latent bug in the employee-calendar-change path**: the block at [hr_employee.py:361](../addons/hr_holidays/models/hr_employee.py#L361) references `l.leave_type_request_unit`, a field `hr.leave` does not have (the field is `work_entry_type_request_unit`). It never raises only because `write` disables itself with `no_leave_resource_calendar_update`; anything that clears that context key will crash.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`hr_holidays_accrual_plans.md`](hr_holidays_accrual_plans.md) — accrual plans, milestones, carry-over
- [`hr_holidays_time_off_units.md`](hr_holidays_time_off_units.md) — day/half-day/hour units and conversion
- [`public_holidays_flow.md`](public_holidays_flow.md) — complete public-holiday lifecycle
- [`work_entries.md`](work_entries.md) — how validated leaves become work entries; the full leave-lifecycle × work-entry table
- [`hr_payroll.md`](hr_payroll.md) — payslip warning records, payroll statuses
- [`attendance_work_entry.md`](attendance_work_entry.md) — attendance-sourced entries interacting with leaves
- [`hr_employee_versions.md`](hr_employee_versions.md) — version model that leave splitting reacts to
- [`hr_access_rights.md`](hr_access_rights.md) — cross-app access and approver fields
- [`resource_calendars.md`](resource_calendars.md) — the calendars that price a leave's duration
- [`payroll_wage_types.md`](payroll_wage_types.md) — how leave-typed worked-day lines get amounts

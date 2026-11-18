# Timesheets — hr_timesheet, timesheet_grid, project_timesheet_holidays, timesheet_grid_holidays

> **Modules:** `hr_timesheet` ([`addons/hr_timesheet/`](../addons/hr_timesheet/)) | `timesheet_grid` ([`enterprise/timesheet_grid/`](../enterprise/timesheet_grid/)) | `project_timesheet_holidays` ([`addons/project_timesheet_holidays/`](../addons/project_timesheet_holidays/)) | `timesheet_grid_holidays` ([`enterprise/timesheet_grid_holidays/`](../enterprise/timesheet_grid_holidays/))
>
> **Updated by Claude and verified against Odoo 20 source: 2026-09-22.** Written payroll-first: what a payroll/work-log bridge must know about timesheet data, its lifecycle, and its locks. Public-holiday relation map: [`public_holidays_flow.md`](public_holidays_flow.md).

## What It Does & Why It Exists

Employees log hours against projects and tasks. The record is not a dedicated model — it is an `account.analytic.line` with `project_id` set. `hr_timesheet` (community) adds the project/task/employee layer on top of analytic lines and costs the hours against the employee's hourly cost. `timesheet_grid` (enterprise) adds the grid UI, the systray/**Timesheets Assistant**, reminders, the merge wizard, and — critically for payroll — the **validation workflow**: an approver freezes lines with `validated = True`, and a per-employee rolling lock date prevents back-dated edits. `project_timesheet_holidays` auto-generates timesheet lines on an internal project when time off is validated and when public holidays exist, so project time reports stay complete. `timesheet_grid_holidays` is glue that keeps those leave-generated lines out of the enterprise overtime/reminder/grid machinery.

There is **no standard payroll bridge** — payslips never read timesheets ([payroll_wage_types.md](payroll_wage_types.md) §3, §7 row 7). Re-verified against v20 enterprise `hr_payroll`: not one file in the module references `account.analytic.line` or timesheets. Anything payroll does with this data is custom, which is why the anatomy and the locks below matter.

### Changed in 20 — read this before trusting older notes

| Area | v19 | v20 |
|---|---|---|
| Model file | `hr_timesheet/models/hr_timesheet.py` | renamed to [`account_analytic_line.py`](../addons/hr_timesheet/models/account_analytic_line.py); views file likewise `hr_timesheet_views.xml` → [`account_analytic_line_views.xml`](../addons/hr_timesheet/views/account_analytic_line_views.xml) |
| Timer | `account.analytic.line` and `project.task` inherited `timer.mixin` / `timer.parent.mixin`; start/stop/add-time actions; stop-timer confirmation wizard | **All removed.** No timesheet model inherits `timer.mixin` anywhere in v20. Replaced by the Timesheets Assistant (§2) |
| Security | `ir.model.access.csv` + `ir.rule` records | one `ir.access` model, `security/ir.access.csv` (§3) |
| Leave type | `hr.leave.type.time_type == 'other'` skipped generation | `hr.leave.type` no longer exists; the switch is `work_entry_type_id.count_as == 'working_time'` (§5) |
| Hourly cost | `hr_hourly_cost` module | module removed; `hourly_cost` lives in `hr` — [hr_employee.py:279](../addons/hr/models/hr_employee.py#L279) |
| Public-holiday lines | writable (delete-guarded only) | now write-guarded too (§5) |
| Approver's own lines | never validatable by the approver | validatable when the approver is their own `timesheet_manager_id` or their manager's user (§4) |

---

## 1. Anatomy — What Makes a Line a Timesheet

| Question | Answer | Source |
|---|---|---|
| Timesheet vs plain analytic line | `project_id` is set. Every report, rule, and guard filters `project_id != False` | [account_analytic_line.py:249-256](../addons/hr_timesheet/models/account_analytic_line.py#L249), [timesheets_analysis_report.py:69-70](../addons/hr_timesheet/report/timesheets_analysis_report.py#L69) |
| Task without project | Forbidden — `ValidationError` "cannot be created on a private task"; task given → `project_id` auto-filled from the task | [account_analytic_line.py:253-256](../addons/hr_timesheet/models/account_analytic_line.py#L253) |
| Time value | `unit_amount` (float, hours by default), on `date` — a plain **Date**, so timesheet data is day-granular and carries no clock times. Absolute value capped at 999999 | [account_analytic_line.py:78-81](../enterprise/timesheet_grid/models/account_analytic_line.py#L78) |
| Company autofill | Forced to the task's company, else the project's company, in `create()` and `write()` | [account_analytic_line.py:258-259](../addons/hr_timesheet/models/account_analytic_line.py#L258), [account_analytic_line.py:373-374](../addons/hr_timesheet/models/account_analytic_line.py#L373) |
| UoM autofill | `product_uom_id` defaults to `company.project_time_mode_id` (Hours by default) — that is the **storage** unit of `unit_amount`. The company "Encoding Method" (`timesheet_encode_uom_id`, hours vs days) only changes widgets/display, not storage | [account_analytic_line.py:266-267](../addons/hr_timesheet/models/account_analytic_line.py#L266), [res_company.py:19-25](../addons/hr_timesheet/models/res_company.py#L19), [res_config_settings.py:20-35](../addons/hr_timesheet/models/res_config_settings.py#L20) |
| Analytic accounts | `account_id` (+ any other mandatory plan columns) copied from the project; missing mandatory plans on the project raise `ValidationError` | [account_analytic_line.py:424-440](../addons/hr_timesheet/models/account_analytic_line.py#L424) |
| Cost | `amount = -unit_amount × employee.hourly_cost`, converted to the account currency, recomputed by `_timesheet_postprocess_values` whenever `unit_amount`/`employee_id`/`account_id` change | [account_analytic_line.py:451-481](../addons/hr_timesheet/models/account_analytic_line.py#L451), [account_analytic_line.py:504-506](../addons/hr_timesheet/models/account_analytic_line.py#L504) |
| Empty description | `name` forced to `'/'` | [account_analytic_line.py:269-270](../addons/hr_timesheet/models/account_analytic_line.py#L269) |

### Employee resolution on create

`create()` guarantees every timesheet ends up with a valid `employee_id` ([account_analytic_line.py:221-364](../addons/hr_timesheet/models/account_analytic_line.py#L221)):

1. Explicit `employee_id` in vals (or `default_employee_id` context) — must be an **active** employee in one of `self.env.companies`, else `ValidationError` "must be created with an active employee in the selected companies" ([L301](../addons/hr_timesheet/models/account_analytic_line.py#L301)). The employee's user becomes `user_id`.
2. No employee — falls back to `user_id` (default: current user) and searches that user's employees **in sudo** (works even though plain employees have no `hr.employee` ACL — [payroll_wage_types.md](payroll_wage_types.md) §8.3). Resolution succeeds if the user has exactly one employee across the allowed companies, or one in the vals' company; otherwise `ValidationError`.
3. On `write()`, setting an archived employee raises `UserError` ([account_analytic_line.py:381-384](../addons/hr_timesheet/models/account_analytic_line.py#L381)).

**Changed in 20 —** enterprise adds a rescue in front of all of this: if the database has **no `hr.employee` record at all** and a timesheet is being created without one, `timesheet_grid` silently creates the employee from the user before delegating to community `create()` ([account_analytic_line.py:35-76](../enterprise/timesheet_grid/models/account_analytic_line.py#L35)). It only fires on a completely employee-less database and only when exactly one employee would be created, so it is a first-run convenience, not a general fallback — a bridge should not rely on it.

`department_id` and `manager_id` are stored relateds of the employee ([account_analytic_line.py:74-75](../addons/hr_timesheet/models/account_analytic_line.py#L74)); the analysis report groups by them.

### The project side

- Projects have `allow_timesheets` (default True) and must own an analytic account to allow it — creating a project auto-creates one ([project_project.py:139-147](../addons/hr_timesheet/models/project_project.py#L139), [project_project.py:185-194](../addons/hr_timesheet/models/project_project.py#L185)).
- Every company gets an auto-created **Internal** project with Training/Meeting tasks on company creation and at module install ([res_company.py:46-66](../addons/hr_timesheet/models/res_company.py#L46), [__init__.py:13-31](../addons/hr_timesheet/__init__.py#L13)).
- Projects and tasks with timesheets cannot be deleted ([project_project.py:219-235](../addons/hr_timesheet/models/project_project.py#L219), [project_task.py:267-298](../addons/hr_timesheet/models/project_task.py#L267)). The task guard is two-tiered: a user who cannot even *read* the blocking lines gets a flat `UserError` telling them to ask someone with more access; everyone else gets a `RedirectWarning` onto the lines. A task with timesheets cannot be made private ([project_task.py:65-68](../addons/hr_timesheet/models/project_task.py#L65)).
- Task rollups `effective_hours` / `total_hours_spent` / `remaining_hours` / `progress` are stored computes summing `timesheet_ids.unit_amount` ([project_task.py:39-45](../addons/hr_timesheet/models/project_task.py#L39), [project_task.py:96-158](../addons/hr_timesheet/models/project_task.py#L96)).

---

## 2. Creation Paths

| Path | Mechanism | Notes |
|---|---|---|
| List/form views | Standard ORM; `default_get` with `is_timesheet` context picks a "favorite" project | [account_analytic_line.py:25-45](../addons/hr_timesheet/models/account_analytic_line.py#L25), context set in [account_analytic_line_views.xml:401](../addons/hr_timesheet/views/account_analytic_line_views.xml#L401) |
| Grid view (enterprise) | Cell edits call `grid_update_cell(domain, field, value)`: one draft line in the cell → add to it; several lines or a single **validated** line → `copy()` a new draft line; empty cell → `create()` (needs a project from grouping/context, else RedirectWarning) | [account_analytic_line.py:396-433](../enterprise/timesheet_grid/models/account_analytic_line.py#L396) |
| Timesheets Assistant (enterprise) | **Replaces the v19 timer.** A systray/assistant panel reconstructs the day from external activity and proposes lines the user accepts. Server side it is read-only helpers — `get_aw_timesheet_data` reads today's lines plus the employee's working hours, `get_assistant_events` merges event streams from pluggable getters, `action_round_timesheet_time` rounds an existing line by the ICPs, `change_description` renames one | [account_analytic_line.py:471-489](../enterprise/timesheet_grid/models/account_analytic_line.py#L471), [account_analytic_line.py:549-596](../enterprise/timesheet_grid/models/account_analytic_line.py#L549), [account_analytic_line.py:1095-1106](../enterprise/timesheet_grid/models/account_analytic_line.py#L1095), [timesheet_systray_controller.py](../enterprise/timesheet_grid/controllers/timesheet_systray_controller.py) |
| Assistant rules (`aw.rule`) | New model matching ActivityWatch browser/window titles by regex to a label, type icon, and optional default project/task. Rules are scoped `everyone` / `departments` / `private` and gate what the assistant suggests — they never create lines by themselves | [aw_rule.py](../enterprise/timesheet_grid/models/aw_rule.py), [aw_rule.py:131-150](../enterprise/timesheet_grid/models/aw_rule.py#L131) |
| Calendar view | `timesheet_calendar` context: create silently **skips days the employee is not scheduled to work** (per `_get_valid_work_intervals`) and reports via bus notification | [account_analytic_line.py:235-246](../addons/hr_timesheet/models/account_analytic_line.py#L235), [account_analytic_line.py:348-362](../addons/hr_timesheet/models/account_analytic_line.py#L348) |
| Portal | Read-only. `/my/timesheets` lists lines matching `_timesheet_get_portal_domain`; the portal `ir.access` row is read-only and **inactive** until project sharing toggles it on | [portal.py:68-71](../addons/hr_timesheet/controllers/portal.py#L68), [account_analytic_line.py:412-422](../addons/hr_timesheet/models/account_analytic_line.py#L412), [hr_timesheet_security.xml:35-46](../addons/hr_timesheet/security/hr_timesheet_security.xml#L35), [project_collaborator.py:10-16](../addons/hr_timesheet/models/project_collaborator.py#L10) |
| Import | XLSX template exposed when `is_timesheet` context is set | [account_analytic_line.py:554-561](../addons/hr_timesheet/models/account_analytic_line.py#L554) |
| Leave validation / public holidays | sudo-created lines on the company internal project — section 5 | |

**Changed in 20 — the favorite project is stricter and no longer falls back.** `_get_favorite_project_id` used to take the *mode* of the last 5 timesheets' projects and, failing that, the company internal project. It now requires the same project on **at least 3 of the 5** most recent lines and otherwise returns `False` ([account_analytic_line.py:25-33](../addons/hr_timesheet/models/account_analytic_line.py#L25)). A new form no longer silently pre-fills the Internal project.

**Changed in 20 — task prefill on project change.** In the assistant's search context, picking a project prefills the task from the user's most recent line on that project in the past month ([account_analytic_line.py:159-185](../enterprise/timesheet_grid/models/account_analytic_line.py#L159)). With `timesheet_grid_holidays` installed, leave lines are excluded from that lookup ([analytic.py:28-34](../enterprise/timesheet_grid_holidays/models/analytic.py#L28)).

---

## 3. Security Model

**Changed in 20 — `ir.model.access` and `ir.rule` are gone.** One `ir.access` model replaces both. Group definitions still load first from `*_security.xml`; `security/ir.access.csv` loads **last** in the manifest ([__manifest__.py:41](../addons/hr_timesheet/__manifest__.py#L41), [__manifest__.py:30](../enterprise/timesheet_grid/__manifest__.py#L30)). A row with a `group_id` is a *permission*; a row with an empty `group_id` is a *restriction* applied to everyone. The old `perm_read/write/create/unlink` booleans collapsed into one `operation` column holding a subset of `crud`.

Three groups, defined in [hr_timesheet_security.xml](../addons/hr_timesheet/security/hr_timesheet_security.xml), all under a shared `res.groups.privilege` "Timesheets" ([L3-7](../addons/hr_timesheet/security/hr_timesheet_security.xml#L3)):

| Group | XML id | Scope |
|---|---|---|
| User: own timesheets only | `group_hr_timesheet_user` ([L9](../addons/hr_timesheet/security/hr_timesheet_security.xml#L9)) | `crud` on own lines (`user_id = user.id`) on visible projects ([ir.access.csv:2](../addons/hr_timesheet/security/ir.access.csv#L2)) |
| User: all timesheets (approver) | `group_hr_timesheet_approver` ([L18](../addons/hr_timesheet/security/hr_timesheet_security.xml#L18)) | `crud` on all lines on visible projects ([ir.access.csv:11](../addons/hr_timesheet/security/ir.access.csv#L11)); may set others' `employee_id` ([account_analytic_line.py:53-57](../addons/hr_timesheet/models/account_analytic_line.py#L53)) |
| Administrator | `group_timesheet_manager` ([L26](../addons/hr_timesheet/security/hr_timesheet_security.xml#L26)) | `crud` on all lines, no project-visibility filter ([ir.access.csv:19](../addons/hr_timesheet/security/ir.access.csv#L19)); implies approver + `hr.group_hr_user` |

- `project.group_project_manager` is **implied approver** ([hr_timesheet_security.xml:52-54](../addons/hr_timesheet/security/hr_timesheet_security.xml#L52)) and gets its own unfiltered row ([ir.access.csv:20](../addons/hr_timesheet/security/ir.access.csv#L20)).
- Python-level ownership guard independent of the access rows: non-approvers writing someone else's line get `AccessError` ([account_analytic_line.py:207-215](../addons/hr_timesheet/models/account_analytic_line.py#L207)); the same check on create in enterprise ([account_analytic_line.py:357-366](../enterprise/timesheet_grid/models/account_analytic_line.py#L357)). Both hang off the shared `_check_can_write` / `_check_can_create` hooks that `analytic` calls from `write()` ([analytic_line.py:240-242](../addons/analytic/models/analytic_line.py#L240)) and that `hr_timesheet` calls after `create()` ([account_analytic_line.py:343](../addons/hr_timesheet/models/account_analytic_line.py#L343)) — every module in this cluster layers onto them rather than overriding `write()`.
- **Enterprise replaces the base user row.** `timesheet_grid` **deactivates** the community `timesheet_line_rule_user` ([timesheet_security.xml:4-6](../enterprise/timesheet_grid/security/timesheet_security.xml#L4)) and publishes two of its own: a `cr` (create/read) row and a `ud` (update/delete) row scoped to `validated = False` ([ir.access.csv:24](../enterprise/timesheet_grid/security/ir.access.csv#L24), [ir.access.csv:33](../enterprise/timesheet_grid/security/ir.access.csv#L33)). So a plain user cannot touch a validated line even via raw ORM. Uninstalling `timesheet_grid` reactivates the community row ([__init__.py:27-28](../enterprise/timesheet_grid/__init__.py#L27)).
- **New in 20:** `timesheet_grid.group_timesheet_assistant` ("Use Timesheets Assistant", [timesheet_security.xml:10-12](../enterprise/timesheet_grid/security/timesheet_security.xml#L10)), toggled from Settings ([res_config_settings.py:23](../enterprise/timesheet_grid/models/res_config_settings.py#L23)), plus `aw.rule` rows giving users read on rules that apply to them and write only on their own private rules ([ir.access.csv:3-23](../enterprise/timesheet_grid/security/ir.access.csv#L3)).

---

## 4. Validation Flow (enterprise) — the Payroll Gate

### State

`validated` is a plain stored Boolean (`copy=False`, `readonly=True`) with a cosmetic `validated_status` selection `draft`/`validated` computed from it ([account_analytic_line.py:27-29](../enterprise/timesheet_grid/models/account_analytic_line.py#L27)). There is no workflow engine — the flag plus guards *is* the workflow. The analysis report exposes both ([timesheets_analysis_report.py:10-18](../enterprise/timesheet_grid/report/timesheets_analysis_report.py#L10)).

### Who may validate — approver resolution

`_get_domain_for_validation_timesheets(validated=False)` ([account_analytic_line.py:1108-1145](../enterprise/timesheet_grid/models/account_analytic_line.py#L1108)) is the single source of truth, used by the validate action, the reset action and the reminder cron:

- **Manager group** (`group_timesheet_manager`): everything with `project_id != False`, including own lines.
- **Approver group**: never own lines through the main branch (`user_id != uid`), and only employees where the approver is `employee.timesheet_manager_id`, OR the employee has no `timesheet_manager_id` set, OR the employee is in the approver's `subordinate_ids`, OR the approver is the `parent_id`'s user, OR the employee has neither manager nor timesheet approver.
- Validation additionally requires `date <= today` — **future-dated lines cannot be validated**. (Reset-to-draft passes `validated=True` and skips that clause.)
- **Changed in 20 — approvers can now validate their own lines in one case.** A new OR-branch matches `user_id = uid` when the approver is their own `timesheet_manager_id` or when their manager's user is themselves ([L1138-1143](../enterprise/timesheet_grid/models/account_analytic_line.py#L1138)). Because it is OR'd at the top level it also bypasses the `date <= today` and `validated` clauses, so a self-approving approver can validate their own future-dated lines. Treat "validated" as a claim about approval, not about the date having passed.

`employee.timesheet_manager_id` ("Timesheet Approver", [hr_employee.py:36-41](../enterprise/timesheet_grid/models/hr_employee.py#L36)) is the pivot. **Changed in 20 —** it no longer auto-fills from the employee's manager. The compute now only *follows* a manager change when the field was already pointing at the previous manager; a blank approver stays blank ([hr_employee.py:45-53](../enterprise/timesheet_grid/models/hr_employee.py#L45)). In v19 the field defaulted to the manager's user whenever that user was in the approver group. The practical effect is that more employees fall into the "no `timesheet_manager_id`" branch above, which **any** approver satisfies.

`project_id.user_id` grants the per-line `user_can_validate` UI flag ([account_analytic_line.py:195-207](../enterprise/timesheet_grid/models/account_analytic_line.py#L195)) but is **not** in the action's domain — see Gotchas.

### Validate

`action_validate_timesheet()` ([account_analytic_line.py:249-285](../enterprise/timesheet_grid/models/account_analytic_line.py#L249)), called from list/grid/kanban/pivot buttons and an `ir.actions.server` ([account_analytic_line_views.xml:343](../enterprise/timesheet_grid/views/account_analytic_line_views.xml#L343)):

1. Requires approver group, filters the selection through the domain above (in sudo).
2. `sudo().write({'validated': True})`.
3. `_update_last_validated_timesheet_date()` pushes each employee's `last_validated_timesheet_date` forward to the max validated date ([account_analytic_line.py:209-225](../enterprise/timesheet_grid/models/account_analytic_line.py#L209)).

**Changed in 20 —** the two timer steps are gone. v19 stopped all running timers on the selected lines before writing and then killed any timer still running on a line behind the new lock date. With the timer removed from the model there is nothing left to interrupt, so validation is now a pure flag write plus a lock-date bump.

### What validation freezes

| Frozen | Mechanism |
|---|---|
| Edits by non-approvers | `_check_can_write` raises; writing the `validated` field itself is approver-only ([account_analytic_line.py:368-377](../enterprise/timesheet_grid/models/account_analytic_line.py#L368)) + the `ud` access row (§3) |
| Deletion by non-approvers | `@api.ondelete` ([account_analytic_line.py:435-441](../enterprise/timesheet_grid/models/account_analytic_line.py#L435)) |
| Project reassignment via task move | `_compute_project_id` skips validated lines ([account_analytic_line.py:154-157](../enterprise/timesheet_grid/models/account_analytic_line.py#L154)) |
| Grid cell edits | New draft line is copied instead of touching the validated one ([account_analytic_line.py:406-411](../enterprise/timesheet_grid/models/account_analytic_line.py#L406)) |
| Merging | Merge candidates filtered to `not validated` ([account_analytic_line.py:1147-1148](../enterprise/timesheet_grid/models/account_analytic_line.py#L1147)) |
| UI editability | `readonly_timesheet` compute → `_is_readonly()` returns True when validated ([account_analytic_line.py:83-84](../enterprise/timesheet_grid/models/account_analytic_line.py#L83), [account_analytic_line.py:112-125](../addons/hr_timesheet/models/account_analytic_line.py#L112)) |

### The rolling period lock — `last_validated_timesheet_date`

Beyond the per-line freeze, validation locks the **period**. `check_if_allowed()` ([account_analytic_line.py:320-355](../enterprise/timesheet_grid/models/account_analytic_line.py#L320)) runs on create, write and delete, reached through `_check_can_create` / `_check_can_write` / `_unlink_if_manager`:

- Applies to everyone except `group_timesheet_manager` and sudo.
- Blocks create/edit/delete of any timesheet dated `<= employee.last_validated_timesheet_date` — **including new draft lines in an already-validated period**, and including the employee's own lines.
- Exception 1: lines dated exactly **today** are always allowed. **Changed in 20 —** "today" is now `fields.Date.context_today(line)`, i.e. the acting user's timezone, not the server's ([L339](../enterprise/timesheet_grid/models/account_analytic_line.py#L339)).
- Exception 2: approvers acting on employees of their own team (same resolution logic as validation, inlined as an employee search at [L323-330](../enterprise/timesheet_grid/models/account_analytic_line.py#L323)) skip the date lock.

`last_validated_timesheet_date` lives on `hr.employee`, readable only by timesheet managers ([hr_employee.py:43](../enterprise/timesheet_grid/models/hr_employee.py#L43)); the grid frontend fetches it per user to grey out locked cells ([res_users.py:10-17](../enterprise/timesheet_grid/models/res_users.py#L10)).

### Un-validation

`action_invalidate_timesheet()` ([account_analytic_line.py:287-318](../enterprise/timesheet_grid/models/account_analytic_line.py#L287)) — same permission domain with `validated=True` — resets the flag and then **recomputes** each affected employee's lock date from scratch as `max(date)` of their remaining validated lines, clearing it first so it can move backward ([`_search_last_validated_timesheet_date`, account_analytic_line.py:227-242](../enterprise/timesheet_grid/models/account_analytic_line.py#L227)). Server action at [account_analytic_line_views.xml:557](../enterprise/timesheet_grid/views/account_analytic_line_views.xml#L557).

### Company settings — there is no company lock date

Locking in this cluster is entirely the per-employee rolling date; there is no company-level "lock timesheets before X" field. Company-level config is limited to encoding UoM (§1), the two rounding ICPs, the assistant toggle, and reminders (§6). (Invoice-side locking such as billed-at-validation lives in `sale_timesheet_enterprise`, outside this cluster.)

---

## 5. The Leave Bridge — project_timesheet_holidays

Auto-installed with `hr_timesheet + hr_holidays` ([__manifest__.py:24](../addons/project_timesheet_holidays/__manifest__.py#L24)). Purpose: when someone is off, project reporting still shows where the week went, on a neutral internal project.

### Configuration surface

- Per company: `internal_project_id` (from hr_timesheet) + `leave_timesheet_task_id` ("Time Off" task), auto-created for new companies ([res_company.py:14-29](../addons/project_timesheet_holidays/models/res_company.py#L14)) and backfilled at install ([__init__.py:7-45](../addons/project_timesheet_holidays/__init__.py#L7)). Exposed in Settings ([res_config_settings.py:10-19](../addons/project_timesheet_holidays/models/res_config_settings.py#L10)).
- **Changed in 20 — the per-leave-type switch moved.** `hr.leave.type` no longer exists; leaves carry a `work_entry_type_id`, and generation is skipped when that type's `count_as` is `'working_time'` ([hr_leave.py:30-31](../addons/project_timesheet_holidays/models/hr_leave.py#L30), field at [hr_work_entry_type.py:36-42](../addons/hr_work_entry/models/hr_work_entry_type.py#L36)). Leave counted as working time produces no timesheet at all. The settings help text still claims "You can specify another project on each time type individually" ([res_config_settings.py:14](../addons/project_timesheet_holidays/models/res_config_settings.py#L14)) — that remains stale in v20: there is no per-type project or task override anywhere in this module, only the per-company pair.

### Personal leave flow (`hr.leave`)

`_validate_leave_request()` → `_generate_timesheets()` ([hr_leave.py:13-78](../addons/project_timesheet_holidays/models/hr_leave.py#L13)):

1. Per leave, work hours are split per day via `employee._list_work_time_per_day()` (the leave's own `resource.calendar.leaves` record is excluded so the days don't count as already-off).
2. **Changed in 20 — schedule handling is version-based.** The calendar comes from `employee.sudo()._get_version(leave.date_from.date())`, so a mid-period schedule change is honoured. Flexible-schedule single-day leaves compute hours from `work_entry_type_request_unit`: hour requests use `request_hour_to - request_hour_from`, half-days use `hours_per_day / 2`, single days use `hours_per_day` ([hr_leave.py:40-54](../addons/project_timesheet_holidays/models/hr_leave.py#L40)).
3. **Changed in 20 — two silent skips.** Employees whose version is **fully flexible**, and employees with no timezone, generate **no leave timesheets at all** ([hr_leave.py:41-42](../addons/project_timesheet_holidays/models/hr_leave.py#L41)). A project-time report will show their leave weeks as empty.
4. One line per day: name "Time Off (i/n)", internal project + Time Off task, `holiday_id` set, employee/user/company from the leave ([hr_leave.py:80-93](../addons/project_timesheet_holidays/models/hr_leave.py#L80)).
5. Pre-existing lines of the same leaves are unlinked first (idempotent regeneration), then all lines are **created in sudo** ([hr_leave.py:72-78](../addons/project_timesheet_holidays/models/hr_leave.py#L72)) — which bypasses every guard in §4, including the period lock.

Deletion mirrors the leave lifecycle: refusal ([hr_leave.py:111-118](../addons/project_timesheet_holidays/models/hr_leave.py#L111)), user cancellation ([L120-126](../addons/project_timesheet_holidays/models/hr_leave.py#L120)), force-cancel ([L128-133](../addons/project_timesheet_holidays/models/hr_leave.py#L128)), shrink-to-zero-days writes ([L135-144](../addons/project_timesheet_holidays/models/hr_leave.py#L135)) and — new in 20 — deleting the leave record itself ([L146-152](../addons/project_timesheet_holidays/models/hr_leave.py#L146)) all sudo-unlink the lines (after clearing `holiday_id` to dodge the delete guard). Refusal, cancel and delete then re-generate any public-holiday lines the leave had suppressed ([`_check_missing_global_leave_timesheets`, L95-109](../addons/project_timesheet_holidays/models/hr_leave.py#L95)).

### Public holidays (`resource.calendar.leaves` with no resource)

- Creating a global leave generates one line per working day for **every employee** on the matching calendar(s) in the allowed companies, skipping employees with an approved personal leave covering that day; `global_leave_id` links the line ([resource_calendar_leaves.py:119-190](../addons/project_timesheet_holidays/models/resource_calendar_leaves.py#L119), entry point [L207-210](../addons/project_timesheet_holidays/models/resource_calendar_leaves.py#L207), [create:260-264](../addons/project_timesheet_holidays/models/resource_calendar_leaves.py#L260)).
- Rescheduling a global leave deletes and regenerates its lines and re-generates the personal-leave lines it had displaced; deleting one cascades its lines (`ondelete='cascade'` on `global_leave_id`, [account_analytic.py:12](../addons/project_timesheet_holidays/models/account_analytic.py#L12)) and regenerates the personal-leave lines ([write:266-284](../addons/project_timesheet_holidays/models/resource_calendar_leaves.py#L266), [ondelete:286-294](../addons/project_timesheet_holidays/models/resource_calendar_leaves.py#L286)).
- Employee lifecycle keeps them consistent: new/unarchived employees get lines for future public holidays; archiving deletes future ones; changing `resource_calendar_id` rebuilds them ([hr_employee.py:11-79](../addons/project_timesheet_holidays/models/hr_employee.py#L11)). Salary-simulation contexts are skipped entirely.

### Guards on generated lines

- Manual deletion blocked: global-leave lines → hard `UserError`; leave lines → RedirectWarning to the leave, or a flat `UserError` for users who are neither a time-off officer nor the leave's owner ([account_analytic.py:35-44](../addons/project_timesheet_holidays/models/account_analytic.py#L35)).
- **Changed in 20 — manual modification is blocked for both kinds.** `_check_can_write` now raises for `global_leave_id` lines as well as `holiday_id` lines, for everyone except sudo ([account_analytic.py:46-51](../addons/project_timesheet_holidays/models/account_analytic.py#L46)). In v19 only `holiday_id` lines were write-protected; public-holiday lines could have their hours edited. Both kinds are also `_is_readonly` in the UI ([account_analytic.py:18-19](../addons/project_timesheet_holidays/models/account_analytic.py#L18)).
- Manual timesheets on a time-off task blocked ([account_analytic.py:53-56](../addons/project_timesheet_holidays/models/account_analytic.py#L53)); a task is `is_timeoff_task` when it is the company's leave task or carries any leave-linked line ([project_task.py:24-27](../addons/project_timesheet_holidays/models/project_task.py#L24)), and the timeoff task is filtered out of the task dropdown ([account_analytic.py:13](../addons/project_timesheet_holidays/models/account_analytic.py#L13)).
- Favorite-project default excludes leave lines ([account_analytic.py:58-63](../addons/project_timesheet_holidays/models/account_analytic.py#L58)).
- Interaction with validated periods: generation and deletion run in sudo, so **the leave bridge writes and deletes straight through the validation lock**. Standard validation does not exclude `holiday_id`/`global_leave_id`; if such a line is validated and later regenerated, sudo deletion does not recompute `employee.last_validated_timesheet_date`, so ordinary earlier timesheets can remain falsely locked.

### timesheet_grid_holidays (glue, auto-installed with both parents)

- Overtime avatar/grid totals exclude leave lines (`holiday_id IS NULL AND global_leave_id IS NULL` in the worked-hours SQL) ([hr_employee.py:10-17](../enterprise/timesheet_grid_holidays/models/hr_employee.py#L10)) — this is the module's stated purpose ("prevents taking time offs into account when computing employee overtime", [__manifest__.py:6-8](../enterprise/timesheet_grid_holidays/__manifest__.py#L6)).
- Reminder cron ignores leave lines when deciding who timesheeted ([res_company.py:10-15](../enterprise/timesheet_grid_holidays/models/res_company.py#L10)).
- Grid cell updates never target leave lines (`holiday_id = False` injected into the cell domain) and merge refuses them ([analytic.py:11-26](../enterprise/timesheet_grid_holidays/models/analytic.py#L11)). **Changed in 20 —** the v19 timer refusals are gone with the timer; a new override keeps leave lines out of the assistant's "recently used" project/task suggestions ([analytic.py:28-34](../enterprise/timesheet_grid_holidays/models/analytic.py#L28)).

---

## 6. Reminders & Crons (enterprise)

Two daily crons on `res.company` ([ir_cron_data.xml](../enterprise/timesheet_grid/data/ir_cron_data.xml)), each self-scheduling via a company `..._nextdate` field recomputed from delay + weekly/monthly interval ([res_company.py:21-99](../enterprise/timesheet_grid/models/res_company.py#L21)):

| Cron | Recipients | Trigger condition |
|---|---|---|
| `_cron_timesheet_reminder_employee` | Users with ≥1 timesheet in the last 3 months whose timesheeted hours < calendar working hours for the elapsed week/month | [res_company.py:110-156](../enterprise/timesheet_grid/models/res_company.py#L110), window at [res_company.py:101-108](../enterprise/timesheet_grid/models/res_company.py#L101) |
| `_cron_timesheet_reminder` | Every approver-group user who has lines pending validation (per `_get_domain_for_validation_timesheets`) where they are the `timesheet_manager_id` | [res_company.py:158-207](../enterprise/timesheet_grid/models/res_company.py#L158) |

Settings toggles/delays are related fields on the company ([res_config_settings.py:9-19](../enterprise/timesheet_grid/models/res_config_settings.py#L9)). With `timesheet_grid_holidays`, leave lines don't count toward "has timesheeted".

Note the second cron only mails approvers who are the employee's explicit `timesheet_manager_id`. Since v20 stopped auto-filling that field (§4), employees left with a blank approver produce lines that *anyone* in the approver group may validate but that nobody is reminded about.

## 7. Merge Wizard (enterprise)

`hr_timesheet.merge.wizard` ([hr_timesheet_merge_wizard.py](../enterprise/timesheet_grid/wizard/hr_timesheet_merge_wizard.py)) — list-view action on selected lines, entered through `action_merge_timesheets` ([account_analytic_line.py:1150-1172](../enterprise/timesheet_grid/models/account_analytic_line.py#L1150)). Eligible lines: `project_id` set and not validated ([default_get:28-46](../enterprise/timesheet_grid/wizard/hr_timesheet_merge_wizard.py#L28)); **changed in 20 —** the v19 "no running timer" condition is gone with the timer. All merged lines must share one encoding UoM ([L22-26](../enterprise/timesheet_grid/wizard/hr_timesheet_merge_wizard.py#L22)). It concatenates distinct descriptions, sums `unit_amount`, takes date/project/task/employee from the first line, then **creates one new line and unlinks the originals** ([action_merge:65-91](../enterprise/timesheet_grid/wizard/hr_timesheet_merge_wizard.py#L65)) — original IDs do not survive a merge. Leave lines refuse merging ([timesheet_grid_holidays/analytic.py:11-18](../enterprise/timesheet_grid_holidays/models/analytic.py#L11)).

---

## 8. Hooks a Payroll Bridge Would Use

Context: [payroll_wage_types.md](payroll_wage_types.md) §7 row 7 (no standard bridge; salary rule may query timesheets directly) and §9.7 (validate → compute flow, worked examples). What to read:

| Need | Read | Why |
|---|---|---|
| "Is a timesheet" | `project_id != False` | The only discriminator (§1) |
| Pay gate | `validated = True` | The approval state; `validated_status` is derived UI sugar ([account_analytic_line.py:28-29](../enterprise/timesheet_grid/models/account_analytic_line.py#L28)) |
| Period | `date` (Date) + `employee_id` | Day-granular, no clock times — the same day+hours shape a work-entry-style consumer expects |
| Hours | `unit_amount` | Stored in `company.project_time_mode_id` units — Hours unless someone changed it; do **not** confuse with the encoding UoM (§1) |
| Exclude leave-generated time | `holiday_id = False AND global_leave_id = False` | Otherwise every validated vacation double-pays (leave already pays through the work-entry side). Filtering `task_id.is_timeoff_task = False` is a weaker substitute (non-stored compute) |
| Period-close coordination | `employee.sudo().last_validated_timesheet_date` | The rolling lock the UI enforces; a bridge can require it ≥ payslip `date_to` before computing |
| Rate | not here | `amount` is the negative analytic **cost** (hourly_cost), not a pay rate — keep pay rates on the version/salary rule |

Index reality check: `project_timesheet_holidays` declares two partial indexes on `account_analytic_line` ([account_analytic.py:15-16](../addons/project_timesheet_holidays/models/account_analytic.py#L15)). Both are keyed on `task_id` and both are built for *finding* leave lines, not for excluding them — a payroll query filtering `holiday_id IS NULL AND global_leave_id IS NULL` is not served by either. On a large database, measure before assuming the exclusion is free.

Sanctioned rule pattern (precedent: UAE EOS rule, see payroll_wage_types.md §7 row 7):

```python
result = payslip.env['account.analytic.line'].sudo().search_read([
    ('employee_id', '=', employee.id),
    ('project_id', '!=', False),
    ('validated', '=', True),
    ('holiday_id', '=', False),
    ('global_leave_id', '=', False),
    ('date', '>=', payslip.date_from), ('date', '<=', payslip.date_to),
], aggregates=...)  # or _read_group on unit_amount:sum
```

`_read_group` is still the right backend call in v20 (`read_group` came back as the public/RPC wrapper — see `v20-changes.md` §3).

Boundary rule from §9.7 applies: lines validated after compute are missed by a date-window rule — enforce validate-then-compute, or claim lines onto the payslip. Note `validated` alone is not immutability: un-validation (§4) and the sudo leave bridge (§5) can still change history after a payslip computed — a defensive bridge stores the summed amount (or line IDs) on the slip at compute time.

---

## Configuration & Settings

- **Encoding Method** (Settings → Timesheets): swaps `company.timesheet_encode_uom_id` between Hours and Days ([res_config_settings.py:20-35](../addons/hr_timesheet/models/res_config_settings.py#L20)). Day mode changes widgets (`float_toggle` vs `float_time`, [hr_timesheet_data.xml:3-12](../addons/hr_timesheet/data/hr_timesheet_data.xml#L3)); storage stays in `project_time_mode_id` units. **Changed in 20 —** day mode no longer disables a timer (there is none); it hides the assistant's sync and configuration menus instead ([ir_ui_menu.py:7-15](../enterprise/timesheet_grid/models/ir_ui_menu.py#L7)).
- **Project Time Unit** (`project_time_mode_id`): the storage/display unit for task hours and the `product_uom_id` default. Changing it re-scales the meaning of every stored `unit_amount` — leave it at Hours.
- **Time Off** (Settings): installs `project_timesheet_holidays`; its own settings are the internal project + Time Off task per company (§5).
- **Timesheets Assistant** (Settings): grants `timesheet_grid.group_timesheet_assistant` ([res_config_settings.py:23](../enterprise/timesheet_grid/models/res_config_settings.py#L23)). Rules are managed under Timesheets → Configuration as `aw.rule` records (§2).
- **Rounding**: ICPs `timesheet_grid.timesheet_min_duration` and `timesheet_grid.timesheet_rounding` (minutes, both default 15) ([res_config_settings.py:20-21](../enterprise/timesheet_grid/models/res_config_settings.py#L20), [ir_config_parameter_data.xml](../enterprise/timesheet_grid/data/ir_config_parameter_data.xml)). In v19 these rounded a stopped timer; in v20 they feed `_get_rounding_values`, used by the assistant's round action ([account_analytic_line.py:443-448](../enterprise/timesheet_grid/models/account_analytic_line.py#L443), [account_analytic_line.py:1095-1101](../enterprise/timesheet_grid/models/account_analytic_line.py#L1095)).
- **Reminders**: per-company employee/approver reminder toggles, delay days, weekly/monthly (§6).

## Dependencies

| Module | Depends on | Notes |
|---|---|---|
| `hr_timesheet` | `hr`, `analytic`, `project`, `uom` | [__manifest__.py:21](../addons/hr_timesheet/__manifest__.py#L21). **Changed in 20:** `hr_hourly_cost` dropped — the module is gone and `hourly_cost` now ships in `hr` |
| `timesheet_grid` | `project_enterprise`, `web_grid`, `hr_timesheet`, `timer` | auto-installs with web_grid+hr_timesheet; [__manifest__.py:10](../enterprise/timesheet_grid/__manifest__.py#L10). **Changed in 20:** `hr_org_chart` dropped. `timer` is still declared but no timesheet model inherits `timer.mixin` any more — only the `round_time_spent` helper is imported from it |
| `project_timesheet_holidays` | `hr_timesheet`, `hr_holidays` | auto-install; [__manifest__.py:14](../addons/project_timesheet_holidays/__manifest__.py#L14) |
| `timesheet_grid_holidays` | `project_timesheet_holidays`, `timesheet_grid` | auto-install; [__manifest__.py:12](../enterprise/timesheet_grid_holidays/__manifest__.py#L12) |

---

## Gotchas & Non-Obvious Behavior

- **The leave bridge punches through validation.** Leave/public-holiday lines are created, rewritten and deleted in sudo ([hr_leave.py:72-78](../addons/project_timesheet_holidays/models/hr_leave.py#L72)), which bypasses the locks. Standard validation can validate these generated lines, then regeneration deletes them without recalculating the employee's last validated date. A payroll bridge must exclude them from payroll **and validation**, plus repair existing validated lines/cut-offs.
- **`validated` is reversible and history is soft.** Un-validation is one click for the right approver and recomputes the lock date backwards; a payroll consumer must not treat `validated = True` at time T as permanent (§8).
- **"Today" pierces the period lock.** `check_if_allowed` always allows lines dated exactly today, even when today ≤ `last_validated_timesheet_date` ([account_analytic_line.py:338-339](../enterprise/timesheet_grid/models/account_analytic_line.py#L338)). An employee can add hours *inside* an already-validated period as long as they do it on that same day. In v20 "today" is the user's timezone, so the escape window differs per user.
- **Validation lock ≠ line lock.** New *draft* lines dated before the lock are blocked too — the lock covers the whole period, not just validated records. Conversely, drafts dated after the lock stay editable indefinitely.
- **`user_can_validate` still lies about project managers.** The compute returns True for a line whose `project_id.user_id` is the current user ([account_analytic_line.py:195-207](../enterprise/timesheet_grid/models/account_analytic_line.py#L195)), but `action_validate_timesheet`'s domain never looks at `project_id.user_id` — the button shows, then the action answers "not part of your team". **Changed in 20:** the own-lines half of this mismatch was partly fixed — an approver who is their own timesheet approver (or whose manager is themselves) can now genuinely validate their own lines (§4). Everyone else still cannot, and only `group_timesheet_manager` can validate arbitrary own lines.
- **Future lines cannot be validated** through the ordinary approver branch (`date <= today`) — relevant for pre-filled schedules. The v20 self-approval branch is the exception.
- **Grid edits on validated cells silently fork.** Adding time in a cell whose only line is validated `copy()`s a new draft line ([account_analytic_line.py:406-411](../enterprise/timesheet_grid/models/account_analytic_line.py#L406)) — the cell total mixes one validated and one draft line afterwards.
- **Merging destroys line IDs** (new record, originals unlinked). Any external reference (e.g. a payslip claim table) must handle this before validation, or only reference validated lines (which can't be merged).
- **`amount` is a cost, and it's recomputed.** `-unit_amount × hourly_cost` refreshes on every unit_amount/employee/account write, in sudo, even on validated lines when an approver edits — do not read `amount` as remuneration.
- **Employee resolution can hard-fail imports.** Batch creates without `employee_id` fail with `ValidationError` when the user has several employees across selected companies and no `company_id` in vals disambiguates (§1). Archived employees are always rejected.
- **UoM trap.** Day-encoding changes only the widget; `unit_amount` stays in hours (via `project_time_mode_id`). Summation code must not multiply by encoding factors — `_compute_total_timesheet_time` shows the correct conversion dance ([project_project.py:149-170](../addons/hr_timesheet/models/project_project.py#L149)).
- **Leave counted as working time produces no timesheets** — the switch is `work_entry_type_id.count_as` on the leave, not a leave-type flag (§5), and the settings help text about per-leave-type projects is stale.
- **Fully-flexible employees get no leave timesheets at all** ([hr_leave.py:41-42](../addons/project_timesheet_holidays/models/hr_leave.py#L41)) — new in v20, and easy to mistake for a generation bug. Same for employees with no timezone.
- **The favorite project no longer falls back to Internal** — a fresh employee's first timesheet form opens with an empty project (§2).
- **Uninstalling `timesheet_grid` drags down `hr_timesheet` and `sale_timesheet`** ([ir_module_module.py:9-16](../enterprise/timesheet_grid/models/ir_module_module.py#L9)), reactivates the community user access row and deactivates the Timesheets root menu ([__init__.py:17-49](../enterprise/timesheet_grid/__init__.py#L17)).
- **Approvers lose the "My Timesheets" root menu item** — it's blacklisted for them because they get the fuller Timesheets submenu ([ir_ui_menu.py:9-13](../addons/hr_timesheet/models/ir_ui_menu.py#L9)).
- **Employees with timesheets can't be deleted, only archived** — the delete wizard forces the termination flow for non-approvers ([hr_employee.py:52-57](../addons/hr_timesheet/models/hr_employee.py#L52), [hr_employee_delete_wizard.py](../addons/hr_timesheet/wizard/hr_employee_delete_wizard.py)).
- **Calendar-view creates silently drop non-working days** — batch creation from the calendar skips days outside the employee's work intervals with only a bus toast ([account_analytic_line.py:235-246](../addons/hr_timesheet/models/account_analytic_line.py#L235)).
- **Timesheet portal visibility narrowed in 20.** `message_partner_ids` on a line now mirrors the **task's** followers only; project followers no longer grant visibility ([account_analytic_line.py:85-100](../addons/hr_timesheet/models/account_analytic_line.py#L85)). Portal domains built on follower-ship behave differently than in v19.

## Files not covered (pure UI / infra)

`account_analytic_line_calendar_employee.py` (calendar-view employee filter prefs), `analytic_applicability.py`, `ir_http.py` + `controllers/project.py` (UoM info into session for JS widgets), `uom_uom.py` (widget name per UoM), `hr_employee_public.py` (both modules — related field mirrors), `project_update.py` (snapshot of allocated/timesheeted time in project updates), `hr_timesheet/report/project_report.py` (task-analysis SQL columns), `timesheet_grid/models/timesheet_grid_mixin.py` (planned-vs-worked widget data for grid/gantt progress bars — inspected, pure presentation, no bearing on validation or locks), `timesheet_grid/models/hr_department.py` and the `aw.rule` cleanup branches in `timesheet_grid/models/project_project.py` (company-change hygiene for assistant rules), `timesheet_grid/models/res_groups.py`, all `static/src` assets (including the whole `aw_timesheet` assistant UI), `data/mail_template_data.xml` (reminder mail bodies), `data/aw_rule_data.xml` (shipped assistant rules), `data/digest_data.xml`, `data/web_tour_data.xml`.

## Adjacent modules (other clusters, not documented here)

`hr_timesheet_attendance` (auto-installed report comparing timesheets vs attendances, [manifest](../addons/hr_timesheet_attendance/__manifest__.py)); `sale_timesheet`, `sale_timesheet_enterprise`(+`_holidays`), `sale_timesheet_margin`, `sale_subscription_timesheet` (billing side, incl. billed-at-validation policy); `helpdesk_timesheet`, `helpdesk_sale_timesheet`; `project_timesheet_forecast`(+`_sale`); `website_timesheet`; `spreadsheet_dashboard_*_timesheet`.

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`payroll_wage_types.md`](payroll_wage_types.md) — §7 row 7 + §9.7: how a salary rule consumes these lines; §8.3 verified constraints kept consistent here
- [`work_entries.md`](work_entries.md) — the parallel "what did this employee do on this day" record that actually feeds payroll; note `hr.work.entry` no longer exists in Odoo 20, so check that doc before mapping anything across
- [`hr_payroll.md`](hr_payroll.md) — payslip engine that would consume the bridge output
- [`hr_holidays_time_off_units.md`](hr_holidays_time_off_units.md) / [`hr_holidays_accrual_plans.md`](hr_holidays_accrual_plans.md) — leave side of the §5 bridge
- [`resource_calendars.md`](resource_calendars.md) — work intervals used by leave-line generation and reminder math
- [`attendance_work_entry.md`](attendance_work_entry.md) — the attendance alternative for actual-hours pay
- [`hr_employee_versions.md`](hr_employee_versions.md) — where pay rates actually live, and the `_get_version` lookup the leave bridge now uses
- [`analytic_accounting.md`](analytic_accounting.md) — the base `account.analytic.line` model timesheets extend

# HR Appraisal

> **Module:** `hr_appraisal` (+ `hr_appraisal_skills`, `hr_appraisal_survey`, `spreadsheet_dashboard_hr_appraisal`) | **Path:** [`enterprise/hr_appraisal/`](../enterprise/hr_appraisal/)
> **Enterprise only** — all four modules ship `license: OEEL-1` and live under `enterprise/`, confirmed in each `__manifest__.py`. Not available on Community.
> **Verified against Odoo 20.0.** Sections marked *Changed in 20.0* differ from 19.0 behaviour.

## What It Does & Why It Exists

Performance review workflow: one `hr.appraisal` record per review cycle per employee, carrying a self-assessment (employee) and a manager assessment side by side, a final rating, a meeting-scheduling shortcut, and optional linked development goals. Used by managers/HR to run periodic reviews and by employees to submit self-feedback. `hr_appraisal_skills` bolts a skills-tracking tab onto the same record so a review cycle can also update the employee's official skill levels. `hr_appraisal_survey` adds an optional 360°-feedback survey layer (colleagues answering a questionnaire about the employee) — separate from, and not required by, the core flow.

---

## The Big Picture — How It Works

```
                  Confirm                 Mark as Done
Draft (1_new) ------------> Ongoing (2_pending) ------------> Done (3_done)
      ^  |                        ^   |                             |
      |  auto-fills dept/job/     |   |                             |
      |  manager from employee    |   +- both sides write feedback  |
      |                           |      in parallel, share when    |
      +------- Reset -------------+      ready, manager schedules   |
                                  |      a meeting                  |
                                  |                                 |
                                  +- confirm email to employee      |
                                  |  + managers                     |
                                  |                                 |
                                  +---------- Reopen ---------------+

Done = record frozen server-side, both feedbacks force-published,
       skills written back to the employee, next-cycle date posted
```

The three states are unchanged in 20.0 (`1_new` / `2_pending` / `3_done`, [hr_appraisal.py:58-63](../enterprise/hr_appraisal/models/hr_appraisal.py#L58-L63)), but the transitions around Done are new:

- **Changed in 20.0 — Done is a real lock, not a convention.** `_check_write_access()` raises `AccessError("You cannot modify a finished appraisal.")` on any write to a `3_done` record unless that write is exactly the reopen ([hr_appraisal.py:143-169](../enterprise/hr_appraisal/models/hr_appraisal.py#L143-L169)). In 19 a Done appraisal was only readonly through view attributes.
- **Changed in 20.0 — Reopen.** A `Reopen` button sends Done back to Ongoing ([hr_appraisal.py:662-663](../enterprise/hr_appraisal/models/hr_appraisal.py#L662-L663)); `Reset` still sends Ongoing back to Draft and clears the Final Rating ([hr_appraisal.py:637-660](../enterprise/hr_appraisal/models/hr_appraisal.py#L637-L660)).
- **Changed in 20.0 — Confirm / Mark as Done / Reset work in bulk.** They are also `ir.actions.server` records bound to the list and kanban views ([hr_appraisal_views.xml:239-288](../enterprise/hr_appraisal/views/hr_appraisal_views.xml#L239-L288)), and the methods skip records already in another state and report that in a notification instead of failing.

Three ways a record is created:
1. **Manual**: someone opens Appraisals → New, or clicks **Request Appraisal** on an employee's form ([hr_employee.py:36-47](../enterprise/hr_appraisal/models/hr_employee.py#L36-L47)). Starts in Draft (`1_new`). `manager_ids` defaults to the acting user ([hr_appraisal.py:64-70](../enterprise/hr_appraisal/models/hr_appraisal.py#L64-L70)), then an onchange resets it to `employee_id.parent_id` once an employee is picked — and re-adds the acting user if they are an indirect manager ([hr_appraisal.py:333-342](../enterprise/hr_appraisal/models/hr_appraisal.py#L333-L342)).
2. **Automatic** — a daily cron (`_run_employee_appraisal_plans`) creates records **directly in Ongoing**, per employee, when that employee's `next_appraisal_date` has arrived ([res_company.py:67-79](../enterprise/hr_appraisal/models/res_company.py#L67-L79)).
3. **Bulk campaign** — the **Launch Campaign** wizard, triggered by a person (see Scenario 1).

Once Ongoing, employee and manager can both write their feedback **at the same time** — nothing in the state machine forces one to go first. What's gated is *visibility*: the manager only sees the employee's real text once the employee flips **Shared to Appraisers** on (a toggle, not a submit button); same in reverse for **Shared to Employee** ([hr_appraisal_views.xml:98-168](../enterprise/hr_appraisal/views/hr_appraisal_views.xml#L98-L168)). Until shared, the other side sees a blurred template preview instead of the real text.

The blur is not cosmetic: `employee_feedback` and `manager_feedback` carry `groups="hr_appraisal.group_hr_appraisal_user"`, and the form actually binds to computed proxy fields `accessible_employee_feedback` / `accessible_manager_feedback` that return the literal string `"Unpublished"` to anyone not entitled to read the real text, and raise `AccessError` on a write from the wrong side ([hr_appraisal.py:416-444](../enterprise/hr_appraisal/models/hr_appraisal.py#L416-L444)).

A manager (not the employee) can also schedule a meeting straight from the record — this opens the standard Calendar app pre-filled with both parties as attendees, it does not create the event by itself ([hr_appraisal.py:587-599](../enterprise/hr_appraisal/models/hr_appraisal.py#L587-L599)).

**Changed in 20.0 — Mark as Done no longer requires a Final Rating.** `action_done()` is now a plain `self.state = '3_done'` ([hr_appraisal.py:634-635](../enterprise/hr_appraisal/models/hr_appraisal.py#L634-L635)); the 19 behaviour (skip the records without an `assessment_note` and show a sticky red notification listing them) is gone. Reaching Done still force-publishes both feedback sides and computes/announces the next automatic appraisal date ([hr_appraisal.py:466-504](../enterprise/hr_appraisal/models/hr_appraisal.py#L466-L504)).

### Key Decision Points
- **Manual vs. automatic creation:** manual = one person picks one employee, starts in Draft, no email until Confirmed. Automatic (cron) = starts directly in Ongoing, confirm email fires immediately. Campaign = Ongoing for everyone except the acting user's own appraisal, which is left in Draft.
- **Sharing feedback:** a toggle field per side, not a workflow gate — either party can keep typing after sharing; sharing only affects what the *other* person can see. **Changed in 20.0:** both toggles now default to `False` (19 defaulted to `True`), so feedback starts private and has to be deliberately shared.
- **Final rating:** a configurable Many2one (`hr.appraisal.note`), not a hardcoded list — Configuration → Evaluation Scale can add/remove/reorder tiers. Optional since 20.0.

---

## When to Use It (and When Not To)

### This module is for:
- Periodic 1:1 performance reviews with a written record, a rating, and an optional meeting log.
- Organizations that want employee self-assessment and manager assessment to coexist on one record before a rating is set.
- Tracking a small number of ongoing development goals per employee alongside reviews.

### Use something else when:
- You need every employee's review cycle to start on **one shared calendar date, automatically, every year** — the built-in automatic plan is per-employee (based on contract start / last-review date + a month interval), not calendar-anchored. See Gotchas.
- You need **colleague/peer 360° input** as a first-class, required part of every cycle — `hr_appraisal_survey` exists but is a bolt-on survey, not integrated into the state machine or the Feedback tab.
- You need a real exportable PDF appraisal document — there's no QWeb/report engine here, only a browser print stylesheet (see Gotchas).
- You need a written history of *how a skill moved at each review*. 20.0 replaced the appraisal-diff report with a time series built from the employee's skill validity intervals, which is better for trends but no longer tied to appraisals at all (see Gotchas).

---

## Real-World Scenarios

### Scenario 1: HR runs an annual review cycle for the whole company
**Situation:** HR wants every employee reviewed around the same time each year, not staggered by hire date.
**What they do:** Appraisals → **Launch Campaign**, leave **Employees** empty (= everyone they are allowed to see), pick a manager rule, an appraisal template and one shared `appraisal_date`. Odoo creates one `hr.appraisal` per employee, all sharing that date ([hr_appraisal_campaign_wizard.py:74-114](../enterprise/hr_appraisal/wizard/hr_appraisal_campaign_wizard.py#L74-L114)).
**What happens:** All confirm emails and "Appraisal to fill" activities fire the same day. This has to be triggered by a person each cycle — it is not a recurring schedule by itself.

**Changed in 20.0 — the campaign wizard was simplified and made safer:**
- The `mode` selector (*By Employee / By Company / By Department / By Employee Tag*) is **gone**. There is now one employee picker; empty means "every employee in `_employees_domain()`", which for a non-officer is only their own subtree ([hr_appraisal_campaign_wizard.py:32-37](../enterprise/hr_appraisal/wizard/hr_appraisal_campaign_wizard.py#L32-L37)).
- Employees who already have an appraisal on that date with those managers are **reused, not duplicated**, and the wizard warns about it up front ([hr_appraisal_campaign_wizard.py:58-72](../enterprise/hr_appraisal/wizard/hr_appraisal_campaign_wizard.py#L58-L72)).
- Everyone gets an appraisal in Ongoing **except the person launching the campaign**, whose own appraisal is left in Draft so they are not auto-notified about themselves ([hr_appraisal_campaign_wizard.py:93-112](../enterprise/hr_appraisal/wizard/hr_appraisal_campaign_wizard.py#L93-L112)).

### Scenario 2: Standard per-employee automatic cycle
**Situation:** A new hire should get their first review some months after joining, then annually after that, with no one having to remember.
**What they do:** Nothing, once Settings → Appraisal → Appraisals Automation is on (default). The employee's `next_appraisal_date` is computed from the contract start date + `duration_after_recruitment` (default 6 months), then + `duration_first_appraisal` for the second review, then + `duration_next_appraisal` (default 12 months) for every one after ([res_company.py:20-22](../enterprise/hr_appraisal/models/res_company.py#L20-L22), [hr_employee.py:141-159](../enterprise/hr_appraisal/models/hr_employee.py#L141-L159)).
**What happens:** A daily cron creates each employee's next appraisal on their own schedule — two employees hired on different dates get reviewed on different dates, permanently staggered.

### Scenario 3: Manager updates an employee's skill levels during a review
**Situation:** During the review, the manager decides the employee's level in a skill has changed.
**What they do:** Opens the Skills tab (only visible once Ongoing, and only visible to the manager while Ongoing — see Gotchas), edits the level, optionally types a reason in the `justification` column.
**What happens:** When the appraisal became Ongoing, `_copy_skills_when_confirmed()` snapshotted the employee's current skills onto the appraisal ([hr_appraisal.py (skills module):117-133](../enterprise/hr_appraisal_skills/models/hr_appraisal.py#L117-L133)). Edits stay on that snapshot until **Mark as Done**, at which point they're written back to the employee's real skill records, added skills are created, removed ones deleted, and a rendered summary of every level change (with justification) is posted to the chatter ([hr_appraisal.py (skills module):73-113](../enterprise/hr_appraisal_skills/models/hr_appraisal.py#L73-L113)).

**Changed in 20.0:** the snapshot is also taken when an appraisal is *created* directly in Ongoing — cron and campaign records ([hr_appraisal.py (skills module):53-62](../enterprise/hr_appraisal_skills/models/hr_appraisal.py#L53-L62)). In 19 only the Draft→Ongoing write triggered it, so automatically created appraisals opened with an empty Skills tab.

Setting a **Target Job** on the appraisal pulls that job's required skills into the tab as rows with no level, so the gap is visible; the column is readonly for the employee and hidden from them entirely when unset ([hr_skills_views.xml:9-10](../enterprise/hr_appraisal_skills/views/hr_skills_views.xml#L9-L10)).

---

## How Things Work Under the Hood

### Core Logic
- **`_run_employee_appraisal_plans()`** ([res_company.py:67-79](../enterprise/hr_appraisal/models/res_company.py#L67-L79)) — the daily cron; finds every employee whose `next_appraisal_date` has passed and creates their next appraisal directly in Ongoing.
- **`write()`** state-transition side effects ([hr_appraisal.py:466-504](../enterprise/hr_appraisal/models/hr_appraisal.py#L466-L504)) — moving to Ongoing resets both publish flags to `False` and re-sends the confirm email; moving to Done force-publishes both sides, posts the next-appraisal-date notice, and notifies every follower.
- **`_check_write_access()` / `_check_create_access()`** ([hr_appraisal.py:119-169](../enterprise/hr_appraisal/models/hr_appraisal.py#L119-L169)) — **new in 20.0.** A per-field write guard on top of the record rules. `assessment_note`, `note`, `manager_feedback_published` and `state` are in `_write_manager_only_fields()` ([hr_appraisal.py:107-117](../enterprise/hr_appraisal/models/hr_appraisal.py#L107-L117)): an employee writing any of them on their own appraisal gets an `AccessError` naming the field, and no one can write to a Done record except to reopen it. This closes the RPC hole where the 19 UI restrictions could simply be bypassed.
- **`read()` override** ([hr_appraisal.py:568-585](../enterprise/hr_appraisal/models/hr_appraisal.py#L568-L585)) — when the reading user is the appraisal's own employee, `note` (Private Note) and `assessment_note` (Final Rating) are scrubbed from the payload server-side, regardless of view. This is real field-level security, not just a hidden tab. **Changed in 20.0:** the redacted set is now `_read_manager_only_fields()`, both fields come back as `False` (19 replaced the Private Note with the literal string `"Note"`), the check covers *all* of the user's employee records rather than the primary one, and it handles the tuple shape the JSON-2 API returns.
- **`action_calendar_event()`** ([hr_appraisal.py:587-599](../enterprise/hr_appraisal/models/hr_appraisal.py#L587-L599)) — opens the standard Calendar app pre-filled with employee + managers + acting user as attendees; no `calendar.event` exists until the user actually saves one.

### Important Fields
- `state` (`1_new`/`2_pending`/`3_done`) — drives almost every `readonly`/`invisible` condition in the form, and since 20.0 the server-side write guard too.
- `employee_feedback_published` / `manager_feedback_published` — toggles, not approvals. **Default `False` since 20.0** (was `True` in 19), and reset to `False` again on every entry into Ongoing. Either side can turn their own off to keep working privately; a manager can force-publish the employee's (logged to chatter) via a confirm dialog ([boolean_confirm.js:34-52](../enterprise/hr_appraisal/static/src/fields/boolean_confirm.js#L34-L52)).
- `accessible_employee_feedback` / `accessible_manager_feedback` — the fields the form actually shows. Read as `"Unpublished"` and refuse writes when the current user isn't the owning side ([hr_appraisal.py:416-444](../enterprise/hr_appraisal/models/hr_appraisal.py#L416-L444)).
- `assessment_note` (Final Rating) — Many2one to `hr.appraisal.note`, configurable, optional since 20.0, never visible or readable by the employee themself.
- `next_appraisal_date` — related to the employee, editable directly on a Done appraisal; lets a manager override the computed next-cycle date for that one employee.
- `appraisal_template_id` — picks which HTML feedback skeleton both sides start from, defaulted from the department/company and re-defaulted on department change, but a generic template deliberately chosen on a saved record is kept ([hr_appraisal.py:288-316](../enterprise/hr_appraisal/models/hr_appraisal.py#L288-L316)).

---

## Configuration & Settings

- **Appraisals Automation** (Settings → Employees → Appraisal, `appraisal_plan`, default on) — master switch for the daily automatic-creation cron. Off = nothing is ever auto-created; every appraisal needs a manual New or a Launch Campaign.
- **Appraisals Plans** (`duration_after_recruitment` / `duration_first_appraisal` / `duration_next_appraisal`, months, defaults 6/6/12) — controls the per-employee stagger described above. There is no setting anywhere that turns this into "same calendar date for everyone" ([res_config_settings.py:13-15](../enterprise/hr_appraisal/models/res_config_settings.py#L13-L15)).
- **Evaluation Scale** (Appraisals → Configuration → Evaluation Scale, `hr.appraisal.note`, Administrator-only) — add/remove/reorder the Final Rating options. Shipped defaults, seeded per company on company creation: Needs improvement, Meets expectations, Exceeds expectations, Strongly Exceed Expectations ([res_company.py:29-45](../enterprise/hr_appraisal/models/res_company.py#L29-L45)) — the note has no color or weight field, just a name, a sequence and a company.
- **Appraisal Plans** (Appraisals → Configuration → Appraisal Plans) — **new in 20.0.** `mail.activity.plan` records scoped to `hr.appraisal`, so a whole checklist of activities ("Mid-Year Review", "Annual Appraisal", …) can be dropped on an appraisal in one click ([mail_activity_plan_views.xml](../enterprise/hr_appraisal/views/mail_activity_plan_views.xml)). Unrelated to the `appraisal_plan` automation switch above, despite the name.

---

## Dependencies

| Requires | Why |
|---|---|
| `hr`, `calendar`, `mail`, `hr_gantt` (Enterprise) | employee/department data, meeting scheduling, activities/notifications, the Gantt reporting view |

| Works With (optional) | What It Adds |
|---|---|
| `hr_appraisal_skills` | Skills tab on the appraisal, Target Job gap analysis, skill-linked goals, org-wide Skills Evolution report. `auto_install` |
| `hr_appraisal_survey` | Optional 360°-feedback survey per appraisal (Community `survey` engine underneath). `auto_install`, also toggled by the **360 Feedback** setting |
| `spreadsheet_dashboard_hr_appraisal` | **New in 20.0.** Auto-installed with `hr_appraisal`; ships a read-only "Employee" spreadsheet dashboard over `hr.appraisal`, visible to the Appraisal Administrator group only ([dashboards.xml](../enterprise/spreadsheet_dashboard_hr_appraisal/data/dashboards.xml)) |

---

## Gotchas & Non-Obvious Behavior

- **No org-wide fixed-date automatic cycle.** The automatic plan is strictly per-employee and interval-based (contract start / last review + N months). "Everyone gets reviewed starting July 1st every year, automatically" is not configurable — the closest built-in equivalent is the **Launch Campaign** bulk wizard, which needs a human to trigger it each cycle and does support one shared date across many employees ([hr_appraisal_campaign_wizard.py:74-114](../enterprise/hr_appraisal/wizard/hr_appraisal_campaign_wizard.py#L74-L114)).
- **The confirm email doesn't fire on manual Draft creation.** `send_appraisal()` only runs when a record is created directly in Ongoing (cron/campaign, [hr_appraisal.py:398-414](../enterprise/hr_appraisal/models/hr_appraisal.py#L398-L414)) or when `write()` moves it Draft→Ongoing via the **Confirm** button ([hr_appraisal.py:482-485](../enterprise/hr_appraisal/models/hr_appraisal.py#L482-L485)). A manually created Draft that never gets confirmed never notifies anyone. Still true in 20.0.
- **The confirm email skips the "Appraisal Form to Fill" activity when the cron created the record.** `send_appraisal()` checks for a `from_cron` context key, set by the cron's server action, because `_generate_activities()` already schedules a richer activity for those ([hr_appraisal.py:388-396](../enterprise/hr_appraisal/models/hr_appraisal.py#L388-L396)). Campaign-created appraisals get the plain activity; cron-created ones get the "last appraisal was N months ago" one.
- **The Skills tab is not gated on "employee submitted feedback."** It's gated purely on `state` + role: hidden entirely in Draft; hidden **from the employee themself** during Ongoing (only the manager/officer sees it then); visible to everyone once Done ([hr_skills_views.xml:13](../enterprise/hr_appraisal_skills/views/hr_skills_views.xml#L13)). It's also `readonly` unless `state == '2_pending' and is_manager` ([hr_skills_views.xml:18](../enterprise/hr_appraisal_skills/views/hr_skills_views.xml#L18)) — **the employee can never edit their own skill level or justification through this tab; only the manager can, and only while Ongoing.** Unchanged in 20.0.
- **Goals don't belong to a review cycle.** `hr.appraisal.goal` has no `appraisal_id` and no link to any specific `hr.appraisal` — it attaches to `employee_ids` directly ([hr_appraisal_goal.py:18-21](../enterprise/hr_appraisal/models/hr_appraisal_goal.py#L18-L21)). The "Goals" button on an appraisal just opens every open, leaf-level goal the employee currently has, filtered by employee, not by cycle ([hr_appraisal.py:681-697](../enterprise/hr_appraisal/models/hr_appraisal.py#L681-L697)). There is no per-cycle snapshot of a goal's progress — the *same* record persists and shows up on every future appraisal until manually completed (`progression` forced to `100%`) or archived. Progress is a fixed 5-step bucket (0/25/50/75/100%), not a free-form percentage; a parent goal's displayed progress is the average of its children ([hr_appraisal_goal.py:117-132](../enterprise/hr_appraisal/models/hr_appraisal_goal.py#L117-L132)). Still true in 20.0.
- **Changed in 20.0 — the Skills Evolution report is no longer an appraisal diff.** The old `hr.appraisal.skill.report` (latest Done appraisal vs. its `previous_skill_level_id` snapshot, with green/red row decorations) was deleted. The replacement `hr.appraisal.skill.evolution.report` is a SQL view over `hr_employee_skill` validity intervals: for every distinct `valid_from`/`valid_to` date in the system it emits each active employee's level in each skill, giving a genuine multi-point time series in list/graph/pivot ([hr_appraisal_skill_evolution_report.py:22-70](../enterprise/hr_appraisal_skills/report/hr_appraisal_skill_evolution_report.py#L22-L70)). Two consequences: it now covers skill changes made **outside** appraisals too, and the per-row "improved / declined" color coding is gone in favour of an averaged progress measure. The action's help text still says "between the two latest appraisals" and is stale ([hr_appraisal_skill_evolution_report_views.xml:60-73](../enterprise/hr_appraisal_skills/report/hr_appraisal_skill_evolution_report_views.xml#L60-L73)).
- **No real PDF export.** The cog-menu "Print" just calls the browser's print dialog against a print stylesheet — there's no `ir.actions.report` anywhere in any of the appraisal modules, despite the manifest description implying a PDF form ([print_menu.js:11-13](../enterprise/hr_appraisal/static/src/component/print_menu.js#L11-L13)). Still true in 20.0.
- **Changed in 20.0 — indirect managers now have real record-level access.** The employee-picker domain still restricts a regular manager to their own subtree ([res_users.py:9-21](../enterprise/hr_appraisal/models/res_users.py#L9-L21)), but the record rule was widened and now grants create/read/write on any appraisal whose `employee_id` is `child_of` the user's employee records — not just the ones where they are listed in `manager_ids` ([ir.access.csv:3](../enterprise/hr_appraisal/security/ir.access.csv#L3)). In practice anyone above you in the org chart can open your appraisal, and the onchange still auto-adds the acting user to `manager_ids`. Managing appraisals org-wide as a matter of policy still means granting **Officer: Access all appraisals**.
- **Deleting is locked down almost everywhere.** Only Draft appraisals can be deleted at all (`@api.ondelete` guard, [hr_appraisal.py:563-566](../enterprise/hr_appraisal/models/hr_appraisal.py#L563-L566)) — this applies even to Administrators, and the access rules back it up: the only row granting `d` on `hr.appraisal` is the "delete new" rule restricted to the employee or their listed managers ([ir.access.csv:4-8](../enterprise/hr_appraisal/security/ir.access.csv#L4-L8)).
- **Registering a departure silently destroys in-flight appraisals.** `hr.employee.departure.action_register()` resets and then **unlinks** every Draft/Ongoing appraisal of the departing employee, strips them out of `manager_ids` on other people's appraisals (posting a chatter note), and archives any goal held solely by them ([hr_employee_departure.py:9-34](../enterprise/hr_appraisal/models/hr_employee_departure.py#L9-L34)). **Changed in 20.0:** in 19 this lived in the `hr.departure.wizard`; it is now on the `hr.employee.departure` model, so it fires from any departure registration path.
- **Changed in 20.0 — the dead `_create_multi_appraisals` server action is gone.** The 19 tree shipped a "Request Appraisals" server action on `hr.employee` calling a method that did not exist, raising `AttributeError`. It was removed upstream; a full-tree grep for `_create_multi_appraisals` in 20.0 returns nothing. Bulk creation now goes through **Launch Campaign** only.
- **Changed in 20.0 — 360 feedback can be requested from any partner.** `appraisal.ask.feedback` swapped `employee_ids` for `partner_ids`, so external reviewers (customers, contractors) can be asked, and re-sending to the same partner updates the existing `survey.user_input` deadline instead of creating a duplicate answer ([appraisal_ask_feedback.py:92-109](../enterprise/hr_appraisal_survey/wizard/appraisal_ask_feedback.py#L92-L109)). The mirror field on the appraisal is now `partner_feedback_ids` ([hr_appraisal.py (survey module):10](../enterprise/hr_appraisal_survey/models/hr_appraisal.py#L10)). The deadline also no longer gets a free +1 day and no longer caps at one month out — it is simply the appraisal's close date ([appraisal_ask_feedback.py:83-86](../enterprise/hr_appraisal_survey/wizard/appraisal_ask_feedback.py#L83-L86)).

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`hr_employee_versions.md`](hr_employee_versions.md) — employee/manager/department data this module reads from

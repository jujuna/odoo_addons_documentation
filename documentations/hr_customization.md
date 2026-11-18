# HR Customization (Alta) (`hr_customization`)

> **Module:** `hr_customization` 20.0.1.0.0 | **Path:** [`custom_addons/alta_hr_customization/hr_customization/`](../custom_addons/alta_hr_customization/hr_customization/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

Alta hires through Odoo Recruitment but does not want candidates to sign contracts in the salary configurator. This module turns the candidate's offer page into a plain **Accept / Reject** decision on fixed terms. The candidate fills in personal data (ID document, bank account, pension-fund membership); accepting stores an archived employee and contract version for HR, and tells the recruiter, the team leader and the lawyer. The lawyer then prepares the real contract outside Odoo.

Around that flow it adds:

- **Contract and trial expiry warnings** 7 days ahead, by daily cron.
- **Team leader visibility**: read-only contract history, validated payslips and attendances of the leader and their direct reports, without HR Officer rights.
- **Timesheet time history**: every change of a timesheet's hours is logged, plus an employee self-validation flag.
- **Smaller UI changes**: a Knowledge welcome email for new users, Knowledge articles linked to departments, job responsibilities on the website, resume and certifications visible only to the manager and the employee, a wrapping department chart, and *Pending Start* / *Left Company* employee filters.

---

## The Big Picture — Candidate Offer

```
Recruiter: Generate Offer on the applicant  -->  Send by Email (tokenized link)
                                                        |
                                                        v
Candidate page: "Employment Offer" card (fixed terms, configurator hidden)
        + personal info (ID document, bank account, pension fund)
        |
        +--> Accept --> /hr_customization/offer/accept
        |                 lock offer, rebuild terms on the server, validate personal info
        |                 --> archived employee + archived version "Accepted offer - <name>"
        |                 --> offer state Accepted (terminal), mails: recruiter + team leader, lawyer (details)
        |
        +--> Reject --> /hr_customization/offer/reject --> offer Refused, mails to all three
```

The decision is terminal. Nothing is activated on accept: the applicant stays in their stage, and the employee and version stay archived until HR activates them after the real contract is signed.

### Key Decision Points
- **Applicant offer or employee offer?** Every override keys off `applicant_id`. Offers to existing employees keep the standard configurator and sign flow.
- **Who is notified?** The applicant's recruiter (`recruiter_id` is an employee; its user gets the mail), team leader and lawyer. The lawyer defaults from the company setting.

---

## When to Use It (and When Not To)

### This module is for:
- Alta recruiters and HR officers who send fixed-term offers and need a clean yes/no from the candidate with verified personal data.
- Team leaders who must see their team's contract history, payslips and attendances without HR rights.
- Managers who need to know when a timesheet's hours were changed and by whom.

### Use something else when:
- **The candidate should negotiate benefits or sign in Odoo**: use the standard `hr_contract_salary` configurator and Sign flow (employee offers still use it).
- **Timesheets need manager approval**: that is `timesheet_grid` validation; this module's employee flag is separate from it.

---

## Real-World Scenarios

### Scenario 1: A candidate accepts an offer
**Situation:** A recruiter at Alta has an applicant for a sales role with a lawyer and team leader set on the applicant.
**What they do:** Generate the offer, **Send by Email**. The candidate opens the link, reads position, gross wage, contract period and validity, uploads an ID document, enters a bank account number and clicks **Accept Offer**.
**What happens:** The server takes every term from the offer, not from the form, validates the personal data and creates an archived employee and an archived version named "Accepted offer - <name>". The offer becomes *Accepted*. Recruiter and team leader get a short notice; the lawyer gets the version with wage, yearly cost and dates, asking to prepare the employment contract. The employee is flagged *Pending Start*.

### Scenario 2: A team leader checks a payslip
**Situation:** A team leader with the group *Team Leader: Own Team Only* wants to see last month's net pay of a direct report.
**What they do:** Open the report's employee card (the public card) and the **Payroll** tab.
**What happens:** A read-only list shows the report's validated and paid payslips: name, period, net wage and state. Drafts and other teams stay hidden.

### Scenario 3: Someone edits a timesheet's hours
**Situation:** A project manager corrects an employee's 8 h entry to 6 h.
**What they do:** Nothing special; they edit the line.
**What happens:** A history row records who changed it, when, 8 → 6 and the -2 difference. Anyone who can read the timesheet can click **History** on the row.

---

## How Things Work Under the Hood

### Candidate offer

- **Send by Email** ([hr_contract_salary_offer.py:44](../custom_addons/alta_hr_customization/hr_customization/models/hr_contract_salary_offer.py#L44)) puts `mark_offer_as_sent` in the composer context; the `message_post` override then logs "Employment offer sent to X by email". The applicant mail template of `hr_contract_salary` is overridden with a plain "Review employment offer" body.
- **Candidate page** ([hr_contract_salary_templates.xml](../custom_addons/alta_hr_customization/hr_customization/views/hr_contract_salary_templates.xml)) — for applicant offers: an "Employment Offer" card with the fixed terms and a hidden `is_applicant_offer` input, the benefit configurator and sidebar hidden with `d-none`, the core submit button limited to non-applicant offers, and **Accept Offer / Reject Offer** inside the personal-info block. The backend offer form hides the Sign template field and the "No PDF templates" alert for applicant offers. An accepted or cancelled offer renders "Offer closed" instead of the page ([offer.py:37](../custom_addons/alta_hr_customization/hr_customization/controllers/offer.py#L37)).
- **Accept** ([offer.py:139](../custom_addons/alta_hr_customization/hr_customization/controllers/offer.py#L139)), called by a patch of `SalaryPackage.submitSalaryPackage` ([offer_decision.js:17](../custom_addons/alta_hr_customization/hr_customization/static/src/interactions/offer_decision.js#L17)):
  1. Token check with `consteq`, `try_lock_for_update()` and a re-read of the state: only open, unexpired, non-simulation applicant offers pass, so a double accept or reject is locked out ([offer.py:19](../custom_addons/alta_hr_customization/hr_customization/controllers/offer.py#L19)). Simulation offers are refused as core `submit` refuses them ([main.py:1332](../enterprise/hr_contract_salary/controllers/main.py#L1332)).
  2. The simulation runs inside `hr_version_context(request, invalidate=True)` and is rolled back ([hr_version.py:82](../enterprise/hr_contract_salary/utils/hr_version.py#L82)). The offer is browsed again inside the block, because `_get_version()` refuses to run outside it; the version values come from core `_compute_submit()`.
  3. **Server-side terms lock** ([offer.py:50](../custom_addons/alta_hr_customization/hr_customization/controllers/offer.py#L50)): the whole `version` section is built on the server: configurable benefit values, every rule-based benefit of the structure (core sets their payroll properties from this section and writes 0 for a missing key, [main.py:1128](../enterprise/hr_contract_salary/controllers/main.py#L1128)), wage and yearly cost; job title, job and department too. Only the personal-info sections (`employee`, `version_personal`, `address`, `bank_account`) come from the form.
  4. Validation ([offer.py:120](../custom_addons/alta_hr_customization/hr_customization/controllers/offer.py#L120)): required personal infos (skipping children hidden by their parent answer), a valid private email, an ID document and a bank account number, unless the employee already has them.
  5. Core `create_new_version()` creates the archived employee (for a new person) and the archived version, with `originated_offer_id` set to this offer ([main.py:683](../enterprise/hr_contract_salary/controllers/main.py#L683)). It gets only `package_submit=True`, never the browser's parameters: core would otherwise take `date_version` from a `version_start_date` in the page URL ([main.py:930](../enterprise/hr_contract_salary/controllers/main.py#L930)). The module names the version, links the applicant, stamps recruiter user, team leader and lawyer on the employee, sets `pending_activation`, and marks the offer *Accepted* with `accepted_date` and `accepted_version_id`.
  6. Mails and a chatter note on the offer and the applicant ([hr_contract_salary_offer.py:21](../custom_addons/alta_hr_customization/hr_customization/models/hr_contract_salary_offer.py#L21)).
- **Core Submit is closed for applicant offers** ([offer.py:176](../custom_addons/alta_hr_customization/hr_customization/controllers/offer.py#L176)) — the public `/salary_package/submit` route returns an error for any offer with an applicant, so the terms lock and validation above cannot be skipped by calling it directly. Employee offers go to core.
- **Reject** ([offer.py:183](../custom_addons/alta_hr_customization/hr_customization/controllers/offer.py#L183)) — core `action_refuse_offer` (its one post on the offer names the candidate) plus a notification to all three users and a note on the applicant. The thank-you page `/hr_customization/offer/<id>/<decision>` is token-gated and requires the matching state.
- **Terminal-state guards** — an accepted offer cannot be refused ([hr_contract_salary_offer.py:60](../custom_addons/alta_hr_customization/hr_customization/models/hr_contract_salary_offer.py#L60)) or deleted ([hr_contract_salary_offer.py:73](../custom_addons/alta_hr_customization/hr_customization/models/hr_contract_salary_offer.py#L73)). Archiving the applicant passes `skip_accepted_offer_refusal`, so it refuses only the other offers ([hr_applicant.py:12](../custom_addons/alta_hr_customization/hr_customization/models/hr_applicant.py#L12)).
- **The accepted snapshot survives sibling offers.** Refusing or deleting another offer of the same applicant removes only the archived versions that offer created ([hr_contract_salary_offer.py:645](../enterprise/hr_contract_salary/models/hr_contract_salary_offer.py#L645)). Core deletes the archived employee only when every offer of the applicant is deleted ([hr_contract_salary_offer.py:539](../enterprise/hr_contract_salary/models/hr_contract_salary_offer.py#L539)), which the delete guard prevents while the accepted offer exists.
- **Pending vs departed** — `pending_activation` is set on accept for a new, archived employee and cleared by any write that activates the employee ([hr_employee.py:16](../custom_addons/alta_hr_customization/hr_customization/models/hr_employee.py#L16)). It is an HR-only field (`groups="hr.group_hr_user"`, the core rule for fields not on `hr.employee.public`, [hr_employee.py:36](../addons/hr/models/hr_employee.py#L36)). The employee search gains **Pending Start** (archived, pending) and **Left Company** (archived, not pending), both HR-only.

### Expiry notifications (cron)

The daily cron `_cron_notify_upcoming_employment_expiry` ([hr_version.py:57](../custom_addons/alta_hr_customization/hr_customization/models/hr_version.py#L57)) looks at the version in force of each employee (`employee.version_id`) and mails each of its two deadlines, `contract_date_end` and `trial_date_end`, only when that deadline itself falls between today and today + 7 days. The markers `contract_expiry_notified_for` and `trial_expiry_notified_for` make it once per employee and date: after a send, the marker is written on every active version of the employee with the same date, and a version that already carries it is skipped, so sibling versions and a version created later for the same deadline do not mail again. Moving the date re-arms it. Older versions are skipped because `trial_date_end` is per version and may be stale there ([hr_employee.py:270](../addons/hr/models/hr_employee.py#L270)). Recipients are the recruiter, team leader and lawyer stamped on the employee at accept time, else the version's HR responsible ([hr_version.py:28](../custom_addons/alta_hr_customization/hr_customization/models/hr_version.py#L28)). Each version runs in its own savepoint.

### Team leader visibility

The group *Team Leader: Own Team Only* sits under the Payroll privilege and implies nothing ([hr_customization_security.xml:5](../custom_addons/alta_hr_customization/hr_customization/security/hr_customization_security.xml#L5)). Its rows in [`ir.access.csv`](../custom_addons/alta_hr_customization/hr_customization/security/ir.access.csv), all read-only, "own team" meaning the employee's user or the employee's manager's user is the current user:

| Model | Scope |
|---|---|
| `hr.version` | own team |
| `hr.payslip` | own team, states `validated` and `paid` only |
| `hr.attendance` | own team |
| `hr.employee.type` | all |

- **Field groups** ([hr_version.py:18](../custom_addons/alta_hr_customization/hr_customization/models/hr_version.py#L18)) — the group is added to eight `hr.version` fields: `date_version`, `contract_date_start`, `contract_date_end`, `employee_type_id`, `wage`, `wage_type`, `hourly_wage` and `attendance_based`. Each override repeats the core groups (HR Officer for the dates, HR Manager or Payroll Officer for the employee type, Payroll Officer for the wage fields, System, HR Manager or Payroll Officer for `attendance_based`) and adds the team-leader group.
- **Payslip form** — `name`, `allowed_version_ids` and `employee_version_ids_count` are non-stored computes that read HR-only fields, so the module computes them as superuser ([hr_payslip.py:7](../custom_addons/alta_hr_customization/hr_customization/models/hr_payslip.py#L7)). Without that, reading a payslip as a pure team leader fails.
- **UI** — "Contract History" and "Payroll" pages on the public employee card, shown to group members only when they are the employee or the employee's manager ([hr_employee_public_views.xml:18](../custom_addons/alta_hr_customization/hr_customization/views/hr_employee_public_views.xml#L18)). The lists are read-only and do not open records: contract history shows dates, job, department, employee type, schedule and wage; payroll shows name, period, net wage and state. The one2many fields on `hr.employee.public` carry the group too ([hr_employee_public.py:8](../custom_addons/alta_hr_customization/hr_customization/models/hr_employee_public.py#L8)), so non-members never receive them. Payslip lines (the rule breakdown) have no access row, so only the net amount is visible.

### Timesheet time history and employee validation

- **History** — a write that changes `unit_amount` on a timesheet line (a line with a project before or after the write) creates an `account.analytic.line.time.history` row with user, time, previous and new hours ([account_analytic_line.py:11](../custom_addons/alta_hr_customization/hr_customization/models/account_analytic_line.py#L11)). The row is created as superuser in the same transaction, so it rolls back with the change. Creating a line, or editing other fields, logs nothing; copies start with empty history; deleting a timesheet deletes its history.
- **Who sees it** — timesheet users read the history of timesheets they can read, through a `('timesheet_id', 'access', 'read')` row, plus a company restriction row. The **History** button sits on timesheet list rows and on a task's timesheet lines ([hr_timesheet_views.xml:20](../custom_addons/alta_hr_customization/hr_customization/views/hr_timesheet_views.xml#L20)).
- **Validated by Employee** — a flag on timesheet lines and a list action *Validate by Employee* ([hr_timesheet_views.xml:57](../custom_addons/alta_hr_customization/hr_customization/views/hr_timesheet_views.xml#L57)). Only the employee, their manager or a timesheet administrator can change it, and an employee cannot validate their own lines older than two months ([account_analytic_line.py:49](../custom_addons/alta_hr_customization/hr_customization/models/account_analytic_line.py#L49)). The check uses the values being written: a save that also changes the date or the employee is judged on the new date, and the user must be allowed on both the old and the new employee. Backdating a line that is already validated is not checked. It is independent of the `validated` flag of `timesheet_grid` ([account_analytic_line.py:27](../enterprise/timesheet_grid/models/account_analytic_line.py#L27)).

### Welcome email and other UI

- **Welcome email** — `knowledge.article` gets a `welcome_message` checkbox in the article top bar. `res.users.create` sends `mail_template_welcome_message` only when the user is created from an employee (`create_employee` or `create_employee_id`, the HR "Create User" path), the employee has a work email, and a flagged article exists ([res_users.py:8](../custom_addons/alta_hr_customization/hr_customization/models/res_users.py#L8)). The article is the most recently edited flagged one that the new user can read, searched as that user in that user's companies, not per department ([hr_employee.py:22](../custom_addons/alta_hr_customization/hr_customization/models/hr_employee.py#L22)); a flagged article the new user cannot open sends no mail. The mail is queued, so user creation does not wait for SMTP.
- **Knowledge and departments** — many2many `knowledge_article_department_rel`: tags in the article top bar and list, and a picker on the department form. Attaching from the department writes on the article, so Knowledge's own permissions apply.
- **Responsibilities** — `hr.job.responsibilities` (translatable HTML, own form tab) shows on the public vacancy page below the description.
- **Resume and certifications** — on the public employee card they are shown only to the direct manager and the employee ([hr_employee_public_views.xml:11](../custom_addons/alta_hr_customization/hr_customization/views/hr_employee_public_views.xml#L11)). UI only: core record rules on resume lines and skills still let every internal user read them.
- **Department chart** — the department hierarchy header (fixed at 30 px by `web_hierarchy`) gets the class `o_hr_department_node_header`, added to core's classes with `add=` ([hr_department_views.xml:23](../custom_addons/alta_hr_customization/hr_customization/views/hr_department_views.xml#L23)), and one SCSS rule on that class lets long names wrap. The employee org chart keeps core's 30 px header.

---

## Email Templates

Six templates; only one reaches a candidate. The four internal ones get their recipients from Python as `email_values={'email_to': ...}`, so their `email_to` field (`eval="False"`) is inert and editing it does nothing.

| XML ID | Model | Recipients | Trigger | Send |
|---|---|---|---|---|
| `hr_contract_salary.mail_template_send_offer_applicant` (overridden) | `hr.contract.salary.offer` | Applicant (core `use_default_to`) | Manual, **Send by Email** | Composer |
| `mail_template_offer_accepted` | `hr.contract.salary.offer` | Recruiter's user + team leader; lawyer separately | Candidate accepts | queued |
| `mail_template_offer_rejected` | `hr.contract.salary.offer` | Recruiter's user + team leader + lawyer | Candidate rejects | queued |
| `mail_template_contract_expiry` | `hr.version` | Stamped recruiter/team leader/lawyer, else HR responsible | Daily cron, 7 days before `contract_date_end` | queued |
| `mail_template_trial_expiry` | `hr.version` | same | Daily cron, 7 days before `trial_date_end` | queued |
| `mail_template_welcome_message` | `hr.employee` | `work_email` | User created for an employee | queued |

- **Candidate mail is an override, not a new record.** Only `name`, `description` and `body_html` are replaced ([mail_template_data.xml:93](../custom_addons/alta_hr_customization/hr_customization/data/mail_template_data.xml#L93)); subject, `use_default_to` and `lang` stay from enterprise. The tokenized link is built from the composer context (`offer_id`, `access_token`, `validity_end`), which core `action_send_by_email` fills ([hr_contract_salary_offer.py:558](../enterprise/hr_contract_salary/models/hr_contract_salary_offer.py#L558)).
- **One template, two audiences.** `_notify_offer_decision()` sends the accepted template twice: plain to recruiter and team leader, and with `show_offer_details=True` to the lawyer, which unlocks wage, yearly cost, dates and "prepare the employment contract" ([hr_contract_salary_offer.py:29](../custom_addons/alta_hr_customization/hr_customization/models/hr_contract_salary_offer.py#L29)). The body reads the flag as `ctx.get('show_offer_details')`; `ctx` is the rendering context ([mail_render_mixin.py:351](../addons/mail/models/mail_render_mixin.py#L351)). Rendering runs as superuser, which is required: the controller is public and the body reads group-restricted `wage`. The sender is the company partner, else the acting user.
- **Expiry sends are self-arming.** `_send_expiry_notification()` returns `False` when no recipient has an email, so the marker is never stamped and the cron retries every day with no chatter trace ([hr_version.py:45](../custom_addons/alta_hr_customization/hr_customization/models/hr_version.py#L45)).
- **Shared traits:** the five module-owned templates have no `lang` (rendered in the sender environment's language); `auto_delete` removes the sent mails, so the chatter notes are the only audit trail; the two mail-template files are not `noupdate`, so hand edits to these templates are reverted on every upgrade (the personal-info and cron files are `noupdate`).

---

## Configuration & Settings

- **Settings > Recruitment > Default Recruitment Lawyer** (`res.company.recruitment_lawyer_id`) — the lawyer new applicants get. The picker offers internal users of the settings company only. Saving the settings with a lawyer also fills every active lawyer-less applicant of that company, on every save; archived (refused) applicants are left alone ([res_config_settings.py:10](../custom_addons/alta_hr_customization/hr_customization/models/res_config_settings.py#L10)).
- **Personal-info questions** (`noupdate`) — a required ID-document upload ([hr_contract_salary_personal_info_data.xml:3](../custom_addons/alta_hr_customization/hr_customization/data/hr_contract_salary_personal_info_data.xml#L3)) and an optional "member of the pension fund" checkbox on `pension_fund_member` from `geo_payroll` ([hr_contract_salary_personal_info_data.xml:14](../custom_addons/alta_hr_customization/hr_customization/data/hr_contract_salary_personal_info_data.xml#L14)). The candidate types only the IBAN; for a Georgian IBAN, `gec_localization` (installed with `geo_payroll`) fills bank name and BIC.
- **Team leader access** — give users the Payroll privilege level *Team Leader: Own Team Only*.
- **Expiry cron** — daily, active, `noupdate` ([ir_cron_data.xml](../custom_addons/alta_hr_customization/hr_customization/data/ir_cron_data.xml)).

---

## Dependencies

| Requires | Why |
|---|---|
| `hr_contract_salary` (enterprise) | Offer model, candidate page, personal-info framework, `create_new_version` |
| `website_hr_recruitment` | Public vacancy page (responsibilities) |
| `knowledge` | Welcome-article flag and department links |
| `geo_payroll` | `pension_fund_member` used by a personal-info question; brings `gec_localization` |
| `hr_payroll`, `hr_payroll_attendance` | Payslips and `attendance_based` for team leaders |
| `hr_timesheet` | Timesheet history and employee validation |
| `hr_skills` | Resume and certification tabs on the public card |

---

## Gotchas & Non-Obvious Behavior

- **No version control.** The module folder is outside every git repository (`custom_addons/` is excluded in the project's `.git/info/exclude`). Back it up before editing.
- **An accepted offer's state is protected only on Refuse and Delete.** A direct write (import, RPC, server action) can still move it to another state; no `write()` guard exists.
- **Core's feedback route still works for applicant offers.** `/salary_package/post_feedback` ([main.py:1460](../enterprise/hr_contract_salary/controllers/main.py#L1460)) posts the candidate's feedback on the offer.
- **The accept flow needs a bank account number** from the page or an existing account, so keep core's "Bank account" personal info on the page. Core reads `bank_account_vals['account_number']` whenever any bank field is submitted ([main.py:639](../enterprise/hr_contract_salary/controllers/main.py#L639)); [Likely] showing another bank field without the number crashes the submit.
- **Lawyer default uses the current company**, not the applicant's company ([hr_applicant.py:10](../custom_addons/alta_hr_customization/hr_customization/models/hr_applicant.py#L10)).
- **The offer status bar does not list *Accepted*.** The green "Accepted" ribbon and the list decoration show the state instead ([hr_contract_salary_offer_views.xml:47](../custom_addons/alta_hr_customization/hr_customization/views/hr_contract_salary_offer_views.xml#L47)).
- **The JS patch no-ops without `is_applicant_offer`**, so employee offers submit through core.
- **No automated tests.** The module `README.md` names a test class `TestTimesheetTimeHistory`, but there is no `tests/` folder.
- **Upgrade warning.** [Unverified] upgrading `geo_payroll` or `gec_payroll_bank` logs an "Access Rights Inconsistency" warning for team leaders, because those views are checked before this module's field groups load.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`hr_employee_versions.md`](hr_employee_versions.md) — how `hr.version` records and contract dates work in Odoo 20
- [`hr_payroll.md`](hr_payroll.md) — payslip states and payroll groups
- [`geo_payroll.md`](geo_payroll.md) — `pension_fund_member` and the Georgian payroll module

# RS Employee Registry (`employee_registry_rs`)

> **Module:** `employee_registry_rs` | **Path:** [`custom_addons/gec_odoo_modules/employee_registry_rs/`](../custom_addons/gec_odoo_modules/employee_registry_rs/)

## What It Does & Why It Exists

Georgian employers must keep the Revenue Service's employee registry (დაქირავებულ პირთა რეესტრი) in sync with their real headcount: every hire, every termination, every contract change. Doing it by hand in the RS portal is tedious and error-prone — this module closes the loop so Odoo is the single source of truth.

The module talks to the RS **Employee Registry API** (`https://eapi.rs.ge`, v1.0.1, REST/JSON). When a contract starts, ends, or an employee is archived, Odoo pushes the new status to RS automatically. An HR manager can still force a sync or mark an employee as suspended manually from the employee form.

Intended users: HR managers and accounting staff of companies filing employment data with Georgia's Revenue Service.

---

## The Big Picture — How It Works

```
Odoo employee state        -->  daily cron  -->  RS /Employees/SaveEmployee  -->  RS registry
(active / terminated via           (reconcile)                                    (1 / 0 / -1)
 contract version + departure)
```

The module derives a *target* status from Odoo state and compares it to the *last pushed* status. Only when they differ does it call the API — this keeps traffic low and the log readable.

**State derivation** (on every employee with an `identification_id`):

| Odoo state | Target RS status |
|---|---|
| `employee.active = True` AND `current_version_id.is_in_contract = True` | `1` Active |
| `employee.active = False` OR `departure_date ≤ today` OR `contract_date_end < today` | `0` Terminated |
| no contract dates / no `identification_id` | *skip — not synced* |

Suspended (`-1`) is never set automatically; it's triggered by the "Suspend in RS" button.

The cron pushes a `0` only for an employee RS already knows (`rs_status` or `rs_registry_id` is set), so former employees who were never registered are not created in RS as terminated ([`_compute_rs_needs_sync`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L130)). **Sync Now** still pushes them when HR asks; **Fetch from RS** links someone registered by hand, after which the cron terminates them.

### Authentication flow

Credentials live on `res.users.settings` (module `rs_base_methods`), one value per user **and per company**; `res.users` shows them for the active company. API calls run as `env.user` under the employee's legal entity (its root company), so the login and token cache of that company are used whatever company is active ([`_request`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L110)).

1. Service asks `env.user._get_rs_rest_token()` for a fresh token.
2. `rs_base_methods` checks the cached `rs_access_token` + `rs_token_expiry` on the user; if fresh → returns it. If expired/missing → POST `/Users/Authenticate`, cache the new token on the user, return it.
3. If RS returns 401, the service calls `_rs_rest_authenticate(force=True)` and retries once.
4. Manual actions (Sync Now, Sync Countries) use the current logged-in user's credentials.
5. The daily cron runs one pass per legal entity as that company's **RS Responsible User** (the flag in Preferences, set per company); the `User` on the `ir.cron` record no longer matters. The responsible user needs HR Officer rights and a login stored under the root company.
6. **One RS login serves one legal entity.** The buttons refuse an employee whose company (with its branches) is not the company you are working in; the cron syncs each legal entity in its own pass. A database with several legal entities needs one RS Responsible User per entity; the same person may be it for all of them, with one login stored per entity.

Only one-step authentication is supported — the service account must have 2FA disabled.

### Key Decision Points
- **Per-employee `rs_sync_mode`** (selection):
  - **Automatic** — daily cron pushes status from contract state (`is_in_contract` / `departure_date` / `active`). `Sync Now` and `Suspend` buttons available; status-override buttons hidden because the cron handles them.
  - **Manual only** — cron skips this employee. Status changes only via buttons on the form (`Sync Now`, `Activate`, `Suspend`, `Terminate`). Use this for employees whose status RS doesn't agree with Odoo's contract state, or where you want full manual control.
  - **Disabled** — excluded from RS entirely. Buttons, including Fetch from RS, refuse with a `UserError` ([`_check_rs_sync_allowed`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L142)).
- **Global `sync_enabled`** (Settings) — master kill-switch; when off, the daily cron runs but does nothing. It is **off until someone switches it on**: the setting has no default, so the checkbox and the cron always agree.
- **RS Work Type** (`rs_work_type`) — defaults to full-time. Change per employee if they're part-time, because `hr.version.employee_type` (employee/worker/student/...) doesn't map cleanly to RS's binary full/part classification.

---

## When to Use It (and When Not To)

### This module is for:
- Georgian companies (or companies with Georgian employees) that need to keep the RS employee registry up to date.
- HR managers who want termination and rehire events pushed to RS without leaving Odoo.

### Use something else when:
- You need the tax/income side of RS (e-invoice, income tax declarations) — that's [`rs_einvoice`](../custom_addons/gec_odoo_modules/rs_einvoice/), a different SOAP API.
- Your RS service account requires SMS-based 2FA on every login — this module only supports one-step auth. Switch to an API account without 2FA.

---

## Real-World Scenarios

### Scenario 1: New hire gets registered automatically
**Situation:** HR creates an employee, sets their Identification ID, mobile phone, and a contract version with `contract_date_start` starting today.
**What they do:** Save the record. No further action.
**What happens:** Within 24h the daily cron notices `rs_target_status = '1'` and `rs_status` is empty, calls `/Employees/SaveEmployee` with `ID = 0`, and stores the returned numeric ID in `rs_registry_id`. If the HR manager is impatient, they click **Sync Now** on the employee form.

### Scenario 2: Employee leaves mid-month
**Situation:** An employee resigns; HR sets `departure_date` to today (or archives them).
**What they do:** Update the employee record and save.
**What happens:** `rs_target_status` flips to `'0'` (terminated). Next cron run pushes `STATUS=0` with the stored `rs_registry_id`. RS registry reflects the termination; `rs_status` is stored as `'0'`. The **RS Sync Log** (Employees → Configuration → RS Sync Log) has one new row for the call.

### Scenario 3: Long unpaid leave — suspended manually
**Situation:** An employee takes 4 months of unpaid leave. RS requires status `-1` (suspended) per Labor Code Article 36.
**What they do:** HR opens the employee, clicks **Suspend in RS** on the RS Registry page.
**What happens:** The action force-calls `SaveEmployee` with `STATUS=-1`. Once the employee returns, HR clicks **Sync Now** to push them back to `1`.

### Scenario 4: Syncing a foreign citizen
**Situation:** A company hires a citizen of Austria.
**What they do:** Set `country_id` = Austria (nationality) on the employee, fill `identification_id` (the local TIN RS will use), set `sex`, `birthday`, and ensure the Austria record has `rs_country_code = '040'` (run **Sync Countries from RS** in settings once to populate this).
**What happens:** `_build_rs_payload` detects `rs_is_foreigner = True` and adds `CITIZEN_COUNTRY_ID`, `FULLNAME`, `GENDER`, `BIRTH_DATE` to the payload per the RS schema.

### Scenario 5: Employee already exists in RS (manually added on rs.ge or imported elsewhere)
**Situation:** HR adds an employee in Odoo with a TIN that's already in the RS Employee Registry — for example, the company was manually maintaining the registry on rs.ge before installing this module.
**What they do:** Save the record, click **Sync Now** (or **Activate** in manual mode).
**What happens:** First `SaveEmployee` call sends `ID = 0` (create) → RS returns `[-801] ეს პიროვნება უკვე გყავთ დამატებული`. The module catches this, calls `_resolve_rs_id_by_tin` to look up the existing record, writes the resolved id to `rs_registry_id`, and retries the call as an update — all in the same click. The user sees a single success notification. The **RS Sync Log** has three rows: the failed create, the TIN lookup, and the successful retry.

Alternative pre-link: click **Fetch from RS** before pushing. The button is visible as soon as `identification_id` is set (it falls back to TIN lookup when `rs_registry_id` is empty), and pulls remote data into Odoo.

---

## How Things Work Under the Hood

### Core Logic

- **`_compute_rs_target_status`** ([`hr_employee.py:110`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L110)) — single source of truth for "what should RS see". Reads `current_version_id.is_in_contract`, `contract_date_end`, `departure_date`, and `active`.
- **`_build_rs_payload`** ([`hr_employee.py:183`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L183)) — constructs the `EMPLOYEE` object per the RS API schema. Validates required fields up front so a bad call never reaches the network.
- **`_cron_sync_employees_to_rs`** ([`hr_employee.py:572`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L572)) — the daily batch. Searches with `active_test=False` so archived employees (departures) are still considered, limited to the cron user's company and its branches. Each employee runs in its own savepoint and is committed right after (`ir.cron._commit_progress`), so one bad record, a database error or a worker timeout never undoes what RS already accepted.
- **`_request`** ([`employee_registry_rs_service.py:110`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L110)) — wraps POST, asks `env.user._get_rs_rest_token()` for a token, retries once on 401 via `_rs_rest_authenticate(force=True)`. Always writes an audit log row ([`_write_log`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L169)) on its own cursor, created as the calling user and stamped with the employee's company. The server log only gets the endpoint and employee id; payloads stay in the audit table.
- **`_sync_single_to_rs`** ([`hr_employee.py:278`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L278)) — per-employee push. Builds payload, calls `SaveEmployee`, and self-heals from two error classes: `[-801]` (sent `ID=0` but TIN already exists in RS) → look up by TIN, link, retry as update. `[-2]` / `[-30]` (sent `ID>0` but record may be stale) → look up by TIN: a different id → retry with it; no record → fresh create; **the same id → the id is valid and RS rejected another field (e.g. "phone used 3 times"), so the original error is shown and nothing is cleared**. Both recovery branches write the canonical RS id back to `rs_registry_id`.
- **`_resolve_rs_id_by_tin`** ([`hr_employee.py:248`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L248)) — looks up a record's RS id by walking `ListEmployees` across all three statuses (1, -1, 0). Necessary because `ListEmployees` defaults to active-only, so a suspended or terminated record would otherwise be invisible. Used by both `_sync_single_to_rs` recovery and `Fetch from RS` when no local id is set.
- **`_get_rs_rest_token`** ([`rs_base_methods/models/res_users.py`](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py)) — owns the token lifecycle: serves from cache if fresh, re-authenticates against `/Users/Authenticate` otherwise.

### Important Fields (only the ones that matter)

- `rs_registry_id` — the RS-assigned record ID. Populated by the first successful `SaveEmployee`. Never reset automatically; clearing it forces a "create new" on next sync.
- `rs_target_status` (computed, non-stored) — vs `rs_status` (stored, last push): the delta drives `rs_needs_sync` and the cron.
- `identification_id` — **the TIN source**. No ID = no sync. It lives on `hr.version` (since v19) and is delegated to `hr.employee`.
- `rs_country_code` on `res.country` — Char(3), ISO 3166-1 numeric. RS uses `036`, `040`, etc. Populate via **Sync Countries from RS**.

---

## Configuration & Settings

### Per-user, per-company credentials (switch to the company, then Settings → Users → select user → Preferences → "Revenue Service (rs.ge)")
Provided by [`rs_base_methods`](../custom_addons/gec_odoo_modules/rs_base_methods/). Each user who interacts with RS gets their own `rs_username` / `rs_password` and their own bearer-token cache, one set per company; the form shows the company it is editing. **Test SOAP (e-invoice)** also stores the company's rs.ge taxpayer id; **Test REST (eapi.rs.ge)** pairs the device for that company.

### Module-wide settings (Settings → Employees → RS Employee Registry)

- **Daily Sync** — master kill-switch, off until switched on. When off, `_cron_sync_employees_to_rs` logs "sync disabled" and returns immediately.
- **Sync Countries from RS** — calls `/Employees/GetCountries` as the current logged-in user and populates `res.country.rs_country_code` by matching on the Georgian country name, compared in `ka_GE` whatever the user's language ([`sync_countries_from_rs`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L216)). The Georgian names come from `gec_i18n_base`. Run once after install, then only when new countries are added on either side.

### Cron identity
The daily cron runs one pass per legal entity (root company) as that company's RS Responsible User ([`_cron_sync_employees_to_rs`](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L572)); the Scheduler User on the `ir.cron` record is irrelevant. Flag the user in each company (Preferences, per company); they need HR Officer rights and a login stored under the root company. A company without a responsible user is skipped with a log line, and a failing company never stops the others. The interval is 1 day; databases installed before 2026-09-23 keep their stored 3-day interval (the record is `noupdate`), so change it on the Scheduled Action.

---

## Dependencies

| Requires | Why |
|---|---|
| `hr` | Employees, contract versions (`hr.version`), `current_version_id`, `is_in_contract`. |
| [`rs_base_methods`](../custom_addons/gec_odoo_modules/rs_base_methods/) | Per-user RS credentials on `res.users` + bearer-token cache + REST auth helper (`_get_rs_rest_token`). This module owns all the `eapi.rs.ge` authentication mechanics. **Not declared in the manifest**: `rs_base_methods` depends on this module, so declaring it would be circular. Installed without it, the cron and buttons fail with `AttributeError`. |
| Python `requests` | HTTPS/JSON transport. Already a hard dep of Odoo 20. |

| Works With (optional) | What It Adds |
|---|---|
| [`rs_einvoice`](../custom_addons/gec_odoo_modules/rs_einvoice/) | Complements this module on the accounting side (invoices to RS). Independent credentials, independent API. |

---

## Gotchas & Non-Obvious Behavior

- **Contract model changed in v19.** There is no `hr.contract` — contracts live as `hr.version` rows with `contract_date_start/end`, and `hr.employee` delegates to the current version via `current_version_id`. The status-derivation reads from `current_version_id`, not from a non-existent `hr.contract`.
- **Future dates don't terminate.** An employee with a `departure_date` in the future stays status `1` until that date arrives. Same for `contract_date_end` — only a *past* end date flips the target to `0`.
- **Archiving is a termination signal.** Setting `active=False` on the employee → target status goes to `0` even without a `departure_date`. The cron sends it only if RS already knows the employee (see the state derivation above).
- **Token cache is per user and per company, survives restarts.** Tokens live on `res.users.settings.rs_access_token` (company-dependent, set by `rs_base_methods`) and are shown on the user for the active company. Each cache is independent. A corrupted token can linger for up to 40 min — switch to the company and click **Test REST (eapi.rs.ge)** on the user form to force a re-auth immediately.
- **2FA needs a one-time pairing per company.** If the RS account has SMS-based 2FA, `/Users/Authenticate` returns a `PIN_TOKEN`; the interactive **Test REST** opens a PIN wizard and stores the device code for that company, after which logins skip the SMS. The cron cannot answer a PIN: pair the device before enabling the sync, or it logs the 2FA error for that entity.
- **`identification_id` is group-gated.** It's declared with `groups="hr.group_hr_user"` on `hr.version`. The cron runs as its Scheduler User and reads it without `sudo()`, so that user needs HR Officer rights. Forms shown to non-HR users don't display the RS page (also gated to `hr.group_hr_user`).
- **Country code drift.** RS numeric codes follow ISO 3166-1, but the RS list is authoritative. If a name doesn't match exactly between Odoo's Georgian translation and RS's Georgian spelling, the sync-countries action silently skips it — review matches if you see missing codes. Before 2026-09-23 the match used the clicking user's language, so an English-language user matched nothing.
- **The sync log is per company.** Each row carries the employee's company (or the active company for calls without an employee) and is only visible in that company; "Created by" is the user who made the call. RS Employee Browser searches are private to the HR manager who ran them.
- **Service methods are not callable over RPC.** `save_employee`, `get_employee`, `list_employees`, `get_countries`, `sync_countries_from_rs` and `ensure_country_codes` are `@api.private`: use the employee buttons.
- **Phone is auto-cleaned.** Spaces, `+`, `-`, and parens are stripped from `mobile_phone` before being sent. If the result has the country prefix embedded (e.g. `995...`), RS will accept it; RS doesn't validate phone format strictly.
- **"Already exists" is auto-recovered.** If you click `Sync Now` / `Activate` on a new employee whose TIN already exists in RS (manually created on rs.ge earlier), the module catches `[-801]`, looks up the existing record by TIN, links it on the Odoo side, and retries the call as an update — one-click success. No manual intervention needed unless TIN lookup itself fails (e.g. the RS record is in some unusual state).
- **Field-only changes don't trigger the cron.** The daily cron only fires when `rs_target_status != rs_status`. If you edit *only* the mobile phone, work type, or TIN — without a status change — the cron will not pick it up. Click `Sync Now` to push the change immediately. Sync Now is visible in both **Automatic** and **Manual** modes for this reason.
- **Button visibility per sync mode and current status** — Sync Now (push current state with computed status) is available in `auto` and `manual`. Activate / Terminate are visible in `manual` only (in `auto`, the cron drives them — use Sync Now if you want immediate). Suspend is visible in both modes, since suspended is never auto-derived. Status-override buttons additionally hide themselves when the employee is **already** in that status — Activate hides when `rs_status == '1'`, Suspend hides when `rs_status == '-1'`, Terminate hides when `rs_status == '0'` — so you don't accidentally fire a redundant call to RS. Fetch from RS is visible whenever `identification_id` is set (works with or without a stored `rs_registry_id`).

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- External: [`Employee_API_Reference.md`](../Employee_API_Reference.md) — the RS API contract this module is built against.

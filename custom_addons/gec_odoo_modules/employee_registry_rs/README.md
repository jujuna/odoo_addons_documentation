# RS Employee Registry

Odoo 20 module that syncs `hr.employee` with Georgia's Revenue Service
Employee Registry at `https://eapi.rs.ge`.

Each employee has a **Sync Mode** (Automatic / Manual / Disabled) that decides
who changes their RS status. Credentials live per user and per company via the
companion module `rs_base_methods`.


## Dependencies

| Requires | Purpose |
|---|---|
| `hr` | hr.employee, hr.version (contract dates, departure, is_in_contract) |
| `rs_base_methods` | per-user, per-company RS username/password + REST token cache (not in `depends`: it depends on this module) |
| `requests` | HTTP transport |


## Setup

1. Install `rs_base_methods`; it installs `employee_registry_rs` with it.
2. In each legal entity (switch to its company first): on the user who will run
   its sync, Preferences → Revenue Service (rs.ge) → fill credentials →
   **Test REST (employee registry)** → tick **RS Responsible User**. That user
   needs HR Officer rights.
3. Technical → Scheduled Actions → "RS Employee Registry: Daily Sync": the
   `User` field no longer matters; the cron runs one pass per legal entity as
   its RS Responsible User.
   Databases installed before 2026-09-23 keep a 3-day interval: set it to 1 day.
4. Settings → Employees → RS Employee Registry → switch on **Daily Sync**
   (off until you do).
5. (Foreigners only) Settings → Employees → RS Employee Registry →
   **Sync Countries from RS**. Also runs automatically on first foreign sync.


## Sync Modes

| Mode | Cron | Sync Now | Activate | Suspend | Terminate | Fetch |
|---|---|---|---|---|---|---|
| Automatic | yes | yes | hidden | yes | hidden | yes |
| Manual only | skipped | yes | yes | yes | yes | yes |
| Disabled | skipped | refused | refused | refused | refused | refused |

- **Sync Now** pushes the computed target status.
- **Activate / Suspend / Terminate** force a specific status.
- **Fetch** pulls RS data back into Odoo.
- Every button refuses an employee of another legal entity than the company
  you work in: switch to that company first (your RS login is used for it).


## Automatic Status Derivation

```
target = 0 (Terminated)  if  not employee.active
                         or  departure_date <= today
                         or  current_version.contract_date_end < today
target = 1 (Active)      if  employee.active
                         and current_version.is_in_contract
                         and identification_id is filled
target = None (skip)     otherwise
```

Cron compares `target` with `rs_status` (last pushed). Pushes only if they
differ. Suspended (-1) is never set automatically. A termination (0) is
pushed only for an employee RS already knows (`rs_status` or `rs_registry_id`
set): former employees never registered are left alone. Sync Now still
pushes them; Fetch links someone registered by hand.


## Fetch — What It Writes Back

| RS field | Odoo field | Applies to |
|---|---|---|
| STATUS | rs_status | all |
| PHONE | mobile_phone | all |
| TIN | identification_id | all |
| FULLNAME | name | foreigners |
| BIRTH_DATE | birthday | foreigners |
| GENDER | sex | foreigners |
| CITIZEN_COUNTRY_ID | country_id | foreigners |


## RS Employee Browser

Employees → Configuration → RS Employee Browser.

Search RS by TIN / name / status. Rows are colored:
- green — exists in Odoo, active in RS
- yellow — exists in Odoo, suspended/terminated in RS
- grey — only in RS, no Odoo match

Per-row actions:
- **Open** — jump to the Odoo employee form.
- **Link** — store the RS ID on the Odoo employee without calling
  SaveEmployee. Used for migration and for fixing stale IDs.


## Stale `rs_registry_id`

RS creates a new record (new ID) on every change. The module handles this:

- Every SaveEmployee response overwrites `rs_registry_id` with the returned ID.
- On `-30` / `-2` errors, the module queries `ListEmployees(TIN, STATUS)`
  across all three statuses (RS defaults to STATUS=1), updates the ID, retries.
  If the lookup returns the ID already stored, the ID is valid and RS rejected
  another field (e.g. the phone): the original RS error is shown.
- If no record exists for the TIN, retries as a fresh create (ID=0).


## Retries

| HTTP / STATUS.ID | Handling |
|---|---|
| 401, -104, -105 | Force re-auth once, retry |
| 5xx, STATUS -1 | Backoff retry: 1s, 3s, 8s |
| -2, -30 on update | Resolve ID via TIN, retry; same ID → show the RS error |
| Other 4xx + STATUS != 0 | Raise with the RS Georgian text |


## Daily Cron

- Skips if master toggle is OFF.
- One pass per legal entity (root company and its branches) as that company's
  RS Responsible User; an entity without one is skipped and logged, and a
  failing entity never stops the others.
- Searches `identification_id IS NOT NULL AND rs_sync_mode = 'auto'` in the
  entity.
- Skips rows where `rs_needs_sync = False`.
- On failures, emails the responsible user. Weekly health summary also goes out.
- One employee failure does not stop the batch: each employee runs in its own
  savepoint and is committed right after, so a timeout keeps what RS accepted.


## Audit Log

Employees → Configuration → RS Sync Log. Also embedded on each employee form
(last 10 calls). Log writes use a separate DB cursor so rollbacks do not erase
evidence. Each row belongs to the employee's company and is visible only in
that company; "Created by" is the user who made the call. Rows older than
90 days are deleted weekly.


## RS Error Codes

| Code | Meaning | Fix |
|---|---|---|
| 0 | Success | — |
| -1 | System error | Backoff retry; if persistent, contact api-support@rs.ge |
| -2 | Invalid action | Stale registry ID — auto-recovers via TIN lookup |
| -30 | Invalid record ID or field | Same as -2, or TIN is malformed |
| -104 / -105 | No permission | Enable Employee Registry service at rs.ge |
| -801 | Person already added | Update existing record instead of creating |


## Quirks

- `SaveEmployee` body is **flat** (no `{"EMPLOYEE": {...}}` wrapper), despite
  what the docs table suggests.
- RS web UI filters default to Active; switch to "All" to see
  suspended/terminated records.
- For Georgian citizens, RS resolves `FULLNAME`, `GENDER`, `BIRTH_DATE`,
  `CITIZENSHIP` from the national registry — whatever you send there is
  ignored.
- Phone uniqueness: -30 "ეს ტელეფონის ნომერი 3 ჯერ უკვე გამოყენებულია" means
  the phone is already used 3 times. Pick another.
- Only 1-step auth. Accounts with SMS 2FA are rejected with a clear error.


## Troubleshooting

1. Open **RS Sync Log**, find the failing row.
2. `status_id` + `status_text` = the RS verdict. `request_payload` = what went
   on the wire.
3. Persistent -2 / -30 means the TIN lookup found nothing. Verify
   `identification_id` and check RS Employee Browser.
4. -104 / -105 means the account lacks Employee Registry access on rs.ge.
5. -1 across all write endpoints while reads work = RS sandbox down.

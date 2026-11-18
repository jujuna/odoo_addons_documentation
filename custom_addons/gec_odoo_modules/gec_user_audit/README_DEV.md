# User Audit & Sessions (`gec_user_audit`) — Developer guide

For a developer who knows Odoo 20 and has to change this module. The user guide is [README.rst](README.rst).
Flow sections (step by step) are not written yet.

## 1. Purpose and facts

Logs who signed in, from where, and what they read, changed, exported, imported and printed, and lists the open
sessions so they can be ended. `gec_access_manager` depends on this module: it uses `_gec_rpc_entry` to tell client
calls from server code and writes its refusals to the log.

| Item | Value |
|---|---|
| Depends | `base` (core models), `web` (controllers: dataset, export, translation, report routes), `mail` (sign-in emails), `rpc` (XML-RPC / JSON-RPC client address) |
| New models | `gec.user.audit.log`, `gec.user.audit.rule`, `gec.user.audit.report.wizard`, `report.gec_user_audit.report_user_activity` (report) |
| Extended models | `base`, `ir.http`, `res.users`, `res.session`, `res.config.settings` |
| Controllers | `controllers/main.py` overrides the dataset, JSON, export, translation and report routes |
| Crons | User Audit: Delete Old Logs (daily, `gec.user.audit.log._cron_clean`); User Audit: End Idle Sessions (hourly, `res.session._cron_end_idle`) |

Data files, in manifest order: `data/ir_cron.xml`, `data/mail_template.xml`, `report/gec_user_audit_report.xml`,
`views/gec_user_audit_log_views.xml`, `views/gec_user_audit_rule_views.xml`, `views/gec_user_audit_session_views.xml`,
`views/res_config_settings_views.xml`, `views/res_users_views.xml`, `wizard/gec_user_audit_report_wizard_views.xml`,
`views/menu.xml`, `security/ir.access.csv`.

## 3. File map

### controllers/

| File | Holds |
|---|---|
| `main.py` | Marks the calls a client makes, keeps the address of the RPC clients, logs the reports printed |

### models/

| File | Holds |
|---|---|
| `base.py` | The data events: reads per client call; creates, edits and deletes per record |
| `client_call.py` | Tells the calls a client or a script makes itself (web client, JSON-2, XML-RPC) from Odoo's own code: `_gec_rpc_entry` |
| `ir_http.py` | Sign-outs, and the sessions idle for longer than the settings allow |
| `gec_user_audit_log.py` | One line per event |
| `gec_user_audit_rule.py` | What is logged |
| `res_users.py` | Sign-ins, failed sign-ins and the sign-in emails; the `res.session` extension |
| `res_config_settings.py` | The settings: retention, Log Reads, Never Logged, sign-in emails, idle minutes |

### wizard/

| File | Holds |
|---|---|
| `gec_user_audit_report_wizard.py` | The activity of users over a period, as a PDF for an audit |

## Guards and invariants

| Rule | Where | Why |
|---|---|---|
| Reads are logged per client call only | `models/base.py`, `models/client_call.py` | Odoo's own code reads all the time and is never logged |
| Creates, edits and deletes are logged per record, whoever makes them but the superuser | `models/base.py` | They change data |
| Audit lines are written in the same transaction | `models/gec_user_audit_log.py` | A savepoint rollback discards the corresponding events |
| Failed sign-ins and refusals are written on a cursor of their own | `models/gec_user_audit_log.py` | These events must survive a rollback |
| With no rule, every operation on every business model is logged; as soon as a rule exists, only what the rules name | `models/gec_user_audit_rule.py` | Defines the logging scope |
| Client calls are marked by `_gec_rpc_entry` | `models/client_call.py`, `controllers/main.py` | Tells a client or script call from Odoo's own code |
| The address of RPC clients is kept by the controllers | `controllers/main.py` | `dispatch_rpc` unbinds the request, so `with_address()` keeps the client's address first |
| Idle sessions are ended on the request and by cron | `models/ir_http.py` | Sessions idle for longer than the settings allow |

## Extending safely

| Never | Because |
|---|---|
| Write an audit line for another module's event outside `_gec_log` | Lines must follow the transaction rules above; pass `separate` for an event that must survive a rollback (refusals, failed sign-ins) |
| Log every Python read | Odoo's own code reads all the time; reads are logged only per client call |
| Decide "is this a client call" without `_gec_rpc_entry` | It is the one place that tells client and script calls from Odoo's own code |

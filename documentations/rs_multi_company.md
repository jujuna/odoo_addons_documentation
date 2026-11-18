# rs.ge Modules — Users, Companies and Logins

> **Modules:** `rs_base_methods`, `rs_einvoice`, `rs_waybill`, `employee_registry_rs` |
> **Path:** [`custom_addons/gec_odoo_modules/`](../custom_addons/gec_odoo_modules/) |
> **State analysed:** 20.0 source and `gec20_prod1` on 2026-09-27. Nothing in the code was changed for this document.

## What This Document Is & Why It Exists

The four rs.ge modules were written for one Odoo company with one rs.ge login. The company is about to
become three. This document answers, for every combination of Odoo users, Odoo companies and rs.ge
logins we may end up with: does it work today, what breaks, what must change, where, roughly how many
lines, and whether the scheduled actions stay safe. It is the input for the implementation plan; the
plan itself is phased and each phase is approved and committed separately.

Two facts drive everything:

- An rs.ge login belongs to one taxpayer (one TIN). Service users are created inside a taxpayer's
  cabinet (the e-invoice service exposes `create_ser_user`), and `get_un_id_from_user_id` returns one
  taxpayer per login ([rs_soap_service.py:307](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L307)).
- Odoo stores one rs.ge login per **user**, not per company, and every rs.ge call takes the login of
  `env.user` without being told which company the document belongs to
  ([rs_soap_service.py:157](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L157),
  [rs_waybill_soap_service.py:35](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L35),
  [employee_registry_rs_service.py:111](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L111)).

Method coverage: every `.py` file of the four modules outside `tests/` was parsed with `ast`:
**608 class methods** (160 call rs.ge) plus 19 module-level helper functions, of which only
`_rs_find_partner_by_tin` touches a company and receives it as a parameter
([rs_einvoice_cron.py:92](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L92)).
Six field defaults read the active company or user at creation time
([rs_waybill.py:93-98](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L93),
[rs_waybill_operation.py:29](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_operation.py#L29),
[rs_invoice_from_waybill_wizard.py:39](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L39));
that is the document's own company, so they stay. XML views, `ir.access.csv`, the JS widget and
`rs_base_methods/scripts/` carry no company or credential logic. The appendix lists each method that
calls rs.ge, reads `env.user` or `env.company`, filters by company, or is a cron or button, with its
verdict; the 293 class methods not listed do none of these.

---

## The Big Picture — How a rs.ge Call Finds Its Login Today

```
User clicks a button in company X          Cron fires (Scheduler User = OdooBot, uid 1)
        |                                          |
        v                                          v
account.move / rs.waybill / hr.employee     cron method searches records of ALL companies (sudo)
        |                                          |
        v                                          v
service = env['rs.soap.service']            with_user(one responsible user)   (e-invoice buyer sync)
   (no company passed)                      or nothing at all                 (e-invoice refresh crons)
        |                                          |
        v                                          v
env.user.rs_username / rs_password  <---  one value per user (res.users.settings, UNIQUE(user_id))
        |
        v
seller taxpayer = get_un_id_from_user_id(login)   -->   never compared with company.vat
```

- The login is read from `res.users.settings`, one row per user
  ([res_users_settings.py:7](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users_settings.py#L7);
  core constraint `UNIQUE(user_id)`, [res_users_settings.py:14](../odoo/addons/base/models/res_users_settings.py#L14)).
  The SOAP user id, the REST token and the 2FA device pairing are single fields on `res.users`
  ([res_users.py:59-99](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L59)).
  Saving a new login wipes all of them ([res_users.py:125](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L125)):
  Test SOAP and the SMS PIN again after every swap.
- The seller on an outgoing e-invoice is the login's taxpayer
  ([account_move_seller.py:102](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L102)).
  A waybill carries `SELER_UN_ID` from the login; its own `seller_tin` field is not sent
  ([rs_waybill_soap_service.py:238](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L238)).
  Nothing checks either against `company_id.vat`.
- The only company guard on the seller side compares the user's **default** company with the invoice
  ([account_move.py:1112](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1112)).
  The company switcher does not change the default company; it only sets the `cids` cookie
  ([user.js:79](../addons/web/static/src/core/user.js#L79)). So a user whose default is A gets
  "Switch to company B" while already in B.
- The buyer side has the one real check: Pull refuses a document whose buyer is not the company's TIN
  ([account_move_buyer.py:166](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L166)).
- `rs_waybill` already runs its crons once per company, borrowing a user whose default company matches
  ([rs_waybill_sync.py:19](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L19),
  [:49](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L49)). The other two
  modules do not.

### State of `gec20_prod1` on 2026-09-27 (SELECT only)

| Fact | Value |
|---|---|
| Companies | 1 (`My Company`, TIN 206322102) |
| Users with a rs.ge login | 1 (`admin`), default company 1, no responsible flag set |
| Scheduler User of all 14 RS crons | uid 1 (OdooBot), which has no login |
| Active crons | Deadline Check, Employee Registry Daily Sync (3 days), Log Rotation, the 4 RS.GE waybill crons |
| Inactive crons | e-invoice Sync Buyer Invoices, both Refresh Status, Recover Stranded, Escalate, Stuck Sends, Vacuum |

Consequence today: the waybill crons work because `_get_rs_sync_user` finds `admin`; the employee
registry cron logs "cron user has no RS credentials" and does nothing
([hr_employee.py:581](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L581));
the e-invoice refresh crons would log one warning per candidate and refresh nothing if switched on
([rs_einvoice_cron.py:493](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L493)).

---

## The Variants — Which Work Today, Which Don't

Example used throughout: companies **Alpha** (TIN 2001), **Beta** (2002), **Gamma** (2003). Users
**Nino** (Alpha only), **Giorgi** (Beta only), **Lika** (Gamma only), **Dato** (all three).

### The four named cases

| Case | Meaning | Possible on rs.ge | Today | After the change |
|---|---|---|---|---|
| **A.** 3 companies, each its own rs | `alpha_srv`, `beta_srv`, `gamma_srv`; nobody spans companies | Yes | Buttons work (default company = only company). Buyer sync serves one company; both refresh crons run without a login; employee cron needs one cron record per company | Works, crons per company |
| **B.** 3 companies, one rs | everybody uses `alpha_srv` | Two ways. (1) The three companies are one taxpayer, one TIN. (2) Three TINs and rs.ge lets this login act for all three (a representative login): the e-invoice API names the taxpayer in every call (`save_invoice(seller_un_id)`, `get_user_invoices(un_id)`), the waybill list calls do not ([rs_waybill_soap_service.py:527](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L527) takes no `un_id`), so (2) is settled by the phase 0 tests. Today's code files everything under the login's own taxpayer either way | Same as A on the seller side; incoming documents addressed to the shared TIN can be imported into any company, and into two of them (uniqueness of `rs_einv_id` is per company, [account_move.py:382](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L382)); waybill sync puts every row into the first company with that TIN ([rs_waybill_sync.py:88](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L88)) | With three TINs: the plan as is; every call names the company's taxpayer, so each company's pass fetches its own incoming documents. With one shared TIN: plus a routing rule for incoming documents and a cross-company duplicate check (Layer 3, +1 day) |
| **C.** 3 companies, 3 rs, Dato holds all three logins | one Odoo user, three service users | Yes | Cannot be configured: one login slot per user. With Alpha's login stored: Beta's invoice refused by the default-company guard; if the default is changed to Beta, Beta's invoice goes out as Alpha's; Beta's waybill goes out as Alpha's with no error; Inbox in Beta lists Alpha's incoming invoices and imports them into Beta; Beta's employee lands in Alpha's registry (guard checks only employee company = active company, [hr_employee.py:153](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L153)) | Works: three logins on one user, one per company; the document's company picks the login; crons per company as Dato |
| **D.** 3 companies, one rs, Dato | one Odoo user, one service user | As B | Blocked by the default-company guard for the two non-default companies; otherwise as B | As B; Dato enters the same login in each of the three companies |

All four cases are approved as real (2026-09-29). B and D therefore fix one design decision: the
taxpayer id sent to rs.ge comes from the **company's TIN**, never from the login (rule 3). With that, a
representative login works for B and D wherever rs.ge accepts it, and the shared-TIN variant needs only
the Layer 3 routing rule. Whether rs.ge accepts a representative login over SOAP cannot be read from
code; the phase 0 tests settle it. The employee registry payload carries the employee's TIN and no
employer ([hr_employee.py](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py), `_build_rs_payload`),
so there one login means one employer's registry unless the REST login itself can choose the taxpayer.

### All user/company setups the design covers

| # | Setup | Today | After |
|---|---|---|---|
| 1 | One company, one user (prod1 now) | Works, crons half configured | Unchanged |
| 2 | One company, several users, each their own login | Works; one user must be responsible | Unchanged |
| 3 | One company, several users sharing one login | Works; each user enters the same login; each pairs 2FA separately | Unchanged |
| 4 | Three companies, every user in one company only (case A) | Buttons work; e-invoice crons serve one company or nothing | Crons per company |
| 5 | Three companies, one user in all three with three logins (case C) | Not configurable | Works |
| 6 | Multi-company user with a login for only some companies | Same failure as 5 in the other companies | Other companies refused with "no rs.ge credentials for company X"; their crons run as another responsible user or are skipped and logged |
| 7 | Any mix of 2-6 | Depends on which user acts | Works: storage is per (user, company) |
| 8 | A company where nobody has a login | Buttons refused | Crons skip that company and log it; the other companies are unaffected |
| 9 | Responsible user archived, login changed, 2FA pairing revoked | Buyer sync stops silently | Cron loop takes only active users with a login; the company is skipped with a warning |
| 10 | Users who never touch rs.ge | Unchanged | Unchanged |

Not covered by design: borrowing a colleague's login (only crons use another user's login, and only the
responsible one's). A representative login, one login for several taxpayers, is covered by rule 3 as far
as rs.ge allows it.

---

## What Must Change

### Four rules

1. **Credentials per (user, company).** The existing fields become `company_dependent=True`: one value
   per company on the same record. Core supports this for char, boolean and datetime
   ([fields.py:43](../odoo/orm/fields.py#L43)), stores the values as JSON keyed by company, and evaluates
   searches for the current company ([fields.py:1378](../odoo/orm/fields.py#L1378)). Core uses it the
   same way on partners (`invoice_edi_format_store`, [partner.py:636](../addons/account/models/partner.py#L636)).
   In Preferences the user sees and fills the login of the company they are in; switch to Beta, fill
   Beta's. No new model, no list view.
2. **Every rs.ge call runs under the document's company** (`with_company(record.company_id)`), so the
   right login is picked even when several companies are ticked in the switcher.
3. **The taxpayer comes from the company, never from the login.** Every call that names a taxpayer
   (`save_invoice(seller_un_id)`, `get_user_invoices(un_id)`, `get_buyer_invoices(un_id)`, the advance
   calls, the waybill `SELER_UN_ID`) sends the id resolved from `company_id.vat` and stored per company at
   Test SOAP. A wrong login can no longer file a document under its own taxpayer; rs.ge refuses the call
   instead. Closes the wrong-seller gap in both e-invoice and waybill, and is what makes B and D possible.
4. **Crons loop over companies**, each company running as the user flagged "RS responsible" **for that
   company**. In case C, Dato flags himself in Alpha, Beta and Gamma. The responsible user needs the
   company in Allowed Companies; `with_company` raises `AccessError` otherwise
   ([environments.py:258](../odoo/orm/environments.py#L258)), which is the right refusal.

### Changes by module (approximate lines)

**rs_base_methods** — about 130 lines

| Where | Change | Lines |
|---|---|---|
| [res_users_settings.py:7](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users_settings.py#L7) | `rs_username`, `rs_password` get `company_dependent=True`; add here, also company-dependent: `rs_user_id`, `rs_un_id` (new: the login's taxpayer), `rs_is_responsible`, `rs_access_token`, `rs_token_expiry`, `rs_device_code`, `rs_device_paired_on` | +15 |
| [`_get_fields_blacklist` res_users_settings.py:11](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users_settings.py#L11) | add the moved fields: core sends every non-blacklisted settings field to the browser in session info ([res_users_settings.py:31](../odoo/addons/base/models/res_users_settings.py#L31)) | 1 |
| [res_users.py:42-99](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L42) | the 8 fields become computed proxies from settings, like `rs_username` today, with `@api.depends_context('company')`; same shape as core's `account.account.code` over the company-dependent `code_store` ([account_account.py:46](../addons/account/models/account_account.py#L46), [:313](../addons/account/models/account_account.py#L313)) | ~40 |
| [`_compute_rs_credentials`:101](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L101), inverses :113, :120 | cover all 8 fields; inverses write `settings.with_company(env.company)` | ~45 |
| [`write()`:125](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L125) | reset token, user id and device pairing for the current company only | ~8 |
| [`_check_single_rs_responsible`:143](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L143) | one responsible per company | ~10 |
| [`_get_rs_credentials`:162](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L162) | error names the company | 2 |
| [`action_rs_test_credentials`:180](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L180) | after `chek`: store `rs_user_id`; resolve the company's taxpayer id with `get_un_id_from_tin(env.company.vat)` and store it as `rs_un_id`; compare it with the login's own taxpayer (`get_un_id_from_user_id`) and, when they differ, probe authorization with one read for that id (`get_user_invoices`, last hour), refusing on an auth error. The message says whether the login is the company's own or a representative | ~30 |
| 12 REST helpers :234-604 | no logic change: they read `self.sudo().rs_access_token` etc., which now resolve per company | 0 |
| [rs_auth_pin_wizard.py](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_auth_pin_wizard.py) | add `company_id` (default active company); `user_id.with_company(company_id)._rs_rest_complete_pin(...)` | ~6 |
| [res_users_views.xml](../custom_addons/gec_odoo_modules/rs_base_methods/views/res_users_views.xml) | both forms: show which company the block belongs to | ~10 |
| account_move.py, rs_einvoice_waybill_link.py (10 methods) | none: they go through `_rs_get_service()` | 0 |

**rs_einvoice** — about 80 lines

| Where | Change | Lines |
|---|---|---|
| [`_rs_get_service` account_move.py:2012](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L2012) | `return self.env['rs.soap.service'].with_company(self.company_id)`. Covers the 21 methods that call it and the 22 that receive the service from them (appendix) | 1 |
| [`_rs_validate`:1112](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1112) | delete the default-company guard; rule 2 replaces it (CODE_REVIEW 1.1) | -10 |
| the 6 sites that send the login's taxpayer: [account_move_seller.py:102](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L102), [account_move.py:2176](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L2176), [account_move_seller.py:508](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L508), [account_move_buyer.py:1015](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L1015), [rs_einvoice_cron.py:185](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L185), [rs_buyer_inbox_wizard.py:88](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_buyer_inbox_wizard.py#L88) | rule 3: one helper on the service, `_rs_company_un_id()`, returns `env.user.rs_un_id` for `env.company` (refusing when empty: "run Test SOAP in this company"); the six sites call it instead of `get_seller_un_id()`. `_check_auth` stays as it is | ~15 |
| [`_get_credentials`:150](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L150) | error names the company | 3 |
| [`_cron_sync_buyer_invoices`:136](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L136) | loop companies with a responsible user, `with_user(u).with_company(c)._sync_one_user()`, failures isolated per company | ~35 |
| [`_cron_refresh_status`:440](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L440) | group candidates by company, run each as that company's responsible user, skip and log a company without one | ~25 |
| `_sync_one_user`, inbox wizard, 22 service wrappers | none: they run in `env.company`, which the loop or the switcher sets | 0 |
| [res_config_settings_views.xml](../custom_addons/gec_odoo_modules/rs_einvoice/views/res_config_settings_views.xml) | help text | 3 |

**rs_waybill** — about 70 lines

| Where | Change | Lines |
|---|---|---|
| new `rs.waybill._rs_service()` | `return self.env['rs.waybill.soap.service'].with_company(self.company_id)` | 6 |
| 24 direct `self.env['rs.waybill.soap.service']` calls on one waybill: 17 actions in [rs_waybill_actions.py](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py), [`_compute_adjustment_count`:366](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L366), [`_action_reverse_completed_waybill`:1513](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L1513), [rs_waybill_adjustment.py:26](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_adjustment.py#L26), [stock_picking.py:542](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L542), [live_rs_view.py:96](../custom_addons/gec_odoo_modules/rs_waybill/wizards/live_rs_view.py#L96), [template_wizards.py:19](../custom_addons/gec_odoo_modules/rs_waybill/wizards/template_wizards.py#L19), [rs_waybill_sync.py:992](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L992) | replace with `self._rs_service()` | 24 |
| [`_build_waybill_xml` rs_waybill_soap_service.py:208](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L208) | rule 3: `SELER_UN_ID` = the company's stored `rs_un_id` instead of the login's `_get_seller_un_id()` | ~5 |
| [`_get_rs_sync_user`:19](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L19) | `Users.with_company(company).search(...)`; the existing domain on `rs_username` then finds users with a login **for that company**; drop the default-company preference | ~6 |
| `_rs_sync_contexts`, `_rs_run_per_company`, 8 sync methods, 36 wrappers, 8 lookups (barcodes, car numbers, driver names) | none | 0 |
| [test_sync_users.py](../custom_addons/gec_odoo_modules/rs_waybill/tests/test_sync_users.py) (11 refs), [test_sync_resilience.py](../custom_addons/gec_odoo_modules/rs_waybill/tests/test_sync_resilience.py) (1) | set credentials `with_company` | ~20 |

**employee_registry_rs** — about 50 lines

| Where | Change | Lines |
|---|---|---|
| [`_request`:111](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L111) | when `employee_id` is given: `user = self.env.user.with_company(employee.company_id)` | ~6 |
| [`_cron_sync_employees_to_rs`:572](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L572) | loop root companies with a responsible user instead of one cron record per entity | ~40 |
| digests [:619](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L619), [:654](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L654) | recipient = that company's responsible user | ~4 |
| `_check_rs_sync_allowed`, browser, 4 wrappers, 3 employee methods | none | 0 |

**Docs and strings:** [`employee_registry_rs.md`](employee_registry_rs.md) (per-user statements at lines
39-45 and 126-158), [`rs_einvoice.md`](rs_einvoice.md) (line 123), the two module READMEs, 28
Georgian strings in `rs_base_methods` and `rs_einvoice` `ka_GE.po`.

**Total:** 44 methods touched, about 330-350 lines, plus field declarations, views and tests.

---

## Core Compatibility — Proven

The design uses five core mechanisms and nothing else: `company_dependent` fields, computed proxies
with `depends_context('company')` and an inverse, `with_company()`, `user_writeable` fields on
`res.users`, and per-company cron loops with `with_user().with_company()`. The precedent for the proxy
is core's own `account.account.code` over `code_store`
([account_account.py:46-47](../addons/account/models/account_account.py#L46),
[:313-327](../addons/account/models/account_account.py#L313)).

Run on 2026-09-27 in an Odoo shell on the scratch database `scratch_rs_einvoice_buyer_test`
(a second company created inside the transaction, everything rolled back, nothing committed):

| # | Check | Result |
|---|---|---|
| 1 | Write a company-dependent Char (`res.partner.invoice_edi_format_store`) with `with_company(c1)` and `with_company(c2)`, read both back | c1 reads its value, c2 reads its own |
| 2 | Search that field through a relational `any` sub-domain from `res.users`, per company | found under c2 only, empty under c1 |
| 3 | `('field', '!=', False)` per company | each company sees only its own value |
| 4 | Core proxy in one transaction: set `account.code` under c2 (inverse writes `code_store` for c2), read under c1 and c2 | c1 unchanged (`101000`), c2 reads the new value: cache invalidation per company works |
| 5 | Non-superuser `with_company(c2)` when c2 is not in the user's Allowed Companies | `AccessError: Access to unauthorized or invalid companies` |
| 6 | Cron pattern `self.with_user(admin).with_company(c1)` | `env.user` = admin, `env.company` = c1 |

Not proven by running: the two rs.ge-side assumptions listed under Gotchas. Everything Odoo-side in the
four rules has a core precedent and a passing check above.

### Where core keeps external credentials

| Pattern | Core example | Fits |
|---|---|---|
| Per company, on `res.company`, admin-only | `l10n_in_ewaybill_username` ([res_company.py:9](../addons/l10n_in_ewaybill/models/res_company.py#L9)), `l10n_pl_edi_access_token` ([res_company.py:12](../addons/l10n_pl_edi/models/res_company.py#L12)) | one shared login per taxpayer |
| Per company, one record per company | `account_edi_proxy_client.user` ([account_edi_proxy_user.py:33](../addons/account_edi_proxy_client/models/account_edi_proxy_user.py#L33)) | same, with keys |
| Per user, on `res.users.settings` behind the owner rule | VoIP `voip_username` / `voip_secret` ([res_users_settings.py:84](../enterprise/voip/models/res_users_settings.py#L84)), Google Calendar refresh token ([res_users_settings.py:20](../addons/google_calendar/models/res_users_settings.py#L20)) | personal logins: what `rs_base_methods` does today |
| Per user **and** per company, user-writeable | `property_warehouse_id` on `res.users`: `company_dependent=True, user_writeable=True` ([sale_stock/res_users.py:9](../addons/sale_stock/models/res_users.py#L9)) | the plan: the same declaration, on the settings row so the owner rule keeps the password private |

The plan is the third pattern plus the fourth's `company_dependent`. If the three companies ever share one
login for everybody, the first pattern is the smaller design; it does not carry the personal REST login
with SMS pairing, which is why it was not chosen.

---

## Core Flows the Plan Sits On — Verified

Second pass, against the core `account`, `sale`, `purchase` and `stock` code our flows call, and a re-read
of our modules at the same points.

| Flow | Core rule | Our code | Verdict |
|---|---|---|---|
| Which company an invoice or bill belongs to | Computed from the journal; `env.company` only when the journal's company is one of its parents ([account_move.py:932](../addons/account/models/account_move.py#L932)); `_check_company_auto` and `check_company` on `partner_id` ([:88](../addons/account/models/account_move.py#L88), [:429](../addons/account/models/account_move.py#L429)) | Cron and Inbox create bills with an explicit purchase journal of `env.company` ([rs_einvoice_cron.py:202](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L202), [rs_buyer_inbox_wizard.py:209](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_buyer_inbox_wizard.py#L209)) | Consistent: under the per-company loop the bill lands in the loop's company |
| Core itself scopes work by the document's company | `move.with_company(move.company_id)` in eight `account.move` methods: fiscal position ([:1092](../addons/account/models/account_move.py#L1092)), payment term ([:1115](../addons/account/models/account_move.py#L1115)), preferred payment method ([:1564](../addons/account/models/account_move.py#L1564)), credit warning ([:2092](../addons/account/models/account_move.py#L2092)), COGS ([:5996](../addons/account/models/account_move.py#L5996)), QR method, partner onchange, qty available | Rule 2 (`_rs_get_service().with_company(self.company_id)`); our own `_rs_execute_cancel_and_reissue` already does it ([account_move_buyer.py:643](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L643)) | Same pattern as core |
| Taxes on pulled bill lines | Computed from the move's company ([account_move_line.py:1305](../addons/account/models/account_move_line.py#L1305)) | The 18% purchase tax is searched with `self.company_id` ([account_move_sync.py:666](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L666)); sibling and correction lookups too ([account_move.py:724](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L724), [account_move_buyer.py:634](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L634)) | Correct, no change |
| Invoicing a sale order | `_prepare_invoice` takes `self.company_id`; `_create_invoices` runs `order.with_company(order.company_id)` ([sale_order.py:2054](../addons/sale/models/sale_order.py#L2054)) | Invoice-from-waybill wizard uses `env.company` after refusing waybills of another company ([rs_waybill.py:152](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_waybill.py#L152), [rs_invoice_from_waybill_wizard.py:452](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L452)) | Consistent |
| Billing a purchase order | `order.with_company(order.company_id)` ([purchase_order.py:829](../addons/purchase/models/purchase_order.py#L829)), `company_id` of the order ([:1000](../addons/purchase/models/purchase_order.py#L1000)) | Not called by our modules; bills come from rs.ge or by hand | Nothing to align |
| Who sees which document | `company_id in company_ids` rows on `account.move`, `sale.order`, `purchase.order` ([account/ir.access.csv:37](../addons/account/security/ir.access.csv#L37), [sale/ir.access.csv:35](../addons/sale/security/ir.access.csv#L35), [purchase/ir.access.csv:6](../addons/purchase/security/ir.access.csv#L6)) | Same row on `rs.waybill` (plus legacy `company_id = False` rows) and on every rs_einvoice model ([rs_waybill/ir.access.csv:3](../custom_addons/gec_odoo_modules/rs_waybill/security/ir.access.csv#L3), [rs_einvoice/ir.access.csv](../custom_addons/gec_odoo_modules/rs_einvoice/security/ir.access.csv)) | Consistent: a document a user can open is one whose company they may switch to |
| Stock | `stock.picking.company_id` from the picking type ([stock_picking.py:114](../addons/stock/models/stock_picking.py#L114)) | Waybill address from `warehouse.company_id or env.company` ([stock_picking.py:392](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L392)) | Consistent |

Finding from this pass, outside the credential plan: **no `check_company` anywhere in our four modules**.
`rs.waybill` links `sales_order_id`, `purchase_id`, `picking_id`, `buyer_id`, `driver_partner_id` to
company-scoped records without `check_company=True`, and its `company_id` has no `_check_company_auto`
([rs_waybill.py:82-192](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L82)); core
enforces it on `sale.order` ([sale_order.py:48](../addons/sale/models/sale_order.py#L48)) and
`account.move`. A waybill of Alpha can today point at Beta's sale order. Hardening: `_check_company_auto
= True` plus `check_company=True` on those five fields, about 10 lines; `company_id` cannot become
`required` while the legacy `company_id = False` rows exist.

---

## Crons — Today, After, and Whether They Stay Safe

| Cron (Scheduler User uid 1 on prod1) | Calls rs.ge | Today | After | Safety after |
|---|---|---|---|---|
| RS E-Invoice: Sync Buyer Invoices ([:136](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L136)) | Yes | One responsible user, its default company only | One pass per company as its responsible user, main company first; a bill that any company with the same Tax ID already holds is skipped (no duplicate in a branch) | Safe: advisory lock per company ([:214](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L214)) and a savepoint per bill already exist; add a `_commit_progress` after each company so one company's failure never rolls back another's bills |
| RS E-Invoice: Refresh Buyer / Seller Status ([:440](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L440)) | Yes | Runs as uid 1 without a login: one warning per candidate, nothing refreshed | One batch per company that has a responsible user (a company without one cannot use up the batch), each refreshed as that user | Safe: skip-locked row lock ([:477](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L477)), savepoint and `_commit_progress` per move stay; `with_user` per move changes only the env |
| RS E-Invoice: Recover Stranded Cancellations | No | Already `with_company(locked.company_id)` ([:572](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L572)) | Unchanged | Safe |
| RS E-Invoice: Escalate, Stuck Sends, Vacuum, Deadline Check | No | Company-neutral | Unchanged | Safe |
| RS.GE: Sync Updated / Templates / Transporter / Drift Repair ([:287](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L287), [:1082](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L1082)) | Yes | One pass per company, borrowing a user whose default company matches | Same loop; the user lookup reads the per-company login | Safe: `_rs_run_per_company` rolls back a failed company and continues ([:101](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L101)); rows commit as they go |
| RS Employee Registry: Daily Sync ([:572](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L572)) | Yes | Cron user's company and branches; uid 1 has no login, so it no-ops today | One pass per root company as its responsible user | Safe: savepoint and `_commit_progress` per employee stay ([:600](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L600)); wrap each company in try/except |
| RS Employee Registry: Log Rotation | No | — | Unchanged | Safe |

Rule for the loop, shared by the three modules: for each company with a TIN, take the active user whose
`rs_is_responsible` is set for that company and who has a login for it; run
`self.with_user(user).with_company(company)`; on exception, log, roll back that company's savepoint and
continue with the next. This is what `rs_waybill` does today; e-invoice and the registry get the same.

---

## Day-to-Day After the Change (case C)

Dato switches to Alpha: Preferences > Revenue Service, enters `alpha_srv`, Test SOAP (Odoo checks the
login belongs to TIN 2001 and stores the SOAP user id), Test REST (SMS PIN, pairs the device), ticks
RS responsible. Switches to Beta and Gamma: same. Three logins, three pairings, one Odoo user.

Then: in Alpha he creates and sends Alpha's invoices with `alpha_srv`. If Beta is also ticked and he
opens a Beta invoice, Odoo uses `beta_srv`, because the document belongs to Beta. The rs.ge Inbox in
Beta lists Beta's incoming invoices and imports them into Beta. Beta's employees go to Beta's registry.
Every night the crons run three times, once per company, all as Dato.

---

## Gotchas & Open Points

- **No migration script.** Existing values (one user on prod1) are re-entered by hand per company; the
  old columns stay unused.
- **Phase 0, three live tests with a real login (the second and third need a login that represents two
  taxpayers):** (1) the waybill service's `chek_service_user.un_id` equals the e-invoice
  `get_un_id_from_tin` for the same taxpayer, so one stored id serves both services; (2) `save_invoice`
  on a draft and `get_user_invoices` with the **other** taxpayer's id are accepted for a representative
  login; (3) `get_waybills` for that login returns the other taxpayer's rows and `save_waybill` accepts
  its `SELER_UN_ID`. (1) failing means rule 3 stores and compares TINs instead of ids; (2) or (3) failing
  means B and D exist only with a shared TIN, for e-invoices or waybills respectively.
- **Same TIN on several companies (branches or one entity split):** rules 1-4 work, but incoming supplier
  invoices and waybills addressed to that TIN need a routing rule and a cross-company duplicate check.
  About one extra day, not in the estimate.
- **Dependency inversion stays:** `rs_base_methods` depends on the three modules and they reach its
  credential methods with `getattr` ([rs_soap_service.py:157](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L157)).
  The per-company responsible lookup is needed by all three crons; either write it three times or move
  the credential layer into a small base module the three depend on (about half a day).
- **Branches:** every check in `rs_einvoice` is strict `company_id ==`; `employee_registry_rs` uses
  `root_id`. Decide once whether a branch uses the root company's login.
- **`check_company` hardening (optional, see "Core Flows"):** about 10 lines in `rs.waybill`; independent
  of the credential change, worth doing in the same release because the second and third company make
  cross-company links possible for the first time.
- **Barcodes and car numbers are per taxpayer:** with three logins, each company pushes its products and
  vehicles from its own company. No code change; an operating rule.

---

## Implementation Status (2026-09-29)

Phases 1-5 are implemented, uncommitted; `gec20_prod1` is not upgraded. The source links in the
sections above point at the code **before** the change (analysis of 2026-09-27); the appendix keeps
that state on purpose. Verified on the scratch database `scratch_rs_einvoice_buyer_test`:

| Phase | Done | Proof |
|---|---|---|
| 0 | Test (1) passed on prod1 with the stored login: taxpayer id `731937` in both services, equal to the id from the company TIN, so one stored id serves both. Tests (2) and (3) still need a login authorized on two taxpayers | read-only shell, rolled back |
| 1 | Company-dependent fields on `res.users.settings`; nine computed proxies on `res.users` sharing one compute (`depends_context('uid', 'company')`) with factory-made inverses; reset per company; one responsible per company (constraint on the settings row); Test SOAP stores `rs_user_id` and the company's `rs_un_id`, and probes a representative login with one read; PIN wizard carries the company; session-info blacklist; `res.users._rs_responsible_user(company)` | 9-step shell test |
| 2 | `_rs_get_service()` bound to the document's company; default-company guard deleted; `rs.soap.service._rs_company_un_id()` at the six sites; `rs.einvoice.cron._rs_company_passes()`, buyer sync and both refresh crons one pass per company as its responsible user, failures isolated per company | 4-step shell test with a patched service |
| 3 | `rs.waybill._rs_service()` at the 24 sites; `SELER_UN_ID` from the company's stored id (`_rs_company_un_id(waybill)`); `_get_rs_sync_user(company)` takes the responsible user, else any login holder for that company; tests adapted (logins written per company, mocked client stubs the taxpayer id) | rs_waybill suite |
| 4 | `_request` runs under the employee's root company; daily sync one pass per root company as its responsible user (`_cron_sync_company_employees`), failures isolated | shell test |
| 5 | READMEs of rs_waybill and employee_registry_rs, the new README pair and `developer_map.html` of rs_einvoice, this file, `employee_registry_rs.md`, `rs_einvoice.md`, both CODE_REVIEW files. Georgian strings (`ka_GE.po`) not yet updated | — |

Done in the same session on top of the phases, also uncommitted: the rs_einvoice code-quality refactor (an offline SOAP test harness with 12 tests, the write() audit helper and the inbox parent lookup, `account_move.py` split into `account_move_cancel.py` and `account_move_checks.py`, outlines for the five longest methods; user texts unchanged, verified by inventory compare), the items adopted from Odoo's `l10n_ge_edi` (partner taxpayer cache `res.partner.rs_un_id`, DataTable envelopes built by zeep, the journal dashboard refresh hook, Reset to Draft hidden on rs.ge bills), and on `rs.waybill` `_check_company_auto = True` with `check_company=True` on the transfer, warehouses, buyer, driver, vehicle, sale and purchase order fields (rs_waybill suite: 216 tests, 0 failures; `gec20_prod1` holds no waybill without a company and no cross-company link, checked by SELECT).

Cutover on prod1: `-u rs_base_methods,rs_einvoice,rs_waybill,employee_registry_rs`; then in each
company: switch to it, Preferences → Revenue Service (rs.ge), enter the login, Test SOAP, Test REST
(SMS PIN), tick RS Responsible User. The old single-slot values are not migrated; `admin`'s login on
prod1 is re-entered once. Enable the e-invoice crons afterwards.

Lesson from the verification: `ir.cron._commit_progress` commits even from `odoo shell`, so never
exercise a cron method in a shell on a database that must stay unchanged.

---

## Estimate and Phases

| Phase | Content | Days |
|---|---|---|
| 0 | three live rs.ge tests (see Gotchas); they decide the B and D mechanics | 0.25 |
| 1 | rs_base_methods: company-dependent fields, company taxpayer id at Test SOAP, PIN wizard, views | 1 |
| 2 | rs_einvoice: service scoping, guard removal, company taxpayer id at 6 sites, two cron loops | 1 |
| 3 | rs_waybill: helper + 24 sites, XML taxpayer id, sync user lookup, test updates | 1 |
| 4 | employee_registry_rs: `_request`, cron loop, digests | 0.5 |
| 5 | docs, strings, prod1 cutover (re-enter credentials per company) | 0.5 |
| 6 | only if a shared TIN exists: Layer 3 routing of incoming documents + cross-company duplicate check | 1 |

About 4 days for A-D with three TINs; plus 1 day for a shared TIN; plus 1 day if new tests are wanted
(credential per company, cron loops, wrong-login refusal).
Each phase is approved before it starts and committed by the user when it passes.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`rs_einvoice.md`](rs_einvoice.md) — the sales and purchase flows the crons and buttons above serve
- [`employee_registry_rs.md`](employee_registry_rs.md) — the registry cron and its "one login per legal entity" rule
- [`rs_waybill_fix_plan.md`](../dev_notes/plans/rs_waybill_fix_plan.md) — waybill corrections; independent of this change
- [`CODE_REVIEW.md`](../custom_addons/gec_odoo_modules/rs_einvoice/CODE_REVIEW.md) — items 1.1 and 3.x are resolved by this design

---

## Appendix — Method Inventory

Generated from the source with `ast` on 2026-09-27. One table per module; only methods that call rs.ge,
read `env.user` or `env.company`, filter by company, or are a cron or button are listed. Columns:
the route a rs.ge call takes, where the company comes from today, and the change with an approximate
line count. "none" means the method is correct as soon as its caller passes the company.

### rs_base_methods — 93 methods, 47 listed, 8 change

| Method | File | rs.ge route | Company today | Change (approx. lines) |
|---|---|---|---|---|
| `AccountMove._rs_sync_waybill_links` | [account_move.py:105](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L105) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_find_product_for_pulled` | [account_move.py:194](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L194) | - | record `company_id` | none |
| `AccountMove._rs_refresh_waybill_links` | [account_move.py:217](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L217) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove.action_rs_edit` | [account_move.py:262](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L262) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove.action_rs_send` | [account_move.py:269](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L269) | - | - | none |
| `AccountMove.action_rs_delete` | [account_move.py:285](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L285) | - | - | none |
| `AccountMove.action_rs_refresh_status` | [account_move.py:297](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L297) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove._rs_carry_waybill_links_to_replacement` | [account_move.py:304](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L304) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove.action_open_rs_waybill_links` | [account_move.py:348](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L348) | - | - | none |
| `AccountMove._rs_sync_buyer_waybill_links` | [account_move.py:364](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L364) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove.action_rs_sync_buyer_waybills` | [account_move.py:437](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L437) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove.action_rs_buyer_pull` | [account_move.py:452](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L452) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove._rs_link_purchase_order_lines` | [account_move.py:472](../custom_addons/gec_odoo_modules/rs_base_methods/models/account_move.py#L472) | - | record `company_id` | none |
| `ResUsers._compute_rs_credentials` | [res_users.py:103](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L103) | credential layer | stored once per user | compute all 8 credential fields from settings, `depends_context('company')` (25) |
| `ResUsers._inverse_rs_username` | [res_users.py:113](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L113) | credential layer | stored once per user | write `settings.with_company(env.company)` (3) |
| `ResUsers._inverse_rs_password` | [res_users.py:120](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L120) | credential layer | stored once per user | same; plus one inverse per moved field (20) |
| `ResUsers.write` | [res_users.py:125](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L125) | credential layer | stored once per user | reset token, user id and device pairing for `env.company` only (8) |
| `ResUsers._check_single_rs_responsible` | [res_users.py:143](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L143) | credential layer | stored once per user | one responsible per company (`with_company` count) (10) |
| `ResUsers._get_rs_credentials` | [res_users.py:162](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L162) | credential layer | stored once per user | error names the company (2) |
| `ResUsers.action_rs_test_credentials` | [res_users.py:180](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L180) | credential layer | stored once per user | resolve the login's taxpayer TIN, refuse if not `env.company.vat`, store `rs_user_id` + `rs_un_id` per company (25) |
| `ResUsers._rs_rest_authenticate_step1` | [res_users.py:265](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L265) | credential layer | stored once per user | none: reads and writes go through the per-company computed fields |
| `ResUsers._rs_rest_authenticate` | [res_users.py:317](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L317) | credential layer | stored once per user | none: reads and writes go through the per-company computed fields |
| `ResUsers._get_rs_rest_token` | [res_users.py:353](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L353) | credential layer | stored once per user | none: reads and writes go through the per-company computed fields |
| `ResUsers.action_rs_test_rest_credentials` | [res_users.py:358](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L358) | credential layer | stored once per user | none: reads and writes go through the per-company computed fields |
| `ResUsers._rs_rest_authenticated_call` | [res_users.py:424](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L424) | credential layer | stored once per user | none: reads and writes go through the per-company computed fields |
| `ResUsers.action_rs_signout_rest` | [res_users.py:571](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L571) | credential layer | stored once per user | none: reads and writes go through the per-company computed fields |
| `ResUsers._rs_rest_get_transaction_result` | [res_users.py:593](../custom_addons/gec_odoo_modules/rs_base_methods/models/res_users.py#L593) | credential layer | stored once per user | none: reads and writes go through the per-company computed fields |
| `RsEinvoiceWaybillLink._detach_remote` | [rs_einvoice_waybill_link.py:199](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_einvoice_waybill_link.py#L199) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `RsSoapService.save_invoice_waybill_link` | [rs_soap_service.py:25](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_soap_service.py#L25) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.delete_invoice_waybill_link` | [rs_soap_service.py:48](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_soap_service.py#L48) | service wrapper | `env.user` of the caller | none |
| `RsWaybill.action_view_rs_invoices` | [rs_waybill.py:55](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_waybill.py#L55) | - | - | none |
| `RsWaybill.action_refuse_waybill` | [rs_waybill.py:86](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_waybill.py#L86) | - | - | none |
| `RsWaybill.action_edit_waybill` | [rs_waybill.py:90](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_waybill.py#L90) | - | - | none |
| `RsWaybill.action_submit_edit_to_rs` | [rs_waybill.py:94](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_waybill.py#L94) | - | - | none |
| `RsWaybill.action_delete_waybill` | [rs_waybill.py:98](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_waybill.py#L98) | - | - | none |
| `RsWaybill._validate_waybills_for_invoicing` | [rs_waybill.py:106](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_waybill.py#L106) | - | `env.company` | none |
| `RsWaybill.action_open_invoice_from_waybill_wizard` | [rs_waybill.py:230](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_waybill.py#L230) | - | - | none |
| `RsWaybill.action_save_invoice` | [rs_waybill.py:246](../custom_addons/gec_odoo_modules/rs_base_methods/models/rs_waybill.py#L246) | - | - | none |
| `SaleOrder.action_open_rs_invoice_from_waybill_wizard` | [sale_order.py:21](../custom_addons/gec_odoo_modules/rs_base_methods/models/sale_order.py#L21) | - | - | none |
| `RsAuthPinWizard.action_confirm` | [rs_auth_pin_wizard.py:30](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_auth_pin_wizard.py#L30) | - | - | add `company_id`; `user_id.with_company(company_id)._rs_rest_complete_pin()` (6) |
| `RsInvoiceFromWaybillWizard._resolve_currency` | [rs_invoice_from_waybill_wizard.py:93](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L93) | - | `env.company` | none |
| `RsInvoiceFromWaybillWizard._default_journal` | [rs_invoice_from_waybill_wizard.py:108](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L108) | - | `env.company` | none |
| `RsInvoiceFromWaybillWizard._validate_preflight` | [rs_invoice_from_waybill_wizard.py:224](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L224) | - | `env.company` | none |
| `RsInvoiceFromWaybillWizard._prepare_invoice_vals` | [rs_invoice_from_waybill_wizard.py:436](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L436) | - | `env.company` | none |
| `RsInvoiceFromWaybillWizard.action_create_invoice` | [rs_invoice_from_waybill_wizard.py:504](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L504) | - | - | none |
| `RsInvoiceFromWaybillWizardLine._rs_prefetch_sale_line_candidates` | [rs_invoice_from_waybill_wizard_line.py:62](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard_line.py#L62) | - | `env.company` | none |
| `RsInvoiceFromWaybillWizardLine._match_sale_line` | [rs_invoice_from_waybill_wizard_line.py:91](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard_line.py#L91) | - | `env.company` | none |

### rs_einvoice — 224 methods, 101 listed, 6 change

| Method | File | rs.ge route | Company today | Change (approx. lines) |
|---|---|---|---|---|
| `AccountMove._compute_rs_einv_parties` | [account_move.py:397](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L397) | - | record `company_id` | none |
| `AccountMove._cron_rs_einv_check_deadlines` | [account_move.py:577](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L577) | cron | - | none |
| `AccountMove._rs_notify` | [account_move.py:679](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L679) | - | `env.user` | none |
| `AccountMove._rs_find_other_move_by_rs_id` | [account_move.py:716](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L716) | - | record `company_id` | none |
| `AccountMove._rs_get_fx_rate` | [account_move.py:744](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L744) | - | record `company_id` | none |
| `AccountMove._rs_verify_tin_identity` | [account_move.py:772](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L772) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_schedule_manual_reversal_activity` | [account_move.py:812](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L812) | - | `env.user` | none |
| `AccountMove._rs_is_prior_vat_period` | [account_move.py:966](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L966) | - | record `company_id` | none |
| `AccountMove._rs_validate` | [account_move.py:1108](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1108) | - | `env.user` | delete the default-company guard (lines 1112-1121) (-10) |
| `AccountMove.write` | [account_move.py:1508](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1508) | - | `env.user` | none |
| `AccountMove._rs_get_service` | [account_move.py:2012](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L2012) | document via `_rs_get_service()` | none passed (active login) | `return self.env['rs.soap.service'].with_company(self.company_id)` (1) |
| `AccountMove._rs_get_correction_base_id` | [account_move.py:2029](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L2029) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove._rs_push_header_to_rs` | [account_move.py:2173](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L2173) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_target_is_correction` | [account_move.py:2236](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L2236) | - | record `company_id` | none |
| `AccountMove.action_rs_buyer_pull` | [account_move_buyer.py:26](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L26) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove.action_rs_buyer_reimport_lines` | [account_move_buyer.py:225](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L225) | - | - | none |
| `AccountMove.action_rs_buyer_accept` | [account_move_buyer.py:353](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L353) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove._rs_check_cancel_reissue_blockers` | [account_move_buyer.py:458](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L458) | - | record `company_id` | none |
| `AccountMove._rs_execute_cancel_and_reissue` | [account_move_buyer.py:533](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L533) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove.action_rs_import_supplier_correction` | [account_move_buyer.py:750](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L750) | - | - | none |
| `AccountMove.action_rs_buyer_reject` | [account_move_buyer.py:789](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L789) | - | - | none |
| `AccountMove._rs_do_buyer_reject` | [account_move_buyer.py:817](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L817) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove.action_rs_resolve_orphan` | [account_move_buyer.py:934](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L934) | - | - | none |
| `AccountMove._rs_do_resolve_orphan` | [account_move_buyer.py:960](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L960) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove.action_rs_clear_pending` | [account_move_buyer.py:1076](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L1076) | - | - | none |
| `AccountMove.action_rs_view_reversals` | [account_move_buyer.py:1105](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L1105) | - | - | none |
| `AccountMove.action_rs_view_replacement` | [account_move_buyer.py:1124](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L1124) | - | - | none |
| `AccountMove.action_rs_view_replaces` | [account_move_buyer.py:1138](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L1138) | - | - | none |
| `AccountMove.action_rs_clear_cancelled_replacement_link` | [account_move_buyer.py:1152](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L1152) | - | - | none |
| `AccountMove._rs_do_correct_reissue` | [account_move_reissue.py:182](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_reissue.py#L182) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove.action_rs_create` | [account_move_seller.py:20](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L20) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove._rs_create_invoice` | [account_move_seller.py:101](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L101) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_expected_advance_settlements` | [account_move_seller.py:194](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L194) | - | record `company_id` | none |
| `AccountMove._rs_diagnose_unattachable` | [account_move_seller.py:376](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L376) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_advance_settlement_usage` | [account_move_seller.py:408](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L408) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_sync_native_advance_settlements` | [account_move_seller.py:473](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L473) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_create_invoice_correction` | [account_move_seller.py:677](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L677) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove.action_rs_edit` | [account_move_seller.py:790](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L790) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove.action_rs_delete` | [account_move_seller.py:835](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L835) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove.action_rs_send` | [account_move_seller.py:913](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L913) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove.action_rs_cancel` | [account_move_seller.py:1054](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L1054) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_cancel_core` | [account_move_seller.py:1084](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L1084) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove._rs_apply_status_update` | [account_move_seller.py:1147](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L1147) | - | record `company_id` | none |
| `AccountMove.action_rs_refresh_status` | [account_move_sync.py:20](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L20) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `AccountMove._rs_refresh_supplier_correction` | [account_move_sync.py:154](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L154) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_refresh_legacy_corrections` | [account_move_sync.py:199](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L199) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_refresh_replacements` | [account_move_sync.py:225](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L225) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_sync_lines` | [account_move_sync.py:292](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L292) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove._rs_amount_to_gel` | [account_move_sync.py:614](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L614) | - | record `company_id` | none |
| `AccountMove._rs_get_purchase_vat_18` | [account_move_sync.py:663](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L663) | - | record `company_id` | none |
| `AccountMove._rs_find_product_for_pulled` | [account_move_sync.py:700](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L700) | - | record `company_id` | none |
| `AccountMove._rs_refresh_pulled_lines` | [account_move_sync.py:747](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L747) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `AccountMove.action_rs_view_current_data` | [account_move_sync.py:808](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L808) | - | - | none |
| `AccountMoveRsCron._cron_sync_buyer_invoices` | [rs_einvoice_cron.py:136](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L136) | cron | - | loop companies with a responsible user: `with_user(u).with_company(c)._sync_one_user()`, failures isolated per company (35) |
| `AccountMoveRsCron._sync_one_user` | [rs_einvoice_cron.py:173](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L173) | direct `rs.soap.service` | `env.company` | none: active company is the right company; `_check_auth` identity check applies |
| `AccountMoveRsCron._cron_escalate_pending_actions` | [rs_einvoice_cron.py:300](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L300) | cron | - | none |
| `AccountMoveRsCron._cron_detect_stuck_sends` | [rs_einvoice_cron.py:353](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L353) | cron | - | none |
| `AccountMoveRsCron._cron_refresh_status` | [rs_einvoice_cron.py:440](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L440) | cron | - | group candidates by company, run each as the company's responsible user, skip + log a company without one (25) |
| `AccountMoveRsCron._cron_refresh_buyer_status` | [rs_einvoice_cron.py:519](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L519) | cron | - | none |
| `AccountMoveRsCron._cron_refresh_seller_status` | [rs_einvoice_cron.py:523](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L523) | cron | - | none |
| `AccountMoveRsCron._cron_rs_recover_stranded_cancellations` | [rs_einvoice_cron.py:527](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L527) | cron | - | none |
| `AccountMoveRsCron._cron_vacuum_rs_logs` | [rs_einvoice_cron.py:600](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L600) | cron | - | none |
| `RsEinvoiceLog._cron_vacuum` | [rs_einvoice_models.py:148](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_models.py#L148) | cron | - | none |
| `RsEinvoiceCorrectionLine._compute_company_id` | [rs_einvoice_models.py:227](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_models.py#L227) | - | record `company_id` | none |
| `RsEinvoiceCorrectionLine._cron_vacuum_snapshots` | [rs_einvoice_models.py:240](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_models.py#L240) | cron | - | none |
| `RsSoapService._get_credentials` | [rs_soap_service.py:150](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L150) | service wrapper | `env.user` of the caller | error names the company (3) |
| `RsSoapService._raw_call` | [rs_soap_service.py:240](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L240) | service wrapper | `env.user` of the caller | none |
| `RsSoapService._check_auth` | [rs_soap_service.py:273](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L273) | service wrapper | `env.user` of the caller | identity check: login taxpayer == `get_un_id_from_tin(env.company.vat)`, cached per login and company (25) |
| `RsSoapService.get_un_id_from_tin` | [rs_soap_service.py:289](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L289) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.get_seller_un_id` | [rs_soap_service.py:307](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L307) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.get_party_from_un_id` | [rs_soap_service.py:316](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L316) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.save_invoice` | [rs_soap_service.py:331](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L331) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.save_invoice_desc` | [rs_soap_service.py:371](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L371) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.delete_invoice_desc` | [rs_soap_service.py:396](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L396) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.change_invoice_status` | [rs_soap_service.py:401](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L401) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.buyer_accept_invoice` | [rs_soap_service.py:430](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L430) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.buyer_reject_invoice` | [rs_soap_service.py:442](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L442) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.get_invoice` | [rs_soap_service.py:450](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L450) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.get_invoice_desc` | [rs_soap_service.py:455](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L455) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.get_invoice_waybills` | [rs_soap_service.py:471](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L471) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.get_attachable_advance_invoices` | [rs_soap_service.py:484](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L484) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.get_attached_advance_invoices` | [rs_soap_service.py:502](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L502) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.attach_advance_invoice` | [rs_soap_service.py:512](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L512) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.update_advance_invoice` | [rs_soap_service.py:535](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L535) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.create_correction` | [rs_soap_service.py:559](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L559) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.get_makoreqtirebeli` | [rs_soap_service.py:566](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L566) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.get_buyer_invoices` | [rs_soap_service.py:589](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L589) | service wrapper | `env.user` of the caller | none |
| `RsSoapService.get_user_invoices` | [rs_soap_service.py:614](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py#L614) | service wrapper | `env.user` of the caller | none |
| `RsBuyerInboxWizard._resolve_company_un_id` | [rs_buyer_inbox_wizard.py:86](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_buyer_inbox_wizard.py#L86) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `RsBuyerInboxWizard.action_search` | [rs_buyer_inbox_wizard.py:97](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_buyer_inbox_wizard.py#L97) | direct `rs.soap.service` | `env.company` | none: active company is the right company; `_check_auth` identity check applies |
| `RsBuyerInboxWizard.action_toggle_all` | [rs_buyer_inbox_wizard.py:193](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_buyer_inbox_wizard.py#L193) | - | - | none |
| `RsBuyerInboxWizard.action_import_selected` | [rs_buyer_inbox_wizard.py:198](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_buyer_inbox_wizard.py#L198) | - | `env.company` | none |
| `RsBuyerInboxLine._do_import` | [rs_buyer_inbox_wizard.py:385](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_buyer_inbox_wizard.py#L385) | - | `env.company` | none |
| `RsOrphanResolveWizard.action_confirm` | [rs_einvoice_orphan_wizard.py:23](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_einvoice_orphan_wizard.py#L23) | - | - | none |
| `RsRejectWizard.action_confirm` | [rs_einvoice_reject_wizard.py:24](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_einvoice_reject_wizard.py#L24) | - | - | none |
| `RsEinvoiceViewWizard._build_from_move` | [rs_einvoice_view_wizard.py:40](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_einvoice_view_wizard.py#L40) | document via `_rs_get_service()` | none passed (active login) | none: covered by the `_rs_get_service` change |
| `RsEinvoiceViewWizard._safe_party` | [rs_einvoice_view_wizard.py:97](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_einvoice_view_wizard.py#L97) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `RsEinvoiceViewWizard._build_goods` | [rs_einvoice_view_wizard.py:105](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_einvoice_view_wizard.py#L105) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `RsEinvoiceViewWizard._build_advances` | [rs_einvoice_view_wizard.py:138](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_einvoice_view_wizard.py#L138) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `RsEinvoiceViewWizard._build_waybills` | [rs_einvoice_view_wizard.py:161](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_einvoice_view_wizard.py#L161) | document, service passed by caller | inherited from `_rs_get_service()` | none: the caller passes a company-scoped service |
| `RsReplacePreview.action_confirm` | [rs_replace_preview_wizard.py:34](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/rs_replace_preview_wizard.py#L34) | - | - | none |

### rs_waybill — 254 methods, 140 listed, 26 change

| Method | File | rs.ge route | Company today | Change (approx. lines) |
|---|---|---|---|---|
| `FleetVehicle.action_update_rs_vehicle` | [fleet_vehicle.py:51](../custom_addons/gec_odoo_modules/rs_waybill/models/fleet_vehicle.py#L51) | direct, lookup | `env.company` (fine) | none |
| `ProductTemplate.action_send_single_barcode` | [product_product.py:65](../custom_addons/gec_odoo_modules/rs_waybill/models/product_product.py#L65) | direct, lookup | `env.company` (fine) | none |
| `ProductTemplate.action_send_bulk_to_rs` | [product_product.py:111](../custom_addons/gec_odoo_modules/rs_waybill/models/product_product.py#L111) | direct, lookup | `env.company` (fine) | none |
| `ProductProduct.action_send_single_barcode` | [product_product.py:182](../custom_addons/gec_odoo_modules/rs_waybill/models/product_product.py#L182) | - | - | none |
| `ProductProduct.action_update_rs_products` | [product_product.py:190](../custom_addons/gec_odoo_modules/rs_waybill/models/product_product.py#L190) | direct, lookup | `env.company` (fine) | none |
| `PurchaseOrder.action_view_waybills` | [purchase_order.py:31](../custom_addons/gec_odoo_modules/rs_waybill/models/purchase_order.py#L31) | - | - | none |
| `ResConfigSettings.action_sync_templates` | [res_config_settings.py:34](../custom_addons/gec_odoo_modules/rs_waybill/models/res_config_settings.py#L34) | - | - | none |
| `ResConfigSettings.action_update_rs_products` | [res_config_settings.py:38](../custom_addons/gec_odoo_modules/rs_waybill/models/res_config_settings.py#L38) | - | - | none |
| `ResConfigSettings.action_update_car_numbers` | [res_config_settings.py:42](../custom_addons/gec_odoo_modules/rs_waybill/models/res_config_settings.py#L42) | - | - | none |
| `ResConfigSettings.action_sync_seller_waybills` | [res_config_settings.py:46](../custom_addons/gec_odoo_modules/rs_waybill/models/res_config_settings.py#L46) | - | - | none |
| `ResConfigSettings.action_sync_buyer_waybills` | [res_config_settings.py:50](../custom_addons/gec_odoo_modules/rs_waybill/models/res_config_settings.py#L50) | - | - | none |
| `ResConfigSettings.action_sync_transporter_waybills` | [res_config_settings.py:54](../custom_addons/gec_odoo_modules/rs_waybill/models/res_config_settings.py#L54) | - | - | none |
| `ResConfigSettings.action_sync_all_waybills` | [res_config_settings.py:58](../custom_addons/gec_odoo_modules/rs_waybill/models/res_config_settings.py#L58) | - | - | none |
| `ResPartner._create_driver_from_tin` | [res_partner.py:21](../custom_addons/gec_odoo_modules/rs_waybill/models/res_partner.py#L21) | direct, lookup | `env.company` (fine) | none |
| `ResPartner.name_create` | [res_partner.py:47](../custom_addons/gec_odoo_modules/rs_waybill/models/res_partner.py#L47) | direct, lookup | `env.company` (fine) | none |
| `RsWaybill._compute_rs_menu_side` | [rs_waybill.py:270](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L270) | - | `env.company` | none |
| `RsWaybill._search_rs_menu_side` | [rs_waybill.py:286](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L286) | - | `env.company` | none |
| `RsWaybill._compute_is_own_transport` | [rs_waybill.py:323](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L323) | - | `env.company` | none |
| `RsWaybill._compute_adjustment_count` | [rs_waybill.py:355](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L355) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill._onchange_transporter_tin` | [rs_waybill.py:425](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L425) | direct, lookup | `env.company` (fine) | none |
| `RsWaybill._onchange_driver_tin_lookup` | [rs_waybill.py:469](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L469) | direct, lookup | `env.company` (fine) | none |
| `RsWaybill._mapping_enabled` | [rs_waybill.py:561](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L561) | - | `env.company` | none |
| `RsWaybill._in_integration_scope` | [rs_waybill.py:577](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L577) | - | `env.company` | none |
| `RsWaybill._get_notification_users` | [rs_waybill.py:654](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L654) | - | `env.company` | none |
| `RsWaybill._rs_match_warehouse_by_address` | [rs_waybill.py:662](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L662) | - | record `company_id` | none |
| `RsWaybill._validate_before_save` | [rs_waybill.py:745](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L745) | - | `env.company` | none |
| `RsWaybill._rs_create_so_and_delivery_from_waybill` | [rs_waybill.py:882](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L882) | - | record `company_id` | none |
| `RsWaybill._rs_create_return_delivery_from_waybill` | [rs_waybill.py:971](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L971) | - | record `company_id` | none |
| `RsWaybill._rs_create_internal_transfer_from_waybill` | [rs_waybill.py:1040](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L1040) | - | record `company_id` | none |
| `RsWaybill._rs_create_return_transfer_from_waybill` | [rs_waybill.py:1074](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L1074) | - | record `company_id` | none |
| `RsWaybill._rs_build_moves_on_picking` | [rs_waybill.py:1102](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L1102) | - | record `company_id` | none |
| `RsWaybill._apply_line_diffs_to_picking_in_place` | [rs_waybill.py:1230](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L1230) | - | record `company_id` | none |
| `RsWaybill._action_reverse_completed_waybill` | [rs_waybill.py:1504](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L1504) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill._reconcile_buyer_decrease_done` | [rs_waybill.py:1793](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L1793) | - | record `company_id` | none |
| `RsWaybill.action_open_sales_order` | [rs_waybill_actions.py:17](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L17) | - | - | none |
| `RsWaybill.action_open_purchase_order` | [rs_waybill_actions.py:28](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L28) | - | - | none |
| `RsWaybill.action_open_picking` | [rs_waybill_actions.py:39](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L39) | - | - | none |
| `RsWaybill.action_open_mapping_wizard` | [rs_waybill_actions.py:50](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L50) | - | - | none |
| `RsWaybill.action_view_adjustments` | [rs_waybill_actions.py:76](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L76) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_save_to_rs` | [rs_waybill_actions.py:106](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L106) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_send_rs_waybill` | [rs_waybill_actions.py:145](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L145) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_edit_waybill` | [rs_waybill_actions.py:180](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L180) | - | - | none |
| `RsWaybill.action_submit_edit_to_rs` | [rs_waybill_actions.py:202](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L202) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_update_rs_status` | [rs_waybill_actions.py:315](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L315) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill._close_on_rs` | [rs_waybill_actions.py:401](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L401) | document, service passed by caller | inherited from the action | none: the caller passes a company-scoped service |
| `RsWaybill.action_close_waybill` | [rs_waybill_actions.py:433](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L433) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_refuse_waybill` | [rs_waybill_actions.py:500](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L500) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_delete_waybill` | [rs_waybill_actions.py:545](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L545) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_confirm_waybill` | [rs_waybill_actions.py:563](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L563) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_reject_waybill` | [rs_waybill_actions.py:634](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L634) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_reconcile_pending_return` | [rs_waybill_actions.py:659](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L659) | - | - | none |
| `RsWaybill.action_send_carrier_waybill` | [rs_waybill_actions.py:680](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L680) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_save_transporter` | [rs_waybill_actions.py:709](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L709) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_active_transporter` | [rs_waybill_actions.py:725](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L725) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_close_transporter` | [rs_waybill_actions.py:741](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L741) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_save_invoice` | [rs_waybill_actions.py:760](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L760) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_create_sub_waybill` | [rs_waybill_actions.py:780](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L780) | - | - | none |
| `RsWaybill.action_create_sub_waybill_internal_trans` | [rs_waybill_actions.py:786](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L786) | - | - | none |
| `RsWaybill._create_sub_waybill` | [rs_waybill_actions.py:790](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L790) | - | record `company_id` | none |
| `RsWaybill.action_create_remainder_waybill` | [rs_waybill_actions.py:842](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L842) | - | record `company_id` | none |
| `RsWaybill.action_open_record_form` | [rs_waybill_actions.py:913](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L913) | - | - | none |
| `RsWaybill.action_open_parent_waybill` | [rs_waybill_actions.py:926](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L926) | - | - | none |
| `RsWaybill.action_subwaybill_complete` | [rs_waybill_actions.py:938](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L938) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_print_pdf` | [rs_waybill_actions.py:989](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_actions.py#L989) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybillAdjustmentLine.action_view_snapshot` | [rs_waybill_adjustment.py:23](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_adjustment.py#L23) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybillSoapService._get_credentials` | [rs_waybill_soap_service.py:34](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L34) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService._get_seller_un_id` | [rs_waybill_soap_service.py:39](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L39) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.check_credentials` | [rs_waybill_soap_service.py:76](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L76) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService._call_datatable` | [rs_waybill_soap_service.py:153](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L153) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService._build_waybill_xml` | [rs_waybill_soap_service.py:202](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L202) | service wrapper | `env.user` of the caller | refuse when `_get_seller_un_id()` != the company's stored `rs_un_id` (10) |
| `RsWaybillSoapService.save_waybill` | [rs_waybill_soap_service.py:311](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L311) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.send_waybill` | [rs_waybill_soap_service.py:356](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L356) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.close_waybill` | [rs_waybill_soap_service.py:371](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L371) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.delete_waybill` | [rs_waybill_soap_service.py:386](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L386) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.refuse_waybill` | [rs_waybill_soap_service.py:401](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L401) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.ref_waybill_vd` | [rs_waybill_soap_service.py:415](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L415) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.confirm_waybill` | [rs_waybill_soap_service.py:433](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L433) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.reject_waybill` | [rs_waybill_soap_service.py:448](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L448) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.send_waybil_vd` | [rs_waybill_soap_service.py:462](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L462) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.close_waybill_vd` | [rs_waybill_soap_service.py:485](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L485) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_waybills_v1` | [rs_waybill_soap_service.py:513](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L513) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_waybills` | [rs_waybill_soap_service.py:527](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L527) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_buyer_waybills` | [rs_waybill_soap_service.py:556](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L556) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_transporter_waybills` | [rs_waybill_soap_service.py:584](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L584) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_full_waybill` | [rs_waybill_soap_service.py:592](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L592) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_adjusted_waybills` | [rs_waybill_soap_service.py:615](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L615) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_adjusted_waybill` | [rs_waybill_soap_service.py:636](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L636) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_full_waybill_with_client` | [rs_waybill_soap_service.py:655](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L655) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_transporter_info` | [rs_waybill_soap_service.py:674](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L674) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.save_transporter_waybill` | [rs_waybill_soap_service.py:686](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L686) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.send_transporter_waybill` | [rs_waybill_soap_service.py:703](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L703) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.close_transporter_waybill` | [rs_waybill_soap_service.py:728](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L728) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.save_waybill_template` | [rs_waybill_soap_service.py:747](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L747) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_waybill_template` | [rs_waybill_soap_service.py:760](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L760) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_waybill_templates` | [rs_waybill_soap_service.py:771](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L771) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.delete_waybill_template` | [rs_waybill_soap_service.py:778](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L778) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_car_numbers` | [rs_waybill_soap_service.py:787](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L787) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_bar_codes` | [rs_waybill_soap_service.py:804](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L804) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_akciz_codes` | [rs_waybill_soap_service.py:812](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L812) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.save_bar_code` | [rs_waybill_soap_service.py:822](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L822) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_waybill_units` | [rs_waybill_soap_service.py:853](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L853) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.get_print_pdf` | [rs_waybill_soap_service.py:859](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L859) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSoapService.save_invoice` | [rs_waybill_soap_service.py:871](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_soap_service.py#L871) | service wrapper | `env.user` of the caller | none |
| `RsWaybillSync._get_rs_sync_user` | [rs_waybill_sync.py:19](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L19) | - | record `company_id` | `Users.with_company(company).search(domain)`; drop the default-company preference (6) |
| `RsWaybillSync._rs_sync_contexts` | [rs_waybill_sync.py:49](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L49) | - | `env.user` + `env.company` | none |
| `RsWaybillSync._rs_run_per_company` | [rs_waybill_sync.py:101](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L101) | - | `env.user` + `env.company` | none |
| `RsWaybillSync.action_sync_all` | [rs_waybill_sync.py:126](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L126) | - | - | none |
| `RsWaybillSync.action_sync_seller_waybills` | [rs_waybill_sync.py:134](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L134) | - | - | none |
| `RsWaybillSync._sync_seller_waybills_one` | [rs_waybill_sync.py:141](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L141) | sync, per company | `with_company` loop | none |
| `RsWaybillSync.action_sync_buyer_waybills` | [rs_waybill_sync.py:178](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L178) | - | - | none |
| `RsWaybillSync._sync_buyer_waybills_one` | [rs_waybill_sync.py:184](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L184) | sync, per company | `with_company` loop | none |
| `RsWaybillSync.action_sync_transporter_waybills` | [rs_waybill_sync.py:215](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L215) | - | - | none |
| `RsWaybillSync._sync_transporter_waybills_one` | [rs_waybill_sync.py:221](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L221) | sync, per company | `with_company` loop | none |
| `RsWaybillSync.action_cron_sync_updated_waybills` | [rs_waybill_sync.py:287](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L287) | cron | - | none |
| `RsWaybillSync._cron_sync_updated_waybills_one` | [rs_waybill_sync.py:293](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L293) | sync, per company | `with_company` loop | none |
| `RsWaybillSync._process_rs_rows` | [rs_waybill_sync.py:401](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L401) | sync, per company | `with_company` loop | none |
| `RsWaybillSync._map_rs_waybill_vals` | [rs_waybill_sync.py:599](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L599) | sync, per company | `with_company` loop | none |
| `RsWaybillSync.action_sync_templates` | [rs_waybill_sync.py:896](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L896) | - | - | none |
| `RsWaybillSync._sync_templates_one` | [rs_waybill_sync.py:905](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L905) | sync, per company | `with_company` loop | none |
| `RsWaybillSync.action_save_as_template` | [rs_waybill_sync.py:966](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L966) | - | - | none |
| `RsWaybillSync.action_create_from_template` | [rs_waybill_sync.py:978](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L978) | - | - | none |
| `RsWaybillSync.action_delete_template` | [rs_waybill_sync.py:988](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L988) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybillSync._cron_rs_drift_repair` | [rs_waybill_sync.py:1082](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L1082) | cron | - | none |
| `RsWaybillSync._cron_rs_drift_repair_one` | [rs_waybill_sync.py:1094](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill_sync.py#L1094) | sync, per company | `with_company` loop | none |
| `SaleOrder.action_view_waybills` | [sale_order.py:20](../custom_addons/gec_odoo_modules/rs_waybill/models/sale_order.py#L20) | - | - | none |
| `StockPicking.action_view_waybill` | [stock_picking.py:88](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L88) | - | - | none |
| `StockPicking.action_assign` | [stock_picking.py:101](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L101) | - | - | none |
| `StockPicking.action_cancel` | [stock_picking.py:109](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L109) | - | - | none |
| `StockPicking._rs_try_create_waybill` | [stock_picking.py:160](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L160) | - | record `company_id` | none |
| `StockPicking._rs_create_internal_waybill` | [stock_picking.py:338](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L338) | - | record `company_id` | none |
| `StockPicking._rs_warehouse_address` | [stock_picking.py:384](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L384) | - | `env.company` | none |
| `StockPicking._rs_create_return_waybill` | [stock_picking.py:449](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L449) | - | record `company_id` | none |
| `StockPicking._rs_resync_waybill_from_picking_type` | [stock_picking.py:481](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L481) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `RsWaybill.action_open_live_rs_view` | [live_rs_view.py:28](../custom_addons/gec_odoo_modules/rs_waybill/wizards/live_rs_view.py#L28) | - | - | none |
| `RsWaybillLive._fetch_and_fill` | [live_rs_view.py:93](../custom_addons/gec_odoo_modules/rs_waybill/wizards/live_rs_view.py#L93) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `ProductMappingWizards.action_apply` | [product_mapping_wizards.py:16](../custom_addons/gec_odoo_modules/rs_waybill/wizards/product_mapping_wizards.py#L16) | - | - | none |
| `RsWaybillReturnDecisionWizard.action_create_with_waybill` | [return_decision_wizard.py:22](../custom_addons/gec_odoo_modules/rs_waybill/wizards/return_decision_wizard.py#L22) | - | - | none |
| `RsWaybillReturnDecisionWizard.action_adjust_odoo_only` | [return_decision_wizard.py:43](../custom_addons/gec_odoo_modules/rs_waybill/wizards/return_decision_wizard.py#L43) | - | - | none |
| `TemplateSaveWizard.action_save` | [template_wizards.py:17](../custom_addons/gec_odoo_modules/rs_waybill/wizards/template_wizards.py#L17) | direct, one waybill | none passed (active login) | replace with `self._rs_service()` (1) |
| `TemplatePickerWizard.action_load` | [template_wizards.py:45](../custom_addons/gec_odoo_modules/rs_waybill/wizards/template_wizards.py#L45) | - | - | none |

### employee_registry_rs — 37 methods, 24 listed, 4 change

| Method | File | rs.ge route | Company today | Change (approx. lines) |
|---|---|---|---|---|
| `EmployeeRegistryRsBrowser.action_search` | [employee_registry_rs_browser.py:36](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_browser.py#L36) | - | - | none |
| `EmployeeRegistryRsBrowserLine._compute_matching_employee` | [employee_registry_rs_browser.py:133](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_browser.py#L133) | - | `env.company` | none |
| `EmployeeRegistryRsBrowserLine.action_open_in_odoo` | [employee_registry_rs_browser.py:149](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_browser.py#L149) | - | - | none |
| `EmployeeRegistryRsBrowserLine.action_link_to_odoo` | [employee_registry_rs_browser.py:165](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_browser.py#L165) | - | - | none |
| `EmployeeRegistryRsLog._compute_company_id` | [employee_registry_rs_log.py:31](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_log.py#L31) | - | `env.company` | none |
| `EmployeeRegistryRsLog._cron_rotate_logs` | [employee_registry_rs_log.py:43](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_log.py#L43) | cron | - | none |
| `EmployeeRegistryRsService._request` | [employee_registry_rs_service.py:110](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L110) | REST via `_request()` | `env.user` login | `user = self.env.user.with_company(employee.company_id)` when `employee_id` is given (6) |
| `EmployeeRegistryRsService._write_log` | [employee_registry_rs_service.py:169](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L169) | - | `env.company` | none |
| `EmployeeRegistryRsService.save_employee` | [employee_registry_rs_service.py:187](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L187) | REST via `_request()` | `env.user` login | none: `_request` carries the company |
| `EmployeeRegistryRsService.get_employee` | [employee_registry_rs_service.py:195](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L195) | REST via `_request()` | `env.user` login | none: `_request` carries the company |
| `EmployeeRegistryRsService.list_employees` | [employee_registry_rs_service.py:203](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L203) | REST via `_request()` | `env.user` login | none: `_request` carries the company |
| `EmployeeRegistryRsService.get_countries` | [employee_registry_rs_service.py:207](../custom_addons/gec_odoo_modules/employee_registry_rs/models/employee_registry_rs_service.py#L207) | REST via `_request()` | `env.user` login | none: `_request` carries the company |
| `HrEmployee._check_rs_sync_allowed` | [hr_employee.py:142](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L142) | - | `env.company` | none |
| `HrEmployee._resolve_rs_id_by_tin` | [hr_employee.py:248](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L248) | REST via `_request()` | `env.user` login | none: `_request` carries the company |
| `HrEmployee._sync_single_to_rs` | [hr_employee.py:278](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L278) | REST via `_request()` | `env.user` login | none: `_request` carries the company |
| `HrEmployee.action_rs_sync_now` | [hr_employee.py:348](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L348) | - | - | none |
| `HrEmployee.action_rs_activate` | [hr_employee.py:363](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L363) | - | - | none |
| `HrEmployee.action_rs_suspend` | [hr_employee.py:378](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L378) | - | - | none |
| `HrEmployee.action_rs_terminate` | [hr_employee.py:393](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L393) | - | - | none |
| `HrEmployee.action_rs_fetch` | [hr_employee.py:408](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L408) | REST via `_request()` | `env.user` login | none: `_request` carries the company |
| `HrEmployee._cron_sync_employees_to_rs` | [hr_employee.py:572](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L572) | cron | - | loop root companies with a responsible user instead of one cron record per entity (40) |
| `HrEmployee._cron_maybe_send_weekly_digest` | [hr_employee.py:619](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L619) | cron | - | recipient = the company's responsible user (2) |
| `HrEmployee._cron_send_failure_digest` | [hr_employee.py:654](../custom_addons/gec_odoo_modules/employee_registry_rs/models/hr_employee.py#L654) | cron | - | recipient = the company's responsible user (2) |
| `ResConfigSettings.action_employee_registry_rs_sync_countries` | [res_config_settings.py:13](../custom_addons/gec_odoo_modules/employee_registry_rs/models/res_config_settings.py#L13) | - | - | none |

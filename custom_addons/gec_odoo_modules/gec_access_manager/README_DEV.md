# User Access Manager (`gec_access_manager`) — Developer guide

For a developer who knows Odoo 20 and has to change this module. The user guide is [README.rst](README.rst).
Flow sections (step by step) are not written yet.

## 1. Purpose and facts

An access profile is one screen that lists what a group of users cannot see or do: menus, models, fields, buttons,
tabs, reports, actions, records, and when and from where they sign in. Profiles only subtract access from what
Odoo groups already give. The rules are enforced on the server, not only hidden in the views.

| Item | Value |
|---|---|
| Depends | `base` (core models), `web` (views, controllers, routes), `mail` (chatter on the profile, message guards), `rpc` (XML-RPC and JSON-RPC functions that are wrapped), `gec_user_audit` (marks the calls a client makes, `_gec_rpc_entry`; stores the refusals) |
| New models | `gec.access.profile`, `gec.access.profile.model`, `.menu`, `.field`, `.button`, `.element`, `.assignment`, `.version`; `gec.access.allowed`, `gec.access.login.slot`; abstract mixins `gec.access.history.mixin`, `gec.access.rights.mixin`, `gec.access.condition.mixin`; wizards `gec.access.app.wizard` (with `.menu`, `.model`, `.report`, `.action`), `gec.access.assign`, `gec.access.copy.access`, `gec.access.copy.restrictions`, `gec.access.explain`, `gec.access.import`, `gec.access.load.models`, `gec.access.scan.buttons` (with `.line`), `gec.access.template.wizard`, `gec.access.test.user` |
| Extended models | `base`, `res.users`, `res.groups`, `ir.http`, `ir.ui.menu`, `ir.actions.actions`, `ir.actions.report`, `ir.actions.server`, `ir.attachment`, `ir.binary`, `ir.filters`, `ir.module.module`, `mail.thread`, `mail.message`, `mail.scheduled.message`, `mail.template`, `mail.compose.message`, `gec.user.audit.log` |
| Controllers | `controllers/` overrides of core routes (see the file map) |
| Cron | Access Profiles: Start and End Temporary Users (hourly fallback, plus a trigger at each start and end; `gec.access.profile.assignment._cron_refresh`) |
| Hook | `uninstall_hook` |

The same profile class `gec.access.profile` is split over many files with `_inherit = 'gec.access.profile'`:
checks, grants, exposure, login, membership, menu panel, resolver, result, transfer, version, view rules.

Data files, in manifest order: `security/gec_access_security.xml`, `data/ir_cron.xml`,
`data/gec_access_version_data.xml`, `data/gec_access_group_data.xml`, `wizard/gec_access_wizard_views.xml`,
`views/gec_access_profile_views.xml`, `views/gec_access_version_views.xml`, `views/res_users_views.xml`,
`views/menu.xml`, `security/ir.access.csv`.

## 3. File map

### controllers/

| File | Holds |
|---|---|
| `action.py` | Server-side blocking of action buttons, reports and server actions by id; `/web/action/load` runs under `sudo()` with no access check, so it is done here |
| `dataset.py` | Blocks object buttons, and the hidden fields a client sends to the read methods of `CLIENT_READ_ENTRIES`, on `call_button` and `call_kw`; judges the values of write and create (`CLIENT_VALUES`) before any override renames their keys |
| `json.py` | The `/json` views run an action given in the URL: refuses the hidden ones |
| `json2.py` | JSON-2 API: the same checks as `call_kw`; a locked value is refused |
| `mail.py` | Refuses Send message from the chatter when a profile hides it; Log note stays allowed |
| `preview.py` | Ending a preview (see `models/gec_access_preview.py`) |
| `report.py` | Refuses printing a report a profile hides, on the routes the web client prints through |
| `rpc.py` | XML-RPC and JSON-RPC: the same button, archive and read checks as `call_kw`; a locked value is refused |
| `translation.py` | Refuses the translation dialog for a field the profile hides |

### models/ — enforcement

| File | Holds |
|---|---|
| `base_model.py` | `_access_domain()`, the one place where access is subtracted per user |
| `field_guard.py` | Hidden and read-only fields, enforced on client calls only |
| `ir_actions.py` | `get_bindings()` per user, so hidden reports and actions leave the menus; `run()` guard for server actions |
| `ir_attachment.py` | Files of a binary field hidden under a condition: the attachment checks apply the condition to the record |
| `ir_binary.py` | `/web/content` and `/web/image`: refuses the binary fields a profile hides, always or under a condition |
| `ir_filters.py` | Saved searches, refused with 'No Saved Searches' |
| `ir_http.py` | `_handle_debug()` (developer mode), `session_info` (body classes of the profile), `_authenticate_explicit` (sign-in rules on every request) |
| `ir_module.py` | Install, upgrade and uninstall refused with 'Block Installing Apps' |
| `ir_ui_menu.py` | Menu filtering in `_load_menus_blacklist()` |
| `mail_thread.py` | Blocks `message_post`, `message_notify` and `message_post_with_source` called by a client, scheduled messages and the full composer; keeps a tracking message that shows a hidden field out of notifications and out of searches through `message_ids` |
| `gec_access_checks.py` | The refusals the controllers and ORM hooks call |
| `gec_access_view_rules.py` | The view rewriting applied from `Base.get_view()` |

### models/ — profile and its lines

| File | Holds |
|---|---|
| `gec_access_profile.py` | The access profile, the single screen the administrator edits |
| `gec_access_profile_model.py` | Per-model rules: R/C/U/D, record filters, model-scoped UI switches; the `gec.access.rights.mixin` |
| `gec_access_profile_menu.py` | Rights set on a menu; they reach the data of every menu below it |
| `gec_access_profile_field.py` | Per-field rules |
| `gec_access_profile_button.py` | Per-button rules; `button_id` tells apart buttons sharing a name |
| `gec_access_profile_element.py` | View elements removed: notebook pages, search filters, the search panel, whole view types |
| `gec_access_allowed.py` | Allowed Records ("only these journals") |
| `gec_access_condition.py` | `gec.access.condition.mixin`: the condition of a field, button or tab rule |
| `gec_access_login.py` | Sign-in rules: working hours, allowed networks, one session per user |
| `gec_access_membership.py` | Who carries a profile besides its users: Odoo group members and temporary users |
| `res_users.py` | The profiles a user carries; the export group this module hides on purpose |
| `gec_access_history.py` | `gec.access.history.mixin`: note on the profile when a line is added, changed or removed |

### models/ — engine and tools

| File | Holds |
|---|---|
| `gec_access_resolver.py` | Builds the rules of a user from his profiles and caches them |
| `gec_access_rules.py` | The constants, the frozen `ProfileRules` and the `AccessRules` the resolver builds |
| `conditions.py` | Conditions of rules written as view conditions, parsed to domains |
| `value_filters.py` | Value filters of fields, combined as domain expressions; `check_filter()`, `eval_filter()` |
| `login_tools.py` | Sign-in helpers, free of any model |
| `gec_access_menu_panel.py` | The Menus & Apps tab: menu tree and the panel of the clicked menu |
| `gec_access_exposure.py` | What a hidden menu still exposes, and the Block that denies it |
| `gec_access_result.py` | The result block of the panel: what members can really do, Odoo groups plus profile limits |
| `gec_access_grants.py` | The "What they get" page |
| `gec_access_preview.py` | Preview as a user |
| `gec_access_templates.py` | Ready-made profiles kept as recipes in code (see Recipe format) |
| `gec_access_transfer.py` | Export and import of profiles between databases |
| `gec_access_version.py` | Versions of a profile: saved, compared, restored |

### wizard/

| File | Holds |
|---|---|
| `gec_access_app_wizard.py` | Restrict an App: menus, data, reports and actions of an app on one screen |
| `gec_access_assign.py` | Set the profiles of several users at once, from the Users list |
| `gec_access_copy_access.py` | Give a user the access of another (replacement, newcomer, job change) |
| `gec_access_copy_restrictions.py` | Copy the rules of one profile into another |
| `gec_access_explain.py` | Why can, or can't, a user do something: Odoo's answer, then the profiles', with recent refusals |
| `gec_access_import.py` | Import profiles from a file exported on another database |
| `gec_access_load_models.py` | Seeds model rules from the models reachable through the menus a profile leaves visible |
| `gec_access_scan_buttons.py` | Lists the buttons and view elements of a model from its views |
| `gec_access_template_wizard.py` | New from Template: turns a recipe into an ordinary profile |
| `gec_access_test_user.py` | Shows the access a user really ends up with, and which profile set each line |

## Recipe format

Recipes live in `models/gec_access_templates.py`.

| Key | Meaning |
|---|---|
| `key`, `name`, `description` | Identity and text of the recipe |
| `requires` | Modules that must be installed for the recipe to be offered |
| `any_app` | `True`: the administrator picks the app, and every part of `apps` with `'app': None` applies to it |
| `apps` | `[{'app': menu xmlid, 'level': ..., 'own_records': bool, 'optional': bool}]`, run through the Restrict an App engine; `'app'` may be a tuple of alternatives, the first one found is used |
| `hide_menus` | Menu xmlids; a tuple lists alternatives, the first one found is hidden |
| `models` | `{model: {perm_read/perm_create/perm_write/perm_unlink: bool}}`, applied after the apps, for what an app level cannot know |
| `fields` | `[(model, field, mode)]`, mode as `gec.access.profile.field` |
| `switches` | `{profile field: value}` |

Recipes are code, not data, so they never point to an app that is not installed; missing optional parts are skipped.

## Guards and invariants

| Rule | Where | Why |
|---|---|---|
| Subtract access only in `_access_domain()` | `models/base_model.py` | `ir.access` permissions are OR-ed in Odoo 20: adding records never removes access, so this is the one place access can be subtracted per user |
| Hidden and read-only fields are enforced on client calls only | `models/field_guard.py`, `controllers/dataset.py` | Odoo 20 checks field access on every Python read; denying them in `_has_field_access()` would break business code. Server code never goes through the client doors, so it is never blocked |
| Hidden values are blanked, not removed | `models/field_guard.py` | Views that refer to them keep working; the field stays in the arch the client receives, as invisible |
| Domains, orders, group-bys and exports on a hidden field are refused | `models/field_guard.py` (rules of `gec_access_profile_field.py`) | The value would leak through the query |
| What a client called is told by `_gec_rpc_entry` | `gec_user_audit` | The read methods that call the guards under their own name (`CLIENT_READ_ENTRIES`) are checked on their arguments at the RPC doors |
| Values of write and create are judged before any override renames their keys | `controllers/dataset.py` (`CLIENT_VALUES`) | An override could rename the keys and hide a locked field |
| Web client drops a locked value; API doors refuse it | `dataset.py` (web) against `json2.py`, `rpc.py` (API) | The views send what an onchange filled in; the API must refuse, as core refuses a field the user may not write |
| RPC routes run without a database, so `call_kw` is wrapped at the function level | `controllers/rpc.py` | Overriding the controllers would not apply; wrap the function they call, which the web client and JSON-2 import under their own name and do not go through |
| `/web/action/load` is checked by id | `controllers/action.py` | It runs under `sudo()` with no access check |
| Report printing is refused on the web client's routes only | `controllers/report.py` | Server-side rendering (Send & Print, mail templates) does not come here and is left alone |
| Chatter: Send message refused, Log note allowed | `controllers/mail.py` | Log note uses the note subtype |
| Client-side posting is blocked; server-side posting is left alone | `models/mail_thread.py` | The chatter guard does not see the API, scheduled messages and the full composer |
| Tracking messages that show a hidden field stay out of notifications and of `message_ids` searches | `models/mail_thread.py` | Otherwise the hidden value leaks; the read access domain of the users concerned is in `base_model.py` |
| Translation dialog checked before `get_field_translations` | `controllers/translation.py` | The dialog reads xml and html values straight from the record, never through `get_field_translations` |
| Menus are filtered in `_load_menus_blacklist()`, cached per user | `models/ir_ui_menu.py` | `_visible_menu_ids()` is cached per group set; filtering there leaks between users |
| `get_bindings()` is per user and uncached | `models/ir_actions.py` | Hidden reports and actions leave the menus; enforcement is in `controllers/action.py`, `controllers/report.py` and `run()` |
| Developer mode is cleared in `_handle_debug()` | `models/ir_http.py` | It is the single place the debug flag enters the session, so the menu and the URL are both blocked |
| Sign-in rules are checked at sign-in and on every request | `models/gec_access_login.py`, `models/ir_http.py` | Open sessions end too |
| Binary fields hidden under a condition are checked on the attachment | `models/ir_attachment.py`, `models/ir_binary.py` | Core asks the attachment, not the field, so the condition is applied to the record |
| Conditions are parsed, never run as Python | `models/conditions.py`, `models/value_filters.py` | A filter text is written by a profile author; `check_filter()` accepts a small syntax and `eval_filter()` evaluates it. Unsupported conditions are refused when the rule is saved |
| Value filters combine as domain expressions | `models/value_filters.py` | A filter that reads the record (`company_id`, `parent.partner_id`) combines like a literal, in the views (evaluated by the web client) and in the check made when a value is saved |
| Rules set on a menu reach every menu below it | `models/gec_access_profile_menu.py` | Hiding a menu hides its branch, and data added later by other modules is included |
| Closest setting wins | `models/gec_access_profile_menu.py` | Order: a model line on the data itself, then the deepest menu line above a menu opening the data; data opened from several menus takes the most restrictive setting |
| Button hiding is narrowed by `view_type` and `button_id`; blocking is not | `models/gec_access_profile_button.py` | Blocking only knows the model and method |
| View types are stripped from the action itself | `models/gec_access_profile_element.py` | Whole view types are removed at the action |
| A restriction bites only when every additive profile of the user carries it | `wizard/gec_access_copy_restrictions.py` | Why the copy wizard exists |
| Allowed records are `Many2oneReference` | `models/gec_access_allowed.py` | The module depends on no business app; a kind also filters every dependent model (entries, payments...) |
| Preview is read only | `models/gec_access_preview.py` | The session keeps the administrator signed in; each request is served as the previewed user on a read-only transaction. When the hour is over, requests stay read only but are served as the administrator again until Exit is clicked |
| Profile versions: one per transaction | `models/gec_access_version.py` | The whole profile, as its export describes it, is saved once per transaction that changed it |
| Import: missing allowed records refuse, other missing references are skipped and reported | `models/gec_access_transfer.py` | Records travel by technical name, external id or name, never by database id |
| Block / Unblock write through the panel's own handler | `models/gec_access_exposure.py` | The exposure lines are read only; the lines Block creates are the ordinary ones of the Models tab |
| The panel writes ordinary profile lines | `models/gec_access_menu_panel.py`, `wizard/gec_access_app_wizard.py` | Model, menu, field, button, element lines, hidden reports and actions, allowed records: the other tabs show the same rules |
| Line changes are logged as a note on the profile | `models/gec_access_history.py` | `mail.thread` tracking only covers the profile's own fields |
| Scan Buttons runs under `sudo()` | `wizard/gec_access_scan_buttons.py` | The views must come back unfiltered; only the ticked lines become rules |
| Profile members | `models/gec_access_membership.py` | Members of Odoo groups and users given the profile for a while (replacement, leave) |

## Extending safely

| Never | Because |
|---|---|
| Subtract access anywhere but `_access_domain()` | Permissions are OR-ed; nothing else removes access |
| Deny hidden fields in `_has_field_access()` | Odoo 20 calls it on every Python read; business code would break |
| Filter menus in `_visible_menu_ids()` | Cached per group set; leaks between users. Use `_load_menus_blacklist()` |
| Override the XML-RPC / JSON-RPC controllers to add a check | The routes run without a database; wrap the function they call (`controllers/rpc.py`) |
| Rely on the view hiding alone | The hidden field stays in the arch as invisible; the server enforces it |
| Run a profile condition or value filter as Python | The text comes from a profile author; extend the parsers in `models/conditions.py` and `models/value_filters.py` instead |
| Add a business-app dependency or a data record pointing to an app | Allowed records are `Many2oneReference` and recipes are code, so the module installs without any app |
| Block server-side code | Guards sit on client doors (RPC, JSON-2, controllers) only; server code is never blocked, by design |

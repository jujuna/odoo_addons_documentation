# Finding the exact UI in the source

Use this whenever you tell someone where to click. Every string you give must come from
one of these places.

## 1. Menus: the click path

Menus are `<menuitem>` elements in `addons/<module>/views/*.xml` (often `*_menus.xml` or
`*_views.xml`).

```xml
<menuitem id="menu_hr_holidays_configuration" name="Configuration"
          parent="menu_hr_holidays_root" groups="hr_holidays.group_hr_holidays_manager"/>
```

- **Build the path** by following `parent=` up to the root (the app). A parent in another
  module is written `module.menu_id`, so search for that id in that module.
- **Menus can be nested** inside each other in XML instead of using `parent=`. Read the
  surrounding elements.
- **No `name=`?** The menu shows the name of its `action=`. Find that action record and
  use its `name`.
- **`groups=`**: only users in one of those groups see the menu. Translate the group into
  words (see section 5).
- **Menus from other modules**: search all folders for `parent="<module>.<menu_id>"`.
  Other apps often add entries to a menu.
- A menu with no action and no visible children is hidden.
- **Menus moved by code:** some apps rename or move menus in Python install hooks, not in
  XML. Example: `enterprise/accountant/__init__.py` moves the accounting menus. If a path
  looks wrong, check the module's `__init__.py` for `post_init_hook` / `uninstall_hook`.

Search: `rg -n 'menu_id_here' addons enterprise custom_addons`

## 2. Actions: what the menu opens

The menu's `action=` points to an `ir.actions.act_window` record:
- `res_model`: which records are shown (e.g. `hr.leave.allocation`).
- `domain`: a permanent filter. The user cannot remove it. This explains "why do I only
  see some records here".
- `context` with `search_default_xxx`: a default filter the user *can* remove.
- `view_mode`: which views exist (list, form, kanban, calendar, pivot, graph).

## 3. Views: buttons, fields, tabs

Form, list and other views are `<record model="ir.ui.view">` in `views/*.xml`.

| Element | Label shown to user | Visibility |
|---|---|---|
| `<button string="Approve" .../>` | `string=` | `invisible="..."`, `groups="..."` |
| `<field name="x" string="..."/>` | view `string=`, else the model field's `string=` in `models/*.py`, else the field name | `invisible=`, `groups=`, `column_invisible=` (list columns) |
| `<page string="...">` | tab name | `invisible=`, `groups=` |
| list `optional="hide"` | column is hidden by default; user enables it from the column toggler at the end of the header row | |
| `readonly=`, `required=` | | when editable / mandatory |

**Read `invisible=` conditions in plain words.** Example:
`invisible="not can_approve or not id"` means "shown only on a saved record that you are
allowed to approve". If the condition uses a computed field (`can_approve`), open the model
and read that compute method. It usually says who is allowed.

**Tooltips:** the field's `help=` in `models/*.py` is the tooltip text. Quote it when it
helps.

## 4. Inherited views change things

Other modules modify a view with `inherit_id` + `xpath`. They add or hide buttons, rename
fields, add tabs. Before you say "the form has X", search:

```
rg -n '<view_xml_id>' addons enterprise custom_addons
```

Say which app adds a button: "the **Payslips** smart button appears only if Payroll is
installed".

## 5. Access rights: who can see it

- Groups are defined in `security/*.xml` as `res.groups` records, linked to a
  `res.groups.privilege` (the app line on the user's access rights).
- `implied_ids` means that having one group automatically gives another (Administrator
  includes Officer, etc.).
- Say it in words, as privilege + group name from the records: "only users with
  **Time Off: Administrator**", not `group_hr_holidays_manager`.
- Users get groups at **Settings > Users & Companies > Users**, open the user, tab
  **Access Rights**. (Source: `odoo/addons/base/views/base_menus.xml`,
  `odoo/addons/base/views/res_users_views.xml`)
- Inspect the target checkout’s loaded security definitions, including access CSV files,
  group implications, record restrictions and Python checks. File formats differ by
  version. Do not infer effective access or record visibility from a menu’s groups alone.
- `groups="base.group_no_one"` = visible only in **developer mode**.

## 6. Settings page

Settings are in `views/res_config_settings_views.xml` of each module:

```xml
<app data-string="Employees" string="Employees" name="hr">       -> left sidebar entry in Settings
  <block title="Work Organization">                              -> section heading
    <setting string="Presence Display" help="..." company_dependent="1">  -> one setting
```

- Path to give: **Settings > Employees > Work Organization > (setting name)**. The Settings
  page also has a search box; mention it.
- If `<setting>` has no `string=`, the label is the field's `string` in
  `models/res_config_settings.py`.
- Fields named `module_xxx` **install a module** when ticked. Warn the user: installing
  adds menus, fields and sometimes data, and removing it later is not trivial.
- Fields named `group_xxx` (with `implied_group=`) alter group implications; inspect which
  groups and users are affected. This can make hidden fields/menus appear. This is the most common reason for "I don't see
  that field".
- `company_dependent="1"` marks company-related UI. Verify actual field storage or related
  company fields before asserting scope. In multi-company databases, check active company.
- Not every app has a settings page (e.g. `hr_holidays` has none in Odoo 20; its setup is
  under **Time Off > Configuration**).

Developer mode: **Settings**, bottom of the page, **Activate the developer mode**.
(Source: `addons/web/static/src/webclient/settings_form_view/widgets/res_config_dev_tool.xml`)

## 7. "Why can't I see it?" checklist

Go in this order and tell the user which one applies:
1. **App/module not installed**: find which app/module defines it (the folder name).
2. **Access rights**: the menu/button/field has `groups=` the user lacks.
3. **Feature toggle off**: a `group_xxx` setting must be enabled.
4. **Condition not met**: `invisible=` depends on state or other fields (e.g. button only
   in state To Approve).
5. **Developer mode**: `base.group_no_one`.
6. **Wrong company** active, or the record belongs to another company.
7. **Filter/domain**: the action's `domain` or a default filter hides records.
8. **Optional column** hidden in list view.

## 8. Translations

Check the relevant language files (`msgid` and `msgstr`) for translated UI labels. Do
not assume translation coverage from historical percentages. Database translations and
custom views may differ from the checkout. Give a verified English label when a translated
label cannot be confirmed, and say which language it is.

## 9. State names

States shown to users are the selection **labels**, not the keys. Example: `hr.leave`
state `confirm` shows as **To Approve**. Read the `fields.Selection([...])` in the model
and give the label.

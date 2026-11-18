# Dashboards (board + spreadsheet_dashboard)

> **Modules:** `board` + `spreadsheet_dashboard` (+ Enterprise `spreadsheet_dashboard_edition`) | **Path:** [`addons/board/`](../addons/board/), [`addons/spreadsheet_dashboard/`](../addons/spreadsheet_dashboard/), [`enterprise/spreadsheet_dashboard_edition/`](../enterprise/spreadsheet_dashboard_edition/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

Odoo has **two dashboard systems** under the same **Dashboards** menu:

| System | Best use | Storage and scope |
|---|---|---|
| **My Dashboard** (`board.board`) | A personal page of pinned, filtered list/graph/pivot views | XML layout in `ir.ui.view.custom`, one per user |
| **Spreadsheet dashboards** (`spreadsheet.dashboard`) | Shared KPIs: formulas, pivots, lists, charts, scorecards | Spreadsheet snapshot (+ revisions in Enterprise), with access groups, users and companies |

A salesperson pins "my open quotations" and "pipeline by stage" to My Dashboard. A finance team shares one KPI sheet with every manager as a spreadsheet dashboard. Many apps install ready-made spreadsheet dashboards (Sales, Accounting, CRM, Inventory, Helpdesk, Payroll, POS, eCommerce, …), shown with sample data until real records exist.

Dashboards are read-only views on live data; data entry stays in the apps. A public share is a frozen copy, not a live query endpoint.

`board` depends on `spreadsheet_dashboard`, which depends on `spreadsheet`; all three are Community. Enterprise `spreadsheet_dashboard_edition` (auto-installed with `spreadsheet_edition`) adds editing, revisions and the in-editor publish toggle. Sharing, favorites and saved filters are already in Community.

---

## Real-World Scenarios

### Scenario 1: A sales manager's morning page (My Dashboard)
**Situation:** A sales manager wants open quotations, last week's orders by salesperson and the pipeline by stage on one screen.
**What they do:** Sales → Quotations, filter "My Quotations", then in the cog menu **Dashboard → Add to my dashboard**, name it, **Add**. Repeat on Orders (graph, grouped by salesperson) and CRM Pipeline (pivot by stage). Open Dashboards → My Dashboard, pick the `2-1` layout, drag blocks between columns.
**What happens:** Three `<action>` blocks are stored in the manager's own `ir.ui.view.custom`. Data refreshes on every visit, but the filters and grouping are frozen as pinned.

### Scenario 2: A shared finance dashboard (spreadsheet, Enterprise editing)
**Situation:** The CFO wants every department head to see the same revenue and expense figures.
**What they do:** A dashboard administrator opens a pivot of journal items, cog menu → **Insert in Spreadsheet** → *Dashboards* tab → *Blank dashboard*, sets name, section and access groups, then builds charts and scorecards in the editor. They restrict `group_ids` to the managers' group and publish it.
**What happens:** Everyone in the group sees the dashboard under its section; each viewer's figures still pass through their own record rules.

### Scenario 3: Sharing with an outside stakeholder
**Situation:** A project manager must show KPIs to a client without an Odoo account.
**What they do:** Open the dashboard, click **Share**, optionally include an Excel export, send the link.
**What happens:** A `spreadsheet.dashboard.share` copy is stored with a random token. The client sees a read-only snapshot at `/dashboard/share/<id>/<token>`. Later edits do not reach that copy; archive or delete the share to revoke it.

---

## My Dashboard (`board.board`)

### Pinning a view — the add-to-dashboard flow

1. Open a window action in any view except form, apply filters, grouping and sorting.
2. Cog menu → **Dashboard** → type a title → **Add** ([add_to_board.xml](../addons/board/static/src/add_to_board/add_to_board.xml#L13)).
3. Open **Dashboards → My Dashboard** ([menu](../addons/board/views/board_views.xml#L32)).

The item appears only for `ir.actions.act_window` actions with an id and a view type other than `form` ([`isDisplayed`](../addons/board/static/src/add_to_board/add_to_board.js#L97)); kanban and calendar are not excluded by the menu, though a view must render inside a block.

**What gets saved:** action id, view mode, current domain, and the context with `group_by` and `orderedBy`. `search_default_*` keys are removed from the context ([add_to_board.js](../addons/board/static/src/add_to_board/add_to_board.js#L46)). The [`/board/add_to_dashboard`](../addons/board/controllers/main.py#L11) route (JSON-RPC, logged-in users) drops `allowed_company_ids` so the block follows the company switcher ([controller](../addons/board/controllers/main.py#L26)), inserts the new `<action>` at the **top of the first column**, and saves a new `ir.ui.view.custom` for the user.

### Arranging blocks

- **Layouts** `1`, `1-1`, `1-1-1`, `1-2`, `2-1` (default `2-1`) from the layout dropdown ([board_controller.xml](../addons/board/static/src/board_controller.xml#L23)). Reducing columns moves the extra blocks into the last visible column ([`selectLayout`](../addons/board/static/src/board_controller.js#L78)).
- **Drag** a block by its header to another position or column; **fold** it to its title; **close** it after a confirmation ([`closeAction`](../addons/board/static/src/board_controller.js#L102)).
- Every change serializes the XML and saves it through [`/web/view/edit_custom`](../addons/board/static/src/board_controller.js#L127).
- On small screens the board shows one column without saving that as the layout.

### Storage and loading

[`board.board`](../addons/board/models/board.py#L7) is an abstract model with `_auto = False` and a dummy `id`; `create()` returns an empty recordset. Nothing business-related is stored on it. [`get_view()`](../addons/board/models/board.py#L23) takes the current user's latest `ir.ui.view.custom` for the base view (they are ordered newest first, [ir_ui_view.py](../odoo/addons/base/models/ir_ui_view.py#L76)), substitutes its arch and forces `js_class="board"`. [`_arch_preprocessing()`](../addons/board/models/board.py#L39) drops `<action>` nodes that carry an `invisible` attribute. Data shown in blocks is still filtered by the user's own access rights.

A stored arch looks like this:

```xml
<form string="My Dashboard" js_class="board">
    <board style="2-1">
        <column>
            <action name="123" string="My Quotations" view_mode="list"
                    context="{'group_by': ['partner_id']}" domain="[('state', '=', 'draft')]" fold="0"/>
        </column>
        <column>
            <action name="456" string="Pipeline" view_mode="pivot" context="{}" domain="[]" fold="1"/>
        </column>
    </board>
</form>
```

| `<action>` attribute | Purpose |
|---|---|
| `name` | Numeric id of an `ir.actions.act_window` (`%(xmlid)d` in module XML) |
| `string` | Block title |
| `view_mode` | View to render (`list`, `graph`, `pivot`, …) |
| `context` / `domain` | Saved grouping, ordering and filters |
| `fold` | `"1"` collapsed, `"0"` expanded |

Each block loads its action once through `/web/action/load` (cached per action id) and embeds the view without a control panel; clicking a list row opens the record ([board_action.js](../addons/board/static/src/board_action.js#L26)).

### Developer example: ship a team board

A personal board cannot be shared through the UI. A module can ship a base board view plus its own action and menu; each user's later changes stay personal.

```xml
<record id="my_team_board_view" model="ir.ui.view">
    <field name="name">My Team Board</field>
    <field name="model">board.board</field>
    <field name="arch" type="xml">
        <form string="My Team Board">
            <board style="1-1">
                <column>
                    <action name="%(sale.action_orders)d" string="Confirmed Orders"
                            view_mode="list" domain="[('state', '=', 'sale')]"/>
                </column>
                <column/>
            </board>
        </form>
    </field>
</record>

<record id="action_my_team_board" model="ir.actions.act_window">
    <field name="name">My Team Board</field>
    <field name="res_model">board.board</field>
    <field name="view_mode">form</field>
    <field name="context">{'disable_toolbar': True}</field>
    <field name="usage">menu</field>
    <field name="view_id" ref="my_team_board_view"/>
</record>

<menuitem id="menu_my_team_board" name="My Team Board"
          parent="spreadsheet_dashboard.spreadsheet_dashboard_menu_root"
          action="action_my_team_board" sequence="50"/>
```

The module depends on `board` and `sale`. The action mirrors the shipped [My Dashboard action](../addons/board/views/board_views.xml#L19). **Add to my dashboard** always writes into *My Dashboard*, not into custom boards.

---

## Spreadsheet Dashboards (`spreadsheet.dashboard`)

### Models

Source: [spreadsheet_dashboard.py](../addons/spreadsheet_dashboard/models/spreadsheet_dashboard.py#L8).

| Field / model | Purpose |
|---|---|
| `name`, `sequence` | Translated name and order within its section |
| `dashboard_group_id` | Required **Section** — the heading the dashboard is listed under |
| `spreadsheet_binary_data` / `spreadsheet_data` | Snapshot, from `spreadsheet.mixin` |
| `is_published` | Default true; only published dashboards appear in the navigator |
| `group_ids` | Access groups, default internal users ([`group_ids`](../addons/spreadsheet_dashboard/models/spreadsheet_dashboard.py#L19)) |
| `allowed_user_ids` | Individual users who may also read it |
| `company_ids` | Company restriction; empty = all companies |
| `favorite_user_ids` / `is_favorite` | Per-user favorites; toggling writes only the current user, with sudo |
| `main_data_model_ids` + `sample_dashboard_file_path` | Sample-data trigger (below) |
| `spreadsheet.dashboard.group` | Section, with all and published dashboards ([model](../addons/spreadsheet_dashboard/models/spreadsheet_dashboard_group.py#L16)) |
| `spreadsheet.dashboard.favorite.filters` | Named global-filter presets: personal (`user_ids`) or shared (empty), optional default ([model](../addons/spreadsheet_dashboard/models/spreadsheet_dashboard_favorite_filters.py#L9)) |
| `spreadsheet.dashboard.share` | Frozen copy with token, active flag and optional Excel zip |

### Loading, publication and sample data

The client action `action_spreadsheet_dashboard` (optional `params.dashboard_id`) lists sections that have published dashboards, plus a **Favorites** section ([loader](../addons/spreadsheet_dashboard/static/src/bundle/dashboard_action/dashboard_loader_service.js#L107)). The data route [`/spreadsheet/dashboard/data/<dashboard>`](../addons/spreadsheet_dashboard/controllers/dashboards_controllers.py#L7) (logged-in users) returns the snapshot with the user's locale and company currency. Enterprise adds the revisions and a locale command.

**Sample data** is served when `sample_dashboard_file_path` is set and [`_dashboard_is_empty()`](../addons/spreadsheet_dashboard/models/spreadsheet_dashboard.py#L67) is true: **any** listed main model without records. It is re-evaluated on each load, so emptying a model brings samples back. The count runs in sudo when the user cannot read the model; that is not a grant to see its data. Enterprise also requires the dashboard to have no revisions, archived ones included ([edition](../enterprise/spreadsheet_dashboard_edition/models/spreadsheet_dashboard.py#L93)).

**Publication controls navigation, not access.** An unpublished dashboard is hidden from the navigator but still readable by anyone the access rules allow. Restrict groups, users or companies — and revoke share links — to actually close it.

### Creating and editing (Enterprise)

| Entry point | Who / where |
|---|---|
| **Insert in Spreadsheet** → *Dashboards* tab → *Blank dashboard* or an existing one | Cog menu of any non-form view on desktop ([cog menu](../enterprise/spreadsheet_edition/static/src/assets/spreadsheet_cog_menu/spreadsheet_cog_menu.js#L20)); the *Dashboards* tab shows for Dashboard admins only ([`_get_spreadsheet_selector`](../enterprise/spreadsheet_dashboard_edition/models/spreadsheet_dashboard.py#L109)). A dialog asks for name, section and access groups ([form](../enterprise/spreadsheet_dashboard_edition/views/spreadsheet_dashboard_views.xml#L55)) |
| **Edit in Spreadsheet** | Dashboards → Configuration → Dashboards, list/kanban button or form action ([view](../enterprise/spreadsheet_dashboard_edition/views/spreadsheet_dashboard_views.xml#L16)) |
| Edit icon on an open dashboard | Only in **developer mode**, for Dashboard admins ([dashboard_edit.js](../enterprise/spreadsheet_dashboard_edition/static/src/bundle/components/dashboard_edit/dashboard_edit.js#L20)) |
| **Published** toggle | Configuration → Dashboards (Community) and inside the editor (Enterprise) |

Dashboards shipped by modules (an XML id plus a sample file, [`is_from_data`](../enterprise/spreadsheet_dashboard_edition/models/spreadsheet_dashboard.py#L18)) show the edit icon in warning color: changes to them are lost on Odoo upgrades. Copy the dashboard and edit the copy.

With [`spreadsheet_dashboard_documents`](../enterprise/spreadsheet_dashboard_documents/wizard/documents_to_dashboard.py#L39), a spreadsheet document can be turned into a dashboard; its cell comments move over and the **original document is archived**. The two are not kept in sync.

---

## Access Control

**My Dashboard.** Every user reads only their own `ir.ui.view.custom` layout. Embedded views apply the user's normal model access and record rules.

**Spreadsheet dashboards** ([ir.access.csv](../addons/spreadsheet_dashboard/security/ir.access.csv)):

| Model | Internal users | Dashboard admin (`spreadsheet_dashboard.group_dashboard_manager`) |
|---|---|---|
| `spreadsheet.dashboard` | Read when one of `group_ids` is theirs **or** they are in `allowed_user_ids`; always within `company_ids` (a global restriction) | Full access (company restriction still applies) |
| `spreadsheet.dashboard.group` (sections) | Read | Full access |
| `spreadsheet.dashboard.share` | Their own shares only (`create_uid`) | Full access |
| `spreadsheet.dashboard.favorite.filters` | Full access to their own **and to shared** filters | Full access |

- Reading a dashboard never grants access to the models its pivots, lists and charts query; each viewer sees only the records their rules allow.
- The **Dashboards** menu requires `base.group_user_regular`, so light users do not see it ([menu_views.xml](../addons/spreadsheet_dashboard/views/menu_views.xml#L13)).
- The Admin group ships with the administrator and OdooBot ([security.xml](../addons/spreadsheet_dashboard/security/security.xml#L13)).
- Sections created by module XML cannot be deleted; sections exported with an `__export__` id can ([`_unlink_except_spreadsheet_data`](../addons/spreadsheet_dashboard/models/spreadsheet_dashboard_group.py#L16)).

### Share links

[`action_get_share_url()`](../addons/spreadsheet_dashboard/models/spreadsheet_dashboard_share.py#L34) stores the snapshot sent by the browser (and zips any Excel files) as a share with a UUID token. Every public request passes [`_check_dashboard_access`](../addons/spreadsheet_dashboard/models/spreadsheet_dashboard_share.py#L48): the token must match (constant-time compare), the share must be active, and **its creator must still be able to read the dashboard**. Remove the creator's access and their links stop working.

| Route | Access |
|---|---|
| `/dashboard/share/<share_id>/<token>` | Public read-only page ([share.py](../addons/spreadsheet_dashboard/controllers/share.py#L13)) |
| `/dashboard/data/<share_id>/<token>` | Public JSON of the stored copy |
| `/dashboard/download/<share_id>/<token>` | **Logged-in user with Export rights** (`base.group_allow_export`) ([share.py](../addons/spreadsheet_dashboard/controllers/share.py#L33)) |

---

## Customization Approaches

| Need | Approach | Code? |
|---|---|---|
| Personal page of existing views | Pin views to My Dashboard | No |
| Shared KPI page | Build a spreadsheet dashboard in the editor (Enterprise) | No |
| Ship a dashboard with a module | XML `spreadsheet.dashboard` record + exported JSON snapshot | Yes |
| Ship a pre-filled board to all users | Custom `board.board` view + action + menu (above) | Yes |

### Developer example: install a spreadsheet dashboard

Export a snapshot from this build's editor (or start from a shipped JSON) and declare dependencies for every model and XML id it references.

```xml
<odoo>
    <record id="my_dashboard_section" model="spreadsheet.dashboard.group">
        <field name="name">Operations</field>
        <field name="sequence">50</field>
    </record>
    <record id="my_dashboard" model="spreadsheet.dashboard">
        <field name="name">Operations Overview</field>
        <field name="dashboard_group_id" ref="my_dashboard_section"/>
        <field name="spreadsheet_binary_data" type="bytes" file="my_module/data/files/operations_dashboard.json"/>
        <field name="main_data_model_ids" eval="[Command.link(ref('sale.model_sale_order'))]"/>
        <field name="sample_dashboard_file_path">my_module/data/files/operations_sample_dashboard.json</field>
        <field name="group_ids" eval="[Command.link(ref('sales_team.group_sale_manager'))]"/>
        <field name="sequence">10</field>
        <field name="is_published">True</field>
    </record>
</odoo>
```

`my_module` and its files are placeholders; the record mirrors the shipped [Sales dashboard](../addons/spreadsheet_dashboard_sale/data/dashboards.xml#L4). `group_ids` given at creation replaces the default (internal users), so `Command.link` grants only the listed group. On module update, `Command.link` adds to the current groups while `Command.set` resets them.

---

## Snapshot Format and Formulas

Spreadsheet data has its own version and client-side migrations. **Do not set the snapshot version to `20.0` because the server is Odoo 20** — the shipped [Sales snapshot](../addons/spreadsheet_dashboard_sale/data/files/sales_dashboard.json) declares `19.3.10`. Copy an exported structure rather than hand-writing JSON.

A snapshot holds `sheets` (cells, formats, figures, tables, sizes), `styles`, `formats`, `borders`, `settings`, `pivots`, `lists`, `globalFilters`, `namedRanges`, `customTableStyles`, counters and `odooLinkReferences`. Pivot definitions carry model, domain, context, row/column fields, measures, sorting, a `formulaId` and `fieldMatching` for global filters. List columns are objects such as `{"name": "amount_total"}`. In Enterprise tests only, list columns of shipped dashboards may not set `string` unless `translateHeaders` is on.

Global filters filter a source only when mapped to one of its fields in `fieldMatching`; a label alone filters nothing. Relation filters name a model; date filters carry ranges and defaults.

| Formula | Purpose |
|---|---|
| `=PIVOT.VALUE("1", "amount_total")` | Aggregate from pivot 1; optional dimension/value pairs narrow it |
| `=PIVOT.HEADER("1", "partner_id", 12)` | Pivot group label |
| `=PIVOT("1")` | Spill the whole pivot: `(pivot_id, row_count, include_total, include_column_titles, column_count, include_measure_titles)`, totals and titles default true ([o_spreadsheet.js](../addons/spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js#L88650)) |
| `=ODOO.LIST.VALUE("1", 1, "name")` | One list cell; the row index is 1-based |
| `=ODOO.LIST("1", 20)` | Spill list rows; without a count it stops at 10,000 rows and asks for one ([list_functions.js](../addons/spreadsheet/static/src/list/list_functions.js#L8)) |
| `=ODOO.LIST.HEADER("1", "name")` | Column label; an optional third argument overrides it |
| `=ODOO.FILTER.VALUE("Period")` | Current filter value (may be an array) |
| `=ODOO.FILTER.LABEL("Period")` | Human-readable filter value |

Older snapshots are migrated on load: `ODOO.PIVOT` → `PIVOT.VALUE`, `ODOO.PIVOT.HEADER` → `PIVOT.HEADER`, `ODOO.PIVOT.TABLE` → `PIVOT`, and the three-argument `ODOO.LIST` cell formula → `ODOO.LIST.VALUE` ([migration.js](../addons/spreadsheet/static/src/o_spreadsheet/migration.js#L16)). Write new formulas with the current names.

---

## Troubleshooting & Gotchas

| Symptom | Check |
|---|---|
| Dashboard missing from the navigator | Published? Section set? User in `group_ids` / `allowed_user_ids`? Company allowed? Light user? |
| Dashboard opens but figures are missing | The viewer's model access and record rules, the source domain, global-filter `fieldMatching`, enabled companies |
| Sample values appear | A main model has no records (Enterprise: and no revisions) |
| Public link stopped working | Share archived, token wrong, or the creator lost read access to the dashboard |
| Anonymous viewer cannot download Excel | Download needs a logged-in user with Export rights |
| Board block ignores a new action default | Blocks keep the domain and context captured when pinned |
| Changed a shipped dashboard, lost it after upgrade | Standard dashboards are reloaded from module data; edit a copy |
| No edit icon on the dashboard | It shows only in developer mode for Dashboard admins; use Configuration → Dashboards → Edit in Spreadsheet |
| A user changed a shared filter preset | Shared presets (no `user_ids`) are writable by every internal user |
| Source XML of a board changed, a user's board did not | That user's `ir.ui.view.custom` overrides the base view |

## Related Docs

- [`INDEX.md`](INDEX.md)

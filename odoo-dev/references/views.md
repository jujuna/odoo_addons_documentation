# XML Views & Inheritance — Odoo 20

## Table of Contents

1. [View Types](#1-view-types)
2. [Form Views](#2-form-views)
3. [List Views](#3-list-views)
4. [Search Views](#4-search-views)
5. [Kanban Views](#5-kanban-views)
6. [Pivot, Graph, Calendar & Activity Views](#6-pivot-graph-calendar--activity-views)
7. [View Inheritance](#7-view-inheritance)
8. [Expressions (invisible/readonly/required)](#8-expressions)
9. [QWeb Report Templates](#9-qweb-report-templates)
10. [Actions & Menus](#10-actions--menus)
11. [Common Patterns](#11-common-patterns)
12. [Icons (Material Symbols)](#12-icons-material-symbols)
13. [Antipatterns](#13-antipatterns)

---

## 1. View Types

| Type | Tag | Purpose |
|------|-----|---------|
| Form | `<form>` | Single record editing |
| List | `<list>` | Multi-record table — `<list>`, never `<tree>` |
| Search | `<search>` | Filters, group-by, search fields |
| Kanban | `<kanban>` | Card-based view |
| Calendar | `<calendar>` | Date-based view |
| Pivot | `<pivot>` | Pivot table analysis |
| Graph | `<graph>` | Charts |
| Activity | `<activity>` | Activity-centric view |
| Card | `<card>` | **v20** — card layout, new `ir.ui.view` type |

---

## 2. Form Views

### Standard structure:
```xml
<record id="my_model_view_form" model="ir.ui.view">
    <field name="name">my.model.view.form</field>
    <field name="model">my.model</field>
    <field name="arch" type="xml">
        <form string="My Model">
            <header>
                <!-- Status buttons -->
                <button name="action_confirm" type="object"
                        string="Confirm" class="oe_highlight"
                        invisible="state != 'draft'"/>
                <!-- Statusbar widget -->
                <field name="state" widget="statusbar"
                       statusbar_visible="draft,confirmed,done"/>
            </header>
            <sheet>
                <!-- Smart buttons -->
                <div class="oe_button_box" name="button_box">
                    <button name="action_open_invoices" type="object"
                            class="oe_stat_button" icon="payments">
                        <field name="invoice_count" string="Invoices"
                               widget="statinfo"/>
                    </button>
                </div>
                <!-- Title area -->
                <div class="oe_title">
                    <h1><field name="name" placeholder="e.g. SO001"/></h1>
                </div>
                <!-- Field groups (2-column layout) -->
                <group>
                    <group>
                        <field name="partner_id"/>
                        <field name="date"/>
                    </group>
                    <group>
                        <field name="user_id"/>
                        <field name="company_id" groups="base.group_multi_company"/>
                    </group>
                </group>
                <!-- Tabs -->
                <notebook>
                    <page string="Lines" name="lines">
                        <field name="line_ids">
                            <list editable="bottom">
                                <field name="sequence" widget="handle"/>
                                <field name="product_id"/>
                                <field name="quantity"/>
                                <field name="price_unit"/>
                                <field name="price_total" sum="Total"/>
                            </list>
                        </field>
                    </page>
                    <page string="Notes" name="notes">
                        <field name="notes"/>
                    </page>
                </notebook>
            </sheet>
            <!-- Chatter (requires mail.thread inheritance) -->
            <chatter/>
        </form>
    </field>
</record>
```

### Key rules:
- Always add `name` attribute on `<page>` and `<filter>` — needed for stable inheritance
- Use `<chatter/>` when model inherits `mail.thread`
- Use `class="oe_highlight"` for primary action buttons
- Use `groups="base.group_multi_company"` on `company_id` fields

---

## 3. List Views

```xml
<record id="my_model_view_list" model="ir.ui.view">
    <field name="name">my.model.view.list</field>
    <field name="model">my.model</field>
    <field name="arch" type="xml">
        <list string="My Models" multi_edit="1" default_order="date desc">
            <header>
                <!-- List-level action buttons -->
                <button name="action_confirm" type="object" string="Confirm"/>
            </header>
            <field name="name" decoration-bf="1"/>
            <field name="partner_id"/>
            <field name="date"/>
            <field name="amount_total" sum="Total"/>
            <field name="state" widget="badge"
                   decoration-success="state == 'done'"
                   decoration-info="state == 'confirmed'"
                   decoration-muted="state == 'cancelled'"/>
        </list>
    </field>
</record>
```

### Decorations:
| Attribute | Color | Use for |
|-----------|-------|---------|
| `decoration-bf` | **Bold** | Key identifier fields |
| `decoration-success` | Green | Positive states (done, paid) |
| `decoration-info` | Blue | In-progress states |
| `decoration-warning` | Orange | Needs attention |
| `decoration-danger` | Red | Error / overdue |
| `decoration-muted` | Gray | Cancelled / archived |

### List features:
- `multi_edit="1"` — allow editing multiple rows at once
- `default_order="date desc"` — override `_order` for this view
- `editable="bottom"` or `editable="top"` — inline editing
- `sum="Label"` on numeric fields — shows column total
- `optional="show"` / `optional="hide"` — let user toggle columns

---

## 4. Search Views

```xml
<record id="my_model_view_search" model="ir.ui.view">
    <field name="name">my.model.view.search</field>
    <field name="model">my.model</field>
    <field name="arch" type="xml">
        <search string="Search">
            <!-- Quick search fields -->
            <field name="name"/>
            <field name="partner_id" operator="child_of"/>
            <field name="user_id"/>
            <separator/>
            <!-- Predefined filters -->
            <filter name="filter_draft" string="Draft"
                    domain="[('state', '=', 'draft')]"/>
            <filter name="filter_confirmed" string="Confirmed"
                    domain="[('state', '=', 'confirmed')]"/>
            <separator/>
            <filter name="filter_my" string="My Records"
                    domain="[('user_id', '=', uid)]"/>
            <separator/>
            <filter name="filter_this_month" string="This Month"
                    date="date" default_period="this_month"/>
            <separator/>
            <filter name="filter_archived" string="Archived"
                    domain="[('active', '=', False)]"/>
            <!-- Group By -->
            <group expand="0" string="Group By">
                <filter name="groupby_state" string="Status"
                        context="{'group_by': 'state'}"/>
                <filter name="groupby_partner" string="Partner"
                        context="{'group_by': 'partner_id'}"/>
                <filter name="groupby_date" string="Date"
                        context="{'group_by': 'date:month'}"/>
            </group>
            <!-- Search panels (left sidebar) -->
            <searchpanel>
                <field name="state" icon="checklist"
                       select="one" enable_counters="1"/>
                <field name="user_id" icon="person"
                       select="multi" enable_counters="1"/>
            </searchpanel>
        </search>
    </field>
</record>
```

### Key rules:
- Always give `name` to filters — required for `search_default_*` context and inheritance
- Use `date` attribute for date filters — gives automatic period picker
- `operator="child_of"` on Many2one — searches parent + children
- `enable_counters="1"` on searchpanel — shows record counts (has perf cost)

---

## 5. Kanban Views

```xml
<record id="my_model_view_kanban" model="ir.ui.view">
    <field name="name">my.model.view.kanban</field>
    <field name="model">my.model</field>
    <field name="arch" type="xml">
        <kanban default_group_by="state" class="o_kanban_small_column"
                quick_create="false" records_draggable="true">
            <progressbar field="state"
                         colors='{"draft": "muted", "confirmed": "warning", "done": "success"}'/>
            <templates>
                <t t-name="card">
                    <div class="oe_kanban_details">
                        <strong>
                            <field name="name"/>
                        </strong>
                        <div class="o_kanban_record_bottom">
                            <div class="oe_kanban_bottom_left">
                                <field name="date"/>
                            </div>
                            <div class="oe_kanban_bottom_right">
                                <field name="user_id" widget="many2one_avatar_user"/>
                            </div>
                        </div>
                    </div>
                </t>
            </templates>
        </kanban>
    </field>
</record>
```

---

## 6. Pivot, Graph, Calendar & Activity Views

### Pivot View:
```xml
<record id="my_model_view_pivot" model="ir.ui.view">
    <field name="name">my.model.view.pivot</field>
    <field name="model">my.model</field>
    <field name="arch" type="xml">
        <pivot string="Analysis" sample="1">
            <field name="partner_id" type="row"/>
            <field name="state" type="col"/>
            <field name="amount_total" type="measure"/>
            <field name="quantity" type="measure"/>
        </pivot>
    </field>
</record>
```

Pivot attributes:
- `type="row"` — row grouping
- `type="col"` — column grouping
- `type="measure"` — aggregated values
- `sample="1"` — show sample data when empty
- `disable_linking="1"` — prevent click-through to records
- `display_quantity="1"` — show count column

### Graph View:
```xml
<record id="my_model_view_graph" model="ir.ui.view">
    <field name="name">my.model.view.graph</field>
    <field name="model">my.model</field>
    <field name="arch" type="xml">
        <graph string="Revenue Analysis" type="bar" stacked="1" sample="1">
            <field name="date" interval="month"/>
            <field name="state" type="col"/>
            <field name="amount_total" type="measure"/>
        </graph>
    </field>
</record>
```

Graph `type` values:
| Type | Use |
|------|-----|
| `bar` | Comparison across categories (default) |
| `line` | Trends over time |
| `pie` | Proportional distribution |

Graph attributes: `stacked="1"`, `cumulative="1"` (line only), `order="DESC"`.

### Calendar View:
```xml
<record id="my_model_view_calendar" model="ir.ui.view">
    <field name="name">my.model.view.calendar</field>
    <field name="model">my.model</field>
    <field name="arch" type="xml">
        <calendar string="Schedule" date_start="date_start" date_stop="date_end"
                  color="user_id" mode="month" event_limit="5"
                  quick_create="false" scales="month,week,day">
            <field name="name"/>
            <field name="partner_id" avatar_field="avatar_128"/>
            <field name="state" filters="1"/>
        </calendar>
    </field>
</record>
```

Calendar attributes:
- `date_start` / `date_stop` — required date fields
- `date_delay` — alternative to `date_stop` (duration in hours)
- `all_day` — boolean field for all-day events
- `color` — field for color coding (each value gets a color)
- `mode` — default view: `day`, `week`, `month`, `year`
- `quick_create="false"` — disable quick-create on click
- `event_limit` — max events per day cell before "+N more"

### Activity View:
```xml
<!-- Activity view requires mail.activity.mixin on the model -->
<!-- No custom arch needed — Odoo generates it from activity types -->
<!-- Just add 'activity' to view_mode in the action: -->
<field name="view_mode">list,form,kanban,activity</field>
```

---

## 7. View Inheritance

### XPath-based inheritance (most common):
```xml
<record id="my_model_view_form_inherit" model="ir.ui.view">
    <field name="name">my.model.view.form.inherit.my_module</field>
    <field name="model">my.model</field>
    <field name="inherit_id" ref="original_module.my_model_view_form"/>
    <field name="arch" type="xml">
        <!-- Add a field after an existing one -->
        <xpath expr="//field[@name='partner_id']" position="after">
            <field name="my_custom_field"/>
        </xpath>

        <!-- Add a field before an existing one -->
        <xpath expr="//field[@name='date']" position="before">
            <field name="priority" widget="priority"/>
        </xpath>

        <!-- Replace a field entirely -->
        <xpath expr="//field[@name='notes']" position="replace">
            <field name="notes" placeholder="Custom placeholder..."/>
        </xpath>

        <!-- Add content inside an element (at the end) -->
        <xpath expr="//div[@name='button_box']" position="inside">
            <button name="action_open_custom" type="object"
                    class="oe_stat_button" icon="settings">
                <field name="custom_count" string="Custom" widget="statinfo"/>
            </button>
        </xpath>

        <!-- Add attributes to an existing element -->
        <xpath expr="//field[@name='name']" position="attributes">
            <attribute name="readonly">state != 'draft'</attribute>
        </xpath>

        <!-- Remove an element -->
        <xpath expr="//field[@name='old_field']" position="replace"/>

        <!-- Add a new notebook page -->
        <xpath expr="//notebook" position="inside">
            <page string="Custom Tab" name="custom_tab">
                <group>
                    <field name="custom_field_1"/>
                    <field name="custom_field_2"/>
                </group>
            </page>
        </xpath>
    </field>
</record>
```

### Shorthand inheritance (when target is unique):
```xml
<!-- Short form — works when the element is unique in the view -->
<field name="arch" type="xml">
    <!-- Instead of xpath, use the element directly -->
    <field name="partner_id" position="after">
        <field name="my_field"/>
    </field>

    <!-- Works for pages too -->
    <page name="notes" position="after">
        <page string="Extra" name="extra">
            <field name="extra_info"/>
        </page>
    </page>
</field>
```

### XPath positions:
| Position | Effect |
|----------|--------|
| `after` | Insert after the matched element |
| `before` | Insert before the matched element |
| `inside` | Append inside the matched element (at the end) |
| `replace` | Replace the matched element (empty = delete) |
| `attributes` | Modify attributes of the matched element |
| `move` | Move the matched element to another location |

### Priority control:
```xml
<!-- Lower priority = loaded first. Default is 16. -->
<field name="priority" eval="20"/>

<!-- Use higher priority to override other inheritance -->
<field name="priority" eval="99"/>
```

### Common XPath expressions:
```xml
<!-- By field name -->
//field[@name='partner_id']

<!-- By page name (that's why name attribute matters!) -->
//page[@name='lines']

<!-- By filter name in search view -->
//filter[@name='filter_draft']

<!-- By CSS class -->
//div[hasclass('oe_button_box')]

<!-- By element + attribute combo -->
//button[@name='action_confirm']

<!-- Nested: field inside a specific page -->
//page[@name='lines']//field[@name='line_ids']

<!-- The header element -->
//header

<!-- The sheet element -->
//sheet

<!-- Notebook -->
//notebook
```

---

## 8. Expressions

Views use **expression strings** directly on elements. The old `attrs` dictionary
syntax is deprecated.

### Modern syntax (v17+):
```xml
<!-- Invisible — hide based on condition -->
<field name="discount" invisible="state != 'draft'"/>
<field name="warranty" invisible="not has_warranty"/>
<group invisible="state in ('cancelled', 'done')">...</group>

<!-- Readonly — prevent editing -->
<field name="partner_id" readonly="state != 'draft'"/>
<field name="amount" readonly="1"/>

<!-- Required — make mandatory based on condition -->
<field name="tracking_ref" required="state == 'confirmed'"/>

<!-- Column invisible in list (hides entire column) -->
<field name="internal_note" column_invisible="1"/>
<field name="warehouse_id" column_invisible="not parent.show_warehouse"/>
```

### Expression syntax rules:
- Expressions are Python-like but evaluated in a limited sandbox
- Can reference: field names, `parent.field` (for embedded lists), `context.get('key')`
- Operators: `==`, `!=`, `>`, `<`, `>=`, `<=`, `in`, `not in`, `and`, `or`, `not`
- Literals: strings, numbers, `True`, `False`, `None`
- No function calls, no complex expressions

### Deprecated `attrs` syntax — DO NOT USE in new code:
```xml
<!-- OLD — do not use -->
<field name="discount" attrs="{'invisible': [('state', '!=', 'draft')]}"/>
<field name="amount" attrs="{'readonly': [('state', '!=', 'draft')], 'required': [('type', '=', 'invoice')]}"/>

<!-- NEW — use direct expressions -->
<field name="discount" invisible="state != 'draft'"/>
<field name="amount" readonly="state != 'draft'" required="type == 'invoice'"/>
```

---

## 9. QWeb Report Templates

### Report action:
```xml
<record id="action_report_my_model" model="ir.actions.report">
    <field name="name">My Report</field>
    <field name="model">my.model</field>
    <field name="report_type">qweb-pdf</field>
    <field name="report_name">my_module.report_my_model</field>
    <field name="report_file">my_module.report_my_model</field>
    <field name="binding_model_id" ref="model_my_model"/>
    <field name="binding_type">report</field>
</record>
```

### Report template:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <template id="report_my_model">
        <t t-call="web.html_container">
            <t t-foreach="docs" t-as="doc">
                <t t-call="web.external_layout">
                    <div class="page">
                        <h2><t t-out="doc.name"/></h2>

                        <div class="row mb-4">
                            <div class="col-6">
                                <strong>Partner:</strong>
                                <span t-field="doc.partner_id"/>
                            </div>
                            <div class="col-6">
                                <strong>Date:</strong>
                                <span t-field="doc.date"/>
                            </div>
                        </div>

                        <table class="table table-sm">
                            <thead>
                                <tr>
                                    <th>Product</th>
                                    <th class="text-end">Qty</th>
                                    <th class="text-end">Price</th>
                                    <th class="text-end">Total</th>
                                </tr>
                            </thead>
                            <tbody>
                                <t t-foreach="doc.line_ids" t-as="line">
                                    <tr>
                                        <td><t t-out="line.product_id.name"/></td>
                                        <td class="text-end">
                                            <t t-out="line.quantity"/>
                                        </td>
                                        <td class="text-end">
                                            <span t-field="line.price_unit"
                                                  t-options='{"widget": "monetary", "display_currency": doc.company_id.currency_id}'/>
                                        </td>
                                        <td class="text-end">
                                            <span t-field="line.price_total"
                                                  t-options='{"widget": "monetary", "display_currency": doc.company_id.currency_id}'/>
                                        </td>
                                    </tr>
                                </t>
                            </tbody>
                        </table>
                    </div>
                </t>
            </t>
        </t>
    </template>
</odoo>
```

### Report rules:
- Use `t-out` for values. It escapes by default; only a `Markup` value passes through raw.
  `t-esc` and `t-raw` are gone — core has 0 `t-esc` and 576 `t-out` in `addons/*/report/`.
- Use `t-field` for formatted output (respects locale, widget options)
- Use `t-options='{"widget": "monetary", "display_currency": doc.currency_id}'` for money
- Use `t-options='{"widget": "date"}'` for locale-aware dates
- `web.external_layout` provides the company header/footer
- `web.html_container` wraps everything for PDF generation
- `report_type`: `qweb-pdf` for PDF, `qweb-html` for browser preview

### v20: `t-call` takes parameters as attributes

The `<t t-set>`-before-`<t t-call>` idiom is gone. Pass values on the `t-call` element:

```xml
<!-- v19 -->
<t t-call="web.brand_promotion_message">
    <t t-set="_utm_medium">portal</t>
</t>

<!-- v20 -->
<t t-call="web.brand_promotion_message" _message.translate="" _utm_medium.f="portal"/>
```

| Form | Meaning |
|---|---|
| `name="expr"` | Python expression |
| `name.f="text"` | format string / literal |
| `name.translate="text"` | translatable literal |

The called template's body is still available as `t-out="0"`. Real example:
[addons/web/views/webclient_templates.xml:103](../../../../addons/web/views/webclient_templates.xml#L103).

---

## 10. Actions & Menus

### Window action:
```xml
<record id="my_model_action" model="ir.actions.act_window">
    <field name="name">My Models</field>
    <field name="res_model">my.model</field>
    <field name="view_mode">list,form,kanban</field>
    <field name="search_view_id" ref="my_model_view_search"/>
    <field name="context">{'search_default_filter_my': 1}</field>
    <field name="domain">[('active', '=', True)]</field>
    <field name="help" type="html">
        <p class="o_view_nocontent_smiling_face">Create your first record</p>
    </field>
</record>
```

### Action to open a specific form:
```xml
<record id="action_open_specific_record" model="ir.actions.act_window">
    <field name="name">Specific Record</field>
    <field name="res_model">my.model</field>
    <field name="view_mode">form</field>
    <field name="res_id" ref="my_specific_record"/>
    <field name="target">new</field>  <!-- dialog -->
</record>
```

### Menu hierarchy:
```xml
<!-- Root menu (app icon in sidebar) -->
<menuitem id="menu_root"
          name="My App"
          sequence="100"
          web_icon="my_module,static/description/icon.png"
          groups="my_module.group_user"/>

<!-- First level (section headers) -->
<menuitem id="menu_operations"
          name="Operations"
          parent="menu_root"
          sequence="10"/>

<!-- Second level (actual menu items with actions) -->
<menuitem id="menu_my_models"
          name="My Models"
          parent="menu_operations"
          action="my_model_action"
          sequence="10"/>
```

### Action `target` values:
| Value | Behavior |
|-------|----------|
| `current` (default) | Opens in main content area |
| `new` | Opens in a dialog/modal |
| `inline` | Opens inline (rare) |
| `fullscreen` | Opens fullscreen (for dashboards) |
| `main` | Opens as main action (clears breadcrumb) |

---

## 11. Common Patterns

### Conditional button with confirmation:
```xml
<button name="action_dangerous" type="object"
        string="Delete All"
        confirm="Are you sure you want to delete all records?"
        groups="my_module.group_manager"
        invisible="state != 'draft'"/>
```

### URL button:
```xml
<button type="object" name="action_open_url"
        string="Open Website" icon="open_in_new"/>
```

### Widget reference (common field widgets):
| Widget | Field type | Purpose |
|--------|-----------|---------|
| `statusbar` | Selection | Status bar in header |
| `badge` | Selection | Colored badge in list |
| `many2one_avatar_user` | Many2one(res.users) | User avatar |
| `many2many_tags` | Many2many | Tag-style display |
| `monetary` | Float | Currency-formatted |
| `percentage` | Float | Percentage display |
| `priority` | Selection | Star rating |
| `handle` | Integer | Drag handle for reordering |
| `image` | Binary | Image preview |
| `html` | Html | Rich text editor |
| `radio` | Selection | Radio buttons |
| `color_picker` | Integer | Color picker |
| `progressbar` | Float/Integer | Progress bar |
| `statinfo` | Integer/Float | Stat button number |
| `date` | Date | Date picker |
| `daterange` | Date | Date range picker |

### Conditional field labels:
```xml
<label for="partner_id" string="Customer"
       invisible="is_vendor"/>
<label for="partner_id" string="Vendor"
       invisible="not is_vendor"/>
<field name="partner_id" nolabel="1"/>
```

---

## 12. Icons (Material Symbols)

Font Awesome is gone in v20. Icons are **Material Symbols**, drawn as font ligatures: the
text in `data-icon` is turned into the glyph by the font.

```xml
<!-- buttons, stat buttons, searchpanel fields: the name only -->
<button name="action_open" type="object" icon="open_in_new" string="Open"/>

<!-- markup: class="oi" + data-icon, plus a title for screen readers -->
<i class="oi me-1" data-icon="warning" title="Out of sync"/>

<!-- solid variant, utilities, brand icons -->
<i class="oi oi-filled" data-icon="check_circle" title="Active"/>
<i class="oi oi-spin oi-2x" data-icon="progress_activity" title="Loading"/>
<i class="oi" data-icon="oi_github" title="GitHub"/>
```

- Button `icon=` is copied into `data-icon` as-is —
  [view_button.js:24](../../../../addons/web/static/src/views/view_button/view_button.js#L24).
  A leftover `icon="fa-search-plus"` renders the ligature it can find plus the literal
  dashes: `-🔍-`. There is no `fa-` compatibility mapping any more.
- **Only names in the shipped font subset render.** The list is `ICONS` in
  [addons/web/icons.py](../../../../addons/web/icons.py) (Material Symbols plus the `oi_`
  brand/legacy set). Check a name before using it:
  `grep -q "^    'zoom_in'" addons/web/icons.py`.
- `<i data-icon>` without `title`, `aria-label` or text in itself, a parent or a child
  triggers a view-validation warning on module update.
- Utilities: `fa-spin` → `oi-spin`, `fa-2x` → `oi-2x`, `fa-fw` → `oi-fw`, `fa-lg` → `oi-lg`.
  Outlined is the default; FA's solid-vs-`-o` pair becomes one name, with `oi-filled` for
  the solid look where the difference carries meaning.
- SCSS and test selectors keyed on the icon must move: `.fa-truck` →
  `[data-icon="local_shipping"]`, `.fa` → `.oi`; tours using `.fa-caret-right` →
  `[data-icon=arrow_right]`.

Common Font Awesome → Material Symbols names (all verified in `icons.py`):

| FA | MS | FA | MS | FA | MS |
|---|---|---|---|---|---|
| check | `check` | times | `close` | plus | `add` |
| trash, trash-o | `delete` | pencil | `edit` | pencil-square-o | `edit_square` |
| search | `search` | search-plus | `zoom_in` | refresh | `refresh` |
| download | `download` | cloud-upload | `cloud_upload` | cloud-download | `cloud_download` |
| print | `print` | external-link | `open_in_new` | link / unlink | `link` / `link_off` |
| lock | `lock` | ban | `block` | undo | `undo` |
| history | `history` | clock-o | `schedule` | calendar | `calendar_today` |
| bell | `notifications` | user / users | `person` / `group` | id-card-o | `badge` |
| truck | `local_shipping` | car | `directions_car` | shopping-cart | `shopping_cart` |
| money | `payments` | file-text(-o) | `description` | list-alt | `list_alt` |
| list / list-ul | `view_list` / `format_list_bulleted` | sort-numeric-asc | `format_list_numbered` | table | `table_chart` |
| line-chart | `show_chart` | tachometer | `speed` | sitemap | `account_tree` |
| exchange | `swap_horiz` | arrows-h | `arrow_range` | arrow-right, long-arrow-right | `east` |
| level-up | `arrow_upward` | caret-right / caret-down | `arrow_right` / `arrow_drop_down` | info-circle | `info` |
| question-circle | `help` | exclamation-triangle | `warning` | exclamation-circle | `error` |
| check-circle(-o) | `check_circle` | times-circle(-o) | `cancel` | check-square-o | `check_box` |
| circle / circle-o | `circle` / `radio_button_unchecked` | play / pause / stop | `play_arrow` / `pause` / `stop` | paper-plane, send | `send` |
| eye | `visibility` | copy | `content_copy` | bookmark | `bookmark` |
| key | `key` | plug | `power` | sign-out | `logout` |
| globe | `public` | flask | `science` | rocket | `rocket_launch` |
| magic | `wand_stars` | eraser | `ink_eraser` | cubes | `deployed_code` |
| building-o | `business` | inbox | `inventory_2` | road | `signpost` |
| bullseye | `my_location` | hourglass-half | `hourglass_top` | circle-o-notch (spin) | `progress_activity` |
| archive | `archive` | cog | `settings` | tasks | `checklist` |
| life-ring | `support` | flag | `flag` | | |

---

## 13. Antipatterns

### DO NOT use deprecated `attrs`:
```xml
<!-- WRONG (v17+ deprecation) -->
<field name="x" attrs="{'invisible': [('state', '!=', 'draft')]}"/>

<!-- CORRECT -->
<field name="x" invisible="state != 'draft'"/>
```

### DO NOT use `<tree>` in new code:
```xml
<!-- WRONG (deprecated alias) -->
<tree string="Records">...</tree>

<!-- CORRECT -->
<list string="Records">...</list>
```

### DO NOT forget `name` on pages and filters:
```xml
<!-- WRONG — cannot be inherited by other modules -->
<page string="Notes">...</page>

<!-- CORRECT -->
<page string="Notes" name="notes">...</page>
```

### DO NOT use inline styles:
```xml
<!-- WRONG -->
<div style="color: red; font-weight: bold;">...</div>

<!-- CORRECT — use Bootstrap or custom SCSS -->
<div class="text-danger fw-bold">...</div>
```

### DO NOT hardcode view IDs for standard models:
```xml
<!-- WRONG — fragile if the view is removed or renamed -->
<field name="view_id" ref="sale.sale_order_form_view_id_that_might_change"/>

<!-- CORRECT — let Odoo resolve the default view -->
<!-- Just use view_mode without specifying explicit view IDs -->
```

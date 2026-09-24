# Data Files — Odoo 20

## Table of Contents

1. [XML Data Files](#1-xml-data-files)
2. [Field Value Types](#2-field-value-types)
3. [noupdate](#3-noupdate)
4. [CSV Data Files](#4-csv-data-files)
5. [Sequences](#5-sequences)
6. [Server Actions](#6-server-actions)
7. [Automated Actions](#7-automated-actions)
8. [Mail Templates](#8-mail-templates)
9. [Demo Data](#9-demo-data)
10. [Manifest Data Order](#10-manifest-data-order)
11. [Special Eval Expressions](#11-special-eval-expressions)
12. [Record Operations](#12-record-operations)
13. [Antipatterns](#13-antipatterns)

---

## 1. XML Data Files

### Basic record creation

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="my_record" model="my.model">
        <field name="name">My Record</field>
        <field name="active" eval="True"/>
        <field name="partner_id" ref="base.main_partner"/>
    </record>
</odoo>
```

### Key attributes

| Attribute | Purpose |
|---|---|
| `id` | XML ID — unique within module, used for `ref()` |
| `model` | Target model |
| `forcecreate` | If `"0"`, skip if record already exists |

---

## 2. Field Value Types

### Text value (default)

```xml
<field name="name">Plain text value</field>
```

### Reference to another record

```xml
<field name="partner_id" ref="base.res_partner_2"/>
<field name="company_id" ref="base.main_company"/>
```

### Eval (Python expression)

```xml
<field name="active" eval="True"/>
<field name="amount" eval="1500.0"/>
<field name="sequence" eval="10"/>
<field name="date" eval="DateTime.today()"/>
<field name="partner_ids" eval="[(4, ref('base.res_partner_2'))]"/>
```

### HTML content

```xml
<field name="body_html" type="html">
    <p>Hello <strong>World</strong></p>
</field>
```

### XML content (for arch fields)

```xml
<field name="arch" type="xml">
    <form>
        <field name="name"/>
    </form>
</field>
```

### Relational field commands in eval

```python
# Link existing record
eval="[(4, ref('module.xml_id'))]"

# Replace all links
eval="[(6, 0, [ref('module.id1'), ref('module.id2')])]"

# Create and link
eval="[(0, 0, {'name': 'New', 'value': 42})]"

# Unlink
eval="[(3, ref('module.xml_id'))]"

# Clear all
eval="[(5, 0, 0)]"
```

---

## 3. noupdate

### When to use `noupdate="1"`

```xml
<data noupdate="1">
    <!-- Records users may customize — won't be overwritten on module update -->
    <record id="..." model="ir.cron">...</record>
    <record id="..." model="mail.template">...</record>
    <record id="..." model="ir.sequence">...</record>
    <record id="..." model="ir.config_parameter">...</record>
</data>
```

### When NOT to use noupdate

```xml
<data>
    <!-- Records that must always match code — overwritten on update -->
    <record id="..." model="ir.ui.view">...</record>
    <record id="..." model="ir.actions.act_window">...</record>
    <record id="..." model="ir.access">...</record>
    <record id="..." model="res.groups">...</record>
</data>
```

### Rule of thumb

| Record type | noupdate? | Why |
|---|---|---|
| Views, actions, menus | No | Must stay in sync with code |
| Security groups, `ir.access` rows | No | Must stay in sync with code |
| Cron jobs | Yes | Admin may change schedule |
| Mail templates | Yes | Admin may customize text |
| Sequences | Yes | Admin may change prefix/padding |
| Config parameters | Yes | Admin sets values |
| Default data records | Yes | Users may modify them |
| Demo data | Yes | Never overwrite |

---

## 4. CSV Data Files

### ir.access.csv (v20 — replaces ir.model.access.csv **and** ir.rule)

```csv
id,name,model_id,group_id/id,operation,domain
access_my_model_user,my.model user,my.model,my_module.group_user,cru,
access_my_model_manager,my.model manager,my.model,my_module.group_manager,crud,
my_model_comp_rule,My Model multi-company,my.model,,crud,"[('company_id', 'in', company_ids)]"
```

- `model_id` is the model **name**, not the `model_xxx` xml id
- `group_id/id` empty means a **restriction** applied to everyone, not "grant to all"
- `operation` is one Selection value (`r`, `cru`, `crud`, …), not four boolean columns
- this file goes **last** in the manifest `data` list

Full semantics: `security.md`.

### Bulk data CSV

```csv
"id","name","code","active"
"data_record_1","Record One","R001","1"
"data_record_2","Record Two","R002","1"
```

CSV file naming: `data/<model_name_with_dots_replaced>.csv` (e.g., `data/my.model.csv`).

---

## 5. Sequences

### Definition

```xml
<data noupdate="1">
    <record id="seq_my_model" model="ir.sequence">
        <field name="name">My Model Sequence</field>
        <field name="code">my.model</field>
        <field name="prefix">MM/%(year)s/</field>
        <field name="padding">5</field>
        <field name="company_id" eval="False"/>
    </record>
</data>
```

### Usage in Python

```python
@api.model_create_multi
def create(self, vals_list):
    for vals in vals_list:
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('my.model') or _('New')
    return super().create(vals_list)
```

### Prefix patterns

| Pattern | Output |
|---|---|
| `%(year)s` | `2026` |
| `%(month)s` | `03` |
| `%(day)s` | `14` |
| `%(y)s` | `26` (2-digit year) |
| `%(h24)s` | `14` (hour 0-23) |

---

## 6. Server Actions

### Code action

```xml
<record id="action_mass_archive" model="ir.actions.server">
    <field name="name">Archive Selected</field>
    <field name="model_id" ref="model_my_model"/>
    <field name="binding_model_id" ref="model_my_model"/>
    <field name="binding_view_types">list</field>
    <field name="state">code</field>
    <field name="code">
        records.write({'active': False})
    </field>
</record>
```

### Available variables in server action code

| Variable | Value |
|---|---|
| `records` | Selected recordset (from `active_ids`) |
| `record` | First selected record |
| `env` | Environment |
| `model` | Model class |
| `user` | Current user record |
| `datetime`, `dateutil` | Date utilities |
| `time` | Python time module |
| `log` | Logger function |
| `Warning` | `odoo.exceptions.UserError` |
| `action` | Set this to return an action dict |

### Email server action

```xml
<record id="action_send_reminder" model="ir.actions.server">
    <field name="name">Send Reminder</field>
    <field name="model_id" ref="model_my_model"/>
    <field name="state">email</field>
    <field name="template_id" ref="email_template_reminder"/>
</record>
```

---

## 7. Automated Actions

Automated actions trigger on record events (create, write, delete, timed).

```xml
<record id="auto_action_on_confirm" model="base.automation">
    <field name="name">Auto-assign on Confirm</field>
    <field name="model_id" ref="model_my_model"/>
    <field name="trigger">on_write</field>
    <field name="trigger_field_ids" eval="[(4, ref('field_my_model__state'))]"/>
    <field name="filter_domain">[('state', '=', 'confirmed')]</field>
    <field name="filter_pre_domain">[('state', '=', 'draft')]</field>
    <field name="state">code</field>
    <field name="code">
        if not record.user_id:
            record.user_id = env.user
    </field>
</record>
```

### Trigger types

| Trigger | When it fires |
|---|---|
| `on_create` | After record creation |
| `on_write` | After record update |
| `on_create_or_write` | After create or update |
| `on_unlink` | Before record deletion |
| `on_change` | On field change in UI (like onchange) |
| `on_time` | Based on a date field + offset |

### Timed trigger

```xml
<record id="auto_action_overdue" model="base.automation">
    <field name="name">Mark Overdue</field>
    <field name="model_id" ref="model_my_model"/>
    <field name="trigger">on_time</field>
    <field name="trg_date_id" ref="field_my_model__date_deadline"/>
    <field name="trg_date_range">1</field>
    <field name="trg_date_range_type">day</field>
    <field name="filter_domain">[('state', '=', 'confirmed')]</field>
    <field name="state">code</field>
    <field name="code">record.write({'is_overdue': True})</field>
</record>
```

---

## 8. Mail Templates

```xml
<data noupdate="1">
    <record id="email_template_confirmed" model="mail.template">
        <field name="name">My Model: Order Confirmed</field>
        <field name="model_id" ref="model_my_model"/>
        <field name="subject">Order {{ object.name }} Confirmed</field>
        <field name="email_from">{{ (object.company_id.email or user.email) }}</field>
        <field name="email_to">{{ object.partner_id.email }}</field>
        <field name="body_html" type="html">
            <div>
                <p>Dear {{ object.partner_id.name }},</p>
                <p>Order <strong>{{ object.name }}</strong> has been confirmed.</p>
            </div>
        </field>
        <field name="auto_delete" eval="True"/>
    </record>
</data>
```

---

## 9. Demo Data

```xml
<!-- demo/demo_data.xml -->
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="1">
        <record id="demo_record_1" model="my.model">
            <field name="name">Demo Record</field>
            <field name="partner_id" ref="base.res_partner_2"/>
            <field name="user_id" ref="base.user_demo"/>
            <field name="date" eval="DateTime.today()"/>
            <field name="state">confirmed</field>
        </record>
    </data>
</odoo>
```

In `__manifest__.py`:

```python
'demo': [
    'demo/demo_data.xml',
],
```

Demo data is only loaded when the database is created with "Load demonstration data" checked.

---

## 10. Manifest Data Order

v20 order — groups first, **access last**:

```python
'data': [
    # 1. Groups and privileges — ALWAYS first
    'security/my_module_security.xml',

    # 2. Core data
    'data/ir_sequence_data.xml',
    'data/ir_cron_data.xml',
    'data/mail_template_data.xml',

    # 3. Reports and wizards
    'report/my_report_templates.xml',
    'wizards/my_wizard_views.xml',

    # 4. Views, actions, menus
    'views/my_model_views.xml',
    'views/my_model_menus.xml',

    # 5. Access rows — ALWAYS last
    'security/ir.access.csv',
],
```

**Why:**
- Views, menus and actions reference groups, so groups load first
- `ir.access` rows carry domains that may reference records defined by the module, so they
  load after everything else
- Menus reference actions, so menu files come after the view files that define them

Verified in `account`, `stock`, `project`, `hr`, `purchase`, `mail`, `sale`: the groups file
is manifest entry 0 and `security/ir.access.csv` is the final entry.

---

## 11. Special Eval Expressions

### Available in eval context

```xml
<!-- Reference another record's ID -->
<field name="partner_id" eval="ref('base.main_partner')"/>

<!-- Current date/time -->
<field name="date" eval="DateTime.today()"/>
<field name="date" eval="(DateTime.today() + relativedelta(months=1)).strftime('%Y-%m-%d')"/>

<!-- Time operations -->
<field name="interval_number" eval="1"/>

<!-- Boolean -->
<field name="active" eval="True"/>
<field name="active" eval="False"/>

<!-- List/tuple -->
<field name="partner_ids" eval="[(4, ref('base.main_partner'))]"/>
<field name="users" eval="[(4, ref('base.user_root')), (4, ref('base.user_admin'))]"/>
```

### Available modules in eval

- `ref(xml_id)` — resolve XML ID to database ID
- `DateTime` — `datetime.datetime`
- `relativedelta` — from `dateutil`
- `time` — Python `time` module

---

## 12. Record Operations

### Delete a record

```xml
<delete id="other_module.record_to_remove" model="ir.ui.view"/>
```

### Function call (legacy, avoid if possible)

```xml
<function model="res.company" name="write">
    <value eval="[ref('base.main_company')]"/>
    <value eval="{'currency_id': ref('base.USD')}"/>
</function>
```

### Conditional record (forcecreate)

```xml
<!-- Only create if this XML ID doesn't already exist -->
<record id="default_config" model="ir.config_parameter" forcecreate="0">
    <field name="key">my_module.setting</field>
    <field name="value">default_value</field>
</record>
```

---

## 13. Antipatterns

### Wrong manifest load order

```python
# BAD — views reference groups that don't exist yet, and access loads too early
'data': [
    'views/my_model_views.xml',
    'security/my_module_security.xml',   # too late
    'security/ir.access.csv',
]

# GOOD — groups first, access last
'data': [
    'security/my_module_security.xml',
    'views/my_model_views.xml',
    'security/ir.access.csv',
]
```

### Missing noupdate on user-configurable records

```xml
<!-- BAD — cron schedule reset on every module update -->
<record id="my_cron" model="ir.cron">
    <field name="interval_number">1</field>
    ...
</record>

<!-- GOOD -->
<data noupdate="1">
    <record id="my_cron" model="ir.cron">
        <field name="interval_number">1</field>
        ...
    </record>
</data>
```

### Hardcoded database IDs

```xml
<!-- BAD — ID 1 is not guaranteed to be the right record -->
<field name="partner_id" eval="1"/>

<!-- GOOD — use XML ID reference -->
<field name="partner_id" ref="base.main_partner"/>
```

### noupdate on views/security

```xml
<!-- BAD — view changes won't apply on module update -->
<data noupdate="1">
    <record id="my_view" model="ir.ui.view">...</record>
</data>

<!-- GOOD — views must update with code -->
<record id="my_view" model="ir.ui.view">...</record>
```

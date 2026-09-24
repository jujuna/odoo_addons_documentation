# Wizards (TransientModel) — Odoo 20

## Table of Contents

1. [TransientModel Basics](#1-transientmodel-basics)
2. [Simple Wizard Pattern](#2-simple-wizard-pattern)
3. [Wizard with Lines](#3-wizard-with-lines)
4. [Multi-Step Wizard](#4-multi-step-wizard)
5. [Pre-Populating Wizards](#5-pre-populating-wizards)
6. [Action Return Values](#6-action-return-values)
7. [Wizard Security](#7-wizard-security)
8. [Antipatterns](#8-antipatterns)

---

## 1. TransientModel Basics

Wizards use `TransientModel` — records are auto-deleted by a daily cron after ~1 hour.

```python
from odoo import api, fields, models, _


class MyWizard(models.TransientModel):
    """Wizard to perform a specific batch operation."""

    _name = 'my.module.wizard'
    _description = 'My Wizard'
```

**Key differences from `Model`:**
- No permanent DB storage — auto-cleaned by `_transient_vacuum()`
- No `mail.thread` or `mail.activity.mixin` — not needed
- No `active` field, no archiving
- **Access is exactly the same as a regular model.** A `TransientModel` does *not*
  auto-filter by `create_uid` — the class docstring says it "uses the same access rights
  mechanisms as a regular Model". Without rows in `security/ir.access.csv`, nobody can open
  the wizard; without an ownership domain, one user can read another user's wizard record.

---

## 2. Simple Wizard Pattern

### Python model:
```python
class MassConfirmWizard(models.TransientModel):
    """Wizard to confirm multiple records at once."""

    _name = 'my.module.mass.confirm.wizard'
    _description = 'Mass Confirm Wizard'

    record_ids = fields.Many2many(
        'my.model',
        string='Records to Confirm',
    )
    note = fields.Text(string='Confirmation Note')

    @api.model
    def default_get(self, fields_list):
        """Pre-fill record_ids from the active selection."""
        defaults = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        if active_ids and 'record_ids' in fields_list:
            records = self.env['my.model'].browse(active_ids).filtered(
                lambda r: r.state == 'draft'
            )
            defaults['record_ids'] = records.ids
        return defaults

    def action_confirm(self):
        """Confirm all selected records."""
        self.ensure_one()
        if not self.record_ids:
            raise UserError(_("No records selected."))
        self.record_ids.action_confirm()
        if self.note:
            for record in self.record_ids:
                record.message_post(body=self.note)
        return {'type': 'ir.actions.act_window_close'}
```

### XML view:
```xml
<record id="mass_confirm_wizard_view_form" model="ir.ui.view">
    <field name="name">my.module.mass.confirm.wizard.form</field>
    <field name="model">my.module.mass.confirm.wizard</field>
    <field name="arch" type="xml">
        <form string="Confirm Records">
            <group>
                <field name="record_ids" widget="many2many_tags" readonly="1"/>
            </group>
            <group>
                <field name="note" placeholder="Optional note..."/>
            </group>
            <footer>
                <button name="action_confirm" type="object"
                        string="Confirm All" class="btn-primary"/>
                <button string="Cancel" special="cancel"/>
            </footer>
        </form>
    </field>
</record>
```

### Action (opened from list view):
```xml
<record id="mass_confirm_wizard_action" model="ir.actions.act_window">
    <field name="name">Confirm Records</field>
    <field name="res_model">my.module.mass.confirm.wizard</field>
    <field name="view_mode">form</field>
    <field name="target">new</field>
    <field name="binding_model_id" ref="my_module.model_my_model"/>
    <field name="binding_view_types">list</field>
</record>
```

### Key elements:
- `target="new"` — opens as dialog
- `binding_model_id` — adds to the action menu of the target model
- `binding_view_types` — `list` for list view, `form` for form view, `list,form` for both
- `special="cancel"` — closes dialog without calling any method
- `default_get()` — reads `active_ids` / `active_id` from context

---

## 3. Wizard with Lines

When the wizard needs editable sub-records:

```python
class ImportWizard(models.TransientModel):
    """Wizard to import data with preview lines."""

    _name = 'my.module.import.wizard'
    _description = 'Import Wizard'

    file = fields.Binary(string='File', required=True)
    filename = fields.Char(string='Filename')
    line_ids = fields.One2many(
        'my.module.import.wizard.line',
        'wizard_id',
        string='Preview Lines',
    )

    def action_parse(self):
        """Parse uploaded file and show preview."""
        self.ensure_one()
        data = base64.b64decode(self.file)
        lines = self._parse_file(data)
        self.line_ids = [(5, 0, 0)]  # clear existing
        self.line_ids = [(0, 0, vals) for vals in lines]
        # Return the same wizard to show parsed lines
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_import(self):
        """Import the parsed lines into the target model."""
        self.ensure_one()
        vals_list = []
        for line in self.line_ids.filtered(lambda l: l.to_import):
            vals_list.append(line._prepare_import_values())
        self.env['my.model'].create(vals_list)
        return {'type': 'ir.actions.act_window_close'}


class ImportWizardLine(models.TransientModel):
    """Line item for the import wizard preview."""

    _name = 'my.module.import.wizard.line'
    _description = 'Import Wizard Line'

    wizard_id = fields.Many2one(
        'my.module.import.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    name = fields.Char(string='Name')
    value = fields.Float(string='Value')
    to_import = fields.Boolean(string='Import', default=True)
    error_message = fields.Char(string='Error', readonly=True)

    def _prepare_import_values(self):
        """Prepare values dict for creating the target record."""
        return {
            'name': self.name,
            'amount': self.value,
        }
```

---

## 4. Multi-Step Wizard

Use state field to show different content at each step:

```python
class SetupWizard(models.TransientModel):
    """Multi-step setup wizard."""

    _name = 'my.module.setup.wizard'
    _description = 'Setup Wizard'

    state = fields.Selection([
        ('step1', 'Configuration'),
        ('step2', 'Review'),
        ('done', 'Done'),
    ], string='Step', default='step1')

    # Step 1 fields
    partner_id = fields.Many2one('res.partner', string='Partner')
    date = fields.Date(string='Date', default=fields.Date.today)

    # Step 2 fields (computed preview)
    preview_text = fields.Text(string='Preview', compute='_compute_preview')

    @api.depends('partner_id', 'date')
    def _compute_preview(self):
        """Generate a preview of what will be created."""
        for wizard in self:
            if wizard.partner_id and wizard.date:
                wizard.preview_text = _(
                    "Will create a record for %s on %s.",
                    wizard.partner_id.name, wizard.date,
                )
            else:
                wizard.preview_text = ''

    def action_next(self):
        """Move to the next step."""
        self.ensure_one()
        if self.state == 'step1':
            if not self.partner_id:
                raise UserError(_("Please select a partner."))
            self.state = 'step2'
        return self._reopen()

    def action_previous(self):
        """Move to the previous step."""
        self.ensure_one()
        if self.state == 'step2':
            self.state = 'step1'
        return self._reopen()

    def action_apply(self):
        """Execute the final action."""
        self.ensure_one()
        self.env['my.model'].create({
            'partner_id': self.partner_id.id,
            'date': self.date,
        })
        return {'type': 'ir.actions.act_window_close'}

    def _reopen(self):
        """Return action to reopen this wizard at current step."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
```

### Multi-step view:
```xml
<form string="Setup Wizard">
    <!-- Step 1 -->
    <group invisible="state != 'step1'">
        <group>
            <field name="partner_id"/>
            <field name="date"/>
        </group>
    </group>

    <!-- Step 2 -->
    <group invisible="state != 'step2'">
        <field name="preview_text" readonly="1"/>
    </group>

    <footer>
        <button name="action_previous" type="object" string="Back"
                invisible="state == 'step1'"/>
        <button name="action_next" type="object" string="Next"
                class="btn-primary"
                invisible="state != 'step1'"/>
        <button name="action_apply" type="object" string="Apply"
                class="btn-primary"
                invisible="state != 'step2'"/>
        <button string="Cancel" special="cancel"/>
    </footer>
</form>
```

---

## 5. Pre-Populating Wizards

### Using context in action:
```xml
<!-- Button on form view that opens wizard with context -->
<button name="%(my_module.my_wizard_action)d" type="action"
        string="Open Wizard"
        context="{'default_partner_id': partner_id, 'default_date': date}"/>
```

### Using `default_get()`:
```python
@api.model
def default_get(self, fields_list):
    """Pre-fill wizard fields from context."""
    defaults = super().default_get(fields_list)
    # Single record context
    active_id = self.env.context.get('active_id')
    if active_id:
        record = self.env['my.model'].browse(active_id)
        defaults.update({
            'partner_id': record.partner_id.id,
            'date': record.date,
        })
    return defaults
```

### Context keys available in wizards:
| Key | Value | When |
|-----|-------|------|
| `active_id` | Single record ID | Opened from form view |
| `active_ids` | List of record IDs | Opened from list view (selected rows) |
| `active_model` | Model name string | Always available |
| `default_<field>` | Default value | Passed via action context |

---

## 6. Action Return Values

### Close the dialog:
```python
return {'type': 'ir.actions.act_window_close'}
```

### Open a record after wizard finishes:
```python
return {
    'type': 'ir.actions.act_window',
    'res_model': 'my.model',
    'res_id': new_record.id,
    'view_mode': 'form',
    'target': 'current',  # replace current view
}
```

### Open a list of created records:
```python
return {
    'type': 'ir.actions.act_window',
    'res_model': 'my.model',
    'view_mode': 'list,form',
    'domain': [('id', 'in', created_ids)],
    'target': 'current',
}
```

### Show a success notification and close:
```python
return {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': _("Success"),
        'message': _("%d records processed.", count),
        'type': 'success',
        'sticky': False,
        'next': {'type': 'ir.actions.act_window_close'},
    },
}
```

### Reload the current view (refresh data):
```python
return {
    'type': 'ir.actions.client',
    'tag': 'reload',
}
```

---

## 7. Wizard Security

### `security/ir.access.csv` (required):
```csv
id,name,model_id,group_id/id,operation,domain
access_my_wizard_user,my.module.wizard user,my.module.wizard,my_module.group_my_module_user,crud,
my_wizard_own_rule,My Wizard: own records only,my.module.wizard,,crud,"[('create_uid', '=', user.id)]"
access_my_wizard_line,my.module.wizard.line,my.module.wizard.line,my_module.group_my_module_user,crud,
```

### Key rules:
- Always add access rows for wizard models — transient does not mean unprotected
- **Add the ownership restriction** `[('create_uid', '=', user.id)]` with an empty
  `group_id`. 22 core access files do exactly this; the ORM does not do it for you.
- Wizard line models need their own rows, or `[('wizard_id', 'access', 'read')]`
- Use `groups=` on the binding action or the button to restrict who can open it
- Validate permissions inside the wizard's `action_*` method — the button's group is a UI
  hint, not a security boundary

---

## 8. Antipatterns

### DO NOT store permanent data on TransientModel:
```python
# WRONG — transient records are auto-deleted
class MyWizard(models.TransientModel):
    _name = 'my.wizard'
    audit_log = fields.Text()  # Will be lost!

# CORRECT — create permanent records from the wizard action
def action_apply(self):
    self.env['my.audit.log'].create({'note': self.audit_log})
```

### DO NOT use sudo() in wizards without validation:
```python
# WRONG — wizard can be opened by anyone with ACL
def action_apply(self):
    self.env['account.move'].sudo().create(vals)  # No permission check

# CORRECT — verify user's right to perform the action
def action_apply(self):
    if not self.env.user.has_group('account.group_account_invoice'):
        raise AccessError(_("You cannot create invoices."))
    # sudo() justified: user has invoicing group but may lack direct write on account.move
    self.env['account.move'].sudo().create(vals)
```

### DO NOT forget to handle empty active_ids:
```python
# WRONG — crashes if opened without selection
def action_apply(self):
    records = self.env['my.model'].browse(self.env.context['active_ids'])

# CORRECT — handle gracefully
def action_apply(self):
    active_ids = self.env.context.get('active_ids', [])
    if not active_ids:
        raise UserError(_("No records selected."))
    records = self.env['my.model'].browse(active_ids)
```

### DO NOT return None from wizard actions:
```python
# WRONG — leaves the dialog in a broken state
def action_apply(self):
    self._do_something()
    # implicitly returns None — dialog stays open but wizard state is gone

# CORRECT — always return an explicit action
def action_apply(self):
    self._do_something()
    return {'type': 'ir.actions.act_window_close'}
```

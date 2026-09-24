# Mail & Tracking — Odoo 20

## Table of Contents

1. [mail.thread Mixin](#1-mailthread-mixin)
2. [mail.activity.mixin](#2-mailactivitymixin)
3. [Field Tracking](#3-field-tracking)
4. [message_post()](#4-message_post)
5. [Mail Templates](#5-mail-templates)
6. [Subtypes](#6-subtypes)
7. [Followers](#7-followers)
8. [Chatter in Views](#8-chatter-in-views)
9. [Context Flags](#9-context-flags)
10. [Bulk Operations](#10-bulk-operations)
11. [Antipatterns](#11-antipatterns)

---

## 1. mail.thread Mixin

Add `mail.thread` to enable the chatter (messages, followers, tracking) on your model.

```python
class MyModel(models.Model):
    _name = 'my.model'
    _description = 'My Model'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
    ], default='draft', tracking=True)
    partner_id = fields.Many2one('res.partner', tracking=True)
```

**What `mail.thread` provides:**
- `message_ids` — One2many to `mail.message` (chatter messages)
- `message_follower_ids` — followers of this record
- `message_post()` — post messages, notes, notifications
- Automatic tracking of field changes
- Email notification system

---

## 2. mail.activity.mixin

Adds activity scheduling (to-do items, follow-ups).

```python
_inherit = ['mail.thread', 'mail.activity.mixin']
```

**What it provides:**
- `activity_ids` — scheduled activities
- `activity_state` — computed: `overdue`, `today`, `planned`
- `activity_date_deadline` — next activity deadline
- `activity_schedule()` — schedule an activity programmatically

### Schedule an activity

```python
def action_schedule_followup(self):
    """Schedule a follow-up activity for the responsible user."""
    self.activity_schedule(
        'mail.mail_activity_data_todo',
        date_deadline=fields.Date.today() + relativedelta(days=7),
        summary=_("Follow up with customer"),
        user_id=self.user_id.id,
    )
```

### Mark activity as done

```python
def action_confirm(self):
    """Confirm and mark related activities as done."""
    self.write({'state': 'confirmed'})
    self.activity_feedback(['mail.mail_activity_data_todo'],
                           feedback=_("Confirmed by %s", self.env.user.name))
```

---

## 3. Field Tracking

### Enable tracking

```python
# Simple tracking — logs changes in chatter
name = fields.Char(tracking=True)

# Ordered tracking — controls display order in tracking message
state = fields.Selection([...], tracking=1)      # shown first
partner_id = fields.Many2one(..., tracking=2)    # shown second
amount = fields.Float(..., tracking=3)           # shown third
```

### What gets tracked

When a tracked field changes, Odoo creates a `mail.tracking.value` record and posts a message like:
> State: Draft → Confirmed

**Rules:**
- Use `tracking=True` on business-critical fields (state, partner, amounts)
- Use `tracking=N` (integer) to control the order fields appear in the tracking message
- Selection fields show the label, not the key
- Many2one fields show the display name

---

## 4. message_post()

`message_post()` is singleton-only. Loop explicitly when posting the same audit
entry on multiple records.

- A plain `str` body is HTML-escaped ([mail_thread.py:2399](../../../../addons/mail/models/mail_thread.py#L2399):
  "escape if text, keep if markup"), so tags show as text. Build HTML with `Markup` and pass
  values through `%` so they are escaped: `Markup("<b>%s</b>") % value`.
- A message posted and then followed by `raise` is rolled back with the transaction: the
  chatter never shows it. To keep a trace of a failure, see `transactions.md` section 9.

### Post a note (internal, no notification)

```python
record.message_post(
    body=_("Internal note: processing started."),
    message_type='comment',
    subtype_xmlid='mail.mt_note',
)
```

### Post a notification (notifies followers)

```python
record.message_post(
    body=_("Order has been confirmed by %s.", self.env.user.name),
    message_type='notification',
    subtype_xmlid='mail.mt_comment',
    partner_ids=record.partner_id.ids,
)
```

### Post with a mail template

```python
record.message_post_with_source(
    self.env.ref('my_module.email_template_confirmed'),
    subtype_xmlid='mail.mt_comment',
)
```

### Attach a file to a message

```python
self.ensure_one()
attachment = self.env['ir.attachment'].create({
    'name': 'report.pdf',
    'datas': base64_content,
    'res_model': self._name,
    'res_id': self.id,
})
self.message_post(
    body=_("Report attached."),
    attachment_ids=[attachment.id],
)
```

### Message types

| `message_type` | Purpose |
|---|---|
| `'comment'` | User comment or note |
| `'notification'` | System notification |
| `'email'` | Incoming/outgoing email |
| `'auto_comment'` | Automated message (no notification) |

### Subtypes

| Subtype XML ID | Purpose |
|---|---|
| `mail.mt_comment` | Discussion — notifies followers |
| `mail.mt_note` | Internal note — no notification |
| `mail.mt_activities` | Activity updates |

---

## 5. Mail Templates

### XML definition

```xml
<record id="email_template_confirmed" model="mail.template">
    <field name="name">My Model: Confirmed</field>
    <field name="model_id" ref="model_my_model"/>
    <field name="subject">Order {{ object.name }} Confirmed</field>
    <field name="email_from">{{ (object.company_id.email or user.email) }}</field>
    <field name="email_to">{{ object.partner_id.email }}</field>
    <field name="body_html" type="html">
        <div style="margin: 0px; padding: 0px;">
            <p>Dear {{ object.partner_id.name }},</p>
            <p>Your order <strong>{{ object.name }}</strong> has been confirmed.</p>
            <p>Total amount: {{ format_amount(object.amount_total, object.currency_id) }}</p>
            <p>Best regards,<br/>{{ object.company_id.name }}</p>
        </div>
    </field>
    <field name="auto_delete" eval="True"/>
</record>
```

### Send template programmatically

```python
def action_send_confirmation_email(self):
    """Send confirmation email using template."""
    template = self.env.ref('my_module.email_template_confirmed')
    for record in self:
        template.send_mail(record.id, force_send=True)
```

### Template rendering context

Available in templates:
- `object` — the record
- `user` — current user
- `ctx` — context dict
- `format_amount(amount, currency)` — format monetary values
- `format_date(date)` — locale-aware date formatting

---

## 6. Subtypes

Custom subtypes let followers subscribe to specific event types.

```xml
<record id="mt_order_confirmed" model="mail.message.subtype">
    <field name="name">Order Confirmed</field>
    <field name="res_model">my.model</field>
    <field name="default" eval="True"/>
    <field name="description">Notified when an order is confirmed</field>
</record>
```

Use in message_post:

```python
self.ensure_one()
self.message_post(
    body=_("Order confirmed."),
    subtype_xmlid='my_module.mt_order_confirmed',
)
```

---

## 7. Followers

### Add a follower programmatically

```python
# Add partner as follower
record.message_subscribe(partner_ids=[partner.id])

# Add with specific subtypes only
record.message_subscribe(
    partner_ids=[partner.id],
    subtype_ids=[self.env.ref('my_module.mt_order_confirmed').id],
)

# Remove follower
record.message_unsubscribe(partner_ids=[partner.id])
```

### Auto-subscribe on create

By default, the creator and the `partner_id` field are auto-subscribed. Control with context:

```python
# Skip auto-subscribe on create
self.with_context(mail_create_nosubscribe=True).create(vals)
```

---

## 8. Chatter in Views

```xml
<form>
    <header>...</header>
    <sheet>...</sheet>
    <!-- Chatter — MUST be after </sheet>, inside <form> -->
    <chatter/>
</form>
```

**Rules:**
- `<chatter/>` is the v17+ shorthand (replaces the old `<div class="oe_chatter">` block)
- Place it after `</sheet>` and before `</form>`
- Only works when model inherits `mail.thread`
- Automatically includes: message log, send message, activities, followers

---

## 9. Context Flags

Control mail behavior with context keys:

| Context key | Effect |
|---|---|
| `tracking_disable=True` | Skip ALL tracking and notifications |
| `mail_create_nolog=True` | Skip "Record created" log message |
| `mail_create_nosubscribe=True` | Don't auto-subscribe creator |
| `mail_notrack=True` | Skip field change tracking (still sends messages) |
| `mail_auto_subscribe_no_notify=True` | Subscribe but don't send notification |
| `mail_activity_automation_skip=True` | Skip automated activity processing |
| `no_reset_password=True` | Skip password reset email on user create |

### Usage

```python
# Bulk import — skip all mail overhead
records = self.with_context(
    tracking_disable=True,
    mail_create_nolog=True,
    mail_create_nosubscribe=True,
).create(vals_list)

# Single operation — just skip tracking
record.with_context(tracking_disable=True).write({'state': 'done'})
```

---

## 10. Bulk Operations

### Problem: mail flood

When writing to many records with tracked fields, each write generates a tracking message and potentially sends emails. This can be extremely slow.

### Solution: tracking_disable

```python
def action_mass_confirm(self):
    """Confirm multiple records without individual tracking messages."""
    # Disable tracking for bulk operation
    records = self.with_context(tracking_disable=True)
    records.write({'state': 'confirmed'})

    # Post a single summary message instead
    for record in self:
        record.message_post(
            body=_("Confirmed in bulk operation by %s.", self.env.user.name),
            subtype_xmlid='mail.mt_note',
        )
```

### For cron jobs

```python
def _cron_process_records(self):
    """Cron: process records without mail notifications."""
    records = self.with_context(
        tracking_disable=True,
        mail_activity_automation_skip=True,
    ).search([('state', '=', 'pending')])
    records.write({'state': 'processed'})
```

---

## 11. Antipatterns

### Using _logger instead of message_post for user-visible events

```python
# BAD — only visible in server logs, not in the record's history
_logger.info("Order %s confirmed by user %s", self.name, self.env.user.name)

# GOOD — visible in the record's chatter
self.ensure_one()
self.message_post(
    body=_("Order confirmed by %s.", self.env.user.name),
    subtype_xmlid='mail.mt_note',
)
```

### Forgetting tracking_disable in bulk operations

```python
# BAD — sends N emails, creates N tracking messages
for vals in vals_list:
    self.create(vals)

# GOOD — single batch, no tracking overhead
self.with_context(tracking_disable=True).create(vals_list)
```

### Missing chatter in form view

```xml
<!-- BAD — model inherits mail.thread but no chatter in view -->
<form>
    <sheet>...</sheet>
</form>

<!-- GOOD -->
<form>
    <sheet>...</sheet>
    <chatter/>
</form>
```

### Wrong subtype for notes vs notifications

```python
# BAD — internal notes should not notify followers
self.message_post(body="Internal note", subtype_xmlid='mail.mt_comment')

# GOOD — use mt_note for internal, mt_comment for notifications
self.ensure_one()
self.message_post(body="Internal note", subtype_xmlid='mail.mt_note')
```

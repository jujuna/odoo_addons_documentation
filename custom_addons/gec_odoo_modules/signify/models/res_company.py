from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    signify_reminder_frequency = fields.Selection([
        ('everyhour', "Every Hour"),
        ('everyday', "Every Day"),
        ('every2days', "Every 2 Days"),
        ('everyweek', "Every Week"),
        ('never', "Never"),
    ], string="Reminder Frequency", required=True, default='everyday',
        help="Sent the same way as the invitation, by email or SMS; Link recipients get none. Only documents sent after a change follow it.")
    signify_reminder_max_count = fields.Integer(string="Maximum Reminders", default=3,
        help="How many reminders one recipient gets at most, from 1 to 10.")

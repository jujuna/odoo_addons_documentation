# Part of bpmn_process_management. License LGPL-3.
from random import randint

from datetime import timedelta

from odoo import fields, models


class BusinessProcessTag(models.Model):
    _name = "business.process.tag"
    _description = "Business Process Tag"
    _order = "name"

    def _default_color(self):
        return randint(1, 11)

    name = fields.Char(required=True, translate=True)
    color = fields.Integer(default=_default_color)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint("unique (name)", "A tag with this name already exists.")


class BusinessProcessKpi(models.Model):
    _name = "business.process.kpi"
    _description = "Business Process Indicator"
    _order = "sequence, id"

    process_id = fields.Many2one("business.process", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char("Indicator", required=True,
                       help="What is measured, e.g. \"Returns refunded within 5 days\".")
    target = fields.Char(help="Target value, e.g. \">= 95 %\".")
    frequency = fields.Selection([
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
        ("quarterly", "Quarterly"),
        ("yearly", "Yearly"),
    ], default="monthly")
    source = fields.Char("Data Source", help="Where the value comes from (Odoo report, spreadsheet...).")

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        for rec, vals in zip(self, vals_list):
            vals["name"] = rec.name
        return vals_list


class BusinessProcessAck(models.Model):
    """"I have read this process": one line per user and version."""
    _name = "business.process.ack"
    _description = "Business Process Read Confirmation"
    _order = "date desc, id desc"
    _rec_name = "user_id"

    process_id = fields.Many2one("business.process", required=True, ondelete="cascade", index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True,
                              default=lambda self: self.env.user)
    version = fields.Char(required=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now)
    carried_over = fields.Boolean(
        "Carried Over", readonly=True,
        help="Confirmed an earlier version; kept because the new version was published as a small change.")

    _process_user_version_uniq = models.Constraint(
        "unique (process_id, user_id, version)", "This version was already confirmed.")


class BusinessProcessEditor(models.Model):
    """Who has a diagram open now (heartbeat every minute), so two managers do not overwrite each other.

    Written only through business.process.bpmn_editing_ping (sudo after the manager check)."""
    _name = "business.process.editor"
    _description = "Business Process Editor Presence"
    _order = "heartbeat desc"

    process_id = fields.Many2one("business.process", required=True, ondelete="cascade", index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade")
    since = fields.Datetime(required=True, default=fields.Datetime.now)
    heartbeat = fields.Datetime(required=True, default=fields.Datetime.now)

    _process_user_uniq = models.Constraint("unique (process_id, user_id)", "One presence row per user.")

    STALE = timedelta(minutes=3)

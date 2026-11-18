# Part of bpmn_process_management. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError


class BusinessProcessPublish(models.TransientModel):
    """Asks if the new version is a small or major change: sets the number and whether all re-read it."""
    _name = "business.process.publish"
    _description = "Publish a process version"

    process_id = fields.Many2one("business.process", required=True, ondelete="cascade")
    previous_version = fields.Char("Valid Version", compute="_compute_numbers")
    has_previous = fields.Boolean("Has a Valid Version", compute="_compute_numbers")
    small_version = fields.Char("Number for a Small Change", compute="_compute_numbers")
    major_version = fields.Char("Number for a Major Change", compute="_compute_numbers")
    ack_required = fields.Boolean(related="process_id.ack_required")
    change_note = fields.Text(
        "What Changed",
        help="A sentence or two for the history: what is different and why. Shown in the "
             "chatter and in the version list.")

    @api.depends("process_id", "process_id.version")
    def _compute_numbers(self):
        for wiz in self:
            proc = wiz.process_id
            prev = proc._previous_release() if proc else proc
            wiz.has_previous = bool(prev)
            wiz.previous_version = prev.version if prev else False
            small, major = proc._release_numbers() if proc else (False, False)
            wiz.small_version = small
            wiz.major_version = major

    def _publish(self, change_type):
        self.ensure_one()
        self.process_id.action_publish(change_type=change_type, change_note=self.change_note)
        return {"type": "ir.actions.act_window_close"}

    def action_publish(self):
        """First version: nothing to choose."""
        if self.has_previous:
            raise UserError(self.env._("Choose whether this is a small or a major change."))
        return self._publish(None)

    def action_publish_minor(self):
        """Small change: next small number, read confirmations are kept."""
        return self._publish("minor")

    def action_publish_major(self):
        """Major change: next major number, everyone reads it again."""
        return self._publish("major")

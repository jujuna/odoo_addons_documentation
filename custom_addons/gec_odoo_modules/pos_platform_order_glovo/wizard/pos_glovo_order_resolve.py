from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.pos_platform_order_glovo.const import PROVIDER_CODE


class PosGlovoOrderResolve(models.TransientModel):
    _name = 'pos.glovo.order.resolve'
    _description = "Resolve a Glovo order without a Glovo notification"

    order_ids = fields.Many2many('pos.order', string="Orders", readonly=True)
    resolution = fields.Selection([('cancelled', "Cancelled"), ('delivered', "Picked up")], required=True, readonly=True)
    reason = fields.Char(required=True, help="Why the order is resolved without Glovo's notification; it is posted on the order.")

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        if 'order_ids' in fields and self.env.context.get('active_model') == 'pos.order':
            res['order_ids'] = [Command.set(self.env.context.get('active_ids', []))]
        return res

    def action_confirm(self):
        """Apply the resolution through the same path as Glovo's cancelled or picked-up notification."""
        self.ensure_one()
        # the access rows make the wizard manager-only; the selected orders must also be in a company they may write
        self.order_ids.check_access('write')
        if self.order_ids.filtered(lambda o: o.platform_order_provider_code != PROVIDER_CODE):
            raise UserError(_("Select only Glovo orders."))
        # sudo: Glovo orders only change through superuser paths; this wizard is for POS managers only
        for order_sudo in self.order_ids.sudo():
            if self.resolution == 'cancelled':
                order_sudo._update_order_status_from_data({'cancel_reason': self.reason})
            else:
                order_sudo._update_order_status_from_data({})
                order_sudo.message_post(body=_("Marked picked up by a manager. Reason: %s", self.reason))

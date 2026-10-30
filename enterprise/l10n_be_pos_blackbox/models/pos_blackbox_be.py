from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PosBlackboxBe(models.Model):
    _name = "pos.blackbox.be"
    _inherit = ["pos.load.mixin"]
    _description = "POS Blackbox BE"
    _rec_name = "fdm_id"

    fdm_id = fields.Char(
        string="FDM ID",
        required=True,
        help="The ID of the blackbox is written on the back of the device.",
    )
    pos_config_ids = fields.One2many(
        comodel_name="pos.config",
        inverse_name="l10n_be_blackbox_be_id",
        string="POS Configurations",
        help="The POS configurations that are linked to this blackbox.",
    )
    local_ip = fields.Char(
        string="Local IP",
        help="The local IP will automatically be set when the blackbox is registered.",
    )
    use_lna = fields.Boolean(string="Use Local Network Access", default=True)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_used_by_pos_config(self):
        configs = self.env['pos.config'].with_context(active_test=False).search([
            ('l10n_be_blackbox_be_id', 'in', self.ids),
            ('l10n_be_pos_id', '!=', False),
        ])
        if configs:
            raise UserError(_(
                "You cannot delete a blackbox that is used by a Point of Sale configuration."
            ))

    @api.model
    def _load_pos_data_domain(self, data):
        if not data.get('pos.config'):
            return False
        return [('id', '=', data['pos.config'].l10n_be_blackbox_be_id.id)]

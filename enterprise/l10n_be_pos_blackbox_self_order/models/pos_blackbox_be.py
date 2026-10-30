from odoo import fields, models


class PosBlackboxBe(models.Model):
    _inherit = "pos.blackbox.be"

    # TODO-manv: remove in master
    obox_id = fields.Many2one(
        comodel_name="obox.obox",
        string="OBOX Device",
        help="The OBOX device that hosts this FDM blackbox.",
    )

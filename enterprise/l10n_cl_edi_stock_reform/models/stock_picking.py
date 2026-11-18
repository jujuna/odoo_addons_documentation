from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_list
from odoo.tools.sql import column_exists, create_column


class Picking(models.Model):
    _inherit = 'stock.picking'

    l10n_cl_delivery_guide_reason = fields.Selection(selection_add=[
        ('7', '7. Merchandise Return'),
        ('10', '10. Third-Party Delivery'),
        ('11', '11. Extended Sale Delivery'),
        ('12', '12. Extended Non-Sale Delivery'),
    ])

    l10n_cl_edi_departure_date = fields.Datetime(string="Departure Date")
    l10n_cl_edi_arrival_date = fields.Date(string="Arrival Date")
    l10n_cl_edi_transport_id = fields.Many2one('l10n_cl_edi.vehicle', string="Transport", check_company=True)
    l10n_cl_edi_driver_id = fields.Many2one(
        comodel_name='res.partner',
        string="Driver",
        compute='_compute_l10n_cl_edi_driver_id',
        store=True,
        check_company=True,
        domain=[('is_company', '=', False)],
        readonly=False,
    )

    def _auto_init(self):
        if not column_exists(self.env.cr, 'stock_picking', 'l10n_cl_edi_driver_id'):
            create_column(self.env.cr, 'stock_picking', 'l10n_cl_edi_driver_id', 'int4')
        return super()._auto_init()

    @api.depends('l10n_cl_edi_transport_id')
    def _compute_l10n_cl_edi_driver_id(self):
        for record in self:
            record.l10n_cl_edi_driver_id = record.l10n_cl_edi_transport_id.operator_id or record.l10n_cl_edi_driver_id

    def _l10n_cl_create_delivery_guide_validation(self):
        """Require the transport data mandated by SII Res. Ex. N° 154 de 2025, art. 1."""
        super()._l10n_cl_create_delivery_guide_validation()
        missing_fields = []
        if not self.l10n_cl_edi_arrival_date:
            missing_fields.append(self.env._("Arrival Date"))
        if missing_fields:
            raise UserError(self.env._(
                "The delivery guide needs the following fields to be set: %(fields)s",
                fields=format_list(self.env, missing_fields),
            ))

    def _l10n_cl_create_dte(self):
        if not self.l10n_cl_edi_departure_date:
            self.l10n_cl_edi_departure_date = fields.Datetime.now()
        return super()._l10n_cl_create_dte()

    def _l10n_cl_edi_get_departure_datetime(self):
        return fields.Datetime.context_timestamp(
            self.with_context(tz='America/Santiago'), self.l10n_cl_edi_departure_date)

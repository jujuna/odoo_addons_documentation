from odoo import api, fields, models


class L10nClEdiVehicle(models.Model):
    _name = 'l10n_cl_edi.vehicle'
    _description = 'CL EDI Transport'
    _check_company_auto = True
    _rec_names_search = ('name', 'license_plate')

    active = fields.Boolean(default=True)
    name = fields.Char(
        string="Transport Name",
        required=True,
    )
    license_plate = fields.Char(
        string="License Plate",
        required=True,
    )
    trailer_license_plate = fields.Char(
        string="Trailer License Plate",
    )
    operator_id = fields.Many2one(
        comodel_name='res.partner',
        string="Default Driver",
        check_company=True,
        help='If set, this person will be auto-filled as the vehicle operator when selecting this vehicle in a transfer.',
        domain=[('is_company', '=', False)],
    )
    transport_company_id = fields.Many2one(
        comodel_name='res.partner',
        string="Transport Company",
        check_company=True,
        domain=[('is_company', '=', True)],
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        default=lambda self: self.env.company,
    )

    @api.depends('name', 'license_plate')
    def _compute_display_name(self):
        # OVERRIDE
        for vehicle in self:
            vehicle.display_name = f"[{vehicle.license_plate}] {vehicle.name}"

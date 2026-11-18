from odoo import fields, models


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    rs_form30_engine_id = fields.Many2one('rs.form30.car.engine', string='rs.ge Engine Band', ondelete='restrict',
        help="Engine band reported in Form 30 annex D when this car is used privately by its driver.")

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrPayrollUnitRate(models.Model):
    _name = 'hr.payroll.unit.rate'
    _description = 'Payroll Unit Work Rate'
    _order = 'name, id'

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', index=True, ondelete='cascade', default=lambda self: self.env.company,
        help="Leave empty to share this rate with every company.")
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True, ondelete='restrict',
        help="Label for the quantity, e.g. ft2 or m2. No unit conversion is applied: quantities are entered and paid in this unit as-is.")
    price_per_unit = fields.Monetary(required=True)
    currency_id = fields.Many2one('res.currency', required=True, ondelete='restrict', default=lambda self: self.env.company.currency_id)
    active = fields.Boolean(default=True)

    @api.onchange('company_id')
    def _onchange_company_id(self):
        """A rate for another company must use that company's currency; approval refuses others."""
        if self.company_id:
            self.currency_id = self.company_id.currency_id

    @api.constrains('price_per_unit')
    def _check_price_positive(self):
        for rate in self:
            if rate.currency_id.compare_amounts(rate.price_per_unit, 0.0) <= 0:
                raise ValidationError(self.env._("Price per Unit must be positive."))

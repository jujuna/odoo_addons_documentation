from datetime import date

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class RsForm30PartnerCategory(models.Model):
    _name = 'rs.form30.partner.category'
    _description = 'Form 30 Partner Category Period'
    _rec_name = 'category_id'
    _order = 'date_from desc, id desc'

    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade', index=True)
    category_id = fields.Many2one('rs.form30.category', required=True, ondelete='restrict')
    use_salary = fields.Boolean(related='category_id.use_salary')
    use_entry = fields.Boolean(related='category_id.use_entry')
    use_bill = fields.Boolean(related='category_id.use_bill')
    date_from = fields.Date(string='Valid From', help="First included payment date. Leave empty if the category has always applied.")
    date_to = fields.Date(string='Valid To', help="Last included payment date. Leave empty while the category remains applicable.")

    _date_order = models.Constraint('CHECK (date_from IS NULL OR date_to IS NULL OR date_from <= date_to)',
        'Valid To must be on or after Valid From.')

    @api.constrains('partner_id', 'date_from', 'date_to')
    def _check_periods(self):
        for partner in self.partner_id:
            periods = partner.rs_form30_category_history_ids.sorted(key=lambda entry: entry.date_from or date.min)
            previous = None
            for period in periods:
                if previous and (not previous.date_to or not period.date_from or period.date_from <= previous.date_to):
                    raise ValidationError(self.env._("Form 30 category periods must not overlap for %s. End the previous period before the next one "
                        "starts.", partner.display_name))
                previous = period

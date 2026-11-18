from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import ValidationError


def check_period_bounds(records):
    for record in records:
        for period in (record.valid_from, record.valid_to):
            if period and not (100001 <= period <= 999912 and 1 <= period % 100 <= 12):
                raise ValidationError(record.env._("Validity must be a YYYYMM month, or empty for an open boundary."))
        if record.valid_from and record.valid_to and record.valid_from > record.valid_to:
            raise ValidationError(record.env._("Valid To must be on or after Valid From."))


class RsForm30ShippedData(models.AbstractModel):
    _name = 'rs.form30.shipped.data'
    _description = 'rs.ge Form 30 Shipped Data'

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('install_mode'):
            # Keep a manager's change through CSV reloads; sudo only touches this module's xml ids.
            self.env['ir.model.data'].sudo().search([
                ('module', '=', 'gec_income_tax_report'),
                ('model', '=', self._name),
                ('res_id', 'in', self.ids),
            ]).write({'noupdate': True})
        return result


class RsForm30ClassifierMixin(models.AbstractModel):
    """``code`` is the ID written in the file."""
    _name = 'rs.form30.classifier.mixin'
    _inherit = ['rs.form30.shipped.data']
    _description = 'rs.ge Form 30 Classifier'
    _order = 'sequence, id'

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    valid_from = fields.Integer(string='Valid From (YYYYMM)')
    valid_to = fields.Integer(string='Valid To (YYYYMM)')
    active = fields.Boolean(default=True)

    @api.constrains('valid_from', 'valid_to')
    def _check_validity(self):
        check_period_bounds(self)

    def _is_valid(self, period):
        self.ensure_one()
        return (not self.valid_from or period >= self.valid_from) and (not self.valid_to or period <= self.valid_to)


class RsForm30Category(models.Model):
    _name = 'rs.form30.category'
    _inherit = 'rs.form30.classifier.mixin'
    _description = 'rs.ge Form 30 Recipient Category'

    display_code = fields.Char(string='RS Number', help="Number shown on the portal, e.g. 1.1")
    is_organization = fields.Boolean(string='Organization',
        help="Enterprise or organization rather than a natural person; its rows feed main-part cells 40 to 56.")
    use_salary = fields.Boolean(string='Salary', help="The category is meant for payslips (the accountant's category guide).")
    use_entry = fields.Boolean(string='Journal Entry', help="The category is meant for journal entries (the accountant's category guide).")
    use_bill = fields.Boolean(string='Vendor Bill', help="The category is meant for vendor bills (the accountant's category guide).")
    usage_note = fields.Text(
        string='When to Use', help="The accountant's guide: when this category applies. A hint only; the rs.ge rate rules decide.")

    _code_uniq = models.Constraint('UNIQUE(code)', 'Category code must be unique.')

    @api.depends('display_code', 'name')
    def _compute_display_name(self):
        for category in self:
            category.display_name = f"{category.display_code}: {category.name}" if category.display_code else category.name


class RsForm30IncomeType(models.Model):
    _name = 'rs.form30.income.type'
    _inherit = 'rs.form30.classifier.mixin'
    _description = 'rs.ge Form 30 Income Type'

    _code_uniq = models.Constraint('UNIQUE(code)', 'Income type code must be unique.')

    rate_rule_ids = fields.One2many('rs.form30.rate.rule', 'income_type_id', string='Allowed Rates')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for income_type in self:
            income_type.display_name = f"{income_type.code} - {income_type.name}"


class RsForm30RateRule(models.Model):
    _name = 'rs.form30.rate.rule'
    _inherit = ['rs.form30.shipped.data']
    _description = 'rs.ge Form 30 Allowed Rate'
    _order = 'category_id, income_type_id, rate, id'

    category_id = fields.Many2one('rs.form30.category', required=True, ondelete='cascade', index=True)
    income_type_id = fields.Many2one('rs.form30.income.type', required=True, ondelete='cascade', index=True)
    rate = fields.Float(required=True, digits=(5, 2))
    valid_from = fields.Integer(string='Valid From (YYYYMM)')
    valid_to = fields.Integer(string='Valid To (YYYYMM)')
    note = fields.Char()

    @api.constrains('valid_from', 'valid_to', 'rate')
    def _check_validity(self):
        check_period_bounds(self)
        for rule in self:
            if not 0 <= rule.rate <= 100:
                raise ValidationError(self.env._("The allowed rate must be between 0 and 100%."))

    @api.model
    def _allowed_rates(self, period):
        """{(category_id, income_type_id): [rates allowed in period]}."""
        allowed = defaultdict(list)
        for rule in self.search([]):
            if (not rule.valid_from or period >= rule.valid_from) and (not rule.valid_to or period <= rule.valid_to):
                allowed[(rule.category_id.id, rule.income_type_id.id)].append(rule.rate)
        return allowed


class RsForm30CarEngine(models.Model):
    """Annex D: the fixed monthly tax follows from the band, not from the salary."""
    _name = 'rs.form30.car.engine'
    _inherit = 'rs.form30.classifier.mixin'
    _description = 'rs.ge Form 30 Car Engine Band'

    amount = fields.Float(string='Tax Amount')

    _code_uniq = models.Constraint('UNIQUE(code)', 'Engine band code must be unique.')

    @api.depends('name', 'amount')
    def _compute_display_name(self):
        for engine in self:
            engine.display_name = f"{engine.name} ({engine.amount:g})"


class RsForm30ServiceType(models.Model):
    """Service kind of annex E, as offered by the portal's own dropdown."""
    _name = 'rs.form30.service.type'
    _inherit = 'rs.form30.classifier.mixin'
    _description = 'rs.ge Form 30 Service Type'

    _code_uniq = models.Constraint('UNIQUE(code)', 'Service type code must be unique.')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for service_type in self:
            service_type.display_name = f"{service_type.code} - {service_type.name}"

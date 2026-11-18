# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class HrSalaryRuleCategory(models.Model):
    _name = 'hr.salary.rule.category'
    _description = 'Salary Rule Category'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    parent_id = fields.Many2one('hr.salary.rule.category', string='Parent', index=True,
        help="The totals of the rules of this category are also added to its parent category (and its ancestors) during the payslip computation.",
        domain="['|', ('country_id', '=', False), ('country_id', '=', country_id)]")
    children_ids = fields.One2many('hr.salary.rule.category', 'parent_id', string='Children')
    note = fields.Html(string='Description')
    country_id = fields.Many2one(
        'res.country',
        string="Country",
        default=lambda self: self.env.company.country_id,
        domain=lambda self: [('id', 'in', self.env.companies.country_id.ids)]
    )
    salary_rule_ids = fields.Many2many('hr.salary.rule', compute='_compute_salary_rule_ids', string='Salary Rules')
    optional_on_work_entry_type_ids = fields.Many2many('hr.work.entry.type',
        relation='hr_salary_rule_category_options_hr_work_entry_type_rel',
        string="Optional on", groups='hr_payroll.group_hr_payroll_user',
        domain="[('country_id', '=', country_id)]",
        help="Time Types on which this category can be added optionally on time off created by HR user")
    is_premium_pay = fields.Boolean(string="Premium Pay",
        help="Legal premium pay category. Custom premium pays can be created as children of this category to grant an extra amount on top of the legal rate.")
    parent_is_premium_pay = fields.Boolean(related='parent_id.is_premium_pay', string="Parent is a Premium Pay")
    premium_amount_per_hour = fields.Float(string="Amount per Hour",
        help="Extra amount granted per hour of worked time carrying this premium pay.")
    premium_amount_per_day = fields.Float(string="Amount per Day",
        help="Extra amount granted per day of worked time carrying this premium pay.")
    premium_percentage_hourly_rate = fields.Float(string="Percentage of Hourly Rate",
        help="Extra percentage of the worked time own hourly rate granted per hour of worked time carrying this premium pay.")
    active = fields.Boolean(string="Active", default=True)
    premium_currency_id = fields.Many2one('res.currency', compute='_compute_premium_currency_id')

    @api.depends('country_id')
    @api.depends_context('company')
    def _compute_premium_currency_id(self):
        for category in self:
            category.premium_currency_id = category.country_id.currency_id or self.env.company.currency_id

    def _compute_salary_rule_ids(self):
        for category in self:
            rules = self.env['hr.salary.rule'].search([
                '|',
                    ('category_ids', 'child_of', category.id),
                    ('category_ids', 'parent_of', category.id),
            ])
            category.salary_rule_ids = rules

    def action_open_salary_rules(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Salary Rules'),
            'res_model': 'hr.salary.rule',
            'view_mode': 'list,form',
            'domain': ['|', ('category_ids', 'child_of', self.id), ('category_ids', 'parent_of', self.id)],
            'context': {'default_category_ids': [self.id]},
        }

    @api.constrains('parent_id')
    def _check_parent_id(self):
        if self._has_cycle():
            raise ValidationError(_('Error! You cannot create recursive hierarchy of Salary Rule Category.'))

    @api.constrains('country_id')
    def _check_rule_category_country(self):
        for category in self:
            if category.country_id and self.env['hr.salary.rule'].sudo().search_count([('category_ids', 'in', category.id), ('country_id', '!=', category.country_id.id)], limit=1):
                raise UserError(_('You cannot change the country of category %s as it is used in existing Salary Rules', category.name))

    def _get_codes_with_ancestors(self):
        """Return the set of codes of these categories and all their ancestors."""
        codes = set()
        for category in self:
            while category:
                codes.add(category.code)
                category = category.parent_id
        return codes

    def _sum_salary_rule_category(self, localdict, amount):
        """
        Add ``amount`` to ``localdict['categories']`` for these categories and all their ancestors.

        Called for each computed payslip line with the categories of its rule. Each category code
        is credited once, even if it is reached through several categories of the rule: for a rule
        with two categories sharing a parent, the parent receives ``amount`` once.

        :param dict localdict: computation context of the payslip, modified in place
        :param float amount: amount to add (the caller passes the difference with the previous
            total of the same rule code, if any)
        :return: ``localdict``
        :rtype: dict
        """
        for code in self._get_codes_with_ancestors():
            localdict['categories'][code] += amount
        return localdict

    def _get_seized_categories(self):
        """
        Hook returning the categories whose rules are seizures of salary, used to compute
        ``hr.salary.attachment.is_seized``. Empty by default, overridden by localizations
        (e.g. ``l10n_be_hr_payroll``).

        :rtype: hr.salary.rule.category
        """
        return self.browse()

import re

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare


class RsForm30TaxChange(models.TransientModel):
    _name = 'rs.form30.tax.change'
    _description = 'Apply Tax / RS Change'

    tax_id = fields.Many2one('account.tax', required=True, readonly=True)
    income_type_id = fields.Many2one(related='tax_id.rs_form30_income_type_id')
    change_kind = fields.Selection([('both', 'Tax percentage and RS rules'), ('tax', 'Tax percentage only'), ('rules', 'RS rules only')],
        required=True, default='both')
    rule_action = fields.Selection([
        ('replace', 'Replace an allowed rate'),
        ('allow', 'Allow a rate for categories'),
        ('stop', 'Stop allowing a rate for categories'),
    ], required=True, default='replace')
    effective_date = fields.Date(string='Effective Month', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1) + relativedelta(months=1))
    old_rate = fields.Float(string='Previous Allowed Rate (%)', digits=(5, 2), required=True)
    new_rate = fields.Float(string='New Rate (%)', digits=(5, 2), required=True)
    category_ids = fields.Many2many('rs.form30.category', string='Affected Categories')
    new_tax_name = fields.Char(string='Replacement Tax Name')
    affected_tax_ids = fields.Many2many('account.tax', compute='_compute_affected_taxes')
    preview = fields.Text(compute='_compute_preview')
    applied = fields.Boolean(readonly=True)
    result_tax_id = fields.Many2one('account.tax', readonly=True)

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        tax = self.env['account.tax'].browse(values.get('tax_id'))
        if tax:
            values.update(old_rate=abs(tax.amount), new_rate=abs(tax.amount))
        return values

    @api.onchange('tax_id', 'old_rate', 'effective_date')
    def _onchange_categories(self):
        if self.tax_id and self.effective_date:
            period = self.effective_date.year * 100 + self.effective_date.month
            rules = self.tax_id.rs_form30_rule_ids.filtered(lambda r: float_compare(r.rate, self.old_rate,
                precision_digits=2) == 0 and (not r.valid_from or r.valid_from <= period) and (not r.valid_to or r.valid_to >= period))
            self.category_ids = rules.category_id

    @api.onchange('tax_id', 'new_rate', 'effective_date')
    def _onchange_tax_name(self):
        if self.tax_id and self.effective_date:
            self.new_tax_name = self.env._("%(tax)s (%(rate)g%%, from %(month)s)", tax=self.tax_id.name, rate=self.new_rate,
                month=self.effective_date.strftime('%Y-%m'))

    @api.depends('income_type_id')
    def _compute_affected_taxes(self):
        for wizard in self:
            wizard.affected_tax_ids = self.env['account.tax'].search([
                ('gec_is_withholding', '=', True),
                ('rs_form30_income_type_id', '=', wizard.income_type_id.id),
                ('amount_type', '=', 'percent'),
                ('amount', '<', 0),
            ]) if wizard.income_type_id else self.env['account.tax']

    @api.depends('tax_id', 'change_kind', 'rule_action', 'effective_date', 'old_rate', 'new_rate', 'category_ids', 'new_tax_name')
    def _compute_preview(self):
        for wizard in self:
            messages = []
            if wizard.change_kind != 'rules':
                messages.append(self.env._("Create a separate %(rate)g%% tax from %(date)s. Keep the original tax and its old transactions. Select "
                    "the replacement on payments from that date; product defaults and fiscal positions are not switched automatically.",
                    rate=wizard.new_rate, date=wizard.effective_date or ''))
            if wizard.change_kind != 'tax':
                action = dict(self._fields['rule_action']._description_selection(self.env)).get(wizard.rule_action, '')
                messages.append(self.env._("%(action)s: %(old)g%% → %(new)g%% from %(date)s for %(categories)s. RS rules are shared across all "
                    "companies and taxes using this income type. Only the selected tax is copied.", action=action, old=wizard.old_rate,
                    new=wizard.new_rate, date=wizard.effective_date or '',
                    categories=', '.join(wizard.category_ids.mapped('display_name')) or self.env._("select categories")))
            if wizard.income_type_id.code == '1':
                messages.append(self.env._("Salary calculation still uses geo_payroll salary rules and the declaration's salary rate. Update payroll "
                    "separately when required."))
            wizard.preview = '\n\n'.join(messages)

    def _rule_plan(self, period):
        """Validate the whole change before writing; keep finite end dates."""
        rules = self.tax_id.rs_form30_rule_ids
        previous = self.effective_date - relativedelta(days=1)
        close_at = previous.year * 100 + previous.month
        close = self.env['rs.form30.rate.rule']
        create = []
        for category in self.category_ids:
            if not category._is_valid(period) or not self.income_type_id._is_valid(period):
                raise UserError(self.env._("The category and income type must be valid in the effective month."))
            current = rules.filtered(lambda r: r.category_id == category and float_compare(r.rate, self.old_rate,
                precision_digits=2) == 0 and (not r.valid_from or r.valid_from <= period) and (not r.valid_to or r.valid_to >= period))
            end = 0
            if self.rule_action != 'allow':
                if not current or any(r.valid_from == period for r in current):
                    raise UserError(self.env._("%(category)s needs a %(rate)g%% rule starting before and covering the effective month. Review the "
                        "periods in the tax's RS Declaration Rules tab.", category=category.display_name, rate=self.old_rate))
                close |= current
                end = 0 if any(not r.valid_to for r in current) else max(current.mapped('valid_to'))
            if self.rule_action == 'stop':
                continue
            existing = rules.filtered(lambda r: r.category_id == category and float_compare(r.rate, self.new_rate,
                precision_digits=2) == 0 and (not r.valid_to or r.valid_to >= period) and (not end or not r.valid_from or r.valid_from <= end))
            if any((not r.valid_from or r.valid_from <= period) and (not r.valid_to or (end and r.valid_to >= end)) for r in existing):
                continue
            if existing:
                raise UserError(self.env._("An overlapping future rule exists for %s. Review its validity before applying this change.",
                    category.display_name))
            create.append({
                'category_id': category.id,
                'income_type_id': self.income_type_id.id,
                'rate': self.new_rate,
                'valid_from': period,
                'valid_to': end,
                'note': self.env._("Configured from tax %s", self.tax_id.name),
            })
        return close, close_at, create

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(self.env._("Only accounting managers can apply Tax / RS changes."))
        self.check_access('write')
        self.lock_for_update()
        if self.applied:
            raise UserError(self.env._("This change has already been applied."))
        tax = self.tax_id
        tax.check_access('write')
        tax.lock_for_update()
        if (not tax.active or not tax.gec_is_withholding or tax.amount_type != 'percent'
                or tax.type_tax_use not in ('purchase', 'none') or tax.amount >= 0):
            raise UserError(self.env._("Select an active withholding tax (Tax Type Purchases or None) with a negative percentage."))
        if not self.income_type_id:
            raise UserError(self.env._("Set the tax's Form 30 Income Type first."))
        if self.effective_date.day != 1:
            raise UserError(self.env._("The effective month must start on its first day."))
        if not 0 <= self.old_rate <= 100 or not 0 <= self.new_rate <= 100:
            raise UserError(self.env._("Rates must be between 0 and 100%."))
        changes_tax = self.change_kind != 'rules'
        if changes_tax:
            if self.change_kind == 'both' and (self.rule_action != 'replace' or float_compare(self.old_rate, abs(tax.amount), precision_digits=2)):
                raise UserError(self.env._("For a combined change, replace the selected tax's current rate. Use RS rules only to change category "
                    "eligibility."))
            if float_compare(self.new_rate, abs(tax.amount), precision_digits=2) == 0:
                raise UserError(self.env._("Enter a different percentage for the replacement tax."))
            if (tax.rs_form30_date_from and self.effective_date <= tax.rs_form30_date_from) or tax.rs_form30_date_to:
                raise UserError(self.env._("Choose an effective month after the tax's start date, on a tax that has not already been replaced."))
            if not self.new_tax_name or not self.new_tax_name.strip():
                raise UserError(self.env._("Enter a name for the replacement tax."))
        period = self.effective_date.year * 100 + self.effective_date.month
        close, close_at, create = self.env['rs.form30.rate.rule'], 0, []
        if self.change_kind != 'tax':
            if not self.category_ids:
                raise UserError(self.env._("Select the affected recipient categories."))
            if self.rule_action == 'replace' and float_compare(self.old_rate, self.new_rate, precision_digits=2) == 0:
                raise UserError(self.env._("The new allowed rate must differ from the previous rate."))
            self.income_type_id.lock_for_update()
            close, close_at, create = self._rule_plan(period)
        result_tax = tax
        if changes_tax:
            result_tax = tax.copy({
                'name': self.new_tax_name.strip(),
                'amount': -self.new_rate,
                'withholding_sequence_id': tax.withholding_sequence_id.id,
                'active': True,
                'rs_form30_date_from': self.effective_date,
                'rs_form30_date_to': False,
                'rs_form30_previous_tax_id': tax.id,
            })
            pattern = re.compile(r'(?<![\d.])%s' % re.escape('%g%%' % abs(tax.amount)))
            langs = [code for code, name in self.env['res.lang'].get_installed()]
            result_tax.write({
                fname: {lang: pattern.sub('%g%%' % self.new_rate, text) for lang in langs if (text := tax.with_context(lang=lang)[fname])}
                for fname in ('invoice_label', 'description')
            })
            tax.rs_form30_date_to = self.effective_date - relativedelta(days=1)
        close.write({'valid_to': close_at})
        self.env['rs.form30.rate.rule'].create(create)
        self.write({'applied': True, 'result_tax_id': result_tax.id})
        return {'type': 'ir.actions.act_window', 'res_model': 'account.tax', 'res_id': result_tax.id, 'view_mode': 'form', 'target': 'current'}

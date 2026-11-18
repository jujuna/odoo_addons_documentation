# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict

from odoo import Command, fields, models, _
from odoo.exceptions import RedirectWarning, UserError
from odoo.fields import Domain
from odoo.tools import float_is_zero


class L10n_Be274_Xx(models.Model):
    _name = "l10n_be.274_xx"

    _inherit = ['l10n_be.274_xx']

    # the natures of the remunerations, the others are withholding tax exemptions
    TAXABLE_NATURES = ('274.10', '274.13', '274.18', '274.20', '274.30')

    move_id = fields.Many2one('account.move', 'Accounting Entry', readonly=True, index='btree_not_null')
    move_state = fields.Selection(related='move_id.state', string='Move State', export_string_translation=False)

    def action_open_move(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entry'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }

    def _get_exemptions_to_book(self):
        """{nature code: amount} of the withholding tax exemptions the declaration grants and the payslips did not
        book: the declared amount (the bachelors' one capped, the 0.12 % one computed on the whole company) minus the
        exemption lines of the payslips, when the payslips book them (the exemption total rule has accounts)."""
        self.ensure_one()
        declared = defaultdict(float)
        for line in self.line_ids:
            if line.nature_code not in self.TAXABLE_NATURES:
                declared[line.nature_code] += line.amount
        declared['274.34'] = self.capped_amount_34
        declared['274.56'] = self.sme_exempted_amount
        booked = defaultdict(float)
        exemption_rule = self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_274_exemption_total').with_company(self.company_id)
        if exemption_rule.account_debit and exemption_rule.account_credit:
            for line in self.env['hr.payslip.line'].search(
                Domain('slip_id', 'in', self.payslip_ids.ids)
                & Domain('salary_rule_id.category_ids.code', '=', 'TAX_EXEMPTION_GRANTED')
                & self.env['hr.payslip']._l10n_be_get_fiscal_line_domain(self.date_start, self.date_end)
            ):
                booked['274.' + line.code.rsplit('_', 1)[1]] += line.total
        precision = self.company_id.currency_id.rounding
        return {
            nature: round(declared[nature] - booked[nature], 2)
            for nature in sorted(set(declared) | set(booked))
            if not float_is_zero(declared[nature] - booked[nature], precision_rounding=precision)
        }

    def action_post_account_entries(self):
        """The journal entry of the withholding tax exemptions the payslips did not book: the withholding tax not to
        be paid (debit of the account the payslips credit with it) against the exemptions account (the one of the
        exemption lines of the payslips), so that the account of the withholding taxes holds what is paid."""
        self.ensure_one()
        withholding_rule = self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_withholding_taxes_total').with_company(self.company_id)
        exemption_rule = self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_274_exemption_total').with_company(self.company_id)
        withholding_account = withholding_rule.account_credit
        exemption_account = exemption_rule.account_credit or self.company_id.exemption_journal_id.default_account_id
        if not self.company_id.exemption_journal_id or not withholding_account or not exemption_account:
            action = self.env.ref('hr_payroll.action_hr_payroll_configuration')
            raise RedirectWarning(
                _('Please make sure that the journal and the accounts are correctly configured on the Payroll Settings.'),
                action.id,
                _('Settings')
            )
        amounts = self._get_exemptions_to_book()
        if not amounts:
            raise UserError(_('The payslips already booked all the withholding tax exemptions of the declaration.'))

        today = fields.Date.context_today(self)
        journal = self.company_id.exemption_journal_id
        line_ids = []
        for nature, amount in amounts.items():
            line_ids.append(Command.create({
                'name': _('Withholding Taxes Exemption %s', nature),
                'account_id': exemption_account.id,
                'debit': max(-amount, 0.0),
                'credit': max(amount, 0.0),
            }))
        total = sum(amounts.values())
        line_ids.append(Command.create({
            'name': _('Withholding Taxes'),
            'account_id': withholding_account.id,
            'debit': max(total, 0.0),
            'credit': max(-total, 0.0),
        }))
        self.move_id = self.env['account.move'].create({
            'narration': _('Withholding Taxes Exemption for %s', self.date_start.strftime('%B %Y')),
            'ref': self.date_start.strftime('%B %Y'),
            'journal_id': journal.id,
            'date': today,
            'line_ids': line_ids,
        })

from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError


class L10nGeCitWizard(models.TransientModel):
    """Post the profit distribution, its CIT and optional dividend withholding as one entry.
    Shareholder stays on the distribution and net-payable lines; CIT and withholding go to the State Treasury.
    Default tax and account are provisional."""
    _name = 'l10n.ge.cit.wizard'
    _description = 'Georgian CIT / Profit Distribution Wizard'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    journal_id = fields.Many2one('account.journal', required=True, domain="[('type', '=', 'general'), ('company_id', '=', company_id)]")
    date = fields.Date(required=True, default=fields.Date.context_today)
    partner_id = fields.Many2one('res.partner', string='Shareholder', required=True)
    net_amount = fields.Monetary(string='Net Distribution', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id')

    distribution_account_id = fields.Many2one('account.account', string='Distribution Account (Dr)', required=True,
        default=lambda self: self._default_chart_account('ge_account_530110'),
        domain="[('account_type', 'in', ('equity', 'equity_unaffected')), ('company_ids', 'in', company_id)]",
        help="Debited with the grossed-up distribution. Typically 530110 Retained Earnings.")
    cit_account_id = fields.Many2one('account.account', string='CIT Payable Account (Cr)', required=True,
        default=lambda self: self._default_chart_account('ge_account_331110'), domain="[('company_ids', 'in', company_id)]",
        help="Credited with the CIT. Typically 331110 Corporate Income Taxes.")
    cit_tax_id = fields.Many2one('account.tax', string='Corporate Income Tax', required=True, check_company=True,
        domain=[('amount_type', '=', 'division'), ('type_tax_use', '=', 'none')], default=lambda self: self._default_chart_account('ge_tax_cit_15'),
        help="Its rate grosses up the net distribution: gross = net / (1 - rate).")
    payable_account_id = fields.Many2one('account.account', string='Shareholder Payable Account (Cr)', required=True,
        default=lambda self: self._default_chart_account('ge_account_340120'),
        domain="[('account_type', 'in', ('liability_payable', 'liability_current')), ('company_ids', 'in', company_id)]",
        help="Credited with the net amount due to the shareholder. Typically 340120 Accrued Dividends Payable.")

    treasury_partner_id = fields.Many2one('res.partner', string='State Treasury', domain=[('gec_treasury_code', '!=', False)], check_company=True,
        required=True, default=lambda self: self.env['res.partner']._gec_state_treasury_partners(self.env.company)[:1],
        help="Partner of the CIT and withholding lines: the taxes are paid to it.")

    apply_dividend_wht = fields.Boolean(string='Withhold Dividend Tax', help="For individual or non-resident shareholders, withhold dividend tax "
        "(Art. 134) on top of the CIT. Leave off for resident company shareholders (exempt).")
    dividend_wht_tax_id = fields.Many2one('account.tax', string='Dividend Withholding Tax', domain=[('gec_is_withholding', '=', True)],
        check_company=True, compute='_compute_dividend_wht_tax_id', store=True, readonly=False, precompute=True)
    dividend_wht_rate = fields.Float(string='Dividend WHT %', compute='_compute_dividend_wht_rate')
    dividend_wht_account_id = fields.Many2one('account.account', string='Dividend WHT Account (Cr)', domain="[('company_ids', 'in', company_id)]",
        default=lambda self: self._default_dividend_wht_account(), help="Credited with the tax withheld from the dividend. Default 331210: pay it to "
        "the State Treasury by a bank entry booked on this account.")

    gross_amount = fields.Monetary(compute='_compute_amounts', currency_field='currency_id')
    cit_amount = fields.Monetary(compute='_compute_amounts', currency_field='currency_id')
    dividend_wht_amount = fields.Monetary(compute='_compute_amounts', currency_field='currency_id')

    def _default_dividend_wht_account(self):
        """The accountant keeps dividend tax on 331210 and pays the Treasury by a bank entry (2026-11-12), so the line gets no Pay link."""
        return self._default_chart_account('ge_account_331210')

    def _default_chart_account(self, xmlid):
        """Provisional defaults until the accountant confirms them; a company without the Georgian chart gets none."""
        return self.env['account.chart.template'].with_company(self.env.company).ref(xmlid, raise_if_not_found=False)

    @api.depends('company_id')
    def _compute_dividend_wht_tax_id(self):
        """Propose the dividend withholding tax once, for the company and the date at opening.
        It does not follow the date, so a tax picked by hand is never replaced."""
        for wizard in self:
            wizard.dividend_wht_tax_id = wizard._gec_default_dividend_wht_tax()

    def _gec_default_dividend_wht_tax(self):
        """Return the dividend withholding tax proposed here: resident individual, 5%.
        Provisional: a non-resident shareholder needs the non-resident tax picked by hand.
        gec_income_tax_report overrides it to follow dated tax replacements by the wizard date."""
        self.ensure_one()
        return self.env['account.chart.template'].with_company(self.company_id).ref(
            'ge_tax_p_wht_res_dividends_5', raise_if_not_found=False) or self.env['account.tax']

    @api.depends('dividend_wht_tax_id.amount')
    def _compute_dividend_wht_rate(self):
        """Take the rate from the tax, so the booked withholding always matches the tax."""
        for wizard in self:
            wizard.dividend_wht_rate = abs(wizard.dividend_wht_tax_id.amount)

    @api.depends('net_amount', 'apply_dividend_wht', 'dividend_wht_rate', 'cit_tax_id.amount')
    def _compute_amounts(self):
        for wizard in self:
            gross = wizard.net_amount / (1 - wizard.cit_tax_id.amount / 100) if wizard.net_amount else 0.0
            wizard.gross_amount = gross
            wizard.cit_amount = gross - wizard.net_amount
            wizard.dividend_wht_amount = (wizard.net_amount * wizard.dividend_wht_rate / 100.0 if wizard.apply_dividend_wht else 0.0)

    def action_post_cit(self):
        """Post the distribution entry; the CIT and withholding lines get the State Treasury as partner.
        The distribution line carries the Withholding Tax in Taxes, as a label Form 30 reads."""
        self.ensure_one()
        currency = self.company_id.currency_id
        net = currency.round(self.net_amount)
        if net <= 0:
            raise UserError(_('Net distribution must be greater than zero.'))
        if self.apply_dividend_wht and not self.dividend_wht_account_id:
            raise UserError(_('Select a Dividend WHT account, or turn off dividend withholding.'))
        if self.apply_dividend_wht and not self.dividend_wht_tax_id:
            raise UserError(_('Select the Dividend Withholding Tax, or turn off dividend withholding.'))

        gross, cit, wht = self.gross_amount, self.cit_amount, self.dividend_wht_amount
        shareholder = net - wht

        line_ids = [
            Command.create({
                'name': _('Profit distribution (gross)'),
                'account_id': self.distribution_account_id.id,
                'partner_id': self.partner_id.id,
                'tax_ids': [Command.set(self.dividend_wht_tax_id.ids if self.apply_dividend_wht else [])],
                'debit': gross,
                'credit': 0.0,
            }),
            Command.create({
                'name': _('CIT payable (%(rate)g%%)', rate=self.cit_tax_id.amount),
                'account_id': self.cit_account_id.id,
                'partner_id': self.treasury_partner_id.id,
                'debit': 0.0,
                'credit': cit,
            }),
            Command.create({
                'name': _('Net payable to shareholder'),
                'account_id': self.payable_account_id.id,
                'partner_id': self.partner_id.id,
                'debit': 0.0,
                'credit': shareholder,
            }),
        ]
        if wht:
            line_ids.append(Command.create({
                'name': _('Dividend WHT %(rate)s%%', rate=self.dividend_wht_rate),
                'account_id': self.dividend_wht_account_id.id,
                'partner_id': self.treasury_partner_id.id,
                'debit': 0.0,
                'credit': wht,
            }))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': self.date,
            'company_id': self.company_id.id,
            'ref': _('Profit distribution + CIT %(rate)g%% (net %(net)s)', rate=self.cit_tax_id.amount, net=net),
            'line_ids': line_ids,
        })
        move.action_post()
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': move.id, 'view_mode': 'form', 'target': 'current'}

from collections import defaultdict

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare
from odoo.tools.translate import get_translation

LIABILITY_TYPES = ('liability_current', 'liability_payable')


def _is_treasury(partner):
    """True when the contact's commercial entity has a Treasury Code (the State Treasury)."""
    return bool((partner.commercial_partner_id.gec_treasury_code or '').strip())


class AccountMove(models.Model):
    _inherit = 'account.move'

    rs_form30_can_set_withholding = fields.Boolean(compute='_compute_rs_form30_can_set_withholding')

    def _rs_form30_plain_entries(self, state='posted'):
        entries = self.filtered(
            lambda move: move.state == state
            and move.move_type == 'entry'
            and move.journal_id.type == 'general'
            and not move.origin_payment_id
            and not move.statement_line_id
            and not move.reversed_entry_id
            and move != move.company_id.account_opening_move_id)
        if entries:
            # sudo: accountants have no payroll access; only the ids of payslip entries are used
            payslip_moves = self.env['hr.payslip'].sudo().search([('move_id', 'in', entries.ids)]).move_id
            entries -= payslip_moves
        return entries

    def _rs_form30_get_rules(self):
        """Return the active Form 30 account rules of the root company of these entries."""
        # sudo: the rules are configuration read by every user who posts; the root company is the filter
        return self.env['rs.form30.account.rule'].sudo().search([('company_id', 'in', self.company_id.root_id.ids)])

    def _rs_form30_get_taxes(self):
        """Return the root company's withholding taxes with an income
        type and a negative rate; 0% labels are never candidates."""
        # sudo: taxes are configuration read by every user who posts; the root company is the filter
        return self.env['account.tax'].sudo().search([
            ('company_id', 'in', self.company_id.root_id.ids),
            ('gec_is_withholding', '=', True),
            ('amount', '<', 0),
            ('rs_form30_income_type_id', '!=', False),
        ])

    def _rs_form30_match(self, rules):
        """Return (tax lines, matched rules) of this entry. Tax line: a credit on a rule tax account, no partner or the
        Treasury. A rule matches when the entry debits its expense accounts, credits its liability accounts and has a
        tax line on its tax accounts."""
        self.ensure_one()
        lines = self.line_ids
        withholding_accounts = rules.tax_account_ids
        tax_lines = lines.filtered(
            lambda line: line.balance < 0
            and line.account_id in withholding_accounts
            and (not line.partner_id or _is_treasury(line.partner_id)))
        debit_accounts = lines.filtered(lambda line: line.balance > 0).account_id
        credit_accounts = (lines - tax_lines).filtered(lambda line: line.balance < 0).account_id
        matched = rules.filtered(
            lambda rule: rule.expense_account_ids & debit_accounts
            and rule.liability_account_ids & credit_accounts
            and rule.tax_account_ids & tax_lines.account_id)
        return tax_lines, matched

    def _rs_form30_recipient_lines(self, tax_lines, rules):
        self.ensure_one()
        liability_accounts = rules.liability_account_ids
        return (self.line_ids - tax_lines).filtered(lambda line: line.account_id in liability_accounts and not _is_treasury(line.partner_id))

    def _rs_form30_entry_split(self, rules):
        """Not-payable lines count in net_total so recipient shares are not inflated."""
        self.ensure_one()
        # sudo: a user working in a branch only cannot read the root company; only the account ids are used
        company = self.company_id.root_id.sudo()
        currency = self.company_id.currency_id
        lines = self.line_ids
        pension_accounts = company.rs_form30_pension_account_ids
        employer_accounts = company.rs_form30_employer_pension_account_ids
        tax_lines = self._rs_form30_match(rules)[0]
        pension_total = (
            -sum(lines.filtered(lambda line: line.account_id in pension_accounts).mapped('balance'))
            - sum(lines.filtered(lambda line: line.account_id in employer_accounts).mapped('balance')))
        others = (lines - tax_lines).filtered(
            lambda line: line.partner_id and not _is_treasury(line.partner_id)
            and line.account_id not in pension_accounts | employer_accounts)
        recipients = {}
        grouped = others.filtered('account_id.reconcile').grouped(lambda line: line.partner_id.commercial_partner_id)
        for partner in sorted(grouped, key=lambda partner: partner.id):
            net = -sum(grouped[partner].mapped('balance'))
            if float_compare(net, 0.0, precision_rounding=currency.rounding) > 0:
                recipients[partner] = {'lines': grouped[partner], 'net': net}
        not_payable = others.filtered(
            lambda line: line.account_id.account_type in LIABILITY_TYPES and not line.account_id.reconcile
            and line.balance < 0)
        not_payable_net = -sum(not_payable.mapped('balance'))
        return {
            'taxes': lines.tax_ids.filtered('rs_form30_income_type_id'),
            'tax_lines': tax_lines,
            'tax_total': -sum(tax_lines.mapped('balance')),
            'pension_total': max(pension_total, 0.0),
            'pension_below_zero': float_compare(pension_total, 0.0, precision_rounding=currency.rounding) < 0,
            'recipients': recipients,
            'net_total': sum(data['net'] for data in recipients.values()) + not_payable_net,
            'not_payable': bool(not_payable),
            'not_payable_net': not_payable_net,
        }

    def _rs_form30_candidates(self, rules, taxes):
        """Return (expense lines, candidate taxes) of this entry; the entry date is used as the payment is not known
        yet. Candidates exist only when the rules match one income type; a tax must fit date, residency and an allowed
        rate."""
        self.ensure_one()
        tax_lines, matched = self._rs_form30_match(rules)
        expense_lines = self.line_ids.filtered(lambda line: line.balance > 0 and line.account_id in matched.expense_account_ids)
        income_type = matched.income_type_id
        no_tax = self.env['account.tax']
        if len(income_type) != 1:
            return expense_lines, no_tax
        date = self.date
        candidates = taxes.filtered(
            lambda tax: tax.rs_form30_income_type_id == income_type
            and (not tax.rs_form30_date_from or tax.rs_form30_date_from <= date)
            and (not tax.rs_form30_date_to or date <= tax.rs_form30_date_to))
        if not candidates:
            return expense_lines, no_tax
        # sudo: tax groups, rate rules and contact categories are configuration; accountants may not read all of them
        template = self.env['account.chart.template'].sudo().with_company(self.company_id.root_id)
        res_group = template.ref('gec_tax_group_wht_res', raise_if_not_found=False)
        nr_group = template.ref('gec_tax_group_wht_nr', raise_if_not_found=False)
        allowed = self.env['rs.form30.rate.rule'].sudo()._allowed_rates(int(date.strftime('%Y%m')))
        recipients = self._rs_form30_recipient_lines(tax_lines, matched).filtered(
            lambda line: line.balance < 0 and line.partner_id).partner_id.commercial_partner_id
        for recipient in recipients.sudo():
            category = recipient._rs_form30_category_on(date)
            if category:
                non_resident = (category.display_code or '').startswith('3.')
            else:
                non_resident = bool(recipient.country_id) and recipient.country_id.code != 'GE'
            wrong_group = res_group if non_resident else nr_group
            if wrong_group:
                candidates = candidates.filtered(lambda tax: tax.tax_group_id != wrong_group)
            if category:
                rates = allowed.get((category.id, income_type.id), [])
                candidates = candidates.filtered(lambda tax: any(float_compare(abs(tax.amount), rate, precision_digits=2) == 0 for rate in rates))
        by_rate = candidates.grouped('amount')
        candidates = no_tax.concat([group.filtered(lambda tax: tax.price_include_override == 'tax_excluded') or group for group in by_rate.values()])
        return expense_lines, candidates

    def _rs_form30_propose_withholding_tax(self):
        """Set the Withholding Tax on expense lines of plain draft entries when exactly one tax fits; hand-set taxes are
        skipped. Runs before posting as core refuses tax changes on posted lines."""
        to_write = defaultdict(lambda: self.env['account.move.line'])
        for moves in self.grouped(lambda move: move.company_id.root_id).values():
            rules = moves._rs_form30_get_rules()
            taxes = moves._rs_form30_get_taxes()
            for move in moves:
                lines = move.line_ids
                if lines.filtered(lambda line: line.tax_ids.filtered('gec_is_withholding') != line.rs_form30_proposed_tax_id):
                    continue
                expense_lines, candidates = move._rs_form30_candidates(rules, taxes)
                tax = candidates if len(candidates) == 1 else self.env['account.tax']
                for line in lines.filtered(lambda line: line.rs_form30_proposed_tax_id or (tax and line in expense_lines)):
                    new = tax if line in expense_lines else self.env['account.tax']
                    old = line.tax_ids.filtered('gec_is_withholding')
                    if old != new:
                        to_write[(tuple((old - new).ids), tuple((new - old).ids), new.id)] |= line
        for (unlink_ids, link_ids, proposed_id), lines in to_write.items():
            lines.write({
                'tax_ids': [Command.unlink(tax_id) for tax_id in unlink_ids] + [Command.link(tax_id) for tax_id in link_ids],
                'rs_form30_proposed_tax_id': proposed_id,
            })

    def _rs_form30_check_no_balancing_line(self):
        """Refuse an entry with a withholding tax and an automatic balancing line, which hides a missing person or
        Treasury line. The line is found by name in every active language."""
        source = 'Automatic Balancing Line'
        names = {get_translation('account', lang, source, ()) for lang, _name in self.env['res.lang'].get_installed()} | {source}
        for move in self:
            balancing = move.line_ids.filtered(
                lambda line: line.name in names
                and not line.tax_ids
                and line.account_id.id == move._get_automatic_balancing_account()
                and not line.company_currency_id.is_zero(line.balance))
            if balancing and move.line_ids.tax_ids.filtered('gec_is_withholding'):
                raise UserError(self.env._("%(entry)s has a withholding tax but is not balanced: Odoo added an Automatic Balancing Line on "
                    "%(account)s. Complete the entry lines (the person and the State Treasury), then post again.", entry=move.display_name,
                    account=balancing[0].account_id.display_name))

    def _post(self, soft=True):
        plain = self._rs_form30_plain_entries(state='draft')
        plain._rs_form30_propose_withholding_tax()
        plain._rs_form30_check_no_balancing_line()
        return super()._post(soft=soft)

    def action_rs_form30_detect_withholding_tax(self):
        """Repost plain entries so the proposal runs; refused for entries in a Form 30 file or locked dates."""
        plain = self._rs_form30_plain_entries()
        if self - plain:
            raise UserError(self.env._("Detect Again works on posted manual journal entries only; these are not: %(entries)s.",
                entries=', '.join((self - plain).mapped('display_name'))))
        self._rs_form30_check_not_in_file()
        self._check_fiscal_lock_dates()
        self.button_draft()
        self.action_post()

    def _rs_form30_check_not_in_file(self):
        """Refuse entries in an exported Form 30 file (annex A or E)."""
        domain = [('move_id', 'in', self.ids), ('in_file', '=', True)]
        moves = (self.env['rs.form30.line'].search(domain).move_id | self.env['rs.form30.service.line'].search(domain).move_id)
        if moves:
            raise UserError(self.env._("These entries are in the file of a Form 30 declaration: %(entries)s. Reset the declaration to draft first.",
                entries=', '.join(moves.mapped('display_name'))))

    @api.depends('state', 'move_type', 'journal_id.type', 'origin_payment_id', 'statement_line_id', 'reversed_entry_id')
    def _compute_rs_form30_can_set_withholding(self):
        """Flag the plain posted entries: only those can use Set Withholding Tax and Detect Again."""
        plain = self._origin._rs_form30_plain_entries()
        for move in self:
            move.rs_form30_can_set_withholding = move._origin in plain

    def _rs_form30_check_can_set_withholding(self):
        plain = self._rs_form30_plain_entries()
        if self - plain:
            raise UserError(self.env._("Set Withholding Tax works on posted manual journal entries only; these are not: %(entries)s.",
                entries=', '.join((self - plain).mapped('display_name'))))
        self._rs_form30_check_not_in_file()

    def action_rs_form30_set_withholding_tax(self):
        self.ensure_one()
        self._rs_form30_check_can_set_withholding()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Set Withholding Tax"),
            'res_model': 'rs.form30.set.withholding.tax',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    def _rs_form30_reversed_after_payment(self):
        """True when a posted credit note is dated after the first payment, so the declaration needs a correction."""
        self.ensure_one()
        payable = self.line_ids.filtered(lambda line: line.display_type == 'payment_term')
        dates = [part['date'] for item in payable._rs_form30_cash_parts().values() for part in item['cash']]
        return bool(dates) and any(reversal.state == 'posted' and reversal.date > min(dates) for reversal in self.reversal_move_ids)

    @api.depends('line_ids.tax_ids', 'line_ids.balance', 'line_ids.account_id', 'line_ids.partner_id', 'state', 'partner_id', 'invoice_date')
    def _compute_alerts(self):
        super()._compute_alerts()

    def _get_alerts(self):
        alerts = super()._get_alerts()
        if self._rs_form30_plain_entries():
            alerts.update(self._rs_form30_get_alerts())
        alerts.update(self._rs_form30_get_bill_alerts())
        return alerts

    def _rs_form30_get_bill_alerts(self):
        self.ensure_one()
        alerts = {}
        if self.state != 'posted' or self.move_type not in ('in_invoice', 'in_receipt'):
            return alerts
        partner = self.commercial_partner_id
        date = self.invoice_date or self.date
        withheld = self.line_ids.tax_ids.filtered(lambda tax: tax.gec_is_withholding and tax.amount < 0)
        default_tax = self.env['account.tax']._gec_partner_purchase_tax(partner, self.company_id, date).filtered('active')
        if (default_tax.gec_is_withholding and (default_tax.amount < 0 or default_tax.rs_form30_annex_e)
                and self.invoice_line_ids.filtered(
                    lambda line: line.display_type == 'product'
                    and not line.product_id.not_taxed
                    and not line.tax_ids.filtered('gec_is_withholding'))):
            alerts['rs_form30_bill_tax_missing'] = {
                'level': 'warning',
                'message': self.env._("%(vendor)s has the Default Purchase Tax %(tax)s but a line of this bill has no withholding tax: Form 30 will "
                    "not declare it.", vendor=partner.display_name, tax=default_tax.display_name),
            }
        if self.invoice_line_ids.filtered(
                lambda line: line.display_type == 'product'
                and line.tax_ids.filtered(lambda tax: tax.gec_is_withholding and tax.amount < 0)
                and line.tax_ids.filtered(lambda tax: tax.gec_is_withholding and not tax.amount)):
            alerts['rs_form30_bill_label_conflict'] = {
                'level': 'warning',
                'message': self.env._("A line of this bill has both a 'no withholding' label and a withholding tax: keep only one of them."),
            }
        if not withheld:
            return alerts
        if partner._rs_form30_pays_own_tax():
            alerts['rs_form30_bill_own_tax'] = {
                'level': 'warning',
                'message': self.env._("%(vendor)s pays their own income tax but this bill withholds %(taxes)s.", vendor=partner.display_name,
                    taxes=', '.join(withheld.mapped('display_name'))),
            }
        elif category := partner._rs_form30_category_on(date):
            allowed = self.env['rs.form30.rate.rule']._allowed_rates(int(date.strftime('%Y%m')))
            if not category.use_bill:
                alerts['rs_form30_bill_category'] = {
                    'level': 'warning',
                    'message': self.env._("Category %(category)s of %(vendor)s is not meant for vendor bills (category guide).",
                        category=category.display_code, vendor=partner.display_name),
                }
            for tax in withheld.filtered('rs_form30_income_type_id'):
                rates = allowed.get((category.id, tax.rs_form30_income_type_id.id), [])
                if not any(float_compare(abs(tax.amount), rate, precision_digits=2) == 0 for rate in rates):
                    alerts[f'rs_form30_bill_rate_{tax.id}'] = {
                        'level': 'warning',
                        'message': self.env._("The rs.ge rules do not allow %(rate)s%% of income type %(type)s for category %(category)s of "
                            "%(vendor)s: Form 30 will flag the row.", rate=f"{abs(tax.amount):g}", type=tax.rs_form30_income_type_id.code,
                            category=category.display_code, vendor=partner.display_name),
                    }
        for tax in withheld:
            version = tax._rs_form30_version_on(date)
            if version != tax:
                alerts[f'rs_form30_bill_tax_expired_{tax.id}'] = {
                    'level': 'warning',
                    'message': self.env._("%(tax)s is not the Form 30 version valid on %(bill_date)s: use %(version)s on this bill.",
                        tax=tax.display_name, bill_date=date, version=version.display_name or self.env._("a version valid on that date")),
                }
        return alerts

    def _rs_form30_get_alerts(self):
        self.ensure_one()
        alerts = {}
        rules = self._rs_form30_get_rules()
        if not rules:
            return alerts
        tax_lines, matched = self._rs_form30_match(rules)
        if not matched:
            return alerts
        taxes = self.line_ids.tax_ids.filtered('rs_form30_income_type_id')
        if not taxes:
            no_label = not self.line_ids.tax_ids.filtered(lambda tax: tax.gec_is_withholding and not tax.amount)
            if no_label and not self.reversal_move_ids.filtered(lambda move: move.state == 'posted'):
                lines = ', '.join(line.name or line.account_id.display_name for line in tax_lines)
                if len(matched.income_type_id) > 1:
                    message = self.env._("Form 30 will not declare %(lines)s: several income types fit these accounts (%(types)s). Use Set "
                        "Withholding Tax.", lines=lines, types=', '.join(matched.income_type_id.mapped('code')))
                else:
                    message = self.env._("Form 30 will not declare %(lines)s: it credits a withholding-tax account without a Withholding Tax. Use "
                        "Set Withholding Tax.", lines=lines)
                alerts['rs_form30_tax_missing'] = {'level': 'warning', 'message': message}
            return alerts
        split = self._rs_form30_entry_split(rules)
        tax = taxes[:1]
        currency = self.company_id.currency_id
        booked = split['tax_total']
        base = split['net_total'] + booked
        expected = currency.round(base * abs(tax.amount) / 100)
        if split['recipients'] and float_compare(abs(expected - booked), 0.01 * max(1, len(split['recipients'])), precision_digits=4) > 0:
            alerts[f'rs_form30_tax_amount_{tax.id}'] = {
                'level': 'warning',
                'message': self.env._("Form 30: the booked tax %(booked)s differs from %(rate)s%% of %(base)s (net + tax) = %(expected)s.",
                    booked=currency.format(booked), rate=f"{abs(tax.amount):g}", base=currency.format(base), expected=currency.format(expected)),
            }
        return alerts

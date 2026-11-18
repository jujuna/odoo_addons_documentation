from odoo import api, fields, models
from odoo.exceptions import UserError


class GecBillPayChoice(models.TransientModel):
    """Ask what to pay on a bill with an open withholding tax: the vendor, the tax, or both.
    Payments are created by Odoo's own Pay code (account.payment.register); the amounts shown here are display only."""
    _name = 'gec.bill.pay.choice'
    _description = 'Pay a Bill and its Withholding Tax'
    _check_company_auto = True

    move_ids = fields.Many2many('account.move', string='Bills', required=True)
    company_id = fields.Many2one('res.company', compute='_compute_company_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    pay_choice = fields.Selection([('both', 'Vendor and Withholding Tax'), ('vendor', 'Vendor Only'), ('tax', 'Withholding Tax Only')], string='Pay',
        required=True, compute='_compute_pay_choice', store=True, readonly=False, precompute=True)
    vendor_line_ids = fields.Many2many('account.move.line', compute='_compute_lines')
    tax_line_ids = fields.Many2many('account.move.line', compute='_compute_lines')
    vendor_amount = fields.Monetary(compute='_compute_amounts', currency_field='currency_id')
    tax_amount = fields.Monetary(compute='_compute_amounts', currency_field='currency_id')
    can_pay_both = fields.Boolean(compute='_compute_can_pay_both')
    pay_both_note = fields.Char(compute='_compute_can_pay_both')
    journal_id = fields.Many2one('account.journal', string='Journal', check_company=True, ondelete='cascade',
        domain="[('type', 'in', ('bank', 'cash')), '|', ('currency_id', '=', False), ('currency_id', '=', currency_id), "
        "('outbound_payment_method_line_ids', '!=', False)]", compute='_compute_journal_id', store=True, readonly=False, precompute=True)
    payment_method_line_id = fields.Many2one('account.payment.method.line', string='Payment Method', check_company=True, ondelete='cascade',
        domain="[('journal_id', '=', journal_id), ('payment_type', '=', 'outbound')]", compute='_compute_payment_method_line_id', store=True,
        readonly=False, precompute=True)
    payment_date = fields.Date(required=True, default=fields.Date.context_today)

    @api.depends('move_ids')
    def _compute_company_id(self):
        for wizard in self:
            wizard.company_id = wizard.move_ids[:1].company_id

    @api.depends('can_pay_both', 'vendor_line_ids', 'move_ids.payment_state')
    def _compute_pay_choice(self):
        """Offer both when possible, else the vendor if it is open and not already being paid, else the tax."""
        for wizard in self:
            if wizard.can_pay_both:
                wizard.pay_choice = 'both'
            elif wizard.vendor_line_ids and 'in_payment' not in wizard.move_ids.mapped('payment_state'):
                wizard.pay_choice = 'vendor'
            else:
                wizard.pay_choice = 'tax'

    @api.depends('move_ids.line_ids.amount_residual', 'move_ids.line_ids.reconciled')
    def _compute_lines(self):
        """Take the open payable lines and the open withholding tax lines of the bills."""
        for wizard in self:
            wizard.vendor_line_ids = wizard.move_ids.line_ids.filtered(
                lambda line: line.account_id.account_type == 'liability_payable' and line._gec_is_open())
            wizard.tax_line_ids = wizard.move_ids._gec_open_withholding_lines()

    @api.depends('vendor_line_ids', 'tax_line_ids')
    def _compute_amounts(self):
        for wizard in self:
            wizard.vendor_amount = abs(sum(wizard.vendor_line_ids.mapped('amount_residual')))
            wizard.tax_amount = abs(sum(wizard.tax_line_ids.mapped('amount_residual')))

    @api.depends('move_ids.payment_state', 'move_ids.currency_id', 'move_ids.reconciled_payment_ids',
        'move_ids.invoice_payment_term_id.early_discount', 'vendor_line_ids', 'tax_line_ids', 'company_id')
    def _compute_can_pay_both(self):
        """Allow one window to pay both only when Odoo's own Pay amounts cannot be disturbed.
        Otherwise two steps: partly paid bill, unmatched paid payments, installments, early payment discount,
        foreign currency, no single State Treasury contact."""
        for wizard in self:
            company = wizard.company_id
            note = False
            if not wizard.vendor_line_ids or not wizard.tax_line_ids:
                note = self.env._("The vendor or the withholding tax is already paid: pay what is left separately.")
            elif any(move.payment_state != 'not_paid' for move in wizard.move_ids):
                note = self.env._("The bill is already partly paid: pay the vendor and the tax separately.")
            elif any(
                move.reconciled_payment_ids.filtered(
                    lambda p: p.state == 'paid' and not p.is_reconciled and not p.is_matched)
                for move in wizard.move_ids
            ):
                note = self.env._("The bill has a payment that is not matched yet: pay the vendor and the tax separately.")
            elif any(
                len(move.line_ids.filtered(lambda line: line.display_type == 'payment_term')) > 1
                or move.invoice_payment_term_id.early_discount
                for move in wizard.move_ids
            ):
                note = self.env._("The bill has installments or an early payment discount: pay the vendor and the tax separately.")
            elif any(move.currency_id != company.currency_id for move in wizard.move_ids):
                note = self.env._("The bill is not in %(currency)s: pay the vendor and the tax separately.", currency=company.currency_id.name)
            elif len(self.env['res.partner']._gec_state_treasury_partners(company)) != 1:
                note = self.env._("No single State Treasury contact with Treasury Code 101001000.")
            wizard.can_pay_both = not note
            wizard.pay_both_note = note

    @api.depends('company_id')
    def _compute_journal_id(self):
        """Take the first bank or cash journal of the company in its currency that has an outgoing payment method."""
        for wizard in self:
            company = wizard.company_id
            wizard.journal_id = self.env['account.journal'].search([*self.env['account.journal']._check_company_domain(company),
                ('type', 'in', ('bank', 'cash')), ('currency_id', 'in', (False, company.currency_id.id)),
                ('outbound_payment_method_line_ids', '!=', False)], limit=1)

    @api.depends('journal_id')
    def _compute_payment_method_line_id(self):
        """Take the first outgoing payment method of the journal, unless the chosen one belongs to it."""
        for wizard in self:
            lines = wizard.journal_id.outbound_payment_method_line_ids
            if wizard.payment_method_line_id not in lines:
                wizard.payment_method_line_id = lines[:1]

    def action_confirm(self):
        """Do the chosen payment: open Odoo's Pay dialog for the vendor or the tax, or pay both now."""
        self.ensure_one()
        if self.pay_choice == 'vendor':
            if not self.vendor_line_ids:
                raise UserError(self.env._("Nothing is left to pay to the vendor."))
            return self.move_ids.with_context(gec_pay_choice_done=True).action_force_register_payment()
        if self.pay_choice == 'tax':
            return self.tax_line_ids._gec_action_pay_withholding()
        return self._gec_pay_both()

    def _gec_pay_both(self):
        """Create the vendor payment and the Treasury payment with Odoo's Pay code, in one transaction.
        Tax lines are netted first; runs use the Pay dialog's own create and _create_payments: no amount computed."""
        if not self.can_pay_both:
            raise UserError(self.pay_both_note)
        if not self.payment_method_line_id.payment_account_id:
            raise UserError(self.env._("Payment method %(method)s of %(journal)s has no Outstanding Payments account, so this payment would not "
                "settle the journal entry line. Set one on the journal's Outgoing Payments tab.", method=self.payment_method_line_id.name,
                journal=self.journal_id.display_name))
        tax_lines = self.tax_line_ids._gec_net_withholding_lines()
        Register = self.env['account.payment.register']
        vals = {'journal_id': self.journal_id.id, 'payment_method_line_id': self.payment_method_line_id.id, 'payment_date': self.payment_date}
        Register.with_context(active_model='account.move.line', active_ids=self.vendor_line_ids.ids).create(vals)._create_payments()
        if tax_lines:
            Register.with_context(active_model='account.move.line', active_ids=tax_lines.ids,
                gec_wht_tax_line_payment=True).create({**vals, 'group_payment': True})._create_payments()
        return {'type': 'ir.actions.act_window_close'}

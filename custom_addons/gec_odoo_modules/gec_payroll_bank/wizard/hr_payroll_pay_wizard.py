from odoo import _, api, Command, fields, models
from odoo.exceptions import UserError

from odoo.addons.gec_bank.models.account_payment_method_line import GEC_BANK_CHANNEL_DOMAIN


class HrPayrollPayWizard(models.TransientModel):
    _name = 'hr.payroll.pay.wizard'
    _description = 'Pay Salaries Through a Bank Channel'

    payslip_ids = fields.Many2many('hr.payslip', string='Payslips', required=True)
    payslip_run_id = fields.Many2one('hr.payslip.run', string='Pay Run', ondelete='cascade')
    company_id = fields.Many2one('res.company', string='Company', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='company_id.currency_id')
    payment_date = fields.Date(required=True, default=fields.Date.context_today)
    channel_id = fields.Many2one('account.payment.method.line', string='Default Bank', required=True, ondelete='cascade',
        domain=GEC_BANK_CHANNEL_DOMAIN)
    line_ids = fields.One2many('hr.payroll.pay.wizard.line', 'wizard_id', string='Employees')
    authority_line_ids = fields.One2many('hr.payroll.pay.wizard.authority', 'wizard_id', string='Authorities')
    warning = fields.Text(compute='_compute_warning')
    manual_ack_required = fields.Boolean(compute='_compute_manual_ack_required')
    manual_ack = fields.Boolean(string='Record only - I will transfer in the bank portal')
    remember_routing = fields.Boolean(string='Remember these banks on the employees', default=True)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        payslips = self._gec_wizard_payslips(defaults)
        if not payslips:
            return defaults
        company = payslips.company_id
        if len(company) != 1:
            raise UserError(_("Select payslips from a single company."))
        default_channel = self._gec_default_channel(company)
        run = payslips[:1].payslip_run_id
        if not run or any(slip.payslip_run_id != run for slip in payslips):
            run = self.env['hr.payslip.run']
        defaults.update({
            'payslip_ids': [Command.set(payslips.ids)],
            'company_id': company.id,
            'payslip_run_id': run.id,
            'channel_id': default_channel.id,
            'line_ids': [Command.create({
                'payslip_id': slip.id,
                'amount': sum(-line.amount_residual for line in slip._gec_payroll_employee_lines()),
                'channel_id': (slip.employee_id.sudo().gec_payroll_channel_id or default_channel).id,
            }) for slip in payslips.filtered(lambda slip: slip.sudo()._gec_payroll_salary_due())],
            'authority_line_ids': [Command.create(vals) for vals in self._gec_authority_vals(payslips, default_channel)],
        })
        return defaults

    @api.model
    def _gec_wizard_payslips(self, defaults):
        """Payslips this wizard was opened on; only the explicit context key is trusted.
        The pay-run button carries ``active_ids`` of ``hr.payslip.run``. Payslips with nothing left to pay are dropped."""
        ids = list(self.env.context.get('gec_payroll_payslip_ids') or [])
        if not ids:
            for command in defaults.get('payslip_ids') or []:
                if isinstance(command, int):
                    ids.append(command)
                elif command[0] == Command.SET:
                    ids.extend(command[2])
                elif command[0] == Command.LINK:
                    ids.append(command[1])
        if not ids and self.env.context.get('active_model') == 'hr.payslip':
            ids = self.env.context.get('active_ids') or []
        payslips = self.env['hr.payslip'].browse(ids).exists()
        return payslips.filtered(lambda slip: slip.state == 'validated' and slip.sudo()._gec_payroll_has_open_legs())

    @api.model
    def _gec_default_channel(self, company):
        """Prefer a channel that really transmits; fall back to the company default."""
        Line = self.env['account.payment.method.line']
        configured = company.gec_payroll_channel_id
        if configured:
            return configured
        candidates = Line.search(Line._gec_bank_channel_domain(company))
        transmitting = candidates.filtered(lambda line: line._gec_bank_channel_kind() in ('api', 'file'))
        return (transmitting or candidates)[:1]

    @api.model
    def _gec_authority_vals(self, payslips, default_channel):
        totals = {}
        for line in payslips._gec_payroll_authority_lines():
            key = (line.partner_id, line.account_id)
            totals[key] = totals.get(key, 0.0) - line.amount_residual
        return [{
            'partner_id': partner.id,
            'account_id': account.id,
            'amount': amount,
            'channel_id': default_channel.id,
        } for (partner, account), amount in totals.items()]

    @api.depends('payslip_ids')
    def _compute_warning(self):
        for wizard in self:
            accounts = wizard.payslip_ids._gec_payroll_blocked_accounts()
            if accounts:
                wizard.warning = _("%s cannot be settled by a payment from the payslip. Those amounts are not included here; settle them through the "
                    "tax or declaration flow.", ', '.join(accounts.mapped('display_name')))
            else:
                wizard.warning = False

    @api.depends('channel_id', 'line_ids.channel_id', 'authority_line_ids.channel_id')
    def _compute_manual_ack_required(self):
        for wizard in self:
            channels = wizard.line_ids.channel_id | wizard.authority_line_ids.channel_id
            wizard.manual_ack_required = any(channel._gec_bank_channel_kind() == 'manual' for channel in channels)

    @api.onchange('channel_id')
    def _onchange_channel_id(self):
        """Fill only the rows the user has not decided yet."""
        for line in self.line_ids.filtered(lambda line: not line.channel_id):
            line.channel_id = self.channel_id
        for line in self.authority_line_ids.filtered(lambda line: not line.channel_id):
            line.channel_id = self.channel_id

    def action_pay(self):
        """Create the payments and the batches, then hand each batch to its bank."""
        self.ensure_one()
        if not self.line_ids and not self.authority_line_ids:
            raise UserError(_("Nothing to pay."))
        missing = [
            line.employee_id.display_name
            for line in self.line_ids if not line.channel_id
        ] + [
            line.partner_id.display_name
            for line in self.authority_line_ids if not line.channel_id
        ]
        if missing:
            raise UserError(_("Choose a bank for: %s", ', '.join(sorted(set(missing)))))
        if self.manual_ack_required and not self.manual_ack:
            raise UserError(_("One of the chosen banks only records the payment in Odoo and transmits nothing. Tick 'Record only' to confirm you "
                "will transfer it yourself."))

        routing = {line.payslip_id.id: line.channel_id for line in self.line_ids}
        authority_routing = {(line.partner_id.id, line.account_id.id): line.channel_id for line in self.authority_line_ids}
        if self.remember_routing:
            self._gec_remember_routing()
        return self.payslip_ids._gec_payroll_pay(routing, authority_routing, self.payment_date, manual_ack=self.manual_ack)

    def _gec_remember_routing(self):
        """Store each chosen bank on its employee as the default for the next run.
        Only payroll managers open this wizard, the group the employee field is restricted to."""
        changed = self.line_ids.filtered(lambda line: line.payslip_id.employee_id.sudo().gec_payroll_channel_id != line.channel_id)
        for channel, lines in changed.grouped('channel_id').items():
            # sudo: the user chose this write in the wizard.
            lines.payslip_id.employee_id.sudo().gec_payroll_channel_id = channel


class HrPayrollPayWizardLine(models.TransientModel):
    _name = 'hr.payroll.pay.wizard.line'
    _description = 'Pay Salaries Wizard Line'

    wizard_id = fields.Many2one('hr.payroll.pay.wizard', required=True, ondelete='cascade', index=True)
    payslip_id = fields.Many2one('hr.payslip', string='Payslip', required=True, ondelete='cascade')
    employee_id = fields.Many2one(related='payslip_id.employee_id', string='Employee')
    company_id = fields.Many2one(related='wizard_id.company_id')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    amount = fields.Monetary(string='Net Amount', currency_field='currency_id')
    channel_id = fields.Many2one('account.payment.method.line', string='Bank', required=True, ondelete='cascade', domain=GEC_BANK_CHANNEL_DOMAIN)


class HrPayrollPayWizardAuthority(models.TransientModel):
    _name = 'hr.payroll.pay.wizard.authority'
    _description = 'Pay Salaries Wizard Authority Line'

    wizard_id = fields.Many2one('hr.payroll.pay.wizard', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one('res.partner', string='Paid To', required=True, ondelete='cascade')
    account_id = fields.Many2one('account.account', string='Account', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='wizard_id.company_id')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    channel_id = fields.Many2one('account.payment.method.line', string='Bank', required=True, ondelete='cascade', domain=GEC_BANK_CHANNEL_DOMAIN)

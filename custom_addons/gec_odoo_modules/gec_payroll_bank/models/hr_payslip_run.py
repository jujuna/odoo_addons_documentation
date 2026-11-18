from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    gec_payroll_batch_ids = fields.One2many('account.batch.payment', 'payslip_run_id', string='Payment Batches')
    gec_payroll_batch_count = fields.Integer(compute='_compute_gec_payroll_batch_count')
    gec_payroll_can_pay = fields.Boolean(compute='_compute_gec_payroll_can_pay')

    @api.depends('gec_payroll_batch_ids')
    def _compute_gec_payroll_batch_count(self):
        for run in self:
            # sudo: account.batch.payment is readable by accounting groups only.
            run.gec_payroll_batch_count = len(run.sudo().gec_payroll_batch_ids)

    @api.depends('slip_ids.state', 'slip_ids.net_wage')
    def _compute_gec_payroll_can_pay(self):
        """Show the button only while a validated payslip still has an open salary or authority leg."""
        for run in self:
            # sudo: payroll users may lack access to journal items.
            run.gec_payroll_can_pay = any(slip.state == 'validated' and slip.sudo()._gec_payroll_has_open_legs() for slip in run.slip_ids)

    def action_gec_pay_salaries(self):
        """Pay the run's validated payslips that still have an open salary or authority leg."""
        self.ensure_one()
        payable = self.slip_ids.filtered(lambda slip: slip.state == 'validated' and slip.sudo()._gec_payroll_has_open_legs())
        if not payable:
            raise UserError(_("This pay run has no confirmed payslip left to pay."))
        return payable.action_gec_pay_salaries()

    def action_gec_payroll_view_batches(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Payment Batches"),
            'res_model': 'account.batch.payment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.gec_payroll_batch_ids.ids)],
        }

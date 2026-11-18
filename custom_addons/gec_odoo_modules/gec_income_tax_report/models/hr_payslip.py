from odoo import models
from odoo.tools import float_is_zero


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_payslip_unpaid(self):
        """Post a note when a payslip already in an exported Form 30 is
        marked unpaid, since paying it again would declare it twice."""
        # sudo: payroll users may not read Form 30 rows; only the note data is read from them
        lines = self.env['rs.form30.line'].sudo().search([('payslip_id', 'in', self._rs_form30_family().ids), ('in_file', '=', True)])
        res = super().action_payslip_unpaid()
        for payslip in self:
            family = payslip._rs_form30_family()
            for declaration in lines.filtered(lambda line: line.payslip_id in family).declaration_id:
                payslip.message_post(body=self.env._("This payslip is in the exported Form 30 of %(period)s: if it is paid again, correct that "
                    "declaration.", period=declaration.date_from.strftime('%Y/%m')), subtype_xmlid='mail.mt_note')
        return res

    def _rs_form30_family_root(self):
        self.ensure_one()
        # sudo: accountants have no payroll access; only the origin links are followed
        root = self.sudo()
        while root.origin_payslip_id:
            root = root.origin_payslip_id
        return root

    def _rs_form30_family(self):
        """Return each root payslip with all its refunds and corrections."""
        # sudo: accountants have no payroll access; only the origin links are followed
        family = self.sudo().browse()
        for slip in self:
            family |= slip._rs_form30_family_root()
        children = family.related_payslip_ids
        while children - family:
            family |= children
            children = family.related_payslip_ids
        return family

    def _rs_form30_net_lines(self):
        """Return the posted credit lines that owe the net pay: lines
        on the NET account, else the employee's reconcilable line."""
        self.ensure_one()
        # sudo: accountants have no payroll access; only the entry lines of the slip are read
        slip = self.sudo()
        if slip.move_id.state != 'posted':
            return self.env['account.move.line']
        net_account = slip._gec_net_account()
        net_lines = slip.move_id.line_ids.filtered(lambda line: line.credit > 0 and line.account_id == net_account)
        if net_lines:
            return net_lines
        rounding = slip.company_id.currency_id.rounding
        return slip.move_id.line_ids.filtered(
            lambda line: line.credit > 0 and line.account_id.reconcile
            and line.partner_id == slip.employee_id.work_contact_id
            and float_is_zero(-line.balance - slip.net_wage, precision_rounding=rounding))[:1]

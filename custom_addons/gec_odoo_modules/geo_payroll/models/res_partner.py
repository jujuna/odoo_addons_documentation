from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    pension_fund_member = fields.Boolean(string='Pension Fund Member', tracking=True,
        help="Takes part in the Georgian funded pension scheme; always the same as on the linked employee.")

    def write(self, vals):
        result = super().write(vals)
        if 'pension_fund_member' in vals and not self.env.context.get('gec_pension_sync'):
            # sudo: the editor is usually an accountant without HR rights
            employees = self.sudo().employee_ids.filtered(lambda employee: employee.pension_fund_member != vals['pension_fund_member'])
            employees.with_context(gec_pension_sync=True).write({'pension_fund_member': vals['pension_fund_member']})
        if 'country_id' in vals:
            companies = self.env['res.company'].sudo().search([('partner_id', 'in', self.ids)])
            if companies:
                self.env['resource.calendar.leaves']._gec_remove_foreign_public_holidays(companies)
                self.env['hr.payroll.structure.type']._gec_fix_foreign_default_work_entry_type()
        return result

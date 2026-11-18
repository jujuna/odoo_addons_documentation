from odoo import fields, models


class PlanningSend(models.TransientModel):
    _inherit = 'planning.send'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, store=False, export_string_translation=False)
    sending_medium = fields.Selection(related="company_id.planning_medium")

    def _get_employee_contact_skipped_message(self):
        if self.sending_medium != "whatsapp":
            return super()._get_employee_contact_skipped_message()
        return self.env._("Shifts published: employees without a work phone number were skipped")

    def action_check_emails(self):
        if self.sending_medium != "whatsapp":
            return super().action_check_emails()

        if self.employees_no_email and self.employee_ids.has_access('write'):
            return {
                'name': self.env._('Some employees are missing a work phone number'),
                'view_mode': 'form',
                'res_model': 'planning.send',
                'views': [(self.env.ref('planning.employee_no_email_list_wizard').id, 'form')],
                'type': 'ir.actions.act_window',
                'res_id': self.id,
                'target': 'new',
            }
        return self.action_send()

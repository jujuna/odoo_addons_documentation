from datetime import datetime
from odoo.tools import format_date
from odoo import models
from odoo.exceptions import UserError


class PlanningPlanning(models.Model):
    _inherit = 'planning.planning'

    def _send_planning(self, slots, message=None, employees=False):
        if self.company_id.planning_medium != 'whatsapp':
            return super()._send_planning(slots, message, employees)

        template = self.company_id.wa_template_schedule_published
        if not template:
            raise UserError(self.env._("Can't send whatsapp message as the needed template is not present"))
        if template.status != 'approved':
            raise UserError(self.env._("Can't send whatsapp message as the needed template has not been approved"))

        employees_sudo = employees.sudo()
        employee_url_map = employees_sudo._planning_get_url(self.date_start, self.date_end)
        ics_url_per_employee_id = {
            e.id: f'/planning/{self.access_token}/{e.employee_token}.ics'
            for e in employees_sudo
        }

        ## /!\ For security reason, we only make message models for public employees
        first_start_date = {}
        last_end_date = {}
        for slot in slots:
            # sudo: hr.employee - can read the employees of the shifts to send them their own dates
            for employee in slot.sudo().employee_ids:
                if employee.id not in first_start_date:
                    first_start_date[employee.id] = slot.start_datetime
                    last_end_date[employee.id] = slot.end_datetime
                    continue
                first_start_date[employee.id] = min(first_start_date[employee.id], slot.start_datetime)
                last_end_date[employee.id] = max(last_end_date[employee.id], slot.end_datetime)

        for employee in employees:
            if employee.id not in first_start_date:
                first_start_date[employee.id] = self.date_start
                last_end_date[employee.id] = self.date_end
        public_employees = self.env['hr.employee.public'].browse(employees.ids)
        if self.allow_self_unassign:
            unassign_message = self.env._(
                "If you are unable to work an assigned shift please unassign yourself at least %s day(s) before the shift starts.",
                self.company_id.planning_self_unassign_days_before,
            )
        else:
            unassign_message = self.env._(
                "If you need to change a shift, please contact your colleagues to request a shift exchange.",
            )
        batch_mode = len(public_employees.employee_id._get_related_partners().ids) > 1
        composers = self.env["whatsapp.composer"].create(
            [
                {
                    "res_model": "res.partner",
                    "res_ids": employee._get_related_partners().ids,
                    "batch_mode": batch_mode,
                    "wa_template_id": template.id,
                    "free_text_1": format_date(
                        self.env,
                        datetime(
                            first_start_date[employee.id].year,
                            first_start_date[employee.id].month,
                            first_start_date[employee.id].day,
                        ),
                    ),
                    "free_text_2": format_date(
                        self.env,
                        datetime(
                            last_end_date[employee.id].year,
                            last_end_date[employee.id].month,
                            last_end_date[employee.id].day,
                        ),
                    ),
                    "free_text_3": unassign_message,
                    "free_text_4": (
                        self.get_base_url() + employee_url_map[employee.id]
                        if employee.id in employee_url_map
                        else "/"
                    ),
                    "button_dynamic_url_1": ics_url_per_employee_id[employee.id],
                }
                for employee in public_employees.employee_id
            ],
        )
        message_vals = [
            vals for composer in composers for vals in composer._create_whatsapp_messages_values()
        ]
        for wa_message in self.env["whatsapp.message"].create(message_vals):
            wa_message._send()

        # mark as sent
        return slots.write({
            'state': '2_published',
            'publication_warning': False,
        })

from odoo import models
from odoo.tools import format_datetime
from odoo.exceptions import UserError


class PlanningSlot(models.Model):
    _inherit = 'planning.slot'

    def _send_slot(self, employees, start_datetime, end_datetime, include_unassigned=True, message=None):
        if self.company_id.planning_medium != 'whatsapp':
            return super()._send_slot(employees, start_datetime, end_datetime, include_unassigned, message)

        if not include_unassigned:
            self = self.filtered("resource_ids")  # noqa: PLW0642
        if not self:
            return False
        self.ensure_one()

        employee_url_map = employees._planning_get_url(start_datetime.date(), end_datetime.date())
        cal_url = self._get_slot_resource_urls()

        if self.employee_public_ids:
            template = self.company_id.wa_template_assigned_shift
        else:
            template = self.company_id.wa_template_open_shift_available

        if not template:
            raise UserError(self.env._("Can't send whatsapp message as the needed template is not present"))
        if template.status != 'approved':
            raise UserError(self.env._("Can't send whatsapp message as the needed template has not been approved"))

        date_line = self.env._("%(start)s → %(end)s", start=format_datetime(self.env, self.start_datetime), end=format_datetime(self.env, self.end_datetime))
        role_line = self.role_id.name if self.role_id else "/"
        project_line = self.project_id.name if hasattr(self, "project_id") and self.project_id else "/"
        task_line = self.task_id.name if hasattr(self, "task_id") and self.task_id else "/"
        sol_line = self.sale_line_id.name if hasattr(self, "sale_line_id") and self.sale_line_id else "/"
        if self.env.company.planning_employee_unavailabilities == 'switch':
            unassign_message = self.env._("If you need to change a shift, please contact your colleagues to request a shift exchange.")
        else:
            unassign_message = self.env._("If you are unable to work an assigned shift please unassign yourself at least %s day(s) before the shift starts.", self.env.company.planning_self_unassign_days_before)

        batch_mode = len(employees._get_related_partners().ids) > 1
        link_per_employee_id = {
            employee_id: self.get_base_url() + path
            for employee_id, path in employee_url_map.items()
        }
        composers = self.env["whatsapp.composer"].create(
            [
                {
                    "res_model": "res.partner",
                    "free_text_1": date_line,
                    "free_text_2": role_line,
                    "free_text_3": project_line,
                    "free_text_4": task_line,
                    "free_text_5": sol_line,
                    "free_text_6": self.name or "/",
                    "free_text_7": link,
                    "free_text_8": unassign_message,
                    "button_dynamic_url_1": "?" + cal_url["google_url"].split("?")[1],
                    "res_ids": link_employees._get_related_partners().ids,
                    "batch_mode": batch_mode,
                    "wa_template_id": template.id,
                }
                for link, link_employees in employees.grouped(
                    lambda employee: link_per_employee_id.get(employee.id, "/"),
                ).items()
            ],
        )
        message_vals = [
            vals for composer in composers for vals in composer._create_whatsapp_messages_values()
        ]
        self.env["whatsapp.message"].create(message_vals)._send()

        self.write({
            'state': '2_published',
            'publication_warning': False,
        })
        return None

    def _send_shift_assigned(self, human_resource):
        if self.company_id.planning_medium != 'whatsapp':
            return super()._send_shift_assigned(human_resource)

        # sudo: hr.employee - can read the employees of the shift to warn the previous ones
        old_assignees = self.sudo().employee_ids.filtered(
            lambda employee: employee.resource_id not in human_resource,
        )
        reassign_names = ", ".join(human_resource.mapped("name"))
        if not old_assignees:
            return False
        template = self.company_id.wa_template_shift_reassigned
        if not template:
            raise UserError(self.env._("Can't send whatsapp message as the needed template is not present"))
        if template.status != 'approved':
            raise UserError(self.env._("Can't send whatsapp message as the needed template has not been approved"))

        url_map = old_assignees._planning_get_url(self.start_datetime.date(), self.end_datetime.date())

        date_line = self.env._("%(start)s → %(end)s", start=format_datetime(self.env, self.start_datetime), end=format_datetime(self.env, self.end_datetime))
        role_line = self.role_id.name if self.role_id else "/"
        project_line = self.project_id.name if hasattr(self, "project_id") and self.project_id else "/"
        task_line = self.task_id.name if hasattr(self, "task_id") and self.task_id else "/"
        sol_line = self.sale_line_id.name if hasattr(self, "sale_line_id") and self.sale_line_id else "/"
        batch_mode = len(old_assignees._get_related_partners().ids) > 1
        link_per_employee_id = {
            employee_id: self.get_base_url() + path for employee_id, path in url_map.items()
        }
        composers = self.env["whatsapp.composer"].create(
            [
                {
                    "res_model": "res.partner",
                    "free_text_1": reassign_names,
                    "free_text_2": date_line,
                    "free_text_3": role_line,
                    "free_text_4": project_line,
                    "free_text_5": task_line,
                    "free_text_6": sol_line,
                    "free_text_7": self.name or "/",
                    "free_text_8": link,
                    "res_ids": link_employees._get_related_partners().ids,
                    "batch_mode": batch_mode,
                    "wa_template_id": template.id,
                }
                for link, link_employees in old_assignees.grouped(
                    lambda employee: link_per_employee_id.get(employee.id, "/"),
                ).items()
            ],
        )
        message_vals = [
            vals for composer in composers for vals in composer._create_whatsapp_messages_values()
        ]
        self.env["whatsapp.message"].create(message_vals)._send()

    def _get_employee_contact_field(self):
        return 'work_phone' if self.company_id.planning_medium == 'whatsapp' else super()._get_employee_contact_field()

    def _get_employee_contact_missing_fields_form_view_ref(self):
        return 'whatsapp_planning.hr_employee_view_form_phone' if self.company_id.planning_medium == 'whatsapp' else super()._get_employee_contact_missing_fields_form_view_ref()

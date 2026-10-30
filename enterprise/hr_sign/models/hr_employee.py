# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    sign_request_ids = fields.Many2many(
        'sign.request', string='Requested Signatures', groups="hr.group_hr_user")
    sign_request_count = fields.Integer(
        compute="_compute_sign_request_count",
        groups="hr.group_hr_manager",
    )

    def _get_employee_signatory_sign_items(self, partners):
        employee_role = self.env.ref('hr_sign.sign_item_role_employee_signatory', raise_if_not_found=False)
        if not partners or not employee_role:
            return self.env['sign.request.item']
        return self.env['sign.request.item'].search_fetch(
            [
                ('partner_id', 'in', partners.ids),
                ('role_id', '=', employee_role.id),
            ],
            ['partner_id', 'sign_request_id'],
        )

    def _compute_sign_request_count(self):
        contracts_per_employee = self.env['hr.version'].sudo().search([('employee_id', 'in', self.ids)]).grouped('employee_id')
        sign_items_per_partner = self._get_employee_signatory_sign_items(
            self.user_id.partner_id | self.work_contact_id).grouped('partner_id')
        for employee in self:
            contracts = contracts_per_employee.get(employee, self.env['hr.version'])
            sign_from_contract = contracts.mapped('sign_request_ids')

            sign_from_role = self.env['sign.request'].browse([])
            partners = employee.user_id.partner_id | employee.work_contact_id
            for partner in partners:
                sign_from_role |= sign_items_per_partner.get(partner, self.env['sign.request.item']).sign_request_id
            employee.sign_request_count = len(set(sign_from_contract + sign_from_role + employee.sign_request_ids))

    def open_employee_sign_requests(self):
        self.ensure_one()
        contracts = self.env['hr.version'].sudo().search([('employee_id', '=', self.id)])
        sign_from_contract = contracts.mapped('sign_request_ids')
        sign_from_role = self._get_employee_signatory_sign_items(self.user_id.partner_id | self.work_contact_id).sign_request_id
        sign_request_ids = sign_from_contract + sign_from_role + self.sign_request_ids
        if len(sign_request_ids.ids) == 1:
            return sign_request_ids.go_to_document()

        if self.env.user.has_group('sign.group_sign_user'):
            view_id = self.env.ref("sign.sign_request_view_kanban").id
        else:
            view_id = self.env.ref("hr_sign.sign_request_employee_view_kanban").id

        return {
            'type': 'ir.actions.act_window',
            'name': 'Signature Requests',
            'view_mode': 'kanban,list',
            'res_model': 'sign.request',
            'view_ids': [(view_id, 'kanban'), (False, 'list')],
            'domain': [('id', 'in', sign_request_ids.ids)]
        }

    def _open_sign_document_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Signature Request'),
            'res_model': 'hr.contract.sign.document.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_version_id': self.version_id.id,
            },
        }

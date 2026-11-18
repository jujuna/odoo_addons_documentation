# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrContractSignatory(models.Model):
    _name = 'hr.contract.signatory'
    _description = 'Contract Signatories'

    sign_role_id = fields.Many2one('sign.item.role', string="Contract Role")
    signatory = fields.Selection([('employee', 'Employee'), ('hr', 'HR Responsible'), ('partner', 'Specific Partner')], string="Signatory")
    partner_id = fields.Many2one('res.partner', copy=True)
    contract_template_id = fields.Many2one('hr.version', index='btree_not_null')
    update_contract_template_id = fields.Many2one('hr.version', index='btree_not_null')
    offer_id = fields.Many2one('hr.contract.salary.offer', index='btree_not_null')
    order = fields.Integer('Sign Order', required=True)

    @api.model
    def create_empty_signatories(self, sign_template):
        """Return the commands creating one signatory per role of the sign template.

        The *Employee* role is signed by the employee, any other role by the HR responsible,
        all in order 1.

        :param sign_template: ``sign.template`` record
        :return: x2many commands replacing the signatories
        :rtype: list
        """
        roles = set(sign_template.sign_item_ids.responsible_id.ids)

        role_dict = {
            self.env.ref('hr_sign.sign_item_role_employee_signatory').id: 'employee',
            self.env.ref('hr_sign.sign_item_role_job_responsible').id: 'hr',
        }

        return [(5, 0, 0)] + [(0, 0, {
            'sign_role_id': role,
            'signatory': role_dict.get(role, 'hr'),
            'order': 1
        }) for role in roles]

    @api.constrains('signatory', 'partner_id')
    def _ensure_partner(self):
        for signatory in self:
            if not signatory.signatory or signatory.signatory == 'partner' and not signatory.partner_id:
                raise ValidationError(_('A signatory role is unassigned. Please ensure there is a valid group or person assigned to each role.'))

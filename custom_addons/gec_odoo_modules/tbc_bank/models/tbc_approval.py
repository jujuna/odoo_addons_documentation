from odoo import fields, models


class TbcApproval(models.Model):
    _name = 'tbc.approval'
    _description = 'TBC Bank Approver'
    _inherit = ['gec.bank.approval.mixin']

    delegate_ids = fields.Many2many('res.users', relation='tbc_approval_delegate_rel', column1='approval_id', column2='user_id', string='Delegates',
        domain="[('share', '=', False)]")

from odoo import fields, models


class BogApproval(models.Model):
    _name = 'bog.approval'
    _description = 'Bank Of Georgia Approver'
    _inherit = ['gec.bank.approval.mixin']

    delegate_ids = fields.Many2many(
        'res.users', relation='bog_approval_delegate_rel', column1='approval_id', column2='user_id',
        string='Delegates', domain="[('share', '=', False)]")

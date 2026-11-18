from odoo import fields, models


class BasisbankApproval(models.Model):
    _name = 'basisbank.approval'
    _description = 'Basis Bank Approver'
    _inherit = ['gec.bank.approval.mixin']

    delegate_ids = fields.Many2many('res.users', relation='basisbank_approval_delegate_rel', column1='approval_id', column2='user_id',
        string='Delegates', domain="[('share', '=', False)]")

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class GecBankApprovalMixin(models.AbstractModel):
    """Who may approve a bank's transfers: one primary approver and delegates.
    Each bank has its own approver model and redeclares ``delegate_ids`` with its own relation table."""

    _name = 'gec.bank.approval.mixin'
    _description = 'Bank Approver Mixin'
    _order = 'id desc'

    name = fields.Char(compute='_compute_name', store=True)
    approver_id = fields.Many2one(
        'res.users', string='Primary Approver', required=True, ondelete='restrict',
        domain="[('share', '=', False)]")
    delegate_ids = fields.Many2many(
        'res.users', string='Delegates', domain="[('share', '=', False)]")
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company,
        index=True)
    active = fields.Boolean(string='Active', default=True)

    @api.depends('approver_id.display_name')
    def _compute_name(self):
        for record in self:
            record.name = record.approver_id.display_name or _('New Approver')

    @api.constrains('approver_id', 'delegate_ids')
    def _check_approver_not_delegate(self):
        for record in self:
            if record.approver_id in record.delegate_ids:
                raise ValidationError(_(
                    "Primary Approver cannot also be a delegate. Remove from the Delegates."))

    def approver_user_ids(self):
        self.ensure_one()
        return self.approver_id | self.delegate_ids

    def user_can_approve(self, user):
        self.ensure_one()
        return user in self.approver_user_ids()

    def _gec_bank_check_approver(self, record, allow_self_approval, bank_label):
        """Approval rule of every bank: an approver of this connection who neither created the transfer nor last
        changed its amount, recipient or purpose, unless the connection allows self-approval."""
        user = self.env.user
        if not self or not self.user_can_approve(user):
            raise UserError(_("You are not authorized to approve %s transfers.", bank_label))
        makers = record.create_uid
        if 'gec_bank_prepared_by' in record._fields:
            makers |= record.gec_bank_prepared_by
        if user in makers and not allow_self_approval:
            raise UserError(_(
                "You created this transfer or changed its amount, recipient or purpose, so you cannot "
                "approve it. Ask another approver, or enable 'Allow Self-Approval' on the %s connection "
                "if your team has no second person.", bank_label))

from odoo import models, fields, _


class GecAllocationPreview(models.TransientModel):
    """What a run would do, held long enough to be read and then thrown away."""
    _name = 'gec.allocation.preview'
    _description = 'Allocation Dry Run'

    run_id = fields.Many2one('gec.allocation.run', required=True, readonly=True)
    currency_id = fields.Many2one(related='run_id.company_id.currency_id')

    log = fields.Text(string='What Each Rule Would Do', readonly=True)
    driver_warning = fields.Text(string='Driver Warnings', readonly=True)
    line_count = fields.Integer(string='Lines', readonly=True)
    allocated_amount = fields.Monetary(string='Would Move', readonly=True)
    line_ids = fields.One2many(
        'gec.allocation.preview.line', 'preview_id', readonly=True,
    )

    def action_confirm(self):
        """Do it for real. The preview is the confirmation step."""
        self.ensure_one()
        self.run_id.action_compute()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'gec.allocation.run',
            'res_id': self.run_id.id,
            'view_mode': 'form',
            'name': _("Allocation Run"),
        }


class GecAllocationPreviewLine(models.TransientModel):
    _name = 'gec.allocation.preview.line'
    _description = 'Allocation Dry Run Line'
    _order = 'amount'

    preview_id = fields.Many2one(
        'gec.allocation.preview', required=True, ondelete='cascade', index=True,
    )
    currency_id = fields.Many2one(related='preview_id.currency_id')

    name = fields.Char(readonly=True)
    date = fields.Date(readonly=True)
    analytic_label = fields.Char(
        string='Analytic Accounts', readonly=True,
        help="Every analytic account the line would be tagged with, across all "
             "plans — the contra keeps the source's tags, the targets carry the "
             "target plan's.",
    )
    general_account_id = fields.Many2one(
        'account.account', string='GL Account', readonly=True,
    )
    kind = fields.Selection(
        [('contra', 'Contra'), ('target', 'Target')], readonly=True,
    )
    amount = fields.Monetary(readonly=True)

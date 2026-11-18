from odoo import fields, models


class RsBuyerInboxWizard(models.TransientModel):
    _inherit = 'rs.einvoice.inbox.wizard'

    rs_spec = fields.Boolean(string='Petroleum (ნსაფ)')

    def action_search(self):
        return super(RsBuyerInboxWizard, self.with_context(rs_spec_inbox=self.rs_spec)).action_search()


class RsBuyerInboxLine(models.TransientModel):
    _inherit = 'rs.einvoice.inbox.line'

    def _do_import(self, Move, purchase_journal):
        if self.wizard_id.rs_spec:
            Move = Move.with_context(default_rs_einv_is_spec=True)
        return super()._do_import(Move, purchase_journal)

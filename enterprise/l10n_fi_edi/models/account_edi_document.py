from odoo import fields, models


class AccountEdiDocument(models.Model):
    _inherit = 'account.edi.document'

    l10n_fi_document_identifier = fields.Char(
        string="Key for the document",
        readonly=True,
    )
    # We store the move_id.state for now as we don't have the connection to the edi yet, once we will integrate it, we will replace
    # this field with the edi state.
    l10n_fi_edi_state = fields.Selection(
        related='move_id.state',
        store=True,
    )
    l10n_fi_date = fields.Datetime(
        string="Request Date",
        default=fields.Datetime.now,
        readonly=True,
    )

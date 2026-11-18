from odoo import models


class AccountMoveSend(models.AbstractModel):
    _inherit = 'account.move.send'

    def _get_placeholder_mail_attachments_data(self, move, invoice_edi_format=None, extra_edis=None, pdf_report=None) -> list[dict]:
        # EXTENDS 'account'
        results = super()._get_placeholder_mail_attachments_data(move, invoice_edi_format=invoice_edi_format, extra_edis=extra_edis, pdf_report=pdf_report)

        if move.partner_id.invoice_edi_format == 'finvoice' and not move.edi_document_ids.filtered(lambda doc: doc.edi_format_id.code == 'finvoice'):
            filename = f"{move.name}_finvoice.xml".replace('/', '_')
            results.append({
                'id': f'placeholder_{filename}',
                'name': filename,
                'mimetype': 'application/xml',
                'placeholder': True,
            })

        return results

    def _call_web_service_before_invoice_pdf_render(self, invoices_data):
        # EXTENDS 'account'
        super()._call_web_service_before_invoice_pdf_render(invoices_data)

        for invoice, invoice_data in invoices_data.items():
            if invoice_data['invoice_edi_format'] == 'finvoice':
                invoice._l10n_fi_edi_create_edi_document()

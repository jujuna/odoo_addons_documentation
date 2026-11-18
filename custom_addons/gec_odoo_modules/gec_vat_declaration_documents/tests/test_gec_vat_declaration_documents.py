import io
from datetime import date

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged
from odoo.tools import file_open

CUSTOMS_FONT = 'gec_vat_declaration/tests/NotoSansGeorgian-Regular.ttf'


def customs_pdf(number, issued):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for x, y, font, text in [
        (400, 806, 'NotoGeorgian', 'გაფორმების საგადასახადო ორგანო'), (400, 794, 'Helvetica', '11111'),
        (329, 210, 'NotoGeorgian', 'შეფასების'), (386, 209, 'Helvetica', number),
        (485, 210, 'NotoGeorgian', 'თარ.'), (513, 209, 'Helvetica', issued),
        (329, 153, 'NotoGeorgian', 'გადახდილია სულ'), (453, 152, 'Helvetica', '100.00'),
        (485, 153, 'NotoGeorgian', 'ლარი'),
    ]:
        pdf.setFont(font, 7)
        pdf.drawString(x, y, text)
    pdf.save()
    return buffer.getvalue()


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestGecVatDeclarationDocuments(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country('ge')
    def setUpClass(cls):
        super().setUpClass()
        with file_open(CUSTOMS_FONT, 'rb') as font:
            pdfmetrics.registerFont(TTFont('NotoGeorgian', font))
        cls.declaration = cls.env['gec.vat.declaration'].create({'date_from': '2026-09-01'})
        cls.folder_customs = cls.env.ref('gec_vat_declaration_documents.folder_customs')
        cls.folder_form4 = cls.env.ref('gec_vat_declaration_documents.folder_form4')

    def _link(self, attachment):
        attachment.write({
            'res_model': 'gec.vat.declaration', 'res_id': self.declaration.id,
            'company_id': self.declaration.company_id.id})
        return self.env['documents.document'].search([('attachment_id', '=', attachment.id)])

    def _drop(self, number, issued, created='2026-09-10 08:00:00', mimetype='application/pdf', raw=None):
        """A PDF dropped in the customs folder in Documents, uploaded at `created` (UTC)."""
        document = self.env['documents.document'].create({
            'name': '%s.pdf' % number, 'raw': raw or customs_pdf(number, issued), 'mimetype': mimetype,
            'folder_id': self.folder_customs.id})
        self.env.flush_all()
        self.env.cr.execute("UPDATE documents_document SET create_date = %s WHERE id = %s", (created, document.id))
        document.invalidate_recordset(['create_date'])
        return document

    def _generate(self):
        declaration = self.declaration.with_context(tz='Asia/Tbilisi')
        declaration.action_generate()
        return sorted(declaration.customs_line_ids.mapped('assessment_number'))

    def test_linked_pdf_becomes_a_document(self):
        attachment = self.env['ir.attachment'].create(
            {'name': 'customs.pdf', 'raw': b'%PDF-1.4', 'mimetype': 'application/pdf'})
        document = self._link(attachment)
        self.assertEqual(len(document), 1)
        self.assertEqual(document.folder_id, self.folder_customs)
        self.assertEqual(document.company_id, self.declaration.company_id)
        self.assertEqual(document.access_internal, 'view')

    def test_form4_row_pdf_goes_to_the_form4_folder(self):
        for pdf_type, folder in (('customs', self.folder_customs), ('form4', self.folder_form4)):
            attachment = self.env['ir.attachment'].create(
                {'name': '%s.pdf' % pdf_type, 'raw': b'%PDF-1.4', 'mimetype': 'application/pdf'})
            self.env['gec.vat.customs.line'].create(
                {'declaration_id': self.declaration.id, 'pdf_type': pdf_type, 'attachment_id': attachment.id})
            self.assertEqual(self._link(attachment).folder_id, folder)

    def test_generate_pulls_pdfs_by_date_and_upload_time(self):
        self._drop('A1', '10/09/2026')
        self._drop('A2', '12/09/2026', created='2026-10-15 19:30:00')
        self._drop('A3', '12/09/2026', created='2026-10-15 20:30:00')
        self._drop('A4', '10/10/2026')
        self.assertEqual(self._generate(), ['A1', 'A2'])
        row = self.declaration.customs_line_ids.filtered(lambda line: line.assessment_number == 'A1')
        self.assertEqual(row.assessment_date, date(2026, 9, 10))

    def test_generate_does_not_pull_a_pdf_twice(self):
        self._drop('A1', '10/09/2026')
        self.assertEqual(self._generate(), ['A1'])
        self.assertEqual(self._generate(), ['A1'])

    def test_generate_does_not_pull_a_new_version_of_a_pulled_pdf(self):
        document = self._drop('A1', '10/09/2026')
        self.assertEqual(self._generate(), ['A1'])
        new_version = self.env['ir.attachment'].create(
            {'name': 'A9.pdf', 'raw': customs_pdf('A9', '11/09/2026'), 'mimetype': 'application/pdf'})
        document.write({'attachment_id': new_version.id})
        self.assertEqual(self._generate(), ['A1'])

    def test_generate_does_not_pull_a_pdf_of_an_unrelated_company(self):
        document = self._drop('A1', '10/09/2026')
        document.attachment_id.company_id = self.setup_other_company()['company']
        self.assertEqual(self._generate(), [])

    def test_generate_does_not_pull_a_pdf_already_uploaded_on_a_row(self):
        pdf = customs_pdf('A1', '10/09/2026')
        attachment = self.env['ir.attachment'].create({'name': 'uploaded.pdf', 'raw': pdf, 'mimetype': 'application/pdf'})
        self.env['gec.vat.customs.line'].create({
            'declaration_id': self.declaration.id, 'pdf_type': 'customs', 'attachment_id': attachment.id,
            'assessment_number': 'A1'})
        self._link(attachment)
        self._drop('A1', '10/09/2026', raw=pdf)
        self.assertEqual(self._generate(), ['A1'])

    def test_generate_pulls_a_pdf_with_a_generic_mimetype(self):
        self._drop('A1', '10/09/2026', mimetype='application/octet-stream')
        self.assertEqual(self._generate(), ['A1'])

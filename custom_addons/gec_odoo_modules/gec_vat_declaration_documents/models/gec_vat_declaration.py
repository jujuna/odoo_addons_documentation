from datetime import datetime, time

from dateutil.relativedelta import relativedelta

from odoo import models
from odoo.fields import Domain
from odoo.addons.gec_vat_declaration.models.gec_vat_declaration import PDF_ERRORS, name_list
from odoo.tools.date_utils import to_timezone

FOLDER_CUSTOMS = 'gec_vat_declaration_documents.folder_customs'
FOLDER_FORM4 = 'gec_vat_declaration_documents.folder_form4'
FOLDERS = (FOLDER_CUSTOMS, FOLDER_FORM4)


class GecVatDeclaration(models.Model):
    _name = 'gec.vat.declaration'
    _inherit = ['gec.vat.declaration', 'documents.mixin']

    def _get_document_folder(self):
        return self.env.ref(FOLDER_CUSTOMS, raise_if_not_found=False)

    def _check_create_documents(self):
        """An archived folder refuses documents, which would break the upload on tab 6. Sudo: the user may not see the folder."""
        folder = self._get_document_folder()
        return bool(folder and folder.sudo().active) and super()._check_create_documents()

    def _get_document_vals_access_rights(self):
        """Internal users only view the filed PDF, so nobody removes a declaration's source by accident."""
        return {'access_internal': 'view', 'is_access_via_link_hidden': True}

    def _get_document_vals(self, attachment):
        """The folders are global: the document takes the declaration's company; a Form 4 row goes to its own folder."""
        vals = super()._get_document_vals(attachment)
        if not vals:
            return vals
        vals['company_id'] = self.company_id.id
        form4 = self.env.ref(FOLDER_FORM4, raise_if_not_found=False)
        if form4 and form4.active and self.env['gec.vat.customs.line'].search_count(
                [('attachment_id', '=', attachment.id), ('pdf_type', '=', 'form4')]):
            vals['folder_id'] = form4.id
        return vals

    def action_generate(self):
        self.check_access('write')
        skipped = {decl: decl._gec_pull_documents() for decl in self.filtered(lambda decl: decl.state == 'draft')}
        result = super().action_generate()
        for declaration, names in skipped.items():
            if names:
                warning = self.env._("B III: %(names)s in Documents cannot be read or show no date; type their rows by hand.",
                    names=name_list(self.env, names))
                declaration.scan_warnings = '\n'.join(filter(None, [declaration.scan_warnings, warning]))
        return result

    def _gec_pull_documents(self):
        """Add a row for each PDF dropped in the two folders in Documents, dated in the month and uploaded by the 15th
        of the next month. Sudo: accountants may lack Documents rights, and a row's PDF may be another user's; the
        attachment company is the uploader's, so any company of the declaration's same-VAT subtree counts."""
        self.ensure_one()
        documents = self.env['documents.document'].sudo()
        refs = [documents.env.ref(xmlid, raise_if_not_found=False) for xmlid in FOLDERS]
        folders = documents.browse([folder.id for folder in refs if folder and folder.active])
        to_utc = to_timezone(None)
        start = datetime.combine(self.date_from, time.min, tzinfo=self.env.tz)
        end = datetime.combine(self.date_from + relativedelta(months=1, day=16), time.min, tzinfo=self.env.tz)
        in_folders = Domain.OR([Domain('folder_id', 'child_of', folder.id) for folder in folders])
        is_pdf = Domain('mimetype', 'in', ('application/pdf', 'application/x-pdf')) | Domain('name', '=ilike', '%.pdf')
        documents = documents.search(Domain([
            ('res_model', '=', False),
            ('shortcut_document_id', '=', False),
            ('attachment_id', '!=', False),
            ('attachment_id.company_id', 'in', self.company_id._gec_vat_companies().ids),
            ('create_date', '>=', to_utc(start)),
            ('create_date', '<', to_utc(end)),
        ]) & in_folders & is_pdf)
        known = self.customs_line_ids.sudo().attachment_id
        checksums = set(known.mapped('checksum'))
        rows = []
        skipped = []
        for document in documents:
            attachment = document.attachment_id
            if (attachment | document.previous_attachment_ids) & known or attachment.checksum in checksums:
                continue
            try:
                parsed = self._gec_parse_pdf(attachment.raw.content)
            except PDF_ERRORS:
                skipped.append(attachment.name)
                continue
            if not parsed['assessment_date']:
                skipped.append(attachment.name)
            elif self.date_from <= parsed['assessment_date'] <= self.date_to:
                rows.append(self._gec_customs_row_vals(attachment, parsed))
        self.env['gec.vat.customs.line'].create(rows)
        return skipped

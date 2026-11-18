from odoo import models
from odoo.exceptions import UserError

from odoo.addons.account_reports.models.account_report import AccountReportFileDownloadException


class AccountReturn(models.Model):
    _inherit = 'account.return'

    def _prepare_submission(self):
        # OVERRIDE
        if self.type_external_id == 'l10n_ma_reports.ma_tax_return_type':
            return self.env['l10n_ma_reports.vat.listing.submission.wizard']._open_submission_wizard(self)

        return super()._prepare_submission()

    def _generate_locking_attachments(self, options):
        # Extends account_reports
        super()._generate_locking_attachments(options)
        if self.type_external_id == 'l10n_ma_reports.ma_tax_return_type':
            try:
                file_data = self.type_id.report_id.dispatch_report_action(options, 'l10n_ma_reports_export_vat_to_xml')
            except AccountReportFileDownloadException as e:
                if blocking_errors := [error for error in e.errors.values() if error.get('level') == 'danger']:
                    raise UserError('\n'.join(error['message'] for error in blocking_errors))
                file_data = e.content
            self._add_attachment(file_data)

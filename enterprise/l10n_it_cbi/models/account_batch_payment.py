from odoo import fields, models
from odoo.exceptions import RedirectWarning, UserError
from odoo.tools import BinaryBytes


class AccountBatchPayment(models.Model):
    _inherit = "account.batch.payment"

    l10n_it_cbi_priority = fields.Selection(
        selection=[('HIGH', 'HIGH - High'), ('NORM', 'NORM - Normal')],
        string="Priority",
        default='NORM',
        help="Priority of the CBI Batch Payment"
    )

    def _get_methods_generating_files(self):
        return super()._get_methods_generating_files() + ['cbi_ct']

    def _generate_export_file(self):
        if self.payment_method_code != 'cbi_ct' or self.journal_id.company_id.country_code != "IT":
            return super()._generate_export_file()

        self._validate_cbi_sepa_requirements()

        xml_content = self.journal_id._create_cbi_credit_transfer_content(
            self.payment_ids,
            batch_booking=self['iso20022_batch_booking'] if 'iso20022_batch_booking' in self._fields else False,
            seq_num=str(self.id),
            batch_date=fields.Date.to_string(self.date),
            priority=self.l10n_it_cbi_priority,
        )

        cuc = self.journal_id.company_id.partner_id._get_additional_identifier('IT_CUC') or ""
        filename = f"{cuc}_{self.date:%Y%m%d}_{self.id}.xml"

        return {
            "file": BinaryBytes(xml_content.encode()),
            "filename": filename,
        }

    def _validate_cbi_sepa_requirements(self):
        self.ensure_one()
        journal = self.journal_id
        company = journal.company_id

        if not journal.bank_account_id or not journal.bank_account_id.account_number:
            action = journal._get_records_action(name=self.env._("Update journal"))
            msg = self.env._("Set a bank account on the journal %(journal)s to generate the CBI file.", journal=journal.name)
            raise RedirectWarning(msg, action, self.env._("Update journal"))

        cuc = company.partner_id._get_additional_identifier('IT_CUC')

        if not cuc:
            title = self.env._("Update Company")
            company_action_dict = company._get_records_action(name=title)
            msg = self.env._("The Company CUC code is required to generate the CBI file.")
            raise RedirectWarning(msg, company_action_dict, title)

        if self.date < fields.Date.context_today(self):
            raise UserError(self.env._("Execution date must be today or in the future."))

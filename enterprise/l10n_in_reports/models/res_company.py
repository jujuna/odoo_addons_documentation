# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_in_gstr_gst_username = fields.Char(string="GST User Name (IN)", groups="base.group_system")
    l10n_in_gstr_gst_token = fields.Char(string="GST Token (IN)", groups="base.group_system")
    l10n_in_gstr_gst_token_validity = fields.Datetime(string="GST Token (IN) Valid Until", groups="base.group_system")
    l10n_in_gstr_activate_einvoice_fetch = fields.Selection(
        string='Fetch Vendor E-Invoiced Documents',
        selection=[
            ('manual', 'Fetch Manually'),
            ('automatic', 'Fetch Automatically'),
        ],
        default='manual',
        help="""
            Fetch Manually - Invoices are created without lines but an IRN number, but there is a button to get the lines.
            Fetch Automatically - Existing documents with an IRN are automatically updated, and incoming documents are fetched and populated automatically."""
    )
    l10n_in_gst_efiling_feature = fields.Boolean(string="GST E-Filing & Matching Feature")
    l10n_in_fetch_vendor_edi_feature = fields.Boolean(string="Fetch Vendor E-Invoiced Document")
    l10n_in_enet_vendor_batch_payment_feature = fields.Boolean(string="ENet Vendor Batch Payment")

    def _is_l10n_in_gstr_token_valid(self):
        self.ensure_one()
        return (
            self.sudo().l10n_in_gstr_gst_token_validity
            and self.sudo().l10n_in_gstr_gst_token_validity > fields.Datetime.now()
        )

    def _l10n_in_set_active_return_and_report(self, return_types, reports, active):
        self.ensure_one()
        active_selection = 'True' if active else 'False'
        if return_types:
            return_types.with_company(self).filtered(lambda return_type: return_type.active_selection != active_selection).active_selection = active_selection
        if reports:
            reports.with_company(self).filtered(lambda report: report.active_selection != active_selection).active_selection = active_selection

    def _l10n_in_toggle_regular_and_composition_returns(self):
        regular_returns = self.env.ref('l10n_in_reports.in_gstr1_return_type') | self.env.ref('l10n_in_reports.in_gstr2b_return_type')
        regular_reports = self.env.ref('l10n_in_reports.account_report_gstr1') | self.env.ref('l10n_in_reports.account_report_gstr2b')\
            | self.env.ref('l10n_in_reports.account_report_gstr3b')
        composition_returns = self.env.ref('l10n_in_reports.in_cmp08_return_type') | self.env.ref('l10n_in_reports.in_gstr4_return_type')
        composition_reports = self.env.ref('l10n_in_reports.account_report_cmp_08') | self.env.ref('l10n_in_reports.account_report_gstr4')
        for company in self:
            registration_type = company.l10n_in_gst_registration_type
            company._l10n_in_set_active_return_and_report(regular_returns, regular_reports, registration_type == 'regular')
            company._l10n_in_set_active_return_and_report(composition_returns, composition_reports, registration_type == 'composition')

    def _l10n_in_toggle_iff_return(self):
        iff_return_type = self.env.ref('l10n_in_reports.in_gstr_iff_return_type')
        iff_report = self.env.ref('l10n_in_reports.account_report_gstr_iff')
        for company in self:
            is_iff_applicable = (
                company.account_fiscal_country_id.code == 'IN'
                and company.l10n_in_gst_registration_type == 'regular'
                and company.account_return_periodicity == 'trimester'
            )
            company._l10n_in_set_active_return_and_report(iff_return_type, iff_report, is_iff_applicable)

    def _inverse_l10n_in_gst_registration_type(self):
        super()._inverse_l10n_in_gst_registration_type()
        self._l10n_in_toggle_regular_and_composition_returns()
        self._l10n_in_toggle_iff_return()

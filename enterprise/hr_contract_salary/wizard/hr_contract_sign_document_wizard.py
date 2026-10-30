# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo import api, fields, models


class HrContractSignDocumentWizard(models.TransientModel):
    _inherit = 'hr.contract.sign.document.wizard'

    sign_template_ids = fields.Many2many(compute='_compute_sign_template_ids', store=True, readonly=False)

    @api.depends('version_id')
    def _compute_sign_template_ids(self):
        for wizard in self:
            version = wizard.version_id
            if not version:
                continue
            current_version = version.employee_id.current_version_id
            # A version of the current (or a past) contract is an amendment, not a new contract
            version_contract_start = version.contract_date_start or date.min
            current_contract_start = current_version.contract_date_start or date.min
            if (version == current_version or version_contract_start <= current_contract_start) and version.contract_update_template_id:
                wizard.sign_template_ids |= version.contract_update_template_id
            elif version_contract_start > current_contract_start and version.sign_template_id:
                wizard.sign_template_ids |= version.sign_template_id

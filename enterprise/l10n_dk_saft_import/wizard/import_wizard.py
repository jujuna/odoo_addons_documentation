# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import models

_DK_V2_JOURNAL_TYPE_MAP = {'GL': 'general', 'AR': 'sale', 'AP': 'purchase', 'AJ': 'bank'}


class AccountSaftImportWizard(models.TransientModel):
    """ SAF-T import wizard to import DK specific files """
    _inherit = 'account.saft.import.wizard'

    def _get_account_types(self):
        """ Returns a mapping between the account types accepted for the SAF-T and the types in Odoo """
        # Overrides
        if self.company_id.country_code != 'DK':
            return super()._get_account_types()
        return {
            'Asset': 'asset_current',
            'Liability': 'liability_current',
            'Sale': 'income',
            'Expense': 'expense',
            'Other': 'off_balance',
        }

    def _prepare_journal_data(self, tree, default_currency, map_accounts, map_taxes, map_currencies, map_partners):
        if self.company_id.country_code == 'DK' and self._get_saft_version(tree) == '2.0':
            nsmap = self._get_cleaned_namespace(tree)
            # Remap v2-restricted journal type codes to Odoo journal types.
            for journal_node in tree.findall('.//saft:Journal', namespaces=nsmap):
                type_node = journal_node.find('saft:Type', namespaces=nsmap)
                if type_node is not None and type_node.text in _DK_V2_JOURNAL_TYPE_MAP:
                    type_node.text = _DK_V2_JOURNAL_TYPE_MAP[type_node.text]

        return super()._prepare_journal_data(tree, default_currency, map_accounts, map_taxes, map_currencies, map_partners)

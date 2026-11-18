{
    'name': 'Georgia - Accounting Extensions (GEC)',
    'countries': ['ge'],
    'icon': '/account/static/description/l10n.png',
    'version': '20.0.1.3.0',
    'category': 'Accounting/Localizations',
    'author': 'GEC - Business Growth Services',
    'summary': 'Our accounts and taxes on top of Odoo\'s Georgian chart (l10n_ge), plus Georgian business helpers',
    'description': """
Extends Odoo's Georgian localization (l10n_ge, template ge) instead of replacing it:
extra accounts, withholding / turnover / CIT and other taxes Odoo does not ship, a
per-company withholding certificate sequence, partner default taxes and Not Taxed
products, a profit distribution (CIT) wizard, bank name and BIC filled from Georgian
IBANs, and user-managed contact categories.

The VAT declaration is Odoo's own l10n_ge VAT report.

Full documentation: README.md and README_DEV.md in the module directory.
""",
    'depends': [
        'l10n_ge',
        'account_edi_ubl_cii',
        'contacts',
        'l10n_account_withholding_tax',
        'sale',
        'purchase',
    ],
    'data': [
        'data/wht_sequence.xml',
        'views/res_partner_views.xml',
        'views/product_views.xml',
        'views/account_tax_views.xml',
        'views/cit_wizard_views.xml',
        'wizards/bill_pay_choice_views.xml',
        'views/account_move_views.xml',
        'views/account_payment_register_views.xml',
        'data/ge_tax_maintenance.xml',
        'data/res_partner_data.xml',
        'security/ir.access.csv',
    ],
    'post_init_hook': 'post_init',
    'license': 'LGPL-3',
}

{
    'name': 'Basis Bank Integration',
    'summary': 'Send transfers and import statements from Basis Bank (bis.bankonline.ge)',
    'description': """
Send outbound payments to Basis Bank (bis.bankonline.ge) with a Digipass OTP, alone or
in batches, and import account statements back into Odoo.

A bank journal is a Basis Bank journal when its bank account BIC is CBASGE22 and its
company, or a parent company, has a Basis Bank connection. A sent payment stays Paid
until its line in an imported bank statement is matched with it, and then becomes
Reconciled; a resync or the hourly 48-hour check only confirms that the bank has the
transfer. Standard Odoo posts the payments and creates the statement lines; this module
transmits the payments and records the bank's answer.

Full documentation: README.md and README_DEV.md in the module directory.
""",
    'version': '20.0.1.16.0',
    'category': 'Accounting/Payment',
    'author': 'GEC Business',
    'license': 'LGPL-3',
    'depends': [
        'account_accountant',
        'account_batch_payment',
        'account_bank_statement_import',
        'mail',
        'gec_localization',
        'gec_bank',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/basisbank_groups.xml',
        'data/basisbank_payment_method.xml',
        'data/ir_cron_data.xml',
        'views/basisbank_connection_views.xml',
        'views/basisbank_approval_views.xml',
        'views/basisbank_api_log_views.xml',
        'views/account_journal_views.xml',
        'views/account_payment_views.xml',
        'views/account_batch_payment_views.xml',
        'views/basisbank_wizard_views.xml',
        'views/basisbank_menus.xml',
        'security/ir.access.csv',
    ],
    'installable': True,
    'application': True,
}

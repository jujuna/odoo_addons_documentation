# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': "Italy - Point of Sale Sign IT - E-invoicing",
    'summary': 'Codice Fiscale of the company with fiskaly SIGN IT',
    'description': """
Bridge between the Italian Point of Sale fiscalization (fiskaly SIGN IT) and the Italian electronic invoicing.
The Codice Fiscale of the company is sent to fiskaly as its tax ID number.
""",
    'category': 'Accounting/Localizations/Point of Sale',
    'depends': ['l10n_it_pos_fiskaly', 'l10n_it_edi'],
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}

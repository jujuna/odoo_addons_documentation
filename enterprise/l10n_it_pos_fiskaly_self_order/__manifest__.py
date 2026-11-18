# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': "Italy - Point of Sale Sign IT - Self Order",
    'summary': 'Self orders and kiosks with fiskaly SIGN IT',
    'description': """
Bridge between the Italian Point of Sale fiscalization (fiskaly SIGN IT) and the Point of Sale self ordering.
The fiskaly compliance number is available on the self order receipts.
""",
    'category': 'Accounting/Localizations/Point of Sale',
    'depends': ['l10n_it_pos_fiskaly', 'pos_self_order'],
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}

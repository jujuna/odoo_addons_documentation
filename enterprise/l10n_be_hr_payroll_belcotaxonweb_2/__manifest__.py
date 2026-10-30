# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Belgian Payroll - Belcotax-on-web 2.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Export the 281 forms as JSON Lines files and check their withholding taxes per employee',
    'description': """
From the income year 2026, Belcotax-on-web only accepts JSON Lines files: the beneficiaries, the debtor and
the contact of the sending are resources that the fiches reference by their key, the amounts are in euros
and the totals are computed by Belcotax-on-web.

Lists, per 281 form and employee, the withholding taxes of the annual forms, the ones of each filed
274/273S declaration of the year and the payslips that no filed declaration covers, with a hint at the
origin of each difference.
    """,
    'depends': ['l10n_be_hr_payroll'],
    'data': [
        'security/ir.access.csv',
        'views/l10n_be_281_xx_withholding_check_views.xml',
        'views/l10n_be_281_xx_views.xml',
    ],
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}

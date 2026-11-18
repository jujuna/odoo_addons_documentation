{
    'name': 'Payroll Bank Channels',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Pay a payslip run through one or several banks, chosen per employee',
    'description': """
Bank-agnostic bridge between payroll and bank payments.

A bank channel is an account.payment.method.line. From a payslip run (or a single
payslip) the user picks a channel per employee and per authority, and the module
creates the payments through the standard payment register, one batch per channel.

Bank integration modules implement a small set of hooks on account.payment.method.line,
defined in gec_bank; this module calls them and never names a bank.
""",
    'author': 'GEC - Business Growth Services',
    'license': 'LGPL-3',
    'depends': [
        'hr_payroll_account',
        'account_batch_payment',
        'gec_bank',
        'gec_localization',
    ],
    'data': [
        'data/ir_cron_data.xml',
        'wizard/hr_payroll_pay_wizard_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_payslip_views.xml',
        'views/hr_payslip_run_views.xml',
        'views/account_batch_payment_views.xml',
        'views/res_config_settings_views.xml',
        'security/ir.access.csv',
    ],
    'installable': True,
    'application': False,
}

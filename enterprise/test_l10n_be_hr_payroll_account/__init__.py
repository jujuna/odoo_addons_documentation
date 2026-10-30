# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from odoo.exceptions import UserError
from odoo.fields import Date
from dateutil.relativedelta import relativedelta
from . import models
from . import wizard

_logger = logging.getLogger(__name__)


def generate_payslips(env):
    """ Generate demo payslips for the Belgian demo company during post-install. """
    demo_company = env.ref('base.demo_company_be', raise_if_not_found=False)
    has_duplicates = env['hr.payslip'].sudo().search([('employee_id.name', '=', 'Marian Weaver')], limit=1)
    if not demo_company or has_duplicates:
        return
    _logger.info('Generating payruns')

    langs = env['res.lang'].with_context(active_test=False).search([('code', 'in', ['fr_BE', 'nl_BE'])])
    for lang in langs:
        if not lang.active:
            env['base.language.install'].create({'lang_ids': [(6, 0, lang.ids)]}).lang_install()

    payslip_values = []
    # Produces 10 monthly runs, from 2 months ago back to 11 months ago.
    for i in range(2, 12):
        date_start = Date.today() - relativedelta(months=i, day=1)
        date_end = Date.today() - relativedelta(months=i, day=31)
        payslip_values.append({
            'name': date_start.strftime('%B %Y'),
            'date_start': date_start,
            'date_end': date_end,
            'company_id': demo_company.id,
            'structure_id': env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
        })

    # Process the payslip runs month by month.
    payslip_runs = env['hr.payslip.run'].with_company(demo_company).with_context(tracking_disable=True).create(payslip_values)
    for run in payslip_runs:
        _logger.info('Processing demo payslip run: %s', run.name)
        run._generate_payslips()
        run.action_validate()

    _generate_withholding_inconsistencies(env, demo_company)


def _generate_withholding_inconsistencies(env, company):
    """ Give Laurie Poiret a full previous year whose 274/273S declarations don't match the 281 forms.

    - every 274 is filed, then her June payslip is cancelled: the June 274 declares too much,
    - the 273S of January to November are filed, the December one is not: her December
      intellectual property isn't declared,
    - her 13th month is then paid: no filed 274 declares it.
    """
    laurie = env.ref('l10n_be_hr_contract_salary.hr_employee_laurie_poiret', raise_if_not_found=False)
    if not laurie:
        return
    _logger.info('Generating the withholding taxes inconsistencies of %s', laurie.name)
    env = env(context=dict(env.context, allowed_company_ids=company.ids, tracking_disable=True))
    laurie = laurie.with_env(env)
    # Without a Belgian language, the validation of her payslips asks for one instead.
    laurie.lang = 'fr_BE'
    year = Date.today().year - 1
    Payslip = env['hr.payslip']

    def create_payslips(structure, months):
        vals_list = []
        for month in months:
            date_from = Date.today().replace(year=year, month=month, day=1)
            date_to = date_from + relativedelta(day=31)
            vals_list.append({
                'name': f'{structure.name} - {date_from.strftime("%B %Y")}',
                'employee_id': laurie.id,
                'version_id': laurie._get_version(date_from).id,
                'company_id': company.id,
                'struct_id': structure.id,
                'date_from': date_from,
                'date_to': date_to,
            })
        payslips = Payslip.create(vals_list)
        payslips.compute_sheet()
        payslips.action_payslip_done()
        return payslips

    # The demo pay runs only cover the last months: validate them and complete the year.
    salary_structure = env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
    salaries = Payslip.search([
        ('employee_id', '=', laurie.id),
        ('struct_id', '=', salary_structure.id),
        ('state', '!=', 'cancel'),
        ('date_from', '>=', Date.today().replace(year=year, month=1, day=1)),
        ('date_to', '<=', Date.today().replace(year=year, month=12, day=31)),
    ])
    salaries.filtered(lambda p: p.state == 'draft').action_payslip_done()
    existing_months = {payslip.date_from.month for payslip in salaries}
    salaries |= create_payslips(salary_structure, [month for month in range(1, 13) if month not in existing_months])

    sheets_274 = env['l10n_be.274_xx'].with_company(company).create([
        {'year': year, 'month': str(month), 'company_id': company.id} for month in range(1, 13)
    ])
    for sheet in sheets_274:
        sheet.write({'belcotax_reference': f'DEMO-274-{year}-{sheet.month}', 'state': 'done'})

    salaries.filtered(lambda p: p.date_from.month == 6).action_payslip_cancel()

    for month in range(1, 13):
        sheet_273 = env['l10n_be.273_xx'].with_company(company).create({
            'year': year,
            'month': str(month),
            'company_id': company.id,
        })
        try:
            sheet_273.action_populate()
        except UserError:
            sheet_273.unlink()
            continue
        if month < 12:
            sheet_273.write({'belcotax_reference': f'DEMO-273-{year}-{month}', 'state': 'done'})

    thirteen_month = create_payslips(env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month'), [12])
    # Paid with the December salary, not deferred to the day the demo data is generated.
    thirteen_month.l10n_be_fiscal_date = thirteen_month.date_to

    declaration = env['l10n_be.281_xx'].with_company(company).create({
        'year': str(year),
        'company_id': company.id,
    })
    declaration.action_generate_test_xml()

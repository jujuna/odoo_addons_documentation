# Part of Odoo. See LICENSE file for full copyright and licensing details.

import csv
import io

from collections import defaultdict
from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import BinaryBytes

STATE_INCOME_TAX_CODES = [
    'CAINCOMETAX', 'NYINCOMETAX', 'COINCOMETAX', 'ALINCOMETAX', 'VTINCOMETAX',
    'ILINCOMETAX', 'AZINCOMETAX', 'NCINCOMETAX', 'VAINCOMETAX', 'DCINCOMETAX',
    'ORINCOMETAX', 'IDINCOMETAX', 'IAINCOMETAX', 'GAINCOMETAX', 'MSINCOMETAX',
    'NJINCOMETAX', 'MIINCOMETAX', 'MOINCOMETAX', 'KYINCOMETAX', 'UTINCOMETAX',
    'SCINCOMETAX', 'KSINCOMETAX',
]
OTHER_TAX_CODES = {
    'CA': {'CA SDI Tax': 'CASDITAX'},
    'NY': {'NY SDI Tax': 'NYSDITAX'},
    'VT': {'VT Childcare Tax': 'VTCHILDCARE'},
    'OR': {'OR Transit Tax': 'ORTRANSITTAX', 'OR FMLI': 'ORFMLI'},
    'NJ': {'NJ SDI Tax': 'NJSDITAX', 'NJ FLI Tax': 'NJFLITAX', 'NJ SUI Tax': 'NJSUITAX'},
}
LOCAL_INCOME_TAX_CODES = {
    'CO': {
        'Aurora': 'COOPTAURORA',
        'Denver': 'COOPTDENVER',
        'Glendale': 'COOPTGLENDALE',
        'Greenwood Village': 'COOPTGREENWOODVILLAGE',
        'Sheridan': 'COOPTSHERIDAN',
    },
    'NY': {
        'New York': 'NYNYCINCOMETAX',
        'Yonkers': 'NYYONKERSINCOMETAX',
    },
    'MO': {
        'Kansas City': 'MOKCTAX',
        'St. Louis': 'MOSTLOUISTAX',
    },
}
# One rule covers all the localities of the state, so the locality name comes from the address
ADDRESS_LOCAL_INCOME_TAX_CODES = {
    'KY': 'KYCOUNTYTAX',
    'MI': 'MICITYTAX',
}


class L10nUsW2(models.Model):
    _name = 'l10n.us.w2'
    _description = 'W2 Form'

    @api.model
    def default_get(self, fields):
        if self.env.company.country_id.code != "US":
            raise UserError(_('You must be logged in a US company to use this feature'))
        return super().default_get(fields)

    date_start = fields.Date("Start Date", default=lambda s: fields.Date.context_today(s) + relativedelta(day=1, month=1))
    date_end = fields.Date("End Date", compute='_compute_date_end', store=True, readonly=False)
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        domain=lambda self: [('id', 'in', self.env.companies.ids)],
        required=True)
    allowed_payslip_ids = fields.Many2many('hr.payslip', compute='_compute_allowed_payslip_ids')
    payslip_ids = fields.Many2many(
        'hr.payslip',
        compute='_compute_payslips_ids',
        store=True,
        readonly=False,
        domain="[('id', 'in', allowed_payslip_ids)]")
    csv_file = fields.Binary("CSV file", readonly=True)

    @api.depends('date_start')
    def _compute_date_end(self):
        for w2 in self:
            if not w2.date_start:
                continue
            w2.date_end = date(w2.date_start.year, 12, 31)

    @api.depends('date_end')
    def _compute_display_name(self):
        for w2 in self:
            w2.display_name = f"W-2 Form - {w2.date_end.year}" if w2.date_end else "W-2 Form"

    @api.depends('allowed_payslip_ids')
    def _compute_payslips_ids(self):
        for w2 in self:
            w2.payslip_ids = w2.allowed_payslip_ids

    def _get_allowed_payslips_domain(self):
        self.ensure_one()
        return [
            ('state', 'in', ['validated', 'paid']),
            ('paid_date', '>=', self.date_start),
            ('paid_date', '<=', self.date_end),
            ('company_id', '=', self.company_id.id),
        ]

    @api.depends('company_id', 'date_start', 'date_end')
    def _compute_allowed_payslip_ids(self):
        for w2 in self:
            if not w2.date_start or not w2.date_end or not w2.company_id:
                w2.allowed_payslip_ids = [(5, 0, 0)]
            else:
                allowed_payslips = self.env['hr.payslip'].search(w2._get_allowed_payslips_domain())
                w2.allowed_payslip_ids = allowed_payslips

    def _get_box14_other_taxes(self, state, line_values):
        box14 = []
        for label, code in OTHER_TAX_CODES.get(state, {}).items():
            box14 += [label, abs(line_values[code]['sum']['total'])]
        return (box14 + [""] * 6)[:6]

    def _get_box17_state_income_tax(self, line_values):
        return abs(sum(line_values[code]['sum']['total'] for code in STATE_INCOME_TAX_CODES))

    def _get_box18_local_wage(self, state, line_values):
        if state == 'CO':
            return abs(line_values['TAXABLE']['sum']['total'])
        return ""

    def _get_box19_local_income_tax(self, state, line_values):
        local_income_tax_codes = list(LOCAL_INCOME_TAX_CODES.get(state, {}).values())
        if state in ADDRESS_LOCAL_INCOME_TAX_CODES:
            local_income_tax_codes.append(ADDRESS_LOCAL_INCOME_TAX_CODES[state])
        if local_income_tax_codes:
            return abs(sum(line_values[code]['sum']['total'] for code in local_income_tax_codes))
        return ""

    def _get_box20_locality_name(self, version):
        state = version.address_id.state_id.code
        if version.address_id.city in LOCAL_INCOME_TAX_CODES.get(state, {}):
            return version.address_id.city
        # MO also taxes the residents of its cities
        if state == 'MO' and version.private_state_id.code == 'MO' and version.private_city in LOCAL_INCOME_TAX_CODES['MO']:
            return version.private_city
        if state in ADDRESS_LOCAL_INCOME_TAX_CODES:
            return self._get_address_locality_name(version)
        return ""

    def _get_address_locality_name(self, version):
        if version.address_id.state_id.code == 'KY':
            return version.address_id.city_id.l10n_us_county_id.name or ""
        mi_city_rates = self.env['hr.rule.parameter']._get_parameter_from_code(
            'l10n_us_mi_city_tax_rates', self.date_end, raise_if_not_found=False) or {}
        if version.private_state_id.code == 'MI' and version.private_city in mi_city_rates:
            return version.private_city
        if version.address_id.city in mi_city_rates:
            return version.address_id.city
        return ""

    def action_generate_csv(self):
        self.ensure_one()
        header = [
            "Employer identification number (EIN)",
            "Employer's name",
            "Street address 1",
            "Street address 2",
            "City or town",
            "State or province",
            "Country",
            "ZIP code",
            "Telephone no.",
            "Email",
            "Employee’s social security number (SSN)",
            "Employee's first name",
            "Employee's  middle initial",
            "Employee's last name",
            "Street address 1",
            "Street address 2",
            "City or town",
            "State or province",
            "Country",
            "ZIP code",
            "Telephone no.",
            "Email",
            "Control number",
            "1 Wages, tips, other compensation",
            "2 Federal income tax withheld",
            "3 Social security wages",
            "4 Social security tax withheld",
            "5 Medicare wages and tips",
            "6 Medicare tax withheld",
            "7 Social security tips",
            "8 Allocated tips",
            "10 Dependent care benefits",
            "11 Nonqualified plans",
            "12a Code A",
            "12a Amount A",
            "12b Code B",
            "12b Amount B",
            "12c Code C",
            "12c Amount C",
            "12d Code D",
            "12d Amount D",
            "13 Statutory employee",
            "13 Retirement plan",
            "13 Third-party sick pay",
            "14a Other A",
            "14a Other amount A",
            "14a Other B",
            "14a Other amount B",
            "14a Other C",
            "14a Other amount C",
            "14b Treasury Tipped Occupation Code(s)",
            "File directly with state",
            "15 State",
            "15 Employer’s state ID number",
            "16 State wages, tips, etc.",
            "17 State income tax",
            "18 Local wages, tips, etc.",
            "19 Local income tax",
            "20 Locality name",
            "File directly with state",
            "Kind of payer",
            "Kind of employer",
            "Terminating Business",
        ]

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(header)

        payslips_by_employee = defaultdict(lambda: self.env['hr.payslip'])
        for payslip in self.payslip_ids:
            payslips_by_employee[payslip.employee_id] += payslip

        for employee, payslips in payslips_by_employee.items():
            line_values = payslips._get_line_values([
                'TAXABLE', 'FIT', '401K', 'TIPS', 'SST', 'MEDICARE', 'MEDICAREADD', 'ALLOCATEDTIPS',
                'MEDICALFSADC', 'MEDICALHSA', 'ROTH401K', 'QAOT',
                *STATE_INCOME_TAX_CODES,
                *(code for taxes in OTHER_TAX_CODES.values() for code in taxes.values()),
                *(code for localities in LOCAL_INCOME_TAX_CODES.values() for code in localities.values()),
                *ADDRESS_LOCAL_INCOME_TAX_CODES.values(),
            ], compute_sum=True)
            qualified_overtime = abs(line_values['QAOT']['sum']['total'])

            version = employee._get_version(self.date_start)

            writer.writerow([
                self.company_id.vat or "",
                self.company_id.name or "",
                self.company_id.street or "",
                self.company_id.street2 or "",
                self.company_id.city or "",
                self.company_id.state_id.code or "",
                self.company_id.country_id.name or "",
                self.company_id.zip or "",
                self.company_id.phone or "",
                self.company_id.email or "",
                employee.l10n_us_ssn or "",
                employee.name or "",
                "",
                employee.name or "",
                version.private_street or "",
                version.private_street2 or "",
                version.private_city or "",
                version.private_state_id.code or "",
                version.private_country_id.name or "",
                version.private_zip or "",
                employee.private_phone or "",
                employee.private_email or "",
                "",
                abs(line_values['TAXABLE']['sum']['total']),
                abs(line_values['FIT']['sum']['total']),
                abs(line_values['TAXABLE']['sum']['total'] - line_values['401K']['sum']['total'] - line_values['TIPS']['sum']['total']),
                abs(line_values['SST']['sum']['total']),
                abs(line_values['TAXABLE']['sum']['total'] - line_values['401K']['sum']['total']),
                abs(line_values['MEDICARE']['sum']['total'] + line_values['MEDICAREADD']['sum']['total']),
                abs(line_values['TIPS']['sum']['total']),
                abs(line_values['ALLOCATEDTIPS']['sum']['total']),
                abs(line_values['MEDICALFSADC']['sum']['total']),
                "",
                "D",
                abs(line_values['401K']['sum']['total']),
                "W",
                abs(line_values['MEDICALHSA']['sum']['total']),
                "AA",
                abs(line_values['ROTH401K']['sum']['total']),
                "TT" if qualified_overtime else "",
                qualified_overtime or "",
                "TRUE" if version.l10n_us_statutory_employee else "FALSE",
                "TRUE" if version.l10n_us_retirement_plan else "FALSE",
                "TRUE" if version.l10n_us_third_party_sick_pay else "FALSE",
                *self._get_box14_other_taxes(version.address_id.state_id.code, line_values),
                "",
                "",
                version.address_id.state_id.code or "",
                self.company_id.l10n_us_state_identifier or "",
                abs(line_values['TAXABLE']['sum']['total']),
                self._get_box17_state_income_tax(line_values),
                self._get_box18_local_wage(version.address_id.state_id.code, line_values),
                self._get_box19_local_income_tax(version.address_id.state_id.code, line_values),
                self._get_box20_locality_name(version),
                "",
                "R",
                "N",
                "",
            ])

        self.csv_file = BinaryBytes(output.getvalue().encode(), filename=f"form_w2_{(self.date_end or date.today()).year}.csv")

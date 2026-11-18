# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from lxml import etree

from odoo.tests import tagged

from odoo.addons.l10n_be_hr_payroll.models.utils import round_eurocent

from .common import TestPayrollCommon


@tagged('post_install', '-at_install', 'post_install_l10n')
class Test273S(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.create_employee({
            'name': 'Copyright Employee',
            'niss': '00000100195',  # Synthetic NISS, unknown birth date.
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
            'wage': 4000,
            'ip_wage_rate': 0.25,
        })

    def _get_273S_data(self, month):
        report = self.env['l10n_be.273_xx'].create({'year': 2026, 'month': str(month)})
        report.action_populate()
        return report, report._get_rendering_data_273S()

    def test_artist_costs_and_onss(self):
        # The 273S declares the withholding base of the payslips: the IP minus its personal social
        # contributions minus the lump-sum costs of the artists
        taxes = {(False, False): 150, (False, True): 130.40, (True, False): 75, (True, True): 55.40}
        employees = self.env['hr.employee']
        for artist, onss in taxes:
            employees |= self.create_employee({
                'name': f'Copyright Artist {artist} ONSS {onss}',
                'niss': self.generate_fake_niss(),
                'date_version': date(2026, 1, 1),
                'contract_date_start': date(2026, 1, 1),
                'wage': 4000,
                'ip_wage_rate': 0.25,
                'ip_artist': artist,
                'ip_onss': onss,
            })
        payslips = self.create_and_validate_payslips(employees, 2026, [8])
        _report, data = self._get_273S_data(8)
        beneficiaries = {item['identification']['name']: item for item in data['beneficiaries']}
        for payslip in payslips:
            version = payslip.version_id
            with self.subTest(artist=version.ip_artist, onss=version.ip_onss):
                costs = 500 if version.ip_artist else 0
                onss = 130.70 if version.ip_onss else 0
                lines = payslip._get_line_values(['IP', 'IP.DED'])
                self.assertAlmostEqual(lines['IP'][payslip.id]['total'], 1000, 2)
                self.assertAlmostEqual(lines['IP.DED'][payslip.id]['total'], -taxes[version.ip_artist, version.ip_onss], 2)
                beneficiary = beneficiaries[payslip.employee_id.legal_name]
                self.assertAlmostEqual(beneficiary['gross_amount'], 1000, 2)
                self.assertAlmostEqual(beneficiary['deductable_costs']['fixed'], costs, 2)
                self.assertAlmostEqual(beneficiary['deductable_costs']['actual'], 0, 2)
                self.assertAlmostEqual(beneficiary['taxable_amount'], 1000 - onss - costs, 2)
                self.assertAlmostEqual(beneficiary['taxable_amount'] * 0.15, taxes[version.ip_artist, version.ip_onss], delta=0.01)
                self.assertAlmostEqual(beneficiary['tax_amount'], lines['IP.DED'][payslip.id]['total'], 2)
        self.assertAlmostEqual(data['declaration']['gross_amount'], 4000, 2)
        self.assertAlmostEqual(data['declaration']['deductable_costs']['fixed'], 1000, 2)
        self.assertAlmostEqual(data['declaration']['taxable_amount'], 2738.60, 2)
        self.assertAlmostEqual(data['declaration']['tax_amount'], 410.80, 2)

    def test_refund_cancels_flat_rate_costs(self):
        # The refund of a payslip cancels its lump-sum costs too: the IP, the costs, the taxable amount and the
        # withholding of the period add up to nothing
        self.employee.write({'ip_artist': False, 'ip_onss': False})
        payslip = self.create_and_validate_payslips(self.employee, 2026, [3])
        _report, data = self._get_273S_data(3)
        self.assertAlmostEqual(data['beneficiaries'][0]['deductable_costs']['fixed'], 500, 2)
        self.assertAlmostEqual(data['beneficiaries'][0]['taxable_amount'], 500, 2)
        payslip._action_refund_payslips()
        _report, data = self._get_273S_data(3)
        beneficiary = data['beneficiaries'][0]
        self.assertAlmostEqual(beneficiary['gross_amount'], 0, 2)
        self.assertAlmostEqual(beneficiary['deductable_costs']['fixed'], 0, 2)
        self.assertAlmostEqual(beneficiary['taxable_amount'], 0, 2)
        self.assertAlmostEqual(beneficiary['tax_amount'], 0, 2)

    def test_artist_yearly_brackets(self):
        # The lump-sum costs depend on the IP paid earlier in the year
        self.employee.write({'wage': 2650, 'ip_artist': True, 'ip_onss': False})
        for code, value in [('ip_deduction_bracket_1', 500), ('ip_deduction_bracket_2', 1000)]:
            parameter = self.env['hr.rule.parameter'].search([('code', '=', code)])
            self.env['hr.rule.parameter.value'].create({
                'rule_parameter_id': parameter.id,
                'date_from': date(2026, 2, 1),
                'parameter_value': value,
            })
        for month, tax in [(3, 55.78), (4, 86.72), (5, 99.38)]:
            payslip = self.create_and_validate_payslips(self.employee, 2026, [month])
            self.assertAlmostEqual(payslip._get_line_values(['IP.DED'])['IP.DED'][payslip.id]['total'], -tax, 2)
        _report, data = self._get_273S_data(5)
        # IP of 662.5 a month: 290.63 (March: 50 % of 500 + 25 % of 162.5)
        # + 84.38 (April: 25 % of the 337.5 left under the second bracket) + 0 (May)
        self.assertAlmostEqual(data['beneficiaries'][0]['deductable_costs']['fixed'], 375, 2)
        self.assertAlmostEqual(data['beneficiaries'][0]['taxable_amount'], 3 * 662.5 - 375, 2)

    def test_flat_rate_costs_payment_date(self):
        # The lump-sum costs are granted to every beneficiary for the IP paid before 11.06.2026 and only to
        # the artists from then on (Loi-programme of 30.05.2026), on the payslip and in the 273S. The yearly
        # brackets still count the IP paid earlier in the year.
        for code, value in [('ip_deduction_bracket_1', 500), ('ip_deduction_bracket_2', 1000)]:
            parameter = self.env['hr.rule.parameter'].search([('code', '=', code)])
            self.env['hr.rule.parameter.value'].create({
                'rule_parameter_id': parameter.id,
                'date_from': date(2026, 2, 1),
                'parameter_value': value,
            })
        artist = self.employee
        artist.write({'wage': 2650, 'ip_artist': True, 'ip_onss': False})
        other = self.create_employee({
            'name': 'Copyright Non Artist',
            'niss': self.generate_fake_niss(),
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
            'wage': 2650,
            'ip_wage_rate': 0.25,
            'ip_artist': False,
            'ip_onss': False,
        })
        # IP of 662.5 a month. May: 50 % of 500 + 25 % of 162.5 = 290.63 for both.
        # June: 25 % of the 337.5 left under the second bracket = 84.38 for the artist only.
        expected = {
            (5, True): (290.625, 55.78),
            (5, False): (290.625, 55.78),
            (6, True): (84.375, 86.72),
            (6, False): (0.0, 99.38),
        }
        for month in (5, 6):
            payslips = self.create_and_validate_payslips(artist | other, 2026, [month])
            for payslip in payslips:
                costs, tax = expected[month, payslip.version_id.ip_artist]
                with self.subTest(month=month, artist=payslip.version_id.ip_artist):
                    self.assertEqual(payslip._l10n_be_has_ip_flat_rate_costs(), bool(costs))
                    self.assertAlmostEqual(payslip._get_line_values(['IP.DED'])['IP.DED'][payslip.id]['total'], -tax, 2)
            # The 273S recomputes the costs of each declared payslip with its own rule
            report, data = self._get_273S_data(month)
            beneficiaries = {item['employee']: item for item in data['beneficiaries']}
            for employee in artist | other:
                declared = report.line_273S_ids.payslip_id.filtered(lambda payslip: payslip.employee_id == employee)
                self.assertIn(month, [payslip.date_to.month for payslip in declared])
                # declared to the cent
                costs = round_eurocent(sum(expected[payslip.date_to.month, employee.ip_artist][0] for payslip in declared))
                tax = sum(expected[payslip.date_to.month, employee.ip_artist][1] for payslip in declared)
                with self.subTest(month=month, artist=employee.ip_artist):
                    beneficiary = beneficiaries[employee]
                    self.assertAlmostEqual(beneficiary['deductable_costs']['fixed'], costs, 2)
                    self.assertAlmostEqual(beneficiary['taxable_amount'], 662.5 * len(declared) - costs, 2)
                    self.assertAlmostEqual(beneficiary['tax_amount'], -tax, 2)

        # Paid on the last day of the payslip period
        version = other.version_id
        for date_to, has_costs in [(date(2026, 6, 10), True), (date(2026, 6, 11), False)]:
            payslip = self.env['hr.payslip'].new({
                'employee_id': other.id, 'version_id': version.id,
                'date_from': date(2026, 6, 1), 'date_to': date_to,
            })
            self.assertEqual(payslip._l10n_be_has_ip_flat_rate_costs(), has_costs)

    def test_xml_amounts(self):
        self.employee.write({'wage': 4000.04, 'ip_onss': True})
        self.create_and_validate_payslips(self.employee, 2026, [8])
        report, _data = self._get_273S_data(8)
        report._generate_xml()
        self.assertEqual(report.xml_validation_state, 'done')
        root = etree.fromstring(report.xml_file.content)
        namespace = {'wt': 'http://withholding.minfin.fgov.be/'}
        income = root.find('.//wt:initialDeclaration[wt:declarationType="273S"]/wt:income', namespaces=namespace)
        for path, expected in [
            ('grossAmount', '100001'),
            ('deductableCosts', '0'),
            ('taxableAmount', '86931'),
            ('taxAmount', '13040'),
            ('beneficiary/wt:taxableAmount', '86931'),
            ('beneficiary/wt:fixedCost', '0'),
            ('beneficiary/wt:taxAmount', '13040'),
        ]:
            with self.subTest(path=path):
                self.assertEqual(income.findtext(f'wt:{path}', namespaces=namespace), expected)

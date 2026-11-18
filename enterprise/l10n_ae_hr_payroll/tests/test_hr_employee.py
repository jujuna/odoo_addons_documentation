# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from freezegun import freeze_time

from odoo.tests import common, tagged


@tagged('post_install', 'post_install_l10n', '-at_install')
class TestHrEmployee(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_worked_years(self):
        employee_1 = self.env['hr.employee'].create({
            'name': 'Test Employee 1',
            'contract_date_start': date(2023, 2, 15),
            'date_version': date(2023, 2, 15),
            'wage': 15_000.0,
        })

        with freeze_time('2025-2-15'):
            departure_notice_1 = self.env['hr.employee.departure'].create({
                'employee_id':  employee_1.id,
                'dismissal_date': date(2025, 2, 14),
                'departure_description': 'foo',
            })
            departure_notice_1.action_register()

        self.assertAlmostEqual(employee_1._l10n_ae_get_worked_years(), 2, 2, "This employee has worked for 2 years")

    def test_departure_reasons(self):
        """ A UAE company only offers the UAE end of service reasons, without default: the reason drives
        the visa cancellation. Before the module update, the generic reasons are kept. """
        ae_company = self.env['res.company'].create({'name': 'AE Company', 'country_id': self.env.ref('base.ae').id})
        be_company = self.env['res.company'].create({'name': 'BE Company', 'country_id': self.env.ref('base.be').id})
        Departure = self.env['hr.employee.departure']
        ae_reasons = self.env['hr.departure.reason'].search([('country_id.code', '=', 'AE')])
        self.assertEqual(len(ae_reasons), 18)

        ae_departure = Departure.with_company(ae_company)
        self.assertEqual(self.env['hr.departure.reason'].search(ae_departure._get_departure_reason_domain()), ae_reasons)
        self.assertFalse(ae_departure._get_default_departure_reason())

        be_departure = Departure.with_company(be_company)
        self.assertIn(self.env.ref('hr.departure_fired'), self.env['hr.departure.reason'].search(be_departure._get_departure_reason_domain()))
        self.assertTrue(be_departure._get_default_departure_reason())

        # UAE reasons not loaded yet (code deployed before the module update)
        ae_reasons.active = False
        self.assertEqual(ae_departure._get_departure_reason_domain(), Departure._get_departure_reason_domain())
        self.assertTrue(ae_departure._get_default_departure_reason())

# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.tests import tagged
from odoo.addons.l10n_be_hr_payroll.tests.common import TestPayrollCommon


@tagged('post_install', '-at_install', 'post_install_l10n')
class TestPublicTransport(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').active = True
        cls.employee = cls.create_employee({'name': 'Commuter'})

    def _bus_reimbursement(self, joint_committee, amount, periodicity, kilometer=0):
        version = self.employee.version_id
        version.write({
            'l10n_be_joint_committee_id': self.env.ref(f'l10n_be_hr_payroll.l10n_be_joint_committee_{joint_committee}').id,
            'bus_transport_employee_amount': amount,
            'bus_transport_periodicity': periodicity,
            'bus_transport_employee_kilometer': kilometer,
        })
        # the employer intervention table of 1 February 2026
        return version.with_context(payslip_date=date(2026, 3, 1))._get_public_transport_reimbursed_amount('bus')

    def test_cp302_bus(self):
        # 80% of the price paid, at most the table amount for 16 km (67 a month, 674 a year), without minimum amount
        for amount, periodicity, expected in (
            (50, 'monthly', 40.0),
            (100, 'monthly', 67.0),
            (20, 'monthly', 16.0),
            (600, 'yearly', 40.0),
            (1000, 'yearly', 674 / 12),
        ):
            self.assertAlmostEqual(self._bus_reimbursement('302', amount, periodicity), expected, places=2,
                                   msg=f"{amount} {periodicity}")

    def test_cp200_bus(self):
        # fixed price: 71.8% of the price, at most the table amount for 7 km (45); price by distance: the table
        # amount for the distance (40 for 5 km), at most 75% of the price
        for amount, periodicity, kilometer, expected in (
            (100, 'fixed', 0, 45.0),
            (50, 'fixed', 0, 35.9),
            (100, 'monthly', 5, 40.0),
            (40, 'monthly', 5, 30.0),
        ):
            self.assertAlmostEqual(self._bus_reimbursement('200', amount, periodicity, kilometer), expected, places=2,
                                   msg=f"{amount} {periodicity} {kilometer} km")

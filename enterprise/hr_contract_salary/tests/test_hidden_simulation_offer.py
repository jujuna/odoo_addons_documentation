from datetime import date

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestHiddenSimulationOffer(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        structure_type = cls.env['hr.payroll.structure.type'].create({'name': 'Simulation Test Type'})
        structure_type.default_struct_id = cls.env['hr.payroll.structure'].create({
            'name': 'Simulation Test Structure',
            'type_id': structure_type.id,
        })
        cls.env['hr.employee'].create({
            'name': 'Simulation Test Employee',
            'contract_date_start': date(2026, 1, 1),
            'structure_type_id': structure_type.id,
        })

    def test_hr_contract_salary_hidden_simulation_offer_tour(self):
        self.start_tour("/odoo", 'hr_contract_salary_hidden_simulation_offer_tour', login='admin', timeout=350)

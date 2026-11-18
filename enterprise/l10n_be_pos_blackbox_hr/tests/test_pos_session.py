from odoo import Command
from odoo.tests import tagged
from odoo.addons.l10n_be_pos_blackbox.tests.common import TestL10nBePosBlackboxCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nBePosBlackboxHrSession(TestL10nBePosBlackboxCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['hr.employee'].sudo().search([]).l10n_be_insz_or_bis_number = '00000000097'
        cls.employee = cls.env['hr.employee'].sudo().create({
            'name': 'Cashier Employee',
            'user_id': cls.pos_user.id,
            'l10n_be_insz_or_bis_number': '00000000097',
        })
        cls.main_pos_config.write({
            'module_pos_hr': True,
            'cashier_employee_ids': [Command.set(cls.employee.ids)],
        })

    def test_clocking_by_pos_user_without_hr_rights(self):
        self.assertFalse(self.pos_user.has_group('hr.group_hr_user'))
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id.with_user(self.pos_user)

        session.set_work_in_out_cashier(self.employee.id, 'in')
        self.assertEqual(session.sudo().l10n_be_employees_clocked_ids, self.employee)
        self.assertEqual(session.sudo().employee_id, self.employee)
        session_data = session._load_pos_data_read(session, session.config_id)
        self.assertEqual(session_data[0]['l10n_be_employees_clocked_ids'], self.employee.ids)

        session.set_work_in_out_cashier(self.employee.id, 'out')
        self.assertFalse(session.sudo().l10n_be_employees_clocked_ids)

        session.set_work_in_out_cashier(self.employee.id, 'in')
        self.assertEqual(session.work_out_all_cashiers(), ['00000000097'])
        self.assertFalse(session.sudo().l10n_be_employees_clocked_ids)
        self.assertEqual(session.sudo().pos_clock_in_out_ids.mapped('type'), ['in', 'out', 'in', 'out'])

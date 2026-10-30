from odoo.tests import TransactionCase


class TestEmployeeForm(TransactionCase):

    def test_a_single_read_a_badge_button(self):
        arch = self.env['hr.employee'].get_view(view_type='form')['arch']
        self.assertIn('open_barcode_scanner', arch)
        self.assertNotIn('open_badge_scanner', arch)

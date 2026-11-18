from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestGlovoResolveForm(HttpCase):

    def test_resolve_form_warnings(self):
        new_test_user(self.env, 'glovo_form_mgr', groups='base.group_user,point_of_sale.group_pos_manager')
        self.start_tour('/odoo', 'glovo_resolve_form_tour', login='glovo_form_mgr')

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

SERVICE_MODULE = 'odoo.addons.employee_registry_rs.models.employee_registry_rs_service'


@tagged('post_install', '-at_install')
class TestServiceGuards(TransactionCase):

    def test_sync_countries_without_georgian_refuses_before_calling_rs(self):
        service = self.env['employee.registry.rs.service']
        with patch.object(type(self.env['res.lang']), '_lang_get', return_value=self.env['res.lang']), \
                patch.object(type(service), 'get_countries') as get_countries, self.assertRaises(UserError):
            service.sync_countries_from_rs()
        get_countries.assert_not_called()

    def test_rs_call_without_rs_base_methods_raises_user_error_and_makes_no_request(self):
        if hasattr(self.env['res.users'], '_get_rs_rest_token'):
            self.skipTest("rs_base_methods is installed.")
        with patch(f'{SERVICE_MODULE}.requests.post') as post, self.assertRaises(UserError):
            self.env['employee.registry.rs.service'].get_countries()
        post.assert_not_called()

# The read methods that search and group through other methods (hierarchy_read, get_gantt_data,
# get_cohort_data): hidden values are blanked and a hidden field in their arguments is refused,
# like the methods they call. They need web_hierarchy, web_gantt and web_cohort, and skip without them.
import xmlrpc.client

from odoo import Command
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import JsonRpcException
from odoo.tools import mute_logger

REFUSED = 'odoo.exceptions.AccessError'


@tagged('post_install', '-at_install')
class TestClientReads(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-reads-pw'
        groups = 'base.group_user,base.group_partner_manager'
        cls.member = new_test_user(cls.env, 'gec_reads_member', groups=groups, password=cls.password)
        cls.plain = new_test_user(cls.env, 'gec_reads_plain', groups=groups, password=cls.password)
        cls.no_parent = new_test_user(cls.env, 'gec_reads_no_parent', groups=groups, password=cls.password)
        cls.admin = new_test_user(cls.env, 'gec_reads_admin', groups='base.group_system', password=cls.password)
        cls.boss = cls.env['res.partner'].create({'name': 'Reads Boss', 'email': 'boss-secret@example.com', 'color': 3})
        cls.staff = cls.env['res.partner'].create({
            'name': 'Reads Staff', 'email': 'staff-secret@example.com', 'parent_id': cls.boss.id, 'color': 3,
            'country_id': cls.env.ref('base.be').id})
        cls.partners = cls.boss + cls.staff
        for user, names in ((cls.member, ('email', 'color', 'create_date')), (cls.plain, ('email',)),
                            (cls.no_parent, ('parent_id',))):
            cls.env['gec.access.profile'].create({
                'name': f'Reads {user.login}',
                'user_ids': [Command.set(user.ids)],
                'field_ids': [Command.create({
                    'model_id': cls.env['ir.model']._get('res.partner').id,
                    'field_id': cls.env['ir.model.fields']._get('res.partner', name).id,
                    'mode': 'hide',
                }) for name in names],
            })

    def _call(self, method, kwargs, endpoint='call_kw'):
        return self.make_jsonrpc_request(f'/web/dataset/{endpoint}/res.partner/{method}', {
            'model': 'res.partner', 'method': method, 'args': [], 'kwargs': kwargs,
        })

    def _login(self, user, method):
        if not hasattr(self.env['res.partner'], method):
            self.skipTest(f"{method} needs its web module")
        self.authenticate(user.login, self.password)

    def _hierarchy(self, **kwargs):
        return self._call('hierarchy_read', {
            'domain': [('id', 'in', self.partners.ids)], 'specification': {'name': {}, 'email': {}},
            'parent_field': 'parent_id', **kwargs})

    def _gantt(self, **kwargs):
        return self._call('get_gantt_data', {
            'domain': [('id', 'in', self.partners.ids)], 'groupby': ['country_id'],
            'read_specification': {'name': {}, 'email': {}}, **kwargs})

    def _cohort(self, **kwargs):
        return self._call('get_cohort_data', {
            'date_start': 'create_date', 'date_stop': 'write_date', 'measure': '__count', 'interval': 'month',
            'domain': [('id', 'in', self.partners.ids)], 'mode': 'retention', 'timeline': 'forward', **kwargs})

    def _assert_refused(self, call, **kwargs):
        with mute_logger('odoo.http'), self.assertRaises(JsonRpcException) as caught:
            call(**kwargs)
        self.assertEqual(str(caught.exception), REFUSED, kwargs)

    def test_hierarchy_read_blanks_the_hidden_values(self):
        self._login(self.member, 'hierarchy_read')
        rows = self._hierarchy()
        self.assertEqual({row['id'] for row in rows}, set(self.partners.ids))
        self.assertTrue(all(row['email'] is False for row in rows))

    def test_hierarchy_read_gives_the_values_to_a_user_without_the_rule(self):
        self._login(self.admin, 'hierarchy_read')
        self.assertEqual({row['email'] for row in self._hierarchy()},
                         {'boss-secret@example.com', 'staff-secret@example.com'})

    def test_hierarchy_read_refuses_a_hidden_field_in_its_arguments(self):
        self._login(self.member, 'hierarchy_read')
        self._assert_refused(self._hierarchy, domain=[('email', '=ilike', 'boss-secret%')])
        self._assert_refused(self._hierarchy, order='email')
        self.authenticate(self.no_parent.login, self.password)
        self._assert_refused(self._hierarchy)

    def test_hierarchy_read_without_a_hidden_field_in_its_arguments_works(self):
        self._login(self.member, 'hierarchy_read')
        rows = self._hierarchy(domain=[('id', 'in', self.partners.ids), ('name', 'ilike', 'Reads')])
        self.assertEqual({row['id'] for row in rows}, set(self.partners.ids))

    def test_hierarchy_read_is_checked_through_call_button_too(self):
        self._login(self.member, 'hierarchy_read')
        with mute_logger('odoo.http'), self.assertRaises(JsonRpcException) as caught:
            self._call('hierarchy_read', {
                'domain': [('email', '=', 'boss-secret@example.com')], 'specification': {'name': {}},
                'parent_field': 'parent_id'}, endpoint='call_button')
        self.assertEqual(str(caught.exception), REFUSED)

    def test_get_gantt_data_blanks_the_hidden_values(self):
        self._login(self.member, 'get_gantt_data')
        result = self._gantt()
        self.assertEqual({row['id'] for row in result['records']}, set(self.partners.ids))
        self.assertTrue(all(row['email'] is False for row in result['records']))

    def test_get_gantt_data_gives_the_values_to_a_user_without_the_rule(self):
        self._login(self.admin, 'get_gantt_data')
        self.assertEqual({row['email'] for row in self._gantt()['records']},
                         {'boss-secret@example.com', 'staff-secret@example.com'})

    def test_get_gantt_data_refuses_a_hidden_field_in_its_arguments(self):
        self._login(self.member, 'get_gantt_data')
        self._assert_refused(self._gantt, groupby=['email'])
        self._assert_refused(self._gantt, domain=[('email', '=ilike', 'boss-secret%')])
        self._assert_refused(self._gantt, unavailability_fields=['email'])
        self._assert_refused(self._gantt, progress_bar_fields=['email'])

    def test_get_cohort_data_refuses_a_hidden_field_in_its_arguments(self):
        self._login(self.member, 'get_cohort_data')
        self._assert_refused(self._cohort, date_start='write_date', measure='color')
        self._assert_refused(self._cohort, date_start='create_date')
        self._assert_refused(self._cohort, date_start='write_date', date_stop='create_date')
        self._assert_refused(self._cohort, date_start='write_date', domain=[('email', '=', 'boss-secret@example.com')])

    def test_get_cohort_data_without_a_hidden_field_in_its_arguments_works(self):
        self._login(self.plain, 'get_cohort_data')
        self.assertTrue(self._cohort()['rows'])
        self.assertTrue(self._cohort(measure='color')['rows'])

    def test_gantt_helpers_neither_read_nor_write_a_hidden_field(self):
        self._login(self.member, 'web_gantt_init_old_vals_per_pill_id')
        self._assert_refused(lambda: self.make_jsonrpc_request(
            '/web/dataset/call_kw/res.partner/web_gantt_init_old_vals_per_pill_id', {
                'model': 'res.partner', 'method': 'web_gantt_init_old_vals_per_pill_id',
                'args': [self.boss.ids, {'email': 1}], 'kwargs': {}}))
        self.make_jsonrpc_request('/web/dataset/call_kw/res.partner/gantt_undo_drag_drop', {
            'model': 'res.partner', 'method': 'gantt_undo_drag_drop',
            'args': [self.boss.ids, 'reschedule', {'email': 'changed@example.com', 'name': 'Reads Boss Moved'}],
            'kwargs': {}})
        self.boss.invalidate_recordset()
        self.assertEqual(self.boss.email, 'boss-secret@example.com')
        self.assertEqual(self.boss.name, 'Reads Boss Moved')

    @mute_logger('odoo.addons.rpc.controllers.xmlrpc', 'odoo.http')
    def test_xmlrpc_checks_the_arguments_too(self):
        if not hasattr(self.env['res.partner'], 'hierarchy_read'):
            self.skipTest("hierarchy_read needs web_hierarchy")
        with self.assertRaises(xmlrpc.client.Fault):
            self.xmlrpc_object.execute_kw(
                self.env.cr.dbname, self.member.id, self.password, 'res.partner', 'hierarchy_read',
                [[('email', '=ilike', 'boss-secret%')], {'name': {}}, 'parent_id'])

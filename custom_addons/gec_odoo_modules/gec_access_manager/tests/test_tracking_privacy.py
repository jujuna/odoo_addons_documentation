# Tracking messages that show a hidden field stay out of the chatter of a profile member: v20 renders tracking into
# the stored message body, where the field guard cannot blank it.
import json

from markupsafe import Markup

from odoo import Command
from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestTrackingPrivacy(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-tracking-pw'
        cls.costs_user = new_test_user(cls.env, 'gec_track_costs', groups='base.group_user', password=cls.password)
        cls.plain_user = new_test_user(cls.env, 'gec_track_plain', groups='base.group_user', password=cls.password)
        cls.conditional_user = new_test_user(cls.env, 'gec_track_cond', groups='base.group_user', password=cls.password)
        Profile = cls.env['gec.access.profile']
        Profile.create({'name': 'Tracking costs', 'hide_costs': True, 'user_ids': [Command.set(cls.costs_user.ids)]})
        Profile.create({'name': 'Tracking plain', 'block_export': True, 'user_ids': [Command.set(cls.plain_user.ids)]})
        Profile.create({
            'name': 'Tracking conditional',
            'user_ids': [Command.set(cls.conditional_user.ids)],
            'field_ids': [Command.create({
                'model_id': cls.env['ir.model']._get('product.template').id,
                'field_id': cls.env['ir.model.fields']._get('product.template', 'list_price').id,
                'mode': 'hide', 'condition': "name == 'Tracked Product'",
            })],
        })
        cls.product = cls.env['product.product'].create(
            {'name': 'Tracked Product', 'standard_price': 100, 'list_price': 5})
        cls._flush_tracking()
        cls.product.standard_price = 1000
        cls._flush_tracking()
        cls.product.product_tmpl_id.list_price = 7
        cls._flush_tracking()

    @classmethod
    def _flush_tracking(cls):
        """ Tracking is written when the transaction commits, which a test never does. """
        cls.env.flush_all()
        cls.env.cr.precommit.run()

    def _bodies(self, user, label):
        """ The tracking messages, of any model, that show ``label``, as the member ``user`` reads them. """
        self.authenticate(user.login, self.password)
        messages = self.make_jsonrpc_request('/web/dataset/call_kw/mail.message/search_read', {
            'model': 'mail.message', 'method': 'search_read',
            'args': [[('message_type', '=', 'tracking'), ('body', 'ilike', '(%s)' % label)]],
            'kwargs': {'fields': ['body']},
        })
        return [message['body'] for message in messages]

    def test_hidden_cost_is_not_in_the_member_chatter(self):
        self.assertEqual(self._bodies(self.costs_user, 'Cost'), [])

    def test_admin_still_sees_the_cost(self):
        admin_messages = self.env['mail.message'].with_user(self.env.ref('base.user_admin')).search(
            [('message_type', '=', 'tracking'), ('body', 'ilike', '(Cost)')])
        self.assertEqual(len(admin_messages), 1)

    def test_chatter_route_hides_the_cost(self):
        self.authenticate(self.costs_user.login, self.password)
        shown = json.dumps(self._thread_messages('product.product'))
        self.assertNotIn('(Cost)', shown)

    def test_chatter_route_shows_the_cost_without_hidden_field(self):
        self.authenticate(self.plain_user.login, self.password)
        self.assertIn('(Cost)', json.dumps(self._thread_messages('product.product')))

    def test_member_without_hidden_field_sees_every_tracking_message(self):
        self.assertEqual(len(self._bodies(self.plain_user, 'Cost')), 1)
        self.assertEqual(len(self._bodies(self.plain_user, 'Sales Price')), 1)

    def test_other_tracked_field_stays_visible(self):
        self.assertEqual(len(self._bodies(self.costs_user, 'Sales Price')), 1)

    def test_field_hidden_under_a_condition_is_hidden_too(self):
        self.assertEqual(self._bodies(self.conditional_user, 'Sales Price'), [])
        self.assertEqual(len(self._bodies(self.conditional_user, 'Cost')), 1)

    def _thread_messages(self, model):
        """ What the chatter of the product asks the server for, through the store route of the web client. """
        return self.make_jsonrpc_request('/mail/store', {'fetch_params': [[
            '/mail/thread/messages',
            {'thread_model': model, 'thread_id': self.product.id, 'fetch_params': {'limit': 30}},
        ]]})

    def test_notifications_skip_the_members_it_hides_a_field_from(self):
        """ A tracking message posted with a subtype is e-mailed and pushed to followers: the member who may
        not see the field is left out, the others stay. """
        self.product.message_subscribe(partner_ids=(self.costs_user | self.plain_user).partner_id.ids)
        message = self.product.message_post(
            body=Markup('<div>100.00 → <b>1,000.00</b> <i>(Cost)</i></div>'), message_type='tracking',
            subtype_xmlid='mail.mt_comment')
        notified = {recipient['id'] for recipient in self.product._notify_get_recipients(message)}
        self.assertNotIn(self.costs_user.partner_id.id, notified)
        self.assertIn(self.plain_user.partner_id.id, notified)

    def test_a_search_through_the_messages_does_not_find_the_hidden_value(self):
        """ message_ids searches past the access rules: the body of a hidden tracking message is not searchable. """
        domain = [('id', '=', self.product.id), ('message_ids', 'any', [('body', 'ilike', '1,000.00')])]
        for user, expected in ((self.costs_user, 0), (self.plain_user, 1)):
            self.authenticate(user.login, self.password)
            count = self.make_jsonrpc_request('/web/dataset/call_kw/product.product/search_count', {
                'model': 'product.product', 'method': 'search_count', 'args': [domain], 'kwargs': {}})
            self.assertEqual(count, expected, user.login)

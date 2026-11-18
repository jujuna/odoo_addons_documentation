# Round 2 (external review, 2026-10-29). Phase A: a profile's technical group is the module's alone, a profile cannot
# give the group of another profile, and the state of a temporary assignment follows its dates. Phase B: the doors
# check the create right first, /json checks the action before running it, a button condition is judged on readable
# records only, an action button is never blocked under a condition, every sending method obeys Hide Send Message,
# Block Export holds on the models an export path crosses, and Read Only Everywhere cannot lock the managers out.
# Item 2 and phase C: a context default of a locked field is refused, a reference read is blanked by its own model's
# rules, an onchange answer leaves a conditionally hidden value out, a conditional lock locks the copies of the field,
# a value filter that cannot be evaluated refuses, and moving records in or out of a one2many respects the lock of
# their inverse field.
import threading
import xmlrpc.client
from contextlib import contextmanager
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

from .test_fixes import ClientCalls

MANAGER = 'gec_access_manager.group_access_manager'


@contextmanager
def client_call(model_name, method):
    """ Like the XML-RPC door: the thread tells which call the client made (gec_user_audit's _gec_rpc_entry). """
    thread = threading.current_thread()
    previous = getattr(thread, 'rpc_model_method', None)
    thread.rpc_model_method = f'{model_name}.{method}'
    try:
        yield
    finally:
        thread.rpc_model_method = previous


@tagged('post_install', '-at_install')
class TestRound2Groups(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, 'gec_r2_manager', groups=f'base.group_user,{MANAGER}')
        cls.system = cls.env.ref('base.group_system')
        cls.contacts = cls.env.ref('base.group_partner_manager')

    def test_a_default_cannot_point_a_new_profile_at_an_existing_group(self):
        """ R1: neither a context default nor a saved default of the group is taken, also in a client create whose
        field guard drops a locked group_id; Settings keeps its name, members and implied groups. """
        before = (self.system.name, self.system.user_ids, self.system.implied_ids)
        self.env['ir.default'].set('gec.access.profile', 'group_id', self.system.id)
        Profile = self.env['gec.access.profile'].with_user(self.manager)
        self.env['gec.access.profile'].create({
            'name': 'R2 lock on the profile group', 'strictness': 'override',
            'user_ids': [Command.set(self.manager.ids)],
            'field_ids': [Command.create({
                'model_id': self.env['ir.model']._get('gec.access.profile').id,
                'field_id': self.env['ir.model.fields']._get('gec.access.profile', 'group_id').id,
                'mode': 'readonly'})]})
        for context in ({'default_group_id': self.system.id}, {}):
            with self.subTest(context=context), client_call('gec.access.profile', 'create'):
                profile = Profile.with_context(context).create({
                    'name': f'R2 default {bool(context)}', 'user_ids': [Command.set(self.manager.ids)]})
                self.assertTrue(profile.sudo().group_id)
                self.assertNotEqual(profile.sudo().group_id, self.system)
        self.system.invalidate_recordset()
        self.assertEqual((self.system.name, self.system.user_ids, self.system.implied_ids), before)
        self.assertNotIn(self.system, self.manager.all_group_ids)

    def test_a_profile_cannot_give_the_group_of_another_profile(self):
        """ R7: active or archived, another profile's group is refused, as is a group that implies it. """
        giver = self.env['gec.access.profile'].create({
            'name': 'R2 giver', 'granted_group_ids': [Command.set(self.contacts.ids)]})
        taker = self.env['gec.access.profile'].create({'name': 'R2 taker'})
        wrapper = self.env['res.groups'].create({
            'name': 'R2 wrapper', 'implied_ids': [Command.set(giver.group_id.ids)]})
        for archived in (False, True):
            giver.active = not archived
            for group in (giver.group_id, wrapper):
                with self.subTest(archived=archived, group=group.name), \
                        self.assertRaisesRegex(ValidationError, 'carries the group of another profile'):
                    taker.granted_group_ids = group

    def test_a_state_written_by_hand_follows_the_dates_again(self):
        """ R5: an assignment set to ended while its dates run is brought back, and its user keeps the profile's
        groups in step with it. """
        user = new_test_user(self.env, 'gec_r2_temporary', groups='base.group_user')
        profile = self.env['gec.access.profile'].create({
            'name': 'R2 temporary', 'granted_group_ids': [Command.set(self.contacts.ids)]})
        line = self.env['gec.access.profile.assignment'].create({
            'profile_id': profile.id, 'user_id': user.id, 'date_from': fields.Date.today() - timedelta(days=1)})
        self.assertEqual(line.state, 'active')
        line.write({'state': 'ended'})
        self.assertEqual(line.state, 'active')
        self.assertIn(user, profile.group_id.user_ids)
        self.assertIn(self.contacts, user.all_group_ids)


@tagged('post_install', '-at_install')
class TestRound2Rules(TransactionCase):

    def test_an_action_button_cannot_be_blocked_under_a_condition(self):
        """ R9: opening an action names no record, so a blocking rule under a condition is refused; hiding stays. """
        Button = self.env['gec.access.profile.button']
        profile = self.env['gec.access.profile'].create({'name': 'R2 action button'})
        values = {'profile_id': profile.id, 'model_id': self.env['ir.model']._get('res.partner').id,
                  'button_type': 'action', 'button_name': str(self.env.ref('base.action_partner_form').id),
                  'condition': "active == True"}
        for mode in ('block', 'hide_block'):
            with self.subTest(mode=mode), \
                    self.assertRaisesRegex(ValidationError, 'cannot be blocked under a condition'):
                Button.create(dict(values, mode=mode))
        self.assertTrue(Button.create(dict(values, mode='hide')))

    def test_read_only_everywhere_cannot_lock_the_last_access_manager_out(self):
        """ R16: Read Only Everywhere, or a switch to override, on the only access manager's profile is refused. """
        manager = new_test_user(self.env, 'gec_r2_last_manager', groups=f'base.group_user,{MANAGER}')
        self.env.ref(MANAGER).sudo().user_ids = manager
        profile = self.env['gec.access.profile'].create({
            'name': 'R2 own profile', 'user_ids': [Command.set(manager.ids)]})
        with self.assertRaisesRegex(ValidationError, 'editing access profiles'):
            profile.with_user(manager).write({'global_readonly': True})
        # an open additive profile outweighs the one that takes the edit right, until that one overrides
        self.env['gec.access.profile'].create({'name': 'R2 open profile', 'user_ids': [Command.set(manager.ids)]})
        profile.model_ids = [Command.create({
            'model_id': self.env['ir.model']._get('gec.access.profile').id, 'perm_write': False})]
        with self.assertRaisesRegex(ValidationError, 'editing access profiles'):
            profile.with_user(manager).write({'strictness': 'override'})


    def test_an_export_below_a_reference_field_is_opaque(self):
        """ R15: a reference field names its model per record, so a path below one is judged as unknown. """
        model, field = next((model, field) for model in self.env.values() if not model._abstract
                            for field in model._fields.values() if field.type == 'reference')
        self.assertEqual(model._gec_export_path_models([f'{field.name}/display_name']), (set(), field.string))
        self.assertEqual(model._gec_export_path_models([field.name])[1], None)


@tagged('post_install', '-at_install')
class TestRound2Doors(ClientCalls, HttpCase):

    def _need(self, model_name):
        if model_name not in self.env:
            self.skipTest(f"{model_name} is not installed")

    def _profile(self, user, **values):
        return self.env['gec.access.profile'].create({
            'name': f'R2 doors {user.login}', 'user_ids': [Command.set(user.ids)], **values})

    @mute_logger('odoo.http')
    def test_read_only_everywhere_stops_an_inventory_adjustment(self):
        """ R11: the create right is checked before stock.quant goes sudo in inventory mode. """
        self._need('stock.quant')
        user = new_test_user(self.env, 'gec_r2_stock', groups='base.group_user,stock.group_stock_user')
        location = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1).lot_stock_id
        product = self.env['product.product'].create({'name': 'R2 stock', 'type': 'consu', 'is_storable': True})
        self.env['stock.quant']._update_available_quantity(product, location, 10.0)
        self._profile(user, global_readonly=True)
        self.authenticate(user.login, user.login)
        error = self._error('stock.quant', 'create', [{
            'product_id': product.id, 'location_id': location.id, 'inventory_quantity_auto_apply': 3.0}],
            {'context': {'inventory_mode': True}})
        self.assertIn('does not allow you to create', error)
        imported = self._call('stock.quant', 'load', [
            ['product_id/.id', 'location_id/.id', 'inventory_quantity_auto_apply'],
            [[str(product.id), str(location.id), '3']]])
        self.assertFalse(imported['ids'])
        self.assertEqual(product.with_context(location=location.id).qty_available, 10.0)
        # what Read Only Everywhere spares is still created at the doors
        self.assertTrue(self._call('ir.filters', 'create', [{
            'name': 'R2 filter', 'model_id': 'res.partner', 'user_ids': [Command.set(user.ids)]}]))

    @mute_logger('odoo.http')
    def test_the_json_route_checks_the_action_before_running_it(self):
        """ R12: a server action the profile hides is refused on /json before it runs. """
        user = new_test_user(self.env, 'gec_r2_json', groups='base.group_user,base.group_allow_export')
        self.env['ir.config_parameter'].sudo().set_bool('web.json.enabled', True)
        server = self.env['ir.actions.server'].create({
            'name': 'R2 partners', 'model_id': self.env['ir.model']._get('res.partner').id, 'state': 'code',
            'path': 'gec-r2-partners', 'code': (
                "action = {'type': 'ir.actions.act_window', 'id': %s, 'name': 'R2 partners', "
                "'res_model': 'res.partner', 'view_mode': 'list', 'views': [[False, 'list']]}"
                % self.env.ref('base.action_partner_form').id)})
        self._profile(user, hidden_action_ids=[Command.set(server.ids)])
        self.authenticate(user.login, user.login)
        response = self.url_open('/json/1/gec-r2-partners', headers={
            'Sec-Fetch-Dest': 'document', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1'})
        self.assertEqual(response.status_code, 403)

    @mute_logger('odoo.http')
    def test_a_button_condition_says_nothing_about_records_the_user_cannot_read(self):
        """ R8: two orders of another company get the same answer, whatever their amount. """
        self._need('sale.order')
        user = new_test_user(self.env, 'gec_r2_sales', groups='base.group_user,sales_team.group_sale_salesman')
        other = self.env['res.company'].create({'name': 'R2 other company'})
        partner = self.env['res.partner'].create({'name': 'R2 customer'})
        product = self.env['product.product'].create({'name': 'R2 product', 'type': 'consu'})
        orders = self.env['sale.order'].create([{
            'partner_id': partner.id, 'company_id': other.id, 'order_line': [Command.create({
                'product_id': product.id, 'product_uom_qty': 1, 'price_unit': price, 'tax_ids': [Command.clear()]})],
        } for price in (5000.0, 10.0)])
        self._profile(user, button_ids=[Command.create({
            'model_id': self.env['ir.model']._get('sale.order').id, 'button_type': 'object',
            'button_name': 'action_confirm', 'mode': 'block', 'condition': 'amount_total > 1000'})])
        self.authenticate(user.login, user.login)
        big, small = (self._error('sale.order', 'action_confirm', [order.ids]) for order in orders)
        self.assertEqual(big, small)
        self.assertNotIn('You cannot use this button', big)

    @mute_logger('odoo.http')
    def test_hide_send_message_covers_every_sending_method(self):
        """ R10: message_mail_with_source and the template's send_mail are refused like the composer. """
        user = new_test_user(self.env, 'gec_r2_mail', groups='base.group_user,base.group_partner_manager')
        partner = self.env['res.partner'].create({'name': 'R2 recipient', 'email': 'gec-r2@example.com'})
        template = self.env['mail.template'].create({
            'name': 'R2 template', 'model_id': self.env['ir.model']._get('res.partner').id, 'subject': 'R2 subject',
            'body_html': '<p>R2</p>', 'email_to': 'gec-r2-to@example.com'})
        self.env['ir.model.data'].create({
            'module': 'gec_access_manager', 'name': 'gec_r2_template', 'model': template._name, 'res_id': template.id})
        self._profile(user, model_ids=[Command.create({
            'model_id': self.env['ir.model']._get('res.partner').id, 'hide_send_message': True})])
        self.authenticate(user.login, user.login)
        for model, method, args in (
                ('res.partner', 'message_mail_with_source', [partner.ids, 'gec_access_manager.gec_r2_template']),
                ('mail.template', 'send_mail', [template.ids, partner.id]),
                ('mail.template', 'send_mail_batch', [template.ids, partner.ids])):
            with self.subTest(method=method):
                self.assertIn('sending messages', self._error(model, method, args))
        self.assertFalse(self.env['mail.message'].search([('subject', '=', 'R2 subject')]))

    @mute_logger('odoo.http')
    def test_block_export_holds_on_the_models_an_export_crosses(self):
        """ R15: Block Export on contacts also refuses partner_id/email exported from the users. """
        user = new_test_user(self.env, 'gec_r2_export', groups='base.group_user,base.group_allow_export')
        self._profile(user, model_ids=[Command.create({
            'model_id': self.env['ir.model']._get('res.partner').id, 'hide_export': True})])
        self.authenticate(user.login, user.login)
        self.assertTrue(self._call('res.users', 'export_data', [user.ids, ['login']]))
        for path in ('partner_id/email', 'partner_id@en_US/email', 'partner_id.id'):
            with self.subTest(path=path):
                self.assertIn('does not allow exporting',
                              self._error('res.users', 'export_data', [user.ids, ['login', path]]))


@tagged('post_install', '-at_install')
class TestRound2FieldRules(TransactionCase):

    def _lock(self, user, model_name, field_name, **values):
        return self.env['gec.access.profile'].create({
            'name': f'R2 {field_name}', 'user_ids': [Command.set(user.ids)], 'field_ids': [Command.create({
                'model_id': self.env['ir.model']._get(model_name).id,
                'field_id': self.env['ir.model.fields']._get(model_name, field_name).id, **values})]})

    def test_a_conditional_lock_locks_the_copies_always(self):
        """ R6: the users' phone copies the contact's: hidden under a condition there, hidden always on the users. """
        user = new_test_user(self.env, 'gec_r2_copies', groups='base.group_user')
        self._lock(user, 'res.partner', 'phone', mode='hide', condition="ref == 'R2'")
        rules = self.env['gec.access.profile']._resolve(user.id)
        self.assertFalse(rules.field_mode('res.partner', 'phone'))
        self.assertEqual(rules.field_mode('res.users', 'phone'), 'hide')

    def test_a_value_filter_that_cannot_be_evaluated_refuses(self):
        """ R3: a filter reading parent.<field> on a contact written on its own refuses instead of letting it pass. """
        user = new_test_user(self.env, 'gec_r2_filter', groups='base.group_user,base.group_partner_manager')
        state = self.env['res.country.state'].search([], limit=1)
        self._lock(user, 'res.partner', 'state_id', mode='keep',
                   field_domain="[('country_id', '=', parent.country_id)]")
        partner = self.env['res.partner'].create({'name': 'R2 filtered'})
        with client_call('res.partner', 'write'), self.assertRaisesRegex(AccessError, 'cannot check the allowed'):
            partner.with_user(user).write({'state_id': state.id})


@tagged('post_install', '-at_install')
class TestRound2FieldDoors(ClientCalls, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_r2_fields', groups='base.group_user,base.group_partner_manager')

    def _lock(self, field_name, **values):
        return self.env['gec.access.profile'].create({
            'name': f'R2 doors {field_name}', 'user_ids': [Command.set(self.user.ids)], 'field_ids': [Command.create({
                'model_id': self.env['ir.model']._get('res.partner').id,
                'field_id': self.env['ir.model.fields']._get('res.partner', field_name).id, **values})]})

    @mute_logger('odoo.http')
    def test_the_api_refuses_a_context_default_of_a_locked_field(self):
        """ Item 2: on XML-RPC, default_ref is refused when ref is read only, on the record created, a copy and the
        lines a write creates at any depth; the web client keeps Odoo's behaviour, its menus preset fields that way. """
        self._lock('ref', mode='readonly')
        company = self.env['res.partner'].create({'name': 'R2 company', 'is_company': True})
        contact = self.env['res.partner'].create({'name': 'R2 contact', 'parent_id': company.id})
        context = {'context': {'default_ref': 'R2-X'}}
        for method, args in (
                ('create', [{'name': 'R2 default'}]),
                ('copy', [contact.ids]),
                ('write', [company.ids, {'child_ids': [(0, 0, {'name': 'R2 line'})]}]),
                ('write', [company.ids, {'child_ids': [
                    (1, contact.id, {'child_ids': [(0, 0, {'name': 'R2 nested'})]})]}])):
            with self.subTest(method=method, args=args), self.assertRaisesRegex(xmlrpc.client.Fault, 'Reference'):
                self.xmlrpc_object.execute_kw(
                    self.env.cr.dbname, self.user.id, self.user.login, 'res.partner', method, args, context)
        self.assertFalse(self.env['res.partner'].search([('ref', '=', 'R2-X')]))
        self.authenticate(self.user.login, self.user.login)
        partner_id = self._call('res.partner', 'create', [{'name': 'R2 web default'}], context)
        self.assertEqual(self.env['res.partner'].browse(partner_id).ref, 'R2-X')

    def test_a_reference_read_is_blanked_by_the_rules_of_its_model(self):
        """ R13: the phone of a contact read through a message's res_id is blanked as on the contact itself. """
        self._lock('phone', mode='hide')
        partner = self.env['res.partner'].create({'name': 'R2 referenced', 'phone': '+995 555 000 111'})
        message = partner.message_post(body='R2 note', message_type='comment')
        self.authenticate(self.user.login, self.user.login)
        [row] = self._call('mail.message', 'web_read', [message.ids, {'res_id': {'fields': {'phone': {}}}}])
        self.assertFalse(row['res_id']['phone'])

    def test_an_onchange_answer_leaves_a_conditionally_hidden_value_out(self):
        """ R4: an onchange answer names no saved record, so a field hidden under a condition is not in it. """
        self._lock('email_normalized', mode='hide', condition="ref == 'R2-MATCH'")
        self.authenticate(self.user.login, self.user.login)
        answer = self._call('res.partner', 'onchange', [
            [], {'name': 'R2 onchange', 'ref': 'R2-MATCH', 'email': 'r2-onchange@example.com'}, ['email'],
            {'name': {}, 'ref': {}, 'email': {}, 'email_normalized': {}}])
        self.assertNotIn('email_normalized', answer['value'])

    def test_an_onchange_judges_the_record_as_the_form_holds_it(self):
        """ R4: a saved contact is judged on its saved values, not on the defaults its form did not send; a new record
        that does not match keeps the value in the answer. """
        self._lock('email_normalized', mode='hide', condition='ref == False')
        saved_partner = self.env['res.partner'].create({'name': 'R2 saved', 'ref': 'R2-SAVED'})
        spec = {'email': {}, 'email_normalized': {}}
        self.authenticate(self.user.login, self.user.login)
        saved = self._call('res.partner', 'onchange', [
            saved_partner.ids, {'email': 'r2-saved@example.com'}, ['email'], spec])
        new = self._call('res.partner', 'onchange', [
            [], {'name': 'R2 new', 'ref': 'R2-NEW', 'email': 'r2-new@example.com'}, ['email'], spec])
        self.assertEqual(saved['value'].get('email_normalized'), 'r2-saved@example.com')
        self.assertEqual(new['value'].get('email_normalized'), 'r2-new@example.com')

    def test_a_new_record_that_matches_keeps_odoo_s_own_value(self):
        """ R4: the client sends a placeholder for the value an onchange left out; a new record matching the
        condition is saved with Odoo's own value instead. """
        self._lock('lang', mode='hide', condition="ref == 'R2-MATCH'")
        self.authenticate(self.user.login, self.user.login)
        partner_id = self._call('res.partner', 'web_save', [[], {
            'name': 'R2 new match', 'ref': 'R2-MATCH', 'lang': False}, {}])[0]['id']
        self.assertTrue(self.env['res.partner'].browse(partner_id).lang)

    @mute_logger('odoo.http')
    def test_moving_a_contact_respects_its_locked_parent(self):
        """ R14: linking, unlinking or listing a contact in another company's contacts writes its parent: refused on
        every door, in every form core accepts, and the contact keeps its company. """
        self._lock('parent_id', mode='readonly')
        first, second = self.env['res.partner'].create([
            {'name': 'R2 first', 'is_company': True}, {'name': 'R2 second', 'is_company': True}])
        contact = self.env['res.partner'].create({'name': 'R2 moved', 'parent_id': first.id})
        self.authenticate(self.user.login, self.user.login)
        for company, value in ((second, [Command.link(contact.id)]), (second, [Command.unlink(contact.id)]),
                               (second, contact.ids), (first, False)):
            with self.subTest(company=company.name, value=value):
                self.assertTrue(self._error('res.partner', 'write', [company.ids, {'child_ids': value}]))
        with self.assertRaisesRegex(xmlrpc.client.Fault, 'Related Company|Parent'):
            self.xmlrpc_object.execute_kw(self.env.cr.dbname, self.user.id, self.user.login, 'res.partner', 'write',
                                          [second.ids, {'child_ids': [(6, 0, contact.ids)]}])
        # a contact already in the company moves nowhere
        self.assertTrue(self._call('res.partner', 'write', [first.ids, {'child_ids': [Command.link(contact.id)]}]))
        contact.invalidate_recordset()
        self.assertEqual(contact.parent_id, first)

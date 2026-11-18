# Each event is logged once, through the entry point that produces it.
import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessDenied, AccessError, MissingError, UserError
from odoo.http import request_var
from odoo.http.session import session_store
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.gec_user_audit.models.ir_http import SEEN_KEY
from odoo.addons.gec_user_audit.models.gec_user_audit_rule import DEFAULT_EXCLUDED

GIF = 'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='


def fake_request(env, identity_checked):
    """ A request for the code that needs one (``check_identity``, translations), with a session
    whose identity was checked just now or never. """
    session = session_store().new()
    if identity_checked:
        session['identity-check-last'] = time.time()
    return SimpleNamespace(env=env, session=session, httprequest=SimpleNamespace(
        remote_addr='127.0.0.1', user_agent=SimpleNamespace(string='test')))


class AuditMixin:

    def _logs(self, **domain):
        self.env.cr.precommit.run()
        self.env.invalidate_all()
        return self.env['gec.user.audit.log'].sudo().search([(key, '=', value) for key, value in domain.items()])


@tagged('post_install', '-at_install')
class TestAuditRules(AuditMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_audit_user', groups='base.group_user,base.group_partner_manager')

    def test_changes_are_logged_with_their_values(self):
        Partner = self.env['res.partner'].with_user(self.user)
        partner = Partner.create({'name': 'Audited', 'phone': '111'})
        partner.write({'phone': '222', 'name': 'Audited'})
        partner.unlink()
        logs = self._logs(model='res.partner', res_id=partner.id)
        self.assertEqual(sorted(logs.mapped('event')), ['create', 'unlink', 'write'])
        edit = logs.filtered(lambda line: line.event == 'write')
        # only what changed
        self.assertEqual(edit.changes, 'Phone: 111 → 222')
        self.assertEqual(edit.user_id, self.user)

    def test_an_editable_computed_field_is_logged(self):
        partner = self.env['res.partner'].with_user(self.user).create({'name': 'Customer'})
        partner.user_id = self.user
        edit = self._logs(model='res.partner', res_id=partner.id, event='write')
        self.assertEqual(edit.changes, f'Salesperson:  → {self.user.name}')

    def test_a_restricted_field_is_logged_without_its_values(self):
        partner = self.env['res.partner'].with_user(self.user).create({'name': 'Restricted', 'phone': '111'})
        with patch.object(partner._fields['phone'], 'groups', 'base.group_partner_manager'):
            partner.write({'phone': '222'})
        edit = self._logs(model='res.partner', res_id=partner.id, event='write')
        self.assertEqual(edit.changes, 'Phone: changed')

    def test_a_text_change_after_the_logged_length_is_logged(self):
        partner = self.env['res.partner'].with_user(self.user).create({'name': 'Long', 'function': 'a' * 250})
        partner.write({'function': 'a' * 249 + 'b'})
        edit = self._logs(model='res.partner', res_id=partner.id, event='write')
        self.assertEqual(edit.changes, f"Job Position: ...{'a' * 21} → ...{'a' * 20}b")

    def test_an_x2many_change_shows_the_records_added_and_removed(self):
        tags = self.env['res.partner.category'].create([{'name': f'T{index:02d}'} for index in range(12)])
        partner = self.env['res.partner'].with_user(self.user).create({
            'name': 'Tagged', 'category_id': [Command.set(tags[:11].ids)]})
        partner.write({'category_id': [Command.set((tags[:10] | tags[11]).ids)]})
        edit = self._logs(model='res.partner', res_id=partner.id, event='write')
        self.assertEqual(edit.changes, 'Tags: +T11; -T10')

    def test_an_x2many_change_lists_at_most_ten_records_each_way(self):
        tags = self.env['res.partner.category'].create([{'name': f'T{index:02d}'} for index in range(12)])
        partner = self.env['res.partner'].with_user(self.user).create({'name': 'Tagged'})
        partner.write({'category_id': [Command.set(tags.ids)]})
        edit = self._logs(model='res.partner', res_id=partner.id, event='write')
        self.assertEqual(edit.changes, 'Tags: ' + ', '.join(f'+T{index:02d}' for index in range(10)) + ' (+2 more)')

    def test_a_file_is_logged_as_added_replaced_or_removed_and_never_for_the_same_file(self):
        partner = self.env['res.partner'].with_user(self.user).create({'name': 'Pictured'})
        label = partner._fields['image_1920'].string
        for image in (GIF, GIF, PNG, False):
            partner.write({'image_1920': image})
        edits = self._logs(model='res.partner', res_id=partner.id, event='write').sorted('id')
        self.assertEqual(edits.mapped('changes'), [
            f'{label}: (file) added', f'{label}: (file) replaced', f'{label}: (file) removed'])

    def test_a_properties_change_names_the_properties_that_changed(self):
        if 'product.template' not in self.env:
            self.skipTest('product is not installed')
        categ = self.env['product.category'].create({
            'name': 'Audited category',
            'product_properties_definition': [{'name': 'size', 'string': 'Size', 'type': 'char'}]})
        product = self.env['product.template'].with_user(self.env.ref('base.user_admin')).create({
            'name': 'Audited product', 'categ_id': categ.id})
        product.write({'product_properties': {'size': 'XL'}})
        edit = self._logs(model='product.template', res_id=product.id, event='write')
        self.assertEqual(edit.changes, 'Properties: changed (Size)')

    def test_a_record_without_a_name_is_logged_by_model_and_id(self):
        industry = self.env['res.partner.industry'].create({'name': False})
        self.assertFalse(industry.display_name)
        partner = self.env['res.partner'].with_user(self.user).create({'name': 'Nameless'})
        partner.write({'industry_id': industry.id})
        edit = self._logs(model='res.partner', res_id=partner.id, event='write')
        self.assertEqual(edit.changes, f'Industry:  → res.partner.industry,{industry.id}')

    def test_adding_a_line_to_an_order_whose_line_has_no_name(self):
        if 'purchase.order' not in self.env:
            self.skipTest('purchase is not installed')
        buyer = new_test_user(self.env, 'gec_audit_buyer', groups='base.group_user,purchase.group_purchase_user')
        product = self.env['product.product'].create({'name': 'Audited product'})
        line = {'product_id': product.id, 'product_qty': 1, 'price_unit': 1}
        order = self.env['purchase.order'].create({
            'partner_id': self.env['res.partner'].create({'name': 'Audited vendor'}).id,
            'order_line': [Command.create(line)]})
        self.assertFalse(order.order_line.display_name)
        order.with_user(buyer).write({'order_line': [Command.create(line)]})
        self.assertEqual(len(self._logs(model='purchase.order', res_id=order.id, event='write')), 1)

    def test_a_group_rule_follows_a_group_change_of_the_user(self):
        group = self.env['res.groups'].create({'name': 'Audited group'})
        self.env['gec.user.audit.rule'].create({'name': 'Group', 'group_ids': [Command.set(group.ids)]})
        Partner = self.env['res.partner'].with_user(self.user)
        Partner.create({'name': 'Before the group'})
        self.user.write({'group_ids': [Command.link(group.id)]})
        Partner.create({'name': 'After the group'})
        self.assertEqual(self._logs(model='res.partner').mapped('res_name'), ['After the group'])

    def test_a_rule_edit_is_logged(self):
        rule = self.env['gec.user.audit.rule'].with_user(self.env.ref('base.user_admin')).create({'name': 'Watch'})
        rule.write({'name': 'Watch more'})
        edit = self._logs(model='gec.user.audit.rule', res_id=rule.id, event='write')
        self.assertEqual(edit.changes, 'Name: Watch → Watch more')

    def test_saving_the_settings_stores_only_what_differs_from_the_defaults(self):
        params = self.env['ir.config_parameter'].sudo()
        keys = ['gec_user_audit.log_reads', 'gec_user_audit.excluded_models']
        params.set_bool(keys[0], True)
        params.set_str(keys[1], 'ir.*')
        Settings = self.env['res.config.settings'].with_user(self.env.ref('base.user_admin'))
        Settings.create({'gec_audit_log_reads': False,
                         'gec_audit_excluded_models': ', '.join(DEFAULT_EXCLUDED)}).set_values()
        self.assertFalse(params.search([('key', 'in', keys)]))
        Settings.create({'gec_audit_log_reads': True, 'gec_audit_excluded_models': 'ir.*'}).set_values()
        self.assertTrue(params.get_bool(keys[0]))
        self.assertEqual(params.get_str(keys[1]), 'ir.*')

    def test_settings_rows_left_by_the_vendor_code_are_not_stored_again(self):
        params = self.env['ir.config_parameter'].sudo()
        keys = ['gec_user_audit.log_reads', 'gec_user_audit.excluded_models']
        vendor_list = [p if p != 'gec.user.audit.log' else 'gec.user.audit.*' for p in DEFAULT_EXCLUDED if p != '*.line']
        params.set_bool(keys[0], True)
        params.set_str(keys[1], ', '.join(reversed(vendor_list)))
        Settings = self.env['res.config.settings'].with_user(self.env.ref('base.user_admin'))
        Settings.create({}).set_values()
        self.assertFalse(params.search([('key', 'in', keys)]))
        self.assertFalse(params.get_bool(keys[0], False))
        Settings.create({'gec_audit_log_reads': True,
                         'gec_audit_excluded_models': ', '.join(DEFAULT_EXCLUDED)}).set_values()
        Settings.create({}).set_values()
        self.assertTrue(params.get_bool(keys[0]))

    def test_the_superuser_and_technical_data_are_not_logged(self):
        self.env['res.partner'].sudo().create({'name': 'By the system'})
        self.env['ir.config_parameter'].with_user(self.env.ref('base.user_admin')).set_str('gec.test', '1')
        self.assertFalse(self._logs(res_name='By the system'))
        self.assertFalse(self._logs(model='ir.config_parameter'))

    def test_python_reads_are_not_logged(self):
        self.env['res.partner'].with_user(self.user).search([]).read(['name'])
        self.assertFalse(self._logs(event='read'))

    def test_a_rule_narrows_what_is_logged(self):
        category_model = self.env['ir.model']._get('res.partner.category')
        self.env['gec.user.audit.rule'].create({'name': 'Tags', 'model_ids': [(6, 0, category_model.ids)],
                                               'log_write': False})
        self.env['res.partner'].with_user(self.user).create({'name': 'Not logged'})
        tag = self.env['res.partner.category'].with_user(self.env.ref('base.user_admin')).create({'name': 'Logged'})
        tag.name = 'Renamed'
        self.assertFalse(self._logs(model='res.partner'))
        self.assertEqual(self._logs(model='res.partner.category').mapped('event'), ['create'])

    def test_a_rule_for_some_users(self):
        other = new_test_user(self.env, 'gec_audit_other', groups='base.group_user,base.group_partner_manager')
        self.env['gec.user.audit.rule'].create({'name': 'One user', 'user_ids': [(6, 0, other.ids)]})
        self.env['res.partner'].with_user(self.user).create({'name': 'By the user'})
        self.env['res.partner'].with_user(other).create({'name': 'By the other'})
        self.assertEqual(self._logs(model='res.partner').mapped('res_name'), ['By the other'])

    def test_old_lines_are_deleted(self):
        Log = self.env['gec.user.audit.log'].sudo()
        old = Log.create({'event': 'other', 'date': fields.Datetime.now() - timedelta(days=100)})
        old_login = Log.create({'event': 'login', 'date': fields.Datetime.now() - timedelta(days=100)})
        recent = Log.create({'event': 'other'})
        self.env['ir.config_parameter'].sudo().set_int('gec_user_audit.keep_sign_in_days', 365)
        Log._cron_clean()
        self.assertFalse(old.exists())
        self.assertTrue(old_login.exists())
        self.assertTrue(recent.exists())

    def test_changes_are_shown_for_readable_and_deleted_records_only(self):
        other_company = self.env['res.company'].create({'name': 'Audit other company'})
        hidden = self.env['res.partner'].create({'name': 'Hidden', 'company_id': other_company.id})
        visible = self.env['res.partner'].create({'name': 'Visible'})
        Log = self.env['gec.user.audit.log'].sudo()
        lines = Log.create([
            {'event': 'write', 'model': 'res.partner', 'res_id': partner.id, 'changes': 'Phone: 111 → 222'}
            for partner in (hidden, visible)])
        gone = Log.create({'event': 'write', 'model': 'res.partner', 'res_id': visible.id + 100000,
                           'changes': 'Phone: 1 → 2'})
        reader = new_test_user(self.env, 'gec_audit_reader', groups='base.group_system')
        shown = (lines | gone).with_user(reader).mapped('changes_shown')
        self.assertEqual(shown, ['changed (not readable by you)', 'Phone: 111 → 222', 'Phone: 1 → 2'])
        plain = new_test_user(self.env, 'gec_audit_plain_reader', groups='base.group_user')
        self.assertEqual(gone.with_user(plain).changes_shown, 'changed (not readable by you)')
        self.assertFalse(Log.create({'event': 'login'}).with_user(reader).changes_shown)
        with self.assertRaises(AccessError):
            lines.with_user(reader).changes

    def test_an_attachment_token_is_logged_without_its_value(self):
        admin = self.env.ref('base.user_admin')
        attachment = self.env['ir.attachment'].with_user(admin).create({'name': 'Shared', 'raw': b'x'})
        attachment.generate_access_token()
        attachment.write({'access_token': 'secret-token-value'})
        edit = self._logs(model='ir.attachment', res_id=attachment.id, event='write')
        self.assertTrue(edit)
        self.assertNotIn('secret-token-value', ' '.join(edit.mapped('changes')))
        self.assertIn('Access Token: changed', edit.mapped('changes'))

    def test_document_lines_are_logged_unless_explicitly_excluded(self):
        """Child values need their own audit events when parent membership is unchanged."""
        self.env['ir.config_parameter'].sudo().search([('key', '=', 'gec_user_audit.excluded_models')]).unlink()
        Rule = self.env['gec.user.audit.rule']
        policy = Rule._gec_policy()
        self.assertFalse(Rule._gec_excluded('purchase.order.line', policy))
        self.assertFalse(Rule._gec_excluded('hr.payslip.line', policy))
        self.assertFalse(Rule._gec_excluded('account.analytic.line', policy))
        self.assertFalse(Rule._gec_excluded('res.partner', policy))
        self.env['ir.config_parameter'].sudo().set_str('gec_user_audit.excluded_models', '*.line')
        self.assertTrue(Rule._gec_excluded('purchase.order.line', Rule._gec_policy()))

    def test_existing_document_line_values_are_logged(self):
        """Parent commands and direct edits keep usable old and new child values."""
        if 'purchase.order' not in self.env:
            self.skipTest('purchase is not installed')
        buyer = new_test_user(self.env, 'gec_audit_line_buyer', groups='base.group_user,purchase.group_purchase_user')
        product = self.env['product.product'].create({'name': 'Line audit product'})
        order = self.env['purchase.order'].create({
            'partner_id': self.env['res.partner'].create({'name': 'Line audit vendor'}).id,
            'order_line': [Command.create({'product_id': product.id, 'product_qty': 1, 'price_unit': 10})]})
        line = order.order_line
        order.with_user(buyer).write({'order_line': [Command.update(line.id, {'price_unit': 999})]})
        line.with_user(buyer).write({'product_qty': 3})
        edits = self._logs(model='purchase.order.line', res_id=line.id, event='write').sorted('id')
        self.assertEqual(len(edits), 2)
        self.assertIn('10.0 → 999.0', edits[0].changes)
        self.assertIn('1.0 → 3.0', edits[1].changes)
        order.with_user(buyer).write({'order_line': [Command.delete(line.id)]})
        self.assertEqual(len(self._logs(model='purchase.order.line', res_id=line.id, event='unlink')), 1)

    def test_translation_changes_include_other_languages_and_removal(self):
        """Editing a foreign translation records that language even in an English session."""
        if 'product.template' not in self.env:
            self.skipTest('product is not installed')
        self.env['res.lang']._activate_lang('fr_FR')
        product = self.env['product.template'].create({'name': 'Original name'})
        product = product.with_user(self.env.ref('base.user_admin')).with_context(lang='en_US')
        product.update_field_translations('name', {'fr_FR': 'Nom traduit'})
        product.update_field_translations('name', {'fr_FR': False})
        edits = self._logs(model='product.template', res_id=product.id, event='write').sorted('id')
        self.assertEqual(edits.mapped('changes'), ['Name: [fr_FR]  → Nom traduit', 'Name: [fr_FR] Nom traduit → '])
        self.assertEqual(product.with_context(lang='fr_FR').name, 'Original name')

    def test_callable_html_translation_is_logged_once(self):
        """HTML term translations retain language codes and do not duplicate write events."""
        if 'product.template' not in self.env:
            self.skipTest('product is not installed')
        self.env['res.lang']._activate_lang('fr_FR')
        product = self.env['product.template'].create({'name': 'HTML audit', 'description': '<p>Hello</p>'})
        product = product.with_user(self.env.ref('base.user_admin')).with_context(lang='en_US')
        self.assertTrue(callable(product._fields['description'].translate))
        product.update_field_translations('description', {'fr_FR': {'Hello': 'Bonjour'}})
        edits = self._logs(model='product.template', res_id=product.id, event='write')
        self.assertEqual(len(edits), 1)
        self.assertIn('[fr_FR]', edits.changes)
        self.assertIn('Bonjour', edits.changes)
        self.assertIn('Bonjour', product.with_context(lang='fr_FR').description)

    def test_nested_savepoints_only_keep_successful_changes(self):
        """Caught raw and flushing rollbacks discard only their own audit rows."""
        for flushing in (False, True):
            with self.subTest(flush=flushing):
                partner = self.env['res.partner'].with_user(self.user).create({'name': 'Savepoint', 'phone': '111'})
                partner.write({'phone': '222'})
                self.env.flush_all()
                with self.env.cr.savepoint(flush=flushing):
                    partner.write({'phone': '333'})
                    self.env.flush_all()
                    try:
                        with self.env.cr.savepoint(flush=flushing):
                            partner.write({'phone': '444'})
                            self.env.flush_all()
                            raise ValueError('Discard the inner edit')
                    except ValueError:
                        self.env.invalidate_all(flush=False)
                edits = self._logs(model='res.partner', res_id=partner.id, event='write').sorted('id')
                self.assertEqual(partner.phone, '333')
                self.assertEqual(edits.mapped('changes'), ['Phone: 111 → 222', 'Phone: 222 → 333'])
                try:
                    with self.env.cr.savepoint(flush=flushing):
                        with self.env.cr.savepoint(flush=flushing):
                            partner.write({'phone': '555'})
                            self.env.flush_all()
                        raise ValueError('Discard the outer edit')
                except ValueError:
                    self.env.invalidate_all(flush=False)
                self.assertEqual(partner.phone, '333')
                self.assertEqual(self._logs(model='res.partner', res_id=partner.id, event='write'), edits.sorted('id', reverse=True))

    def test_record_names_follow_reader_access_in_exports_and_reports(self):
        """Raw names stay private and every public presentation filters unreadable records."""
        company = self.env['res.company'].create({'name': 'Private audit company'})
        hidden = self.env['res.partner'].create({'name': 'Confidential company name', 'company_id': company.id})
        visible = self.env['res.partner'].create({'name': 'Visible name'})
        reader = new_test_user(self.env, 'gec_audit_name_reader', groups='base.group_system')
        Log = self.env['gec.user.audit.log'].sudo()
        lines = Log.create([{'event': 'write', 'model': 'res.partner', 'res_id': record.id,
                             'res_name': record.name, 'changes': 'Phone: 1 → 2'} for record in (hidden, visible)])
        gone = Log.create({'event': 'unlink', 'model': 'res.partner', 'res_id': visible.id + 100000,
                           'res_name': 'Deleted private name'})
        logs = (lines | gone).with_user(reader)
        notice = 'Record (not readable by you)'
        self.assertEqual(logs.mapped('res_name_shown'), [notice, 'Visible name', 'Deleted private name'])
        self.assertNotIn('Confidential company name', ' '.join(logs.mapped('display_name')))
        self.assertNotIn('res_name', logs.fields_get())
        with self.assertRaises(AccessError):
            logs.read(['res_name'])
        with self.assertRaises(AccessError):
            logs.export_data(['res_name'])
        exported = logs.export_data(['res_name_shown', 'display_name'])['datas']
        self.assertNotIn('Confidential company name', str(exported))
        self.assertIn('Deleted private name', str(exported))
        wizard = self.env['gec.user.audit.report.wizard'].with_user(reader).create({
            'date_from': fields.Date.today(), 'date_to': fields.Date.today(), 'events': 'all'})
        html, _format = self.env['ir.actions.report'].with_user(reader)._render_qweb_html(
            'gec_user_audit.action_report_user_activity', wizard.ids, data={'wizard_id': wizard.id})
        self.assertNotIn(b'Confidential company name', html)
        self.assertIn(b'Deleted private name', html)
        self.assertIn(b'Visible name', html)

    def test_record_presentation_cache_follows_sudo_and_company_context(self):
        """Cached privileged values cannot leak when the reader narrows company access."""
        main = self.env.company
        other = self.env['res.company'].create({'name': 'Audit cache other company'})
        partner = self.env['res.partner'].create({'name': 'Private cached name', 'company_id': other.id})
        log = self.env['gec.user.audit.log'].sudo().create({
            'event': 'write', 'model': partner._name, 'res_id': partner.id,
            'res_name': partner.name, 'changes': 'Phone: 111 → 222'})
        reader = new_test_user(
            self.env, 'gec_audit_cache_reader', groups='base.group_system', company_id=main.id,
            company_ids=[Command.set((main | other).ids)])
        view = log.with_user(reader).with_context(allowed_company_ids=main.ids)

        def presentation(line):
            return line.res_name_shown, line.display_name, line.changes_shown

        visible = ('Private cached name', 'Edit Private cached name', 'Phone: 111 → 222')
        hidden = ('Record (not readable by you)', 'Edit Record (not readable by you)', 'changed (not readable by you)')
        self.assertEqual(presentation(view.sudo()), visible)
        self.assertEqual(presentation(view), hidden)
        for companies, expected in [((main | other).ids, visible), (main.ids, hidden), ((main | other).ids, visible)]:
            self.assertEqual(presentation(view.with_context(allowed_company_ids=companies)), expected)

    def test_record_names_do_not_read_restricted_name_fields(self):
        """Readable records cannot disclose names derived from a restricted source field."""
        record = self.env['res.partner.industry'].create({'name': 'Restricted industry name'})
        log = self.env['gec.user.audit.log'].sudo().create({
            'event': 'write', 'model': record._name, 'res_id': record.id, 'res_name': record.name})
        reader = new_test_user(self.env, 'gec_audit_field_reader', groups='base.group_system')
        with patch.object(record._fields['name'], 'groups', fields.NO_ACCESS):
            record.invalidate_recordset(['display_name'])
            self.assertEqual(log.with_user(reader).res_name_shown, 'Record (not readable by you)')

    def test_report_dates_include_the_selected_local_calendar_day(self):
        """Timezone and DST boundaries include the start and exclude the next local midnight."""
        cases = [
            ('UTC', '2026-10-23', '2026-10-23 00:00:00', '2026-10-24 00:00:00'),
            ('Asia/Tbilisi', '2026-10-23', '2026-10-22 20:00:00', '2026-10-23 20:00:00'),
            ('Europe/Paris', '2026-03-29', '2026-03-28 23:00:00', '2026-03-29 22:00:00'),
            ('Europe/Paris', '2026-10-25', '2026-10-24 22:00:00', '2026-10-25 23:00:00'),
        ]
        for zone, day, start, end in cases:
            with self.subTest(tz=zone, day=day):
                start, end = datetime.fromisoformat(start), datetime.fromisoformat(end)
                lines = self.env['gec.user.audit.log'].sudo().create([
                    {'event': 'other', 'user_id': self.user.id, 'date': value}
                    for value in (start - timedelta(seconds=1), start, end - timedelta(seconds=1), end)])
                wizard = self.env['gec.user.audit.report.wizard'].with_context(tz=zone).create({
                    'date_from': day, 'date_to': day, 'events': 'all', 'user_ids': [Command.set(self.user.ids)]})
                values = wizard._report_values(wizard.id)
                ids = [line.id for _user, group in values['groups'] for line in group]
                self.assertEqual(set(ids) & set(lines.ids), set(lines[1:3].ids))

    def test_relation_formatting_only_resolves_displayed_changes(self):
        """Unchanged members and truncated differences never require display-name reads."""
        tags = self.env['res.partner.category'].create([{'name': f'Bounded {index:03d}'} for index in range(130)])
        partner = self.env['res.partner'].with_user(self.user).create({'name': 'Bounded relation'})
        looked_up = set()
        original = type(tags)._compute_display_name

        def names(records):
            looked_up.update(records.ids)
            return original(records)

        tags.invalidate_recordset(['display_name'])
        with patch.object(type(tags), '_compute_display_name', names):
            text = partner._gec_audit_texts('category_id', partner.ids, [tuple(tags[:110].ids)],
                                          [tuple((tags[:100] | tags[110:]).ids)])[0]
        self.assertTrue(looked_up)
        self.assertLessEqual(looked_up, set(tags[100:120].ids))
        self.assertIn('+Bounded 110', text)
        self.assertIn('-Bounded 100', text)
        self.assertIn('(+10 more)', text)
        tags[0].name = 'x' * 500
        text = partner._gec_audit_texts('category_id', partner.ids, [()], [(tags[0].id,)])[0]
        self.assertEqual(text, '+' + 'x' * 200 + '...')

    def test_a_sign_in_is_logged_when_the_session_opens_not_at_the_password(self):
        user = self.user
        credential = {'login': user.login, 'password': user.login, 'type': 'password'}
        self.env['res.users']._login(credential, {'interactive': True})
        self.assertFalse(self._logs(user_id=user.id, event='login'))
        user._after_session_login()
        self.assertEqual(len(self._logs(user_id=user.id, event='login')), 1)

    def test_an_api_sign_in_is_logged_at_the_password(self):
        credential = {'login': self.user.login, 'password': self.user.login, 'type': 'password'}
        self.env['res.users']._login(credential, {'interactive': False})
        logins = self._logs(user_id=self.user.id, event='login')
        self.assertEqual((len(logins), logins.detail), (1, 'API'))

    def test_ending_a_session_asks_for_the_identity(self):
        sessions = self.env['res.session'].with_user(self.env.ref('base.user_admin'))
        with self.assertRaises(UserError):
            sessions.action_gec_end()
        request_reset = request_var.set(fake_request(self.env, identity_checked=False))
        self.addCleanup(request_var.reset, request_reset)
        self.assertEqual(sessions.action_gec_end()['res_model'], 'res.users.identitycheck')
        self.assertEqual(self.env.ref('base.user_admin').action_gec_end_sessions()['res_model'],
                         'res.users.identitycheck')

    def test_old_lines_are_deleted_in_batches_until_the_cron_runs_out_of_time(self):
        Log = self.env['gec.user.audit.log'].sudo()
        old = Log.create([{'event': 'other', 'date': fields.Datetime.now() - timedelta(days=100)}] * 2)
        self.assertEqual(old[0].event, 'other')
        limit = fields.Datetime.now() - timedelta(days=90)
        cron = type(self.env['ir.cron'])
        with patch.object(cron, '_commit_progress', return_value=0) as progress:
            done = Log.with_context(ir_cron_progress_id=1)._gec_delete_before(limit, [('id', 'in', old.ids)], batch=1)
        self.assertFalse(done)
        self.assertEqual(progress.call_count, 1)
        self.assertEqual(len(old.exists()), 1)
        with self.assertRaises(MissingError):
            old[0].event
        self.assertTrue(Log._gec_delete_before(limit, [('id', 'in', old.ids)]))
        self.assertFalse(old.exists())


@tagged('post_install', '-at_install')
class TestAuditHttp(AuditMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-user-audit-pw-1'
        cls.user = new_test_user(cls.env, 'gec_audit_http', password=cls.password,
                                 groups='base.group_user,base.group_partner_manager,base.group_allow_export')
        cls.partner = cls.env['res.partner'].create({'name': 'Read Me'})

    def _call(self, model, method, args, kwargs=None):
        return self.make_jsonrpc_request(f'/web/dataset/call_kw/{model}/{method}', {
            'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {}})

    def test_sign_in_read_export_print_and_sign_out(self):
        self.env['ir.config_parameter'].sudo().set_bool('gec_user_audit.log_reads', True)
        self.authenticate(self.user.login, self.password)
        self.assertEqual(len(self._logs(user_id=self.user.id, event='login')), 1)
        self._call('res.partner', 'web_search_read', [], {
            'domain': [('id', '=', self.partner.id)], 'specification': {'name': {}}})
        read = self._logs(user_id=self.user.id, event='read')
        self.assertEqual((len(read), read.method, read.record_ids), (1, 'web_search_read', str(self.partner.id)))
        data = json.dumps({'model': 'res.partner', 'ids': self.partner.ids, 'domain': [], 'import_compat': False,
                           'fields': [{'name': 'name', 'label': 'Name'}]})
        self.url_open('/web/export/csv', data={'data': data, 'csrf_token': self.csrf_token()})
        export = self._logs(user_id=self.user.id, event='export')
        self.assertEqual((len(export), export.record_count), (1, 1))
        # the export reads nothing more in the log
        self.assertEqual(len(self._logs(user_id=self.user.id, event='read')), 1)
        self.env['ir.ui.view'].create({
            'name': 'gec_user_audit.test_partner', 'type': 'qweb', 'key': 'gec_user_audit.test_partner',
            'arch': '<t t-name="gec_user_audit.test_partner"><p t-foreach="docs" t-as="o" t-out="o.name"/></t>'})
        self.env['ir.actions.report'].create({
            'name': 'Partner Sheet', 'model': 'res.partner', 'report_type': 'qweb-html',
            'report_name': 'gec_user_audit.test_partner'})
        self.assertIn('Read Me', self.url_open(f'/report/html/gec_user_audit.test_partner/{self.partner.id}').text)
        printed = self._logs(user_id=self.user.id, event='print')
        self.assertEqual((len(printed), printed.res_id, printed.detail), (1, self.partner.id, 'Partner Sheet'))
        self.url_open('/web/session/logout', data={'csrf_token': self.csrf_token()})
        self.assertEqual(len(self._logs(user_id=self.user.id, event='logout')), 1)

    def _read_partner(self):
        self.authenticate(self.user.login, self.password)
        self._call('res.partner', 'web_search_read', [], {
            'domain': [('id', '=', self.partner.id)], 'specification': {'name': {}}})

    def test_reads_are_not_logged_by_default(self):
        self.env['ir.config_parameter'].sudo().search([('key', '=', 'gec_user_audit.log_reads')]).unlink()
        self._read_partner()
        self.assertFalse(self._logs(user_id=self.user.id, event='read'))

    def test_rpc_context_cannot_disable_change_or_read_auditing(self):
        """Client-controlled context cannot silence normal CRUD and read hooks."""
        self.env['ir.config_parameter'].sudo().set_bool('gec_user_audit.log_reads', True)
        self.authenticate(self.user.login, self.password)
        context = {'gec_user_audit_off': True}
        id_ = self._call('res.partner', 'create', [{'name': 'RPC context audit'}], {'context': context})
        self._call('res.partner', 'write', [[id_], {'phone': '123'}], {'context': context})
        self._call('res.partner', 'read', [[id_], ['phone']], {'context': context})
        self._call('res.partner', 'unlink', [[id_]], {'context': context})
        logs = self._logs(model='res.partner', res_id=id_, user_id=self.user.id)
        self.assertEqual(sorted(logs.mapped('event')), ['create', 'unlink', 'write'])
        reads = self._logs(model='res.partner', user_id=self.user.id, event='read', method='read')
        self.assertEqual((len(reads), reads.record_ids), (1, str(id_)))

    def test_public_read_entry_points_each_log_once(self):
        """Searches, lookups, grouped reads and translations keep one event per request."""
        self.env['ir.config_parameter'].sudo().set_bool('gec_user_audit.log_reads', True)
        self.authenticate(self.user.login, self.password)
        domain = [('id', '=', self.partner.id)]
        calls = [
            ('search', [domain], {}),
            ('search_count', [domain], {}),
            ('name_search', [], {'name': self.partner.name, 'domain': domain}),
            ('web_name_search', [self.partner.name, {'name': {}}], {'domain': domain}),
            ('read_group', [domain, ['active'], ['__count']], {}),
            ('formatted_read_grouping_sets', [domain, [['active'], []], ['__count']], {}),
            ('get_field_translations', [self.partner.ids, 'name'], {}),
        ]
        for method, args, kwargs in calls:
            with self.subTest(method=method):
                before = self._logs(model='res.partner', user_id=self.user.id, event='read')
                self._call('res.partner', method, args, kwargs)
                added = self._logs(model='res.partner', user_id=self.user.id, event='read') - before
                self.assertEqual((len(added), added.method), (1, method))

    @mute_logger('odoo.addons.rpc.controllers.xmlrpc')
    def test_product_lookups_are_logged_when_the_override_skips_super(self):
        """Concrete product lookups retain coverage through HTTP and XML-RPC boundaries."""
        if 'product.product' not in self.env:
            self.skipTest('product is not installed')
        self.env['ir.config_parameter'].sudo().set_bool('gec_user_audit.log_reads', True)
        product = self.env['product.product'].create({'name': 'Unique audit lookup', 'default_code': 'AUDITLOOKUP'})
        self.authenticate(self.user.login, self.password)
        result = self._call('product.product', 'name_search', [], {'name': 'AUDITLOOKUP'})
        self.assertIn(product.id, [id_ for id_, _name in result])
        logs = self._logs(model='product.product', user_id=self.user.id, event='read', method='name_search')
        self.assertEqual((len(logs), logs.record_ids), (1, str(product.id)))
        result = self.xmlrpc_object.execute_kw(self.env.cr.dbname, self.user.id, self.password,
                                              'product.product', 'name_search', [], {'name': 'AUDITLOOKUP'})
        self.assertIn(product.id, [id_ for id_, _name in result])
        logs = self._logs(model='product.product', user_id=self.user.id, event='read', method='name_search')
        self.assertEqual(len(logs), 2)
        self.assertEqual(set(logs.mapped('record_ids')), {str(product.id)})
        self.assertEqual(set(logs.mapped('ip')), {'127.0.0.1'})

    def test_json2_product_lookup_is_audited_once_despite_context_bypass(self):
        """JSON-2 records final concrete lookup results and ignores an audit-off context."""
        if 'product.product' not in self.env:
            self.skipTest('product is not installed')
        self.env['ir.config_parameter'].sudo().set_bool('gec_user_audit.log_reads', True)
        product = self.env['product.product'].create({
            'name': 'JSON-2 audit lookup', 'default_code': 'AUDITJSON2LOOKUP'})
        key = self.env['res.users.apikeys'].with_user(self.user)._generate(
            'rpc', 'Audit lookup regression', datetime.now() + timedelta(days=1))
        response = self.url_open('/json/2/product.product/name_search', json={
            'name': 'AUDITJSON2LOOKUP', 'context': {'gec_user_audit_off': True},
        }, headers={'Authorization': f'bearer {key}', 'X-Odoo-Database': self.env.cr.dbname})
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertIn(product.id, [id_ for id_, _name in response.json()])
        logs = self._logs(model='product.product', user_id=self.user.id, event='read', method='name_search')
        self.assertEqual((len(logs), logs.record_ids, logs.record_count), (1, str(product.id), 1))

    def test_a_rule_ticking_read_logs_reads_whatever_the_setting(self):
        self.env['ir.config_parameter'].sudo().set_bool('gec_user_audit.log_reads', False)
        self.env['gec.user.audit.rule'].create({'name': 'Reads', 'log_read': True})
        self._read_partner()
        self.assertEqual(len(self._logs(user_id=self.user.id, event='read')), 1)

    def test_a_failed_sign_in_survives_the_rollback(self):
        with self.assertRaises(AccessDenied):
            self.env['res.users'].with_context(active_test=False)._login(
                {'login': self.user.login, 'password': 'wrong', 'type': 'password'}, {'interactive': True})
        # what a rollback does: drop the commit hooks and their data, then run the rollback hooks
        self.env.cr.postcommit.clear()
        self.env.cr.postrollback.run()
        failed = self._logs(event='login_failed', login=self.user.login)
        self.assertEqual((len(failed), failed.user_id), (1, self.user))

    @mute_logger('odoo.addons.rpc.controllers.xmlrpc')
    def test_xmlrpc_reads_are_logged_with_the_address(self):
        self.env['ir.config_parameter'].sudo().set_bool('gec_user_audit.log_reads', True)
        self.xmlrpc_object.execute_kw(self.env.cr.dbname, self.user.id, self.password,
                                      'res.partner', 'read', [self.partner.ids, ['name']])
        read = self._logs(user_id=self.user.id, event='read', method='read')
        self.assertEqual(len(read), 1)
        self.assertEqual(read.ip, '127.0.0.1')

    def test_an_idle_session_is_ended(self):
        self.env['ir.config_parameter'].sudo().set_int('gec_user_audit.idle_minutes', 5)
        session = self.authenticate(self.user.login, self.password)
        session[SEEN_KEY] = time.time() - 600
        session_store().save(session)
        response = self.url_open('/odoo', allow_redirects=False)
        self.assertIn('/web/login', response.headers.get('Location', ''))
        self.assertEqual(len(self._logs(user_id=self.user.id, event='session_end')), 1)

    def _sign_in(self):
        """ Sign in through the login form, as a person does. """
        self.authenticate(None, None)
        response = self.url_open('/web/login', data={
            'login': self.user.login, 'password': self.password, 'csrf_token': self.csrf_token()},
            allow_redirects=False)
        self.assertEqual(response.status_code, 303)

    def test_ending_a_session(self):
        # the test sessions leave no device trace unless asked to
        self.authenticate(self.user.login, self.password, session_extra={'_trace_disable': False})
        self.url_open('/odoo')
        self.env.invalidate_all()
        sessions = self.env['res.session'].sudo().search([('user_id', '=', self.user.id)])
        self.assertTrue(sessions)
        request_reset = request_var.set(fake_request(self.env, identity_checked=True))
        try:
            sessions.with_user(self.env.ref('base.user_admin')).action_gec_end()
        finally:
            request_var.reset(request_reset)
        response = self.url_open('/odoo', allow_redirects=False)
        self.assertIn('/web/login', response.headers.get('Location', ''))
        self.assertEqual(len(self._logs(user_id=self.user.id, event='session_end')), 1)

    def _idle_session(self):
        """ A session of the user, opened and idle for a day, with the cron on. """
        self.env['ir.config_parameter'].sudo().set_int('gec_user_audit.idle_minutes', 5)
        session = self.authenticate(self.user.login, self.password, session_extra={'_trace_disable': False})
        self.url_open('/odoo')
        self.env.invalidate_all()
        self.env['res.device.log'].sudo().search([('user_id', '=', self.user.id)]).write(
            {'last_activity': fields.Datetime.now() - timedelta(days=1)})
        self.env['res.device.log'].flush_model()
        self.assertTrue(self.env['res.session'].sudo().search([('user_id', '=', self.user.id)]))
        return session

    def test_the_idle_cron_ends_an_open_session_once(self):
        self._idle_session()
        self.env['res.session'].sudo()._cron_end_idle()
        self.assertEqual(len(self._logs(user_id=self.user.id, event='session_end')), 1)

    def test_the_idle_cron_skips_a_session_already_signed_out(self):
        session = self._idle_session()
        session_store().delete(session)
        self.env['res.session'].sudo()._cron_end_idle()
        self.assertFalse(self._logs(user_id=self.user.id, event='session_end'))

    def test_every_sign_out_is_logged_once(self):
        self.authenticate(self.user.login, self.password)
        self.make_jsonrpc_request('/web/session/destroy', {})
        self.assertEqual(len(self._logs(user_id=self.user.id, event='logout')), 1)

    def test_the_first_new_device_sign_in_sends_an_email(self):
        """The current login must not count as prior device history for its own email."""
        self.user.email = 'new-device-audit@example.com'
        params = self.env['ir.config_parameter'].sudo()
        params.set_str('gec_user_audit.sign_in_mail', 'user')
        params.set_bool('gec_user_audit.sign_in_mail_new_only', True)
        self._sign_in()
        mails = self.env['mail.mail'].sudo().search([('subject', 'ilike', self.user.name)])
        self.assertEqual(len(mails), 1)
        self._sign_in()
        self.assertEqual(self.env['mail.mail'].sudo().search_count([('subject', 'ilike', self.user.name)]), 1)

    def test_the_sign_in_email(self):
        self.user.email = 'audit@example.com'
        params = self.env['ir.config_parameter'].sudo()
        params.set_str('gec_user_audit.sign_in_mail', 'user')
        self._sign_in()
        mails = self.env['mail.mail'].sudo().search([('subject', 'ilike', self.user.name)])
        self.assertEqual(mails.recipient_ids, self.user.partner_id)
        # only from a new device: the second sign-in from the same browser sends nothing
        params.set_bool('gec_user_audit.sign_in_mail_new_only', True)
        with patch.object(type(self.env['res.users']), '_gec_sign_in_mail', autospec=True,
                          side_effect=type(self.env['res.users'])._gec_sign_in_mail) as sent:
            self._sign_in()
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(len(self.env['mail.mail'].sudo().search([('subject', 'ilike', self.user.name)])), 1)

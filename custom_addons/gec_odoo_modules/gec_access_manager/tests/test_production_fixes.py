# Rule A: an access manager outside Settings sees only what they can read: the names of records in the Explain
# wizard and in the allowed records, and the fields a record filter reads. HR stands in for the hidden data.
# Rule D: a rule is never served stale or half applied: a record filter follows one field of the user, the cache
# clears after an employee changes, and the cron refreshes one assignment at a time.
# Rule B: the preview asks for the password first, as core does before an API key.
# Rule C: a lock stops what the client sends; what Odoo copies or derives meanwhile passes the same way on every
# door (no silent divergence); the API refuses a locked value instead of dropping it.
import xmlrpc.client
from datetime import datetime, timedelta
from unittest import SkipTest
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain
from odoo.http.session import session_store
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.gec_access_manager.models import gec_access_allowed
from odoo.addons.gec_access_manager.models.gec_access_preview import PREVIEW_KEY
from odoo.addons.gec_access_manager.models.value_filters import check_filter

from .test_fixes import ClientCalls

MANAGER = 'gec_access_manager.group_access_manager'
HIDDEN = 'Record (not readable by you)'
# (model, filter): the wage straight, along a path, inside an any and behind an id
WAGE_FILTERS = (
    ('hr.version', "[('wage', '>', 5000)]"),
    ('hr.version', "[('id', 'any', [('wage', '>', 5000)])]"),
    ('hr.employee', "[('version_id.wage', '>', 5000)]"),
    ('hr.employee', "[('version_id', 'any', [('wage', '>', 5000)])]"),
    ('hr.employee', "[('version_id', 'not any', [('wage', '>', 5000)])]"),
)


@tagged('post_install', '-at_install')
class TestRuleA(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'hr.version' not in cls.env:
            raise SkipTest("hr is not installed")
        company = cls.env.company.id
        cls.manager = new_test_user(cls.env, 'gec_rule_a_manager', company_id=company,
                                    groups=f'base.group_user,{MANAGER}')
        cls.hr_manager = new_test_user(cls.env, 'gec_rule_a_hr_manager', company_id=company,
                                       groups=f'base.group_user,hr.group_hr_user,{MANAGER}')
        cls.settings = new_test_user(cls.env, 'gec_rule_a_settings', company_id=company,
                                     groups=f'base.group_user,base.group_system,{MANAGER}')
        cls.target = new_test_user(cls.env, 'gec_rule_a_target', company_id=company, groups='base.group_user')
        cls.employee = cls.env['hr.employee'].create({'name': 'Secret Person'})

    def _explain(self, user, model_name, res_id, companies=None):
        return self.env['gec.access.explain'].with_user(user).with_context(
            allowed_company_ids=(companies or self.env.company).ids,
        ).create({
            'user_id': self.target.id,
            'model_id': self.env['ir.model']._get(model_name).id,
            'res_id': res_id,
            'operation': 'read',
        })

    def _line(self, user, model_name, values, sudo=False):
        """ A line on a fresh profile: a profile has one line per model. """
        Line = self.env['gec.access.profile.model'].with_user(user)
        return (Line.sudo() if sudo else Line).create({
            'profile_id': self.env['gec.access.profile'].create({'name': 'Rule A'}).id,
            'model_id': self.env['ir.model']._get(model_name).id,
            **values,
        })

    def _field_line(self, user, model_name, field_name, values, sudo=False):
        """ A field rule on a fresh profile: a profile has one rule per field. """
        Line = self.env['gec.access.profile.field'].with_user(user)
        return (Line.sudo() if sudo else Line).create({
            'profile_id': self.env['gec.access.profile'].create({'name': 'Rule A'}).id,
            'model_id': self.env['ir.model']._get(model_name).id,
            'field_id': self.env['ir.model.fields']._get(model_name, field_name).id,
            'mode': 'hide',
            **values,
        })

    def test_explain_hides_the_name_of_a_record_the_manager_cannot_read(self):
        self.assertFalse(self.employee.with_user(self.manager).has_access('read'))
        wizard = self._explain(self.manager, 'hr.employee', self.employee.id)
        self.assertEqual(wizard.record_name, HIDDEN)
        self.assertNotIn(self.employee.name, str(wizard.report))
        self.assertEqual(wizard.verdict, self._explain(self.manager, 'hr.employee', 0).verdict,
                         "the verdict is the one of the model")

    def test_explain_gives_the_same_text_for_a_missing_record(self):
        missing = self.employee.id + 100000
        self.assertEqual(self._explain(self.manager, 'hr.employee', missing).record_name, HIDDEN)
        self.assertFalse(self._explain(self.settings, 'hr.employee', missing).record_name)

    def test_explain_keeps_the_name_for_a_reader(self):
        for user in (self.hr_manager, self.settings):
            with self.subTest(user=user.login):
                wizard = self._explain(user, 'hr.employee', self.employee.id)
                self.assertEqual(wizard.record_name, self.employee.name)
                self.assertIn(self.employee.name, str(wizard.report))

    def test_explain_judges_the_reader_in_all_their_companies(self):
        second = self.env['res.company'].create({'name': 'Rule A second company'})
        reader = new_test_user(
            self.env, 'gec_rule_a_two_companies', company_id=self.env.company.id,
            company_ids=[Command.set([self.env.company.id, second.id])], groups=f'base.group_user,{MANAGER}')
        partner = self.env['res.partner'].create({'name': 'Second company partner', 'company_id': second.id})
        self.assertFalse(partner.with_user(reader).with_context(
            allowed_company_ids=self.env.company.ids).has_access('read'))
        self.assertEqual(self._explain(reader, 'res.partner', partner.id).record_name, partner.name)

    def test_a_filter_on_a_field_the_editor_cannot_read_is_refused(self):
        Version = self.env['hr.version'].with_user(self.hr_manager)
        with self.assertRaises(AccessError):
            Version.check_field_access(Version._fields['wage'], 'read')
        for model_name, domain in WAGE_FILTERS:
            for sudo in (False, True):
                with self.subTest(model=model_name, domain=domain, sudo=sudo), self.assertRaises(ValidationError):
                    self._line(self.hr_manager, model_name, {'domain': domain}, sudo=sudo)

    def test_a_condition_on_a_field_the_editor_cannot_read_is_refused(self):
        """ A condition is judged as the superuser: the member would see a yes or no on the hidden wage. """
        condition = 'wage > 5000'
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(ValidationError):
                self._field_line(self.hr_manager, 'hr.version', 'department_id', {'condition': condition}, sudo=sudo)
        line = self._field_line(self.settings, 'hr.version', 'department_id', {'condition': condition})
        self.assertEqual(line.condition, condition)
        readable = 'department_id != False'
        line = self._field_line(self.hr_manager, 'hr.version', 'department_id', {'condition': readable})
        self.assertEqual(line.condition, readable)

    def test_a_value_filter_on_a_field_the_editor_cannot_read_is_refused(self):
        """ A value filter reads the record's fields by name, as the superuser. """
        domain = "[('id', 'in', [wage])]"
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(ValidationError):
                self._field_line(self.hr_manager, 'hr.version', 'department_id', {'field_domain': domain}, sudo=sudo)
        line = self._field_line(self.settings, 'hr.version', 'department_id', {'field_domain': domain})
        self.assertEqual(line.field_domain, domain)
        readable = "[('company_id', '=', company_id)]"
        line = self._field_line(self.hr_manager, 'hr.version', 'department_id', {'field_domain': readable})
        self.assertEqual(line.field_domain, readable)

    def test_a_value_filter_moved_to_another_model_is_checked_again(self):
        """ The filter reads `wage` by name: harmless on a contact, a leak once the line points at hr.version. """
        domain = "[('id', 'in', [wage])]"
        line = self._field_line(self.hr_manager, 'res.partner', 'country_id', {'field_domain': domain})
        with self.assertRaises(ValidationError):
            line.with_user(self.hr_manager).write({'model_id': self.env['ir.model']._get('hr.version').id})

    def test_a_value_filter_on_a_field_of_its_comodel_the_editor_cannot_read_is_refused(self):
        """ The filter is searched on the comodel as the superuser: a manager without HR could read the birthdays
        of the employees one yes or no at a time. The field is a manager of a department: a Many2one to
        hr.employee. """
        paths = ("[('birthday', '<', '1990-01-01')]",
                 "[('parent_id', 'any', [('birthday', '<', '1990-01-01')])]",
                 "['|', ('name', 'ilike', 'a'), ('birthday', '<', '1990-01-01')]")
        for domain in paths:
            with self.subTest(domain=domain):
                with self.assertRaises(ValidationError):
                    self._field_line(self.manager, 'hr.department', 'manager_id', {'field_domain': domain})
                with self.assertRaises(ValidationError):
                    self._field_line(self.manager, 'hr.department', 'manager_id', {'field_domain': domain}, sudo=True)
                for user in (self.hr_manager, self.settings):
                    self.assertEqual(
                        self._field_line(user, 'hr.department', 'manager_id', {'field_domain': domain}).field_domain,
                        domain)
        readable = "[('parent_id', 'any', [('name', 'ilike', 'a')])]"
        self.assertEqual(
            self._field_line(self.manager, 'hr.department', 'manager_id', {'field_domain': readable}).field_domain,
            readable)

    def test_the_presets_save_for_a_manager_without_access_to_the_employees(self):
        self.assertFalse(self.env['hr.employee'].with_user(self.manager).has_access('read'))
        for model_name in ('hr.employee', 'hr.version'):
            presets = self.env['gec.access.profile.model']._preset_domains(model_name)
            for preset in ('own', 'hierarchy'):
                with self.subTest(model=model_name, preset=preset):
                    self.assertIn(preset, presets)
                    field_name, domain = presets[preset]
                    self.assertEqual(self._line(self.manager, model_name, {field_name: domain})[field_name], domain)

    def test_a_settings_user_saves_a_filter_on_any_field(self):
        for model_name, domain in WAGE_FILTERS:
            with self.subTest(model=model_name, domain=domain):
                self.assertEqual(self._line(self.settings, model_name, {'domain': domain}).domain, domain)

    def test_an_allowed_line_shows_only_the_name_of_a_record_the_user_can_read(self):
        kinds = {'gec_test': ('Employees', 'hr.employee', {}), 'gec_test_partner': ('Partners', 'res.partner', {})}
        patcher = patch.dict(gec_access_allowed.ALLOWED_KINDS, kinds)
        patcher.start()
        self.addCleanup(patcher.stop)
        partner = self.env['res.partner'].create({'name': 'Visible partner'})
        profile = self.env['gec.access.profile'].create({'name': 'Rule A allowed'})
        lines = self.env['gec.access.allowed'].create([
            {'profile_id': profile.id, 'kind': 'gec_test', 'res_id': self.employee.id},
            {'profile_id': profile.id, 'kind': 'gec_test_partner', 'res_id': partner.id},
        ])
        employee_line, partner_line = lines
        self.assertEqual(lines.with_user(self.manager).mapped('display_name'), [HIDDEN, partner.name])
        self.assertEqual(employee_line.with_user(self.settings).display_name, self.employee.name)
        self.assertEqual(employee_line.with_user(self.hr_manager).display_name, self.employee.name)
        self.assertEqual(employee_line.with_user(self.manager).display_name, HIDDEN)
        self.env.invalidate_all()
        self.assertEqual(employee_line.with_user(self.manager).sudo().display_name, HIDDEN)

    def test_an_allowed_line_cannot_be_pointed_at_another_model(self):
        """ The record of a line follows its kind: a model written over RPC would carry its name into the
        profile's versions and export, which every access manager reads. """
        patcher = patch.dict(gec_access_allowed.ALLOWED_KINDS, {'gec_test_partner': ('Partners', 'res.partner', {})})
        patcher.start()
        self.addCleanup(patcher.stop)
        partner = self.env['res.partner'].create({'name': 'Visible partner'})
        line = self.env['gec.access.allowed'].create({
            'profile_id': self.env['gec.access.profile'].create({'name': 'Rule A forged'}).id,
            'kind': 'gec_test_partner', 'res_id': partner.id,
        })
        self.assertEqual(line.res_model, 'res.partner')
        for user in (self.manager, self.settings):
            for sudo in (False, True):
                with self.subTest(user=user.login, sudo=sudo), self.assertRaises(ValidationError):
                    target = line.with_user(user)
                    (target.sudo() if sudo else target).write({'res_model': 'hr.employee', 'res_id': self.employee.id})
        self.assertEqual(line.res_model, 'res.partner')


@tagged('post_install', '-at_install')
class TestRuleD(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'hr.version' not in cls.env:
            raise SkipTest("hr is not installed")
        cls.company = cls.env.company
        cls.user = new_test_user(cls.env, 'gec_rule_d_user', company_id=cls.company.id,
                                 groups='base.group_user,hr.group_hr_user')

    def _filter(self, domain):
        """ A record filter on the employees, on a fresh profile of the user (a profile has one line per model). """
        profile = self.env['gec.access.profile'].create({'name': 'Rule D', 'user_ids': [Command.set(self.user.ids)]})
        return self.env['gec.access.profile.model'].create({
            'profile_id': profile.id, 'model_id': self.env['ir.model']._get('hr.employee').id, 'domain': domain})

    def _seen(self, *employees):
        found = self.env['hr.employee'].with_user(self.user).search([('id', 'in', [e.id for e in employees])])
        return set(found.ids)

    def test_a_record_filter_follows_one_field_of_the_user_at_most(self):
        with self.assertRaises(ValidationError):
            self._filter("[('department_id', '=', user.employee_id.department_id.id)]")
        for domain in ("[('id', '=', user.employee_id.id)]", "[('department_id.member_ids.user_id', '=', uid)]"):
            with self.subTest(domain=domain):
                self.assertEqual(self._filter(domain).domain, domain)

    def test_a_value_filter_keeps_its_long_chains(self):
        users = self.env['res.users']
        for text in ("[('id', '=', user.employee_id.department_id.id)]",
                     "[('id', '=', user.company_id.partner_id.id)]"):
            with self.subTest(text=text):
                check_filter(text, users, value_filter=True)
                with self.assertRaises(ValueError):
                    check_filter(text, users)

    def test_a_join_filter_follows_the_department_of_the_version(self):
        d1, d2 = self.env['hr.department'].create([{'name': 'Rule D 1'}, {'name': 'Rule D 2'}])
        Employee = self.env['hr.employee']
        mine = Employee.create({'name': 'Rule D mine', 'user_id': self.user.id, 'department_id': d1.id})
        in_d1 = Employee.create({'name': 'Rule D in 1', 'department_id': d1.id})
        in_d2 = Employee.create({'name': 'Rule D in 2', 'department_id': d2.id})
        self._filter("[('department_id.member_ids.user_id', '=', uid)]")
        self.assertEqual(self._seen(mine, in_d1, in_d2), {mine.id, in_d1.id})
        mine.version_id.write({'department_id': d2.id})
        self.env.flush_all()
        self.assertEqual(self._seen(mine, in_d1, in_d2), {mine.id, in_d2.id})

    def test_the_employee_of_the_user_is_seen_at_once(self):
        Employee = self.env['hr.employee']
        other = Employee.create({'name': 'Rule D other'})
        self._filter("[('id', '=', user.employee_id.id)]")
        self.assertEqual(self._seen(other), set(), "the user has no employee yet: the filter is cached")
        mine = Employee.create({'name': 'Rule D mine', 'user_id': self.user.id})
        self.assertEqual(self._seen(other, mine), {mine.id})

    def test_an_employee_linked_to_the_user_by_a_write_is_seen_at_once(self):
        """ The clear runs after super(): before it, the access check inside the write caches the old link. """
        Employee = self.env['hr.employee']
        other = Employee.create({'name': 'Rule D other'})
        self._filter("[('id', '=', user.employee_id.id)]")
        self.assertEqual(self._seen(other), set(), "the user has no employee yet: the filter is cached")
        other.write({'user_id': self.user.id})
        self.assertEqual(self._seen(other), {other.id})

    def test_a_record_filter_takes_only_what_a_write_of_the_user_changes(self):
        users = self.env['res.users']
        for text in ("[('id', 'in', user.employee_ids.ids)]", "[('id', 'in', user.all_employee_ids.ids)]",
                     "[('id', '=', user.employee_id.id)]", "[('id', '=', user.company_id.id)]"):
            with self.subTest(text=text):
                check_filter(text, users)
        for name, suffix in (('sale_team_id', 'id'), ('crm_team_member_ids', 'ids')):
            if name in users._fields:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    check_filter("[('id', 'in', user.%s.%s)]" % (name, suffix), users)

    def test_a_handover_between_two_managers_moves_both_together(self):
        """ Neither start alone is allowed: the manager leaving is still locked out when the next one starts. """
        group = self.env.ref('gec_access_manager.group_access_manager')
        leaving, arriving = [new_test_user(
            self.env, login, company_id=self.company.id,
            groups='base.group_system,gec_access_manager.group_access_manager')
            for login in ('gec_rule_d_leaving', 'gec_rule_d_arriving')]
        group.write({'user_ids': [Command.set((leaving | arriving).ids)]})
        self.env.transaction.invalidate_ormcache('default')
        self.assertEqual(group.all_user_ids.filtered('active'), leaving | arriving)
        Profile = self.env['gec.access.profile']
        Assignment = self.env['gec.access.profile.assignment']
        first = Profile.create({'name': 'Rule D first', 'block_login': True, 'apply_to_admin': True})
        second = Profile.create({'name': 'Rule D second', 'block_login': True, 'apply_to_admin': True})
        day0 = datetime(2026, 3, 10, 12, 0)
        day1 = day0 + timedelta(days=1)
        with freeze_time(day0):
            ending = Assignment.create({
                'profile_id': first.id, 'user_id': leaving.id,
                'date_from': day0.date() - timedelta(days=5), 'date_to': day0.date()})
            starting = Assignment.create({'profile_id': second.id, 'user_id': arriving.id, 'date_from': day1.date()})
        with freeze_time(day1):
            with self.assertNoLogs('odoo.addons.gec_access_manager.models.gec_access_membership', 'WARNING'):
                Assignment._cron_refresh()
        ending.invalidate_recordset()
        starting.invalidate_recordset()
        self.assertEqual((ending.state, starting.state), ('ended', 'active'))
        self.assertFalse(self.env['mail.message'].search_count([
            ('model', '=', 'gec.access.profile'), ('res_id', 'in', (first | second).ids),
            ('body', 'ilike', 'could not be applied')]))

    def test_deleting_an_employee_clears_the_cached_rules(self):
        self._filter("[('id', '=', user.employee_id.id)]")
        mine = self.env['hr.employee'].create({'name': 'Rule D mine', 'user_id': self.user.id})
        with patch.object(type(self.env.transaction), 'invalidate_ormcache') as invalidate:
            mine.unlink()
        self.assertIn('default', [call.args[0] for call in invalidate.call_args_list if call.args])

    def test_the_cron_refreshes_one_assignment_at_a_time(self):
        """ A start that would lock out the only access manager stays planned and is noted once a day; the
        assignment ending the same day still ends. """
        group = self.env.ref('gec_access_manager.group_access_manager')
        manager = new_test_user(self.env, 'gec_rule_d_manager', company_id=self.company.id,
                                groups='base.group_system,gec_access_manager.group_access_manager')
        group.write({'user_ids': [Command.set(manager.ids)]})
        self.env.transaction.invalidate_ormcache('default')
        self.assertEqual(group.all_user_ids.filtered('active'), manager, "the lock out must be reachable")
        Profile = self.env['gec.access.profile']
        Assignment = self.env['gec.access.profile.assignment']
        blocked = Profile.create({'name': 'Rule D blocked', 'block_login': True, 'apply_to_admin': True})
        quiet = Profile.create({'name': 'Rule D quiet'})
        day0 = datetime(2026, 3, 10, 12, 0)
        day1 = day0 + timedelta(days=1)
        with freeze_time(day0):
            ending = Assignment.create({
                'profile_id': quiet.id, 'user_id': self.user.id,
                'date_from': day0.date() - timedelta(days=5), 'date_to': day0.date()})
            starting = Assignment.create({'profile_id': blocked.id, 'user_id': manager.id, 'date_from': day1.date()})
        logger = 'odoo.addons.gec_access_manager.models.gec_access_membership'
        with freeze_time(day1):
            for run in (1, 2):
                with self.subTest(run=run), self.assertLogs(logger, 'WARNING'):
                    Assignment._cron_refresh()
                ending.invalidate_recordset()
                starting.invalidate_recordset()
                self.assertEqual((ending.state, ending.active), ('ended', False))
                self.assertEqual(starting.state, 'planned')
                self.assertEqual(self.env['mail.message'].search_count([
                    ('model', '=', 'gec.access.profile'), ('res_id', '=', blocked.id),
                    ('body', 'ilike', 'could not be applied')]), 1)


@tagged('post_install', '-at_install')
class TestRuleB(ClientCalls, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, 'gec_rule_b_manager', groups=f'base.group_user,base.group_system,{MANAGER}')
        cls.user = new_test_user(cls.env, 'gec_rule_b_user', groups='base.group_user')

    def setUp(self):
        super().setUp()
        self.authenticate(self.manager.login, self.manager.login)

    def _session(self):
        return session_store().get(self.opener.cookies.get('session_id'))

    def test_the_preview_asks_for_the_password_first(self):
        action = self._call('res.users', 'action_gec_preview', [self.user.ids], route='call_button')
        self.assertEqual(action['res_model'], 'res.users.identitycheck')
        self.assertNotIn(PREVIEW_KEY, self._session())

    def test_the_preview_starts_once_the_password_is_confirmed(self):
        action = self._call('res.users', 'action_gec_preview', [self.user.ids], {'back_url': '/odoo/contacts'},
                            route='call_button')
        result = self._call('res.users.identitycheck', 'run_check', [[action['res_id']]],
                            {'context': {'password': self.manager.login}}, route='call_button')
        self.assertEqual(result['type'], 'ir.actions.act_url')
        preview = self._session()[PREVIEW_KEY]
        self.assertEqual((preview['uid'], preview['back']), (self.user.id, '/odoo/contacts'))


@tagged('post_install', '-at_install')
class TestRuleC(ClientCalls, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_user,base.group_partner_manager'
        cls.user = new_test_user(cls.env, 'gec_rule_c_user', groups=groups)
        cls.control = new_test_user(cls.env, 'gec_rule_c_control', groups=groups)
        Partner = cls.env['res.partner']
        cls.company = Partner.create({'name': 'Rule C Company', 'street': 'Old St', 'city': 'Tbilisi', 'ref': 'locked'})
        cls.contact = Partner.create({'name': 'Rule C Contact', 'parent_id': cls.company.id, 'type': 'contact'})

    def _lock(self, name, mode='readonly', condition=False):
        self.env['gec.access.profile'].create({'name': 'Rule C', 'user_ids': [Command.set(self.user.ids)], 'field_ids': [
            Command.create({'model_id': self.env['ir.model']._get('res.partner').id,
                            'field_id': self.env['ir.model.fields']._get('res.partner', name).id,
                            'mode': mode, 'condition': condition})]})

    def _as(self, user):
        self.authenticate(user.login, user.login)

    def _streets(self):
        (self.company | self.contact).invalidate_recordset()
        return self.company.street, self.contact.street

    def test_odoo_keeps_the_company_and_its_contact_in_sync_on_every_door(self):
        """ P5: the street is locked on the company only; the contact's street the user may edit is copied to the
        company by Odoo, through a write, the contact's form, the company's form and XML-RPC alike. """
        self._lock('street', condition="ref == 'locked'")
        self._as(self.user)
        line = [Command.update(self.contact.id, {'street': 'New St'})]
        doors = {
            'write': lambda: self._call('res.partner', 'write', [self.contact.ids, {'street': 'New St'}]),
            'contact form': lambda: self._call('res.partner', 'web_save', [self.contact.ids, {'street': 'New St'}, {}]),
            # the contact edited in the company's Contacts & Addresses
            'company form': lambda: self._call('res.partner', 'web_save', [self.company.ids, {'child_ids': line}, {}]),
            'xmlrpc': lambda: self.xmlrpc_object.execute_kw(
                self.env.cr.dbname, self.user.id, self.user.login, 'res.partner', 'write',
                [self.contact.ids, {'street': 'New St'}]),
        }
        for door, send in doors.items():
            with self.subTest(door=door):
                self.contact.street = 'Old St'
                self.assertEqual(self._streets(), ('Old St', 'Old St'))
                send()
                self.assertEqual(self._streets(), ('New St', 'New St'))
        self._call('res.partner', 'write', [self.company.ids, {'street': 'Company St'}])
        self.assertEqual(self._streets(), ('New St', 'New St'), "the company's own street stays locked")

    def test_a_contact_moved_under_a_company_takes_its_address(self):
        """ Odoo copies the company's address onto the contact, the locked street too, on both doors. """
        self._lock('street')
        Partner = self.env['res.partner']
        self._as(self.user)
        for method, extra in (('write', []), ('web_save', [{}])):
            with self.subTest(method=method):
                loose = Partner.create({'name': f'Rule C Loose {method}', 'type': 'contact'})
                self._call('res.partner', method, [loose.ids, {'parent_id': self.company.id}, *extra])
                (loose | self.company).invalidate_recordset()
                self.assertEqual((loose.parent_id, loose.street, self.company.street),
                                 (self.company, 'Old St', 'Old St'))

    def test_a_contact_created_under_the_company_takes_its_locked_address(self):
        self._lock('street')
        self._as(self.user)
        result = self._call('res.partner', 'web_save', [[], {'name': 'Rule C New', 'parent_id': self.company.id,
                                                              'type': 'contact'}, {'street': {}}])
        self.assertEqual(result[0]['street'], 'Old St')

    def test_a_locked_value_the_user_sends_is_still_dropped_by_the_web_client(self):
        self._lock('street')
        self._as(self.user)
        self._call('res.partner', 'write', [self.contact.ids, {'street': 'New St'}])
        self.assertEqual(self._streets(), ('Old St', 'Old St'))

    @mute_logger('odoo.http')
    def test_the_api_refuses_a_locked_value_the_web_client_drops(self):
        self._lock('street')
        with self.assertRaisesRegex(xmlrpc.client.Fault, "Street"):
            self.xmlrpc_object.execute_kw(self.env.cr.dbname, self.user.id, self.user.login, 'res.partner', 'write',
                                          [self.company.ids, {'street': 'New St', 'city': 'Batumi'}])
        self.company.invalidate_recordset()
        self.assertEqual((self.company.street, self.company.city), ('Old St', 'Tbilisi'))
        self._as(self.user)
        self.assertTrue(self._call('res.partner', 'write', [self.company.ids, {'street': 'New St', 'city': 'Batumi'}]))
        self.company.invalidate_recordset()
        self.assertEqual((self.company.street, self.company.city), ('Old St', 'Batumi'))

    @mute_logger('odoo.http')
    def test_a_hidden_field_behind_an_id_any_is_refused(self):
        """ R3: ``('id', 'any', ...)`` applies its condition to the same records, in a list and in a parsed Domain. """
        self._lock('street', mode='hide')
        domain = [('id', 'any', [('street', '=', 'Old St')])]
        self._as(self.user)
        self.assertIn("'Street'", self._error('res.partner', 'search_read', [domain, ['name']]))
        Partner = self.env['res.partner'].with_user(self.user)
        with self.assertRaises(AccessError):
            Partner._gec_check_domain(Partner._gec_field_rules(), Domain(domain))

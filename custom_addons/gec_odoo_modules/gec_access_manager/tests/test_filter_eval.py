# The text of a filter written in a profile is never run as Python: it is checked when saved
# (record filters and value filters) and evaluated with the restricted evaluator.
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import JsonRpcException
from odoo.tools import mute_logger

from odoo.addons.gec_access_manager.models.base_model import READONLY_OWN_RECORDS
from odoo.addons.gec_access_manager.models.gec_access_allowed import ALLOWED_KINDS
from odoo.addons.gec_access_manager.models.gec_access_profile_model import DRAFT_DOMAIN
from odoo.addons.gec_access_manager.models.value_filters import check_filter

REFUSED = (
    "user.write({'name': 'x'})",
    "context_today()",
    "context.get('x')",
    "user.company_id.user_ids[0]",
    "user.company_id.user_ids[0].totp_secret",
    "user.company_id.name",
    "user.pin",
    "user.employee_id.country_of_birth.id",
    "user.employee_id.current_version_id.departure_id.id",
    "1/0",
    "[0] * 10 ** 9",
    "(lambda: [])()",
    "[x for x in [1]]",
)


@tagged('post_install', '-at_install')
class TestFilterEval(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-filter-pw'
        cls.manager = new_test_user(cls.env, 'gec_filter_manager',
                                    groups='base.group_user,gec_access_manager.group_access_manager',
                                    password=cls.password)
        cls.member = new_test_user(cls.env, 'gec_filter_member',
                                   groups='base.group_user,base.group_partner_manager', password=cls.password)
        cls.system = cls.env.ref('base.group_system')
        cls.profile = cls.env['gec.access.profile'].create({'name': 'Filter eval', 'user_ids': [(6, 0, cls.member.ids)]})
        cls.partner_model = cls.env['ir.model']._get('res.partner')
        cls.country_field = cls.env['ir.model.fields']._get('res.partner', 'country_id')
        cls.be, cls.fr = cls.env.ref('base.be'), cls.env.ref('base.fr')

    def _call(self, model, method, args, kwargs=None):
        return self.make_jsonrpc_request(f'/web/dataset/call_kw/{model}/{method}', {
            'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {},
        })

    def _record_filter(self, domain):
        return self._call('gec.access.profile.model', 'create', [{
            'profile_id': self.profile.id, 'model_id': self.partner_model.id, 'domain': domain}])

    def _value_filter(self, domain):
        return self._call('gec.access.profile.field', 'create', [{
            'profile_id': self.profile.id, 'model_id': self.partner_model.id,
            'field_id': self.country_field.id, 'mode': 'keep', 'field_domain': domain}])

    def _assert_refused(self, create, domain):
        with mute_logger('odoo.http'), self.assertRaises(JsonRpcException) as caught:
            create(domain)
        self.assertEqual(str(caught.exception), 'odoo.exceptions.ValidationError', domain)

    def _search(self, domain):
        return self._call('res.partner', 'search_read', [domain], {'fields': ['id']})

    def test_an_access_manager_cannot_escalate_through_a_record_filter(self):
        self.assertNotIn(self.system, self.manager.all_group_ids)
        self.authenticate(self.manager.login, self.password)
        payload = "[('id', '!=', 0)] if user.write({'group_ids': [(4, %d)]}) else []" % self.system.id
        self._assert_refused(self._record_filter, payload)
        self.env.invalidate_all()
        self.assertNotIn(self.system, self.manager.all_group_ids)
        self.assertFalse(self.profile.model_ids)

    def test_record_filters_reading_more_than_ids_are_refused_at_save(self):
        self.authenticate(self.manager.login, self.password)
        for text in REFUSED:
            self._assert_refused(self._record_filter, "[('id', '=', %s)]" % text)
        self._assert_refused(self._record_filter, "[('id', 'in', [1])] if user.name == 'x' else 1/0")
        self.env.invalidate_all()
        self.assertFalse(self.profile.model_ids)

    def test_value_filters_are_checked_at_save(self):
        self.authenticate(self.manager.login, self.password)
        self._assert_refused(self._value_filter, "[('id', 'in', [1])] if context_today() else []")
        self._assert_refused(self._value_filter, "[('id', '=', parent.country_id.id)]")
        self.env.invalidate_all()
        self.assertFalse(self.profile.field_ids)
        self._assert_refused(self._value_filter, "[('id', 'in', [%s])]" % ', '.join(['1'] * 2000))
        domain = "[('id', 'in', [%d])]" % self.be.id
        line_id = self._value_filter(domain)
        self.assertEqual(self.profile.field_ids.field_domain, domain)
        # a manager who is not a Settings user edits and deletes the rule (its history reads ir.model)
        self._call('gec.access.profile.field', 'write', [[line_id], {'mode': 'readonly'}])
        self._call('gec.access.profile.field', 'unlink', [[line_id]])
        self.env.invalidate_all()
        self.assertFalse(self.profile.field_ids)

    def test_the_filters_the_module_writes_pass_the_checker(self):
        users = self.env['res.users']
        Rule = self.env['gec.access.profile.model']
        domains = [DRAFT_DOMAIN, "['&'] + [('id', 'in', [3])] + [('id', 'in', [5])]",
                   "([('a', '=', 1)]) + ([('b', '=', 2)])"]
        domains += [domain for name in self.env.registry for _field, domain in Rule._preset_domains(name).values()]
        domains += [domain for _operations, domain in READONLY_OWN_RECORDS.values()]
        domains += [template.format(ids=[3, 5]) for _label, _model, templates in ALLOWED_KINDS.values()
                    for template in templates.values()]
        failures = []
        for domain in domains:
            try:
                check_filter(domain, users)
            except ValueError as error:
                failures.append((domain, str(error)))
        self.assertEqual(failures, [])
        for text in REFUSED:
            with self.assertRaises(ValueError, msg=text):
                check_filter(text, users)

    def test_a_preset_still_limits_a_member_to_their_own_records(self):
        Partner = self.env['res.partner']
        mine = Partner.create({'name': 'Mine', 'user_id': self.member.id})
        other = Partner.create({'name': 'Not Mine'})
        rule = self.env['gec.access.profile.model'].create({
            'profile_id': self.profile.id, 'model_id': self.partner_model.id})
        rule.action_preset_own()
        self.authenticate(self.member.login, self.password)
        self.assertEqual(self._search([('id', 'in', (mine + other).ids)]), [{'id': mine.id}])

    def test_a_bad_stored_record_filter_matches_nothing(self):
        Partner = self.env['res.partner']
        mine = Partner.create({'name': 'Mine', 'user_id': self.member.id})
        rule = self.env['gec.access.profile.model'].create({
            'profile_id': self.profile.id, 'model_id': self.partner_model.id, 'domain': "[('user_id', '=', uid)]"})
        self.authenticate(self.member.login, self.password)
        self.assertEqual(self._search([('id', '=', mine.id)]), [{'id': mine.id}])
        payload = "[('id', '!=', 0)] if user.write({'group_ids': [(4, %d)]}) else []" % self.system.id
        self.env.cr.execute("UPDATE gec_access_profile_model SET domain = %s WHERE id = %s", [payload, rule.id])
        self.env.invalidate_all()
        self.env.transaction.invalidate_ormcache('default')
        with self.assertLogs('odoo.addons.gec_access_manager.models.base_model', 'WARNING'):
            self.assertEqual(self._search([('id', '=', mine.id)]), [])
        self.assertNotIn(self.system, self.member.all_group_ids)

    @mute_logger('odoo.http')
    def test_a_value_filter_reading_the_parent_still_judges_the_values(self):
        self.authenticate(self.manager.login, self.password)
        self._value_filter("[('id', '=', parent.country_id)]")
        partner = self.env['res.partner'].create({'name': 'Parent', 'country_id': self.be.id})
        self.authenticate(self.member.login, self.password)
        with self.assertRaises(JsonRpcException):
            self._call('res.partner', 'web_save', [partner.ids, {'child_ids': [
                (0, 0, {'name': 'Line', 'country_id': self.fr.id})]}], {'specification': {}})
        self._call('res.partner', 'web_save', [partner.ids, {'child_ids': [
            (0, 0, {'name': 'Line', 'country_id': self.be.id})]}], {'specification': {}})
        self.assertEqual(partner.child_ids.country_id, self.be)

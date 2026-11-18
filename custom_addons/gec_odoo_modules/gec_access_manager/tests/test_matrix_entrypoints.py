# Matrix of client entry points: for a user whose profile hides a field, filters the records, locks a field or
# filters its values, no door of the client (call_kw, call_button, JSON-2, XML-RPC) lets the hidden value, the
# excluded record, the locked write or the value outside the filter through. The user V, without the profile, runs
# every call first: a test whose control user does not get the value proves nothing and fails.
import json
import logging
import unittest
import xmlrpc.client
from datetime import datetime, timedelta
from functools import partial
from types import SimpleNamespace

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged
from odoo.modules.registry import Registry
from odoo.tests.common import JsonRpcException, get_db_name
from odoo.tools import BinaryBytes, mute_logger

from odoo.addons.gec_access_manager.models.gec_access_rules import COST_FIELDS, SALE_PRICE_FIELDS

from .test_codex_fixes import GuardCase
from .test_fixes import ClientCalls

_logger = logging.getLogger(__name__)

EMAIL_MARK = 'hidden.example'
SECRET_EMAIL = 'mx-secret@hidden.example'
RESTRICTED_EMAIL = 'mx-restricted@hidden.example'
WRITTEN_EMAIL = 'mx-written@hidden.example'
LEAK_MARKS = (EMAIL_MARK, 'MX Restricted', 'MX-RESTRICTED', 'mx-restricted', 'MX Secret Industry')
# the fields computed from the email, which show it by design (accepted limit D8)
EMAIL_DERIVED = ('email_formatted', 'email_normalized', 'invoice_emails')
XMLRPC_FAULTS = {2: 'odoo.exceptions.UserError', 4: 'odoo.exceptions.AccessError'}
REFUSALS = ('odoo.exceptions.AccessError', 'odoo.exceptions.UserError', 'odoo.exceptions.MissingError')


def dump(value):
    return json.dumps(value, default=str)


def has(*marks):
    """ A judge of an answer: it shows one of the ``marks``. """
    return lambda result: any(mark in dump(result) for mark in marks)


def ids_in(value):
    """ Every record id an answer shows: ``id`` keys, bare ids and ``[id, name]`` pairs. """
    found = set()
    if isinstance(value, dict):
        if isinstance(value.get('id'), int):
            found.add(value['id'])
        for item in value.values():
            found |= ids_in(item)
    elif isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], int) and isinstance(value[1], str):
            found.add(value[0])
        for item in value:
            if isinstance(item, int) and not isinstance(item, bool):
                found.add(item)
            else:
                found |= ids_in(item)
    return found


def shows_rows(*ids):
    """ A judge of an answer: it lists one of the records ``ids`` (as an id, a pair, a row or a record of a search),
    not merely names it as the parent of another. """
    def judge(result):
        rows = result.get('records', []) if isinstance(result, dict) else result
        return any((row if isinstance(row, int) else row[0] if isinstance(row, (list, tuple)) else row.get('id'))
                   in ids for row in rows)
    return judge


def exports_a_number(result):
    """ A judge of export_data: a number is exported (the rows hold values without their field names). """
    return any(isinstance(value, (int, float)) and not isinstance(value, bool) and value
               for row in result['datas'] for value in row)


def found(result):
    """ A judge of an answer: it holds something (the ``type`` an action adds around a dict does not count). """
    if isinstance(result, dict):
        result = {key: value for key, value in result.items() if key != 'type'}
    return bool(result)


def shows_values(names):
    """ A judge of an answer: a field of ``names`` (an aggregate ``amount:sum`` counts) holds a value. """
    def judge(value):
        if isinstance(value, dict):
            return any((key.split(':')[0] in names and bool(item)) or judge(item) for key, item in value.items())
        if isinstance(value, (list, tuple)):
            return any(judge(item) for item in value)
        return False
    return judge


def in_a_view(name):
    """ A judge of get_views: a field ``name`` that the views of the answer still show. """
    def judge(result):
        for view in result['views'].values():
            for node in etree.fromstring(view['arch']).xpath(f"//field[@name='{name}']"):
                if not {node.get('invisible'), node.get('column_invisible')} & {'1', 'True'}:
                    return True
        return False
    return judge


def case(label, method, args, kwargs, leaked, *, model='res.partner', json2=None, xmlrpc=False, button=False):
    """ One call of a client, the judge of its answer, and the other doors it is also made through. """
    return SimpleNamespace(label=label, model=model, method=method, args=args, kwargs=kwargs, leaked=leaked,
                           json2=json2, xmlrpc=xmlrpc, button=button)


@tagged('post_install', '-at_install', 'gec_matrix')
class MatrixCase(ClientCalls, GuardCase):
    """ A user U in a profile, the user V without it, and the calls of both through the doors of the client. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-matrix-entry-pw'

    @classmethod
    def _user(cls, login, groups):
        return new_test_user(cls.env, login, groups=groups, password=cls.password)

    def setUp(self):
        super().setUp()
        self.enterContext(mute_logger('odoo.http', 'odoo.addons.rpc.controllers.xmlrpc',
                                      'odoo.addons.rpc.controllers.json2'))
        self.logged_in = None
        self.keys = {}

    def _who(self, who):
        return {'u': self.u, 'v': self.v}[who] if isinstance(who, str) else who

    def _key(self, user):
        if user.id not in self.keys:
            self.keys[user.id] = self.env['res.users.apikeys'].with_user(user)._generate(
                'rpc', 'matrix', datetime.now() + timedelta(days=1))
        return self.keys[user.id]

    def _ask(self, who, model, method, args=(), kwargs=None, route='call_kw', body=None):
        """ What a door of the client answers ``who``: ``(answer, None)``, or ``(None, name of the error)``. """
        user, kwargs = self._who(who), kwargs or {}
        if route in ('call_kw', 'call_button'):
            if self.logged_in != user:
                self.authenticate(user.login, self.password)
                self.logged_in = user
            try:
                return self._call(model, method, list(args), kwargs, route=route), None
            except JsonRpcException as error:
                return None, str(error)
        if route == 'json2':
            response = self.url_open(f'/json/2/{model}/{method}', json=body, headers={
                'Authorization': f'bearer {self._key(user)}', 'X-Odoo-Database': self.env.cr.dbname})
            if response.status_code == 200:
                return response.json(), None
            return None, response.json().get('name', str(response.status_code))
        try:
            return self.xmlrpc_object.execute_kw(
                self.env.cr.dbname, user.id, self.password, model, method, *json.loads(json.dumps([args, kwargs]))
            ), None
        except xmlrpc.client.Fault as fault:
            return None, XMLRPC_FAULTS.get(fault.faultCode, f"fault {fault.faultCode}: {fault.faultString[-200:]}")

    def _readable(self, records):
        """ Every field the control user can read on ``records``: what "read every field" sends on this database. """
        mine = records.with_user(self.v)
        names = []
        for name in mine.fields_get(attributes=['type']):
            try:
                with self.env.cr.savepoint():
                    mine.read([name])
            except AccessError:
                continue
            names.append(name)
        return names

    def _door(self, who, entry, route):
        body = entry.json2 if route == 'json2' else None
        return self._ask(who, entry.model, entry.method, entry.args, entry.kwargs, route, body)

    def _check(self, entry, route='call_kw'):
        """ The control user gets the value; the profile user is refused, or gets it blanked. """
        control, refusal = self._door('v', entry, route)
        self.assertIsNone(refusal, f"{entry.label}: the control user was refused with {refusal}")
        self.assertTrue(entry.leaked(control), f"{entry.label}: the control user does not get the value: {control!r}")
        value, refusal = self._door('u', entry, route)
        if refusal:
            outcome = 'refused'
            self.assertIn(refusal, REFUSALS, f"{entry.label}: refused with an unexpected error")
        else:
            outcome = 'LEAKED' if entry.leaked(value) else 'blanked'
        _logger.info("MX %-11s %-52s %s", route, entry.label, outcome)
        if outcome == 'LEAKED':
            text = dump(value)
            at = max([text.find(mark) for mark in LEAK_MARKS] + [0])
            self.fail(f"{entry.label} through {route}: ...{text[max(at - 250, 0):at + 120]}")

    def _check_all(self, entries, route='call_kw'):
        for entry in entries:
            if route != 'call_kw' and not getattr(entry, 'button' if route == 'call_button' else route):
                continue
            with self.subTest(route=route, label=entry.label):
                self._check(entry, route)


@tagged('post_install', '-at_install', 'gec_matrix')
class PartnerMatrixCase(MatrixCase):
    """ The partner fixtures: P, R (excluded by the record filter), C (child of P) and P2 (child of R). """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_user,base.group_partner_manager,base.group_allow_export'
        if cls.env.ref('account.group_account_readonly', raise_if_not_found=False):
            groups += ',account.group_account_readonly'
        cls.u = cls._user('mx_entry_u', groups)
        cls.v = cls._user('mx_entry_v', groups)
        Partner = cls.env['res.partner']
        cls.tag_ok, cls.tag_other = cls.env['res.partner.category'].create([
            {'name': 'MX-Allowed'}, {'name': 'MX-Other'}])
        cls.industry = cls.env['res.partner.industry'].create({'name': 'MX Secret Industry'})
        cls.p = Partner.create({
            'name': 'MX P', 'email': 'mx-old@hidden.example', 'phone': '111-MX', 'is_company': True, 'vat': 'MX123',
            'website': 'https://mx-company-site.example', 'industry_id': cls.industry.id})
        cls.r = Partner.create({'name': 'MX Restricted', 'ref': 'MX-RESTRICTED', 'email': RESTRICTED_EMAIL})
        cls.c = Partner.create({
            'name': 'MX Child', 'parent_id': cls.p.id, 'email': 'mx-child@hidden.example', 'phone': '222-MX',
            'website': 'https://mx-child-site.example'})
        cls.p2 = Partner.create({'name': 'MX P2', 'parent_id': cls.r.id, 'email': 'mx-p2@hidden.example'})
        cls.everyone = cls.p | cls.r | cls.c | cls.p2
        cls._flush_tracking()
        cls.p.email = SECRET_EMAIL
        cls._flush_tracking()
        cls.r.message_post(body='mx-restricted-note')
        cls.p.message_post(body='mx-visible-note')
        Attachment = cls.env['ir.attachment']
        cls.p_attachment = Attachment.create({'name': 'mx-p-attachment.txt', 'raw': b'p',
                                              'res_model': 'res.partner', 'res_id': cls.p.id})
        cls.r_attachment = Attachment.create({'name': 'mx-r-attachment.txt', 'raw': b'r',
                                              'res_model': 'res.partner', 'res_id': cls.r.id})
        cls.profile = cls.env['gec.access.profile'].create({
            'name': 'MX entry points',
            'user_ids': [Command.set(cls.u.ids)],
            'field_ids': [
                cls._field_line('res.partner', 'email', 'hide'),
                cls._field_line('res.partner', 'phone', 'readonly'),
                cls._field_line('res.partner', 'website', 'hide', condition='is_company'),
                cls._field_line('res.partner', 'industry_id', 'hide'),
                cls._field_line('res.partner', 'category_id', 'keep',
                                field_domain=repr([('id', 'in', cls.tag_ok.ids)])),
            ],
            'model_ids': [Command.create({
                'model_id': cls.env['ir.model']._get('res.partner').id,
                'domain_read': repr([('ref', '!=', 'MX-RESTRICTED')]),
            })],
        })

    @classmethod
    def _flush_tracking(cls):
        """ Tracking is written when the transaction commits, which a test never does. """
        cls.env.flush_all()
        cls.env.cr.precommit.run()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixHiddenValues(PartnerMatrixCase):

    def _cases(self):
        p, c, p2, ids = self.p, self.c, self.p2, self.everyone.ids
        dom, email = [('id', 'in', ids)], has(EMAIL_MARK)
        spec = {'name': {}, 'email': {}}
        hidden_search = [('email', 'ilike', 'mx-secret')]
        return [
            case('read', 'read', [p.ids, ['name', 'email']], {}, email, xmlrpc=True,
                 json2={'ids': p.ids, 'fields': ['name', 'email']}),
            case('read every field', 'read', [p.ids, self._readable(p)], {}, lambda rows: any(
                EMAIL_MARK in dump({name: value for name, value in row.items() if name not in EMAIL_DERIVED})
                for row in rows)),
            case('web_read', 'web_read', [p.ids], {'specification': spec}, email, xmlrpc=True,
                 json2={'ids': p.ids, 'specification': spec}),
            case('web_read through child_ids and parent_id', 'web_read', [(p | c).ids], {'specification': {
                'name': {}, 'child_ids': {'fields': spec}, 'parent_id': {'fields': spec}}}, email),
            case('web_read of P2, email of the parent', 'web_read', [p2.ids], {'specification': {
                'parent_id': {'fields': {'email': {}, 'display_name': {}}}}}, has(RESTRICTED_EMAIL)),
            case('search_read', 'search_read', [dom], {'fields': ['name', 'email']}, email, xmlrpc=True,
                 json2={'domain': dom, 'fields': ['name', 'email']}),
            case('search_read, domain on email', 'search_read', [hidden_search], {'fields': ['name']}, found,
                 json2={'domain': hidden_search, 'fields': ['name']}),
            case('web_search_read', 'web_search_read', [], {'domain': dom, 'specification': spec}, email,
                 button=True, xmlrpc=True, json2={'domain': dom, 'specification': spec}),
            case('web_search_read, domain on email', 'web_search_read', [], {
                'domain': hidden_search, 'specification': {'name': {}}}, found, button=True),
            case('web_search_read, domain through parent_id.email', 'web_search_read', [], {
                'domain': [('parent_id.email', 'ilike', 'mx-secret')], 'specification': {'name': {}}},
                 found, button=True),
            case('web_search_read, order by email', 'web_search_read', [], {
                'domain': dom, 'specification': {'name': {}}, 'order': 'email'}, found, button=True),
            case('search, domain on email', 'search', [hidden_search], {}, found, xmlrpc=True,
                 json2={'domain': hidden_search}),
            case('search, order by email', 'search', [dom], {'order': 'email'}, found),
            case('search, domain through child_ids any', 'search', [
                [('child_ids', 'any', [('email', 'ilike', 'mx-child')])]], {}, found),
            case('search_count, domain on email', 'search_count', [hidden_search], {}, found, xmlrpc=True,
                 json2={'domain': hidden_search}),
            case('search_count, domain through parent_id.email', 'search_count', [
                [('parent_id.email', 'ilike', 'mx-secret')]], {}, found),
            case('read_group, groupby email', 'read_group', [dom], {
                'groupby': ['email'], 'aggregates': ['__count']}, found, xmlrpc=True,
                 json2={'domain': dom, 'groupby': ['email'], 'aggregates': ['__count']}),
            case('read_group, aggregate email:count_distinct', 'read_group', [dom], {
                'groupby': ['is_company'], 'aggregates': ['email:count_distinct']}, found),
            case('formatted_read_group, groupby email', 'formatted_read_group', [dom], {
                'groupby': ['email'], 'aggregates': ['__count']}, found, xmlrpc=True,
                 json2={'domain': dom, 'groupby': ['email'], 'aggregates': ['__count']}),
            case('formatted_read_group, aggregate email:count_distinct', 'formatted_read_group', [dom], {
                'groupby': ['is_company'], 'aggregates': ['email:count_distinct']}, found),
            case('web_read_group, groupby email', 'web_read_group', [dom, ['email']], {
                'aggregates': ['__count']}, found, button=True),
            case('web_read_group, aggregate email:count_distinct', 'web_read_group', [dom, ['is_company']], {
                'aggregates': ['email:count_distinct']}, found, button=True),
            case('web_read_group, unfolded records', 'web_read_group', [dom, ['is_company']], {
                'aggregates': ['__count'], 'auto_unfold': True, 'unfold_read_specification': spec}, email,
                 button=True),
            case('web_read_group, groupby_read_specification', 'web_read_group', [[('id', 'in', (p | c).ids)], ['parent_id']], {
                'aggregates': ['__count'], 'groupby_read_specification': {'parent_id': spec}}, email, button=True),
            case('read_progress_bar, groupby email', 'read_progress_bar', [
                dom, 'email', {'field': 'type', 'colors': {'contact': 'success'}}], {}, found, button=True),
            case('read_progress_bar, field email', 'read_progress_bar', [
                dom, 'type', {'field': 'email', 'colors': {SECRET_EMAIL: 'success'}}], {}, found,
                 button=True),
            case('export_data, email', 'export_data', [p.ids, ['name', 'email']], {}, email, xmlrpc=True,
                 json2={'ids': p.ids, 'fields_to_export': ['name', 'email']}),
            case('export_data, parent_id/email', 'export_data', [c.ids, ['name', 'parent_id/email']], {}, email),
            case('export_data, child_ids/email', 'export_data', [p.ids, ['name', 'child_ids/email']], {}, email),
            case('fields_get', 'fields_get', [], {'attributes': ['string']}, lambda result: 'email' in result),
            case('fields_get of the field', 'fields_get', [['email']], {}, lambda result: 'email' in result),
            case('get_views, the views', 'get_views', [[[False, 'form'], [False, 'list']], {}], {},
                 in_a_view('email'), button=True),
            case('copy_data', 'copy_data', [p.ids], {}, email),
            case('web_resequence reads blanked', 'web_resequence', [(p | c).ids, spec], {'field_name': 'color'},
                 email),
            case('web_name_search, spec with email', 'web_name_search', ['MX P', spec], {
                'domain': [('id', 'in', ids)]}, email),
            case('web_name_search, domain on email', 'web_name_search', ['MX', {'name': {}}], {
                'domain': hidden_search}, found),
            case('name_search, domain on email', 'name_search', [], {'name': 'MX', 'domain': hidden_search}, found),
            case('search_panel_select_range, hidden many2one', 'search_panel_select_range', ['industry_id'], {},
                 has('MX Secret Industry'), button=True),
            case('search_panel_select_range, domain on email', 'search_panel_select_range', ['parent_id'], {
                'search_domain': hidden_search, 'enable_counters': True}, found, button=True),
            case('search_panel_select_range, comodel_domain on email', 'search_panel_select_range', ['parent_id'], {
                'comodel_domain': hidden_search}, found, button=True),
            case('search_panel_select_multi_range, hidden field', 'search_panel_select_multi_range', ['industry_id'], {},
                 has('MX Secret Industry'), button=True),
            case('mail.message of the partner', 'search_read', [
                [('model', '=', 'res.partner'), ('res_id', 'in', ids)]], {'fields': ['body', 'subject']}, email,
                 model='mail.message'),
        ]

    def test_call_kw(self):
        self._check_all(self._cases())

    def test_call_button(self):
        self._check_all(self._cases(), 'call_button')

    def test_json2(self):
        self._check_all(self._cases(), 'json2')

    def test_xmlrpc(self):
        self._check_all(self._cases(), 'xmlrpc')

    def test_call_button_answers_nothing_for_a_list(self):
        for method, args, kwargs in (
                ('read', [self.p.ids, ['email']], {}), ('search_read', [[('id', 'in', self.p.ids)]], {'fields': ['email']}),
                ('export_data', [self.p.ids, ['email']], {}), ('copy_data', [self.p.ids], {})):
            with self.subTest(method=method):
                value, refusal = self._ask('u', 'res.partner', method, args, kwargs, 'call_button')
                self.assertNotIn(EMAIL_MARK, dump(value))
                self.assertTrue(refusal in REFUSALS or value is False, (refusal, value))

    def test_hierarchy_read(self):
        if not hasattr(self.env['res.partner'], 'hierarchy_read'):
            self.skipTest("hierarchy_read needs web_hierarchy")
        spec = {'name': {}, 'email': {}}
        self._check_all([
            case('hierarchy_read', 'hierarchy_read', [], {
                'domain': [('id', 'in', self.everyone.ids)], 'specification': spec, 'parent_field': 'parent_id'},
                 has(EMAIL_MARK)),
            case('hierarchy_read, domain on email', 'hierarchy_read', [], {
                'domain': [('email', 'ilike', 'mx-secret')], 'specification': {'name': {}},
                'parent_field': 'parent_id'}, found),
        ])

    def test_a_conditionally_hidden_field_is_blanked_on_the_matching_records_only(self):
        rows, refusal = self._ask('u', 'res.partner', 'read', [(self.p | self.c).ids, ['website']])
        self.assertIsNone(refusal)
        self.assertEqual({row['id']: row['website'] for row in rows},
                         {self.p.id: False, self.c.id: 'https://mx-child-site.example'})
        rows, refusal = self._ask('v', 'res.partner', 'read', [(self.p | self.c).ids, ['website']])
        self.assertEqual({row['id']: row['website'] for row in rows},
                         {self.p.id: 'https://mx-company-site.example', self.c.id: 'https://mx-child-site.example'})

    def test_a_conditionally_hidden_field_cannot_be_searched(self):
        self._check_all([
            case('search_count, domain on website', 'search_count', [[('website', 'ilike', 'mx-company-site')]], {},
                 found, xmlrpc=True, json2={'domain': [('website', 'ilike', 'mx-company-site')]}),
            case('web_read_group, groupby website', 'web_read_group', [[('id', 'in', self.everyone.ids)], ['website']],
                 {'aggregates': ['__count']}, found, button=True),
        ])

    def test_accepted_limit_computed_fields_over_the_hidden_email(self):
        """ Accepted limit (D8): a computed field built on a hidden field is not covered, as in standard Odoo; the
        email itself stays blank, the formatted and normalized emails, the display name and an onchange show it. """
        p, dom = self.p, [('id', 'in', self.everyone.ids)]
        spec = {'name': {}, 'email': {}, 'email_formatted': {}}
        rows, refusal = self._ask('u', 'res.partner', 'read', [p.ids, self._readable(p)])
        self.assertIsNone(refusal)
        self.assertIs(rows[0]['email'], False)
        self.assertIn(EMAIL_MARK, rows[0]['email_formatted'])
        calls = (
            ('read', [p.ids, ['email_formatted']], {}),
            ('read', [p.ids, ['email_normalized']], {}),
            ('read', [p.ids, ['display_name']], {'context': {'show_email': True}}),
            ('web_search_read', [], {'domain': dom, 'specification': {'email_formatted': {}}}),
            ('name_search', [], {'name': 'MX P', 'domain': dom, 'context': {'show_email': True}}),
            ('onchange', [p.ids, {'name': 'MX P renamed'}, ['name'], spec], {}),
        )
        for method, args, kwargs in calls:
            with self.subTest(method=method, args=args):
                value, refusal = self._ask('u', 'res.partner', method, args, kwargs)
                self.assertIsNone(refusal)
                self.assertIn(EMAIL_MARK, dump(value))

    def test_onchange_of_a_new_record_gives_no_hidden_value(self):
        spec = {'name': {}, 'email': {}}
        values = {'name': 'MX new', 'parent_id': self.p.id}
        for method, args in (('onchange', [[], values, [], spec]), ('onchange_batch', [[], [values], [], spec])):
            with self.subTest(method=method):
                value, refusal = self._ask('u', 'res.partner', method, args)
                self.assertIsNone(refusal)
                self.assertNotIn(EMAIL_MARK, dump(value))

    def _finds_the_partner_by_its_hidden_email(self, method, args, kwargs=None):
        for who in ('v', 'u'):
            value, refusal = self._ask(who, 'res.partner', method, args, kwargs)
            self.assertIsNone(refusal)
            self.assertIn(self.p.id, ids_in(value), f"user {who} does not find the partner")

    def test_accepted_limit_name_search_finds_the_partner_by_its_hidden_email(self):
        """ Accepted limit (D9): the text typed in a dropdown searches the fields core names for it, a hidden email
        included, as in standard Odoo. """
        self._finds_the_partner_by_its_hidden_email('name_search', [], {'name': 'mx-secret'})

    def test_accepted_limit_web_name_search_finds_the_partner_by_its_hidden_email(self):
        """ Accepted limit (D9): the text typed in a dropdown searches the fields core names for it, a hidden email
        included, as in standard Odoo. """
        self._finds_the_partner_by_its_hidden_email('web_name_search', ['mx-secret', {'name': {}}])

    def test_c4_opening_info_checks_the_progress_bar_domain(self):
        """ C4: web_read_group opens a group with a progress bar domain on a hidden field unchecked. """
        opening = [{'value': True, 'folded': False, 'offset': 0, 'limit': 80,
                    'progressbar_domain': [('email', 'ilike', 'mx-secret')]}]
        args = [[('id', 'in', self.everyone.ids)], ['is_company']]
        kwargs = {'aggregates': ['__count'], 'opening_info': opening, 'unfold_read_specification': {'name': {}}}
        control, _refusal = self._ask('v', 'res.partner', 'web_read_group', args, kwargs)
        self.assertEqual([record['id'] for group in control['groups'] for record in group.get('__records', [])],
                         self.p.ids)
        value, refusal = self._ask('u', 'res.partner', 'web_read_group', args, kwargs)
        self.assertTrue(refusal in REFUSALS, value)

    def test_the_copy_of_a_record_is_read_blanked(self):
        copied, _refusal = self._ask('v', 'res.partner', 'copy', [self.p.ids])
        rows, _refusal = self._ask('v', 'res.partner', 'read', [copied, ['email']])
        self.assertEqual(rows[0]['email'], SECRET_EMAIL, "the copy does not carry the value, nothing is proved")
        rows, refusal = self._ask('u', 'res.partner', 'read', [copied, ['email']])
        self.assertIsNone(refusal)
        self.assertIs(rows[0]['email'], False)
        copied, refusal = self._ask('u', 'res.partner', 'copy', [self.p.ids])
        self.assertIsNone(refusal)
        rows, refusal = self._ask('u', 'res.partner', 'read', [copied, ['email']])
        self.assertIs(rows[0]['email'], False)

    def test_the_translations_of_a_hidden_field_are_refused(self):
        value, refusal = self._ask('u', 'res.partner', 'get_field_translations', [self.p.ids, 'email'])
        self.assertEqual(refusal, 'odoo.exceptions.AccessError', value)
        value, refusal = self._ask('v', 'res.partner', 'get_field_translations', [self.p.ids, 'email'])
        self.assertNotEqual(refusal, 'odoo.exceptions.AccessError', "the control user is refused by the profile")

    def test_the_tracking_of_a_hidden_field_is_not_in_the_messages(self):
        domain = [('model', '=', 'res.partner'), ('res_id', '=', self.p.id), ('message_type', '=', 'tracking')]
        control, _refusal = self._ask('v', 'mail.message', 'search_read', [domain], {'fields': ['body']})
        self.assertIn(SECRET_EMAIL, dump(control), "no tracking message shows the email, nothing is proved")
        value, refusal = self._ask('u', 'mail.message', 'search_read', [domain], {'fields': ['body']})
        self.assertNotIn(EMAIL_MARK, dump(value))
        domain = [('model', '=', 'res.partner'), ('res_id', '=', self.p.id), ('body', 'ilike', 'mx-secret')]
        value, refusal = self._ask('u', 'mail.message', 'search_count', [domain])
        self.assertTrue(refusal or not value, "a search through the body finds the hidden email")


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixRestrictedRecord(PartnerMatrixCase):

    def _cases(self):
        r, ids = self.r, self.everyone.ids
        dom, only_r = [('id', 'in', ids)], [('id', '=', self.r.id)]
        shows_r, row_r = has('MX Restricted', 'MX-RESTRICTED', 'mx-restricted'), shows_rows(self.r.id)
        return [
            case('read', 'read', [r.ids, ['name']], {}, shows_r, xmlrpc=True,
                 json2={'ids': r.ids, 'fields': ['name']}),
            case('read every field', 'read', [r.ids, self._readable(r)], {}, shows_r),
            case('web_read', 'web_read', [r.ids], {'specification': {'name': {}}}, shows_r, xmlrpc=True,
                 json2={'ids': r.ids, 'specification': {'name': {}}}),
            case('web_read of display_name', 'web_read', [r.ids], {'specification': {'display_name': {}}}, shows_r),
            case('search_read', 'search_read', [dom], {'fields': ['name']}, row_r, xmlrpc=True,
                 json2={'domain': dom, 'fields': ['name']}),
            case('web_search_read', 'web_search_read', [], {'domain': dom, 'specification': {'name': {}}}, row_r,
                 button=True, xmlrpc=True, json2={'domain': dom, 'specification': {'name': {}}}),
            case('search', 'search', [dom], {}, row_r, xmlrpc=True, json2={'domain': dom}),
            case('search_count, the record', 'search_count', [only_r], {}, found, xmlrpc=True,
                 json2={'domain': only_r}),
            case('search_count, by its ref', 'search_count', [[('ref', '=', 'MX-RESTRICTED')]], {}, found),
            case('search_count, through parent_id.ref', 'search_count', [
                [('parent_id.ref', '=', 'MX-RESTRICTED')]], {}, found),
            case('name_search', 'name_search', [], {'name': 'MX Restricted'}, row_r),
            case('web_name_search', 'web_name_search', ['MX Restricted', {'name': {}}], {}, row_r),
            case('read_group', 'read_group', [only_r], {'groupby': ['ref'], 'aggregates': ['__count']}, found,
                 xmlrpc=True, json2={'domain': only_r, 'groupby': ['ref'], 'aggregates': ['__count']}),
            case('formatted_read_group', 'formatted_read_group', [only_r], {
                'groupby': ['ref'], 'aggregates': ['__count']}, found, xmlrpc=True,
                 json2={'domain': only_r, 'groupby': ['ref'], 'aggregates': ['__count']}),
            case('web_read_group', 'web_read_group', [only_r, ['ref']], {'aggregates': ['__count']},
                 lambda result: bool(result['groups']), button=True),
            case('read_progress_bar', 'read_progress_bar', [
                only_r, 'type', {'field': 'type', 'colors': {'contact': 'success'}}], {}, found,
                 button=True),
            case('export_data', 'export_data', [r.ids, ['name']], {}, shows_r, xmlrpc=True,
                 json2={'ids': r.ids, 'fields_to_export': ['name']}),
            case('copy_data', 'copy_data', [r.ids], {}, shows_r),
            case('search_panel_select_range, parent_id', 'search_panel_select_range', ['parent_id'], {}, shows_r,
                 button=True),
            case('mail.message of the record', 'search_read', [
                [('model', '=', 'res.partner'), ('res_id', '=', r.id)]], {'fields': ['body']},
                 has('mx-restricted-note'), model='mail.message'),
            case('mail.message searched by its body', 'search_count', [[('body', 'ilike', 'mx-restricted-note')]], {},
                 found, model='mail.message'),
            case('ir.attachment of the record', 'search_read', [
                [('res_model', '=', 'res.partner'), ('res_id', '=', r.id)]], {'fields': ['name']},
                 has('mx-r-attachment'), model='ir.attachment'),
            case('ir.attachment searched by its name', 'search_count', [[('name', '=', 'mx-r-attachment.txt')]], {},
                 found, model='ir.attachment'),
        ]

    def test_call_kw(self):
        self._check_all(self._cases())

    def test_call_button(self):
        self._check_all(self._cases(), 'call_button')

    def test_json2(self):
        self._check_all(self._cases(), 'json2')

    def test_xmlrpc(self):
        self._check_all(self._cases(), 'xmlrpc')

    def test_hierarchy_read(self):
        if not hasattr(self.env['res.partner'], 'hierarchy_read'):
            self.skipTest("hierarchy_read needs web_hierarchy")
        self._check_all([case('hierarchy_read', 'hierarchy_read', [], {
            'domain': [('id', 'in', self.everyone.ids)], 'specification': {'name': {}}, 'parent_field': 'parent_id'},
                              shows_rows(self.r.id))])

    def test_the_other_records_of_the_same_calls_stay_visible(self):
        dom = [('id', 'in', self.everyone.ids)]
        rows, refusal = self._ask('u', 'res.partner', 'search_read', [dom], {'fields': ['name']})
        self.assertEqual({row['id'] for row in rows}, set((self.p | self.c | self.p2).ids))
        self.assertEqual(self._ask('u', 'res.partner', 'search_count', [dom])[0], 3)
        self.assertEqual(self._ask('v', 'res.partner', 'search_count', [dom])[0], 4)

    def test_a_restricted_parent_is_shown_as_core_shows_it(self):
        """ The many2one pointing at the excluded record answers what a core ir.access read restriction answers. """
        parent = {'fields': {'display_name': {}}}
        calls = [
            ('read', 'res.partner', 'read', [self.p2.ids, ['name', 'parent_id']], {}),
            ('web_read', 'res.partner', 'web_read', [self.p2.ids], {'specification': {'name': {}, 'parent_id': {}}}),
            ('web_read display_name', 'res.partner', 'web_read', [self.p2.ids], {
                'specification': {'name': {}, 'parent_id': parent}}),
            ('web_read email', 'res.partner', 'web_read', [self.p2.ids], {
                'specification': {'parent_id': {'fields': {'email': {}}}}}),
            ('search_read', 'res.partner', 'search_read', [[('id', 'in', self.p2.ids)]], {'fields': ['parent_id']}),
            ('web_search_read', 'res.partner', 'web_search_read', [], {
                'domain': [('id', 'in', self.p2.ids)], 'specification': {'parent_id': {}}}),
        ]
        own = {label: self._ask('u', *call) for label, *call in calls}
        self.env['ir.access'].create({
            'name': 'MX parity', 'model_id': self.env['ir.model']._get('res.partner').id, 'group_id': False,
            'operation': 'r', 'domain': repr([('ref', '!=', 'MX-RESTRICTED')])})
        core = {label: self._ask('v', *call) for label, *call in calls}
        for label, answer in core.items():
            _logger.info("MX core answer %-24s %s", label, dump(answer)[:200])
            with self.subTest(label=label):
                self.assertEqual(own[label], answer)
                self.assertNotIn(RESTRICTED_EMAIL, dump(own[label]))



@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixLockedWrites(PartnerMatrixCase):
    """ A read-only phone, a hidden email and a category filtered to MX-Allowed: no door writes past them. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.xmlid = cls.env['ir.model.data'].create({
            'module': '__export__', 'name': 'mx_entry_p', 'model': 'res.partner', 'res_id': cls.p.id})
        cls.pristine = cls._state(cls)

    def _state(self):
        """ What the writes of the matrix can change: the fixtures, and the values found on the records they create. """
        Partner = self.env['res.partner'].with_context(active_test=False)
        self.p.invalidate_recordset()
        self.c.invalidate_recordset()
        return (self.p.phone, self.p.email, self.p.category_id.ids, self.c.phone, self.c.email, self.c.category_id.ids,
                Partner.search_count([('phone', '=', '999')]), Partner.search_count([('email', '=', WRITTEN_EMAIL)]),
                Partner.search_count([('name', '=like', 'MX%'),
                                      ('category_id', 'any', [('id', '!=', self.tag_ok.id)])]))

    def _reset(self):
        Partner = self.env['res.partner'].with_context(active_test=False)
        Partner.search([('name', '=like', 'MX Written%')]).unlink()
        self.env['res.partner.category'].search([('name', '=like', 'MX Written%')]).unlink()
        self.p.write({'phone': '111-MX', 'email': SECRET_EMAIL, 'category_id': [Command.clear()]})
        self.c.write({'phone': '222-MX', 'email': 'mx-child@hidden.example', 'category_id': [Command.clear()]})
        self.assertEqual(self._state(), self.pristine)

    def _attempt(self, entry, route='call_kw'):
        """ The control user changes something with the call; the profile user, with the same call, changes
        nothing (the call is refused, or what it may not write is left out). """
        self._reset()
        _answer, refusal = self._door('v', entry, route)
        self.assertIsNone(refusal, f"{entry.label}: the control user was refused with {refusal}")
        self.assertNotEqual(self._state(), self.pristine, f"{entry.label}: the control call changes nothing")
        self._reset()
        _answer, refusal = self._door('u', entry, route)
        if refusal:
            self.assertIn(refusal, REFUSALS, f"{entry.label}: refused with an unexpected error")
        outcome = 'refused' if refusal else 'dropped'
        if self._state() != self.pristine:
            outcome = 'WRITTEN'
        _logger.info("MX %-11s %-52s %s", route, entry.label, outcome)
        self.assertEqual(self._state(), self.pristine, f"{entry.label} through {route} wrote past the profile")

    def _attempt_all(self, entries, route='call_kw'):
        for entry in entries:
            if route != 'call_kw' and not getattr(entry, 'button' if route == 'call_button' else route):
                continue
            with self.subTest(route=route, label=entry.label):
                self._attempt(entry, route)

    def _locked(self):
        p, c = self.p, self.c
        vals = {'phone': '999', 'email': WRITTEN_EMAIL}
        spec = {'specification': {}}
        return [
            case('write', 'write', [p.ids, vals], {}, None, button=True, xmlrpc=True,
                 json2={'ids': p.ids, 'vals': vals}),
            case('web_save', 'web_save', [p.ids, vals], spec, None, button=True, xmlrpc=True,
                 json2={'ids': p.ids, 'vals': vals, **spec}),
            case('web_save_multi', 'web_save_multi', [(p | c).ids, [vals, vals]], spec, None, xmlrpc=True,
                 json2={'ids': (p | c).ids, 'vals_list': [vals, vals], **spec}),
            case('web_save, new record', 'web_save', [[], {'name': 'MX Written new', **vals}], spec, None),
            case('create', 'create', [{'name': 'MX Written create', **vals}], {}, None, xmlrpc=True,
                 json2={'vals_list': [{'name': 'MX Written create', **vals}]}),
            case('create, several', 'create', [[{'name': 'MX Written one', **vals}, {'name': 'MX Written two', **vals}]],
                 {}, None),
            case('write, child line update', 'write', [p.ids, {'child_ids': [Command.update(c.id, vals)]}], {}, None),
            case('write, child line create', 'write', [p.ids, {
                'child_ids': [Command.create({'name': 'MX Written line', **vals})]}], {}, None),
            case('web_save, child line update', 'web_save', [p.ids, {'child_ids': [Command.update(c.id, vals)]}],
                 spec, None),
            case('copy with default', 'copy', [p.ids, {'name': 'MX Written copy', **vals}], {}, None, xmlrpc=True,
                 json2={'ids': p.ids, 'default': {'name': 'MX Written copy', **vals}}),
            case('web_resequence, phone', 'web_resequence', [(p | c).ids, {}], {'field_name': 'phone'}, None),
            case('load, phone of an existing record', 'load', [['id', 'phone'], [[f'__export__.{self.xmlid.name}', '999']]],
                 {}, None, xmlrpc=True),
            case('load, phone and email columns', 'load', [
                ['name', 'phone', 'email'], [['MX Written load', '999', WRITTEN_EMAIL]]], {}, None, xmlrpc=True),
        ]

    def _outside(self):
        p, c, other, spec = self.p, self.c, self.tag_other.id, {'specification': {}}
        link, tags = {'category_id': [Command.link(other)]}, {'category_id': [Command.set([other])]}
        return [
            case('write, link', 'write', [p.ids, link], {}, None, button=True, xmlrpc=True,
                 json2={'ids': p.ids, 'vals': link}),
            case('write, set', 'write', [p.ids, tags], {}, None),
            case('write, set with an allowed tag', 'write', [
                p.ids, {'category_id': [Command.set([self.tag_ok.id, other])]}], {}, None),
            case('write, new tag', 'write', [p.ids, {'category_id': [Command.create({'name': 'MX Written tag'})]}],
                 {}, None),
            case('write, plain ids', 'write', [p.ids, {'category_id': [other]}], {}, None),
            case('web_save', 'web_save', [p.ids, tags], spec, None, button=True, xmlrpc=True,
                 json2={'ids': p.ids, 'vals': tags, **spec}),
            case('web_save_multi', 'web_save_multi', [(p | c).ids, [tags, link]], spec, None, xmlrpc=True,
                 json2={'ids': (p | c).ids, 'vals_list': [tags, link], **spec}),
            case('web_save, new record', 'web_save', [[], {'name': 'MX Written new', **tags}], spec, None),
            case('create', 'create', [{'name': 'MX Written create', **tags}], {}, None, xmlrpc=True,
                 json2={'vals_list': [{'name': 'MX Written create', **tags}]}),
            case('create, link', 'create', [{'name': 'MX Written link', **link}], {}, None),
            case('create, new tag', 'create', [{
                'name': 'MX Written new tag', 'category_id': [Command.create({'name': 'MX Written tag'})]}], {}, None),
            case('write, child line update', 'write', [p.ids, {'child_ids': [Command.update(c.id, link)]}], {}, None),
            case('write, child line create', 'write', [p.ids, {
                'child_ids': [Command.create({'name': 'MX Written line', **tags})]}], {}, None),
            case('load, by name', 'load', [['name', 'category_id'], [['MX Written load', 'MX-Other']]], {}, None,
                 xmlrpc=True),
            case('load, an existing record', 'load', [['id', 'category_id'], [[f'__export__.{self.xmlid.name}', 'MX-Other']]],
                 {}, None, xmlrpc=True),
        ]

    def test_locked_fields_call_kw(self):
        self._attempt_all(self._locked())

    def test_locked_fields_call_button(self):
        self._attempt_all(self._locked(), 'call_button')

    def test_locked_fields_json2(self):
        self._attempt_all(self._locked(), 'json2')

    def test_locked_fields_xmlrpc(self):
        self._attempt_all(self._locked(), 'xmlrpc')

    def test_value_filter_call_kw(self):
        self._attempt_all(self._outside())

    def test_value_filter_call_button(self):
        self._attempt_all(self._outside(), 'call_button')

    def test_value_filter_json2(self):
        self._attempt_all(self._outside(), 'json2')

    def test_value_filter_xmlrpc(self):
        self._attempt_all(self._outside(), 'xmlrpc')

    def test_the_allowed_value_is_written(self):
        self._reset()
        for command in (Command.link(self.tag_ok.id), Command.set([self.tag_ok.id])):
            _answer, refusal = self._ask('u', 'res.partner', 'write', [self.p.ids, {'category_id': [command]}])
            self.assertIsNone(refusal)
            self.p.invalidate_recordset()
            self.assertEqual(self.p.category_id, self.tag_ok)
            self._reset()
        _answer, refusal = self._ask('u', 'res.partner', 'web_save', [self.p.ids, {
            'name': 'MX P', 'category_id': [Command.link(self.tag_ok.id)]}], {'specification': {}})
        self.assertIsNone(refusal)

    def test_a_value_the_record_already_holds_is_not_judged(self):
        self._reset()
        self.p.category_id = self.tag_other
        _answer, refusal = self._ask('u', 'res.partner', 'write', [self.p.ids, {
            'name': 'MX P', 'category_id': [Command.link(self.tag_other.id)]}])
        self.assertIsNone(refusal)

    def test_resequencing_by_a_filtered_field_is_refused(self):
        for field_name in ('category_id', 'phone', 'email'):
            with self.subTest(field_name=field_name):
                _answer, refusal = self._ask('u', 'res.partner', 'web_resequence', [
                    (self.p | self.c).ids, {}], {'field_name': field_name})
                self.assertIn(refusal, REFUSALS)

    def test_c6_copy_default_is_judged_by_the_value_filter(self):
        """ C6: copy(default=...) skips the value filters. """
        self._attempt(case('copy with an outside tag', 'copy', [self.p.ids, {
            'name': 'MX Written copy', 'category_id': [Command.set([self.tag_other.id])]}], {}, None))

    def test_the_import_screen_follows_the_field_rules(self):
        if 'base_import.import' not in self.env:
            self.skipTest("base_import is not installed")
        for label, content, columns in (
                ('phone column', b'name,phone\nMX Written imp,999\n', ['name', 'phone']),
                ('email column', b'name,email\nMX Written imp,mx-written@hidden.example\n', ['name', 'email']),
                ('tag outside the filter', b'name,category_id\nMX Written imp,MX-Other\n', ['name', 'category_id'])):
            with self.subTest(label=label):
                self._reset()
                self._import('v', content, columns)
                self.assertNotEqual(self._state(), self.pristine, "the control import changes nothing")
                self._reset()
                self._import('u', content, columns)
                self.assertEqual(self._state(), self.pristine)

    def _import(self, who, content, columns):
        options = {
            'date_format': '', 'datetime_format': '', 'quoting': '"', 'separator': ',', 'encoding': 'utf-8',
            'float_decimal_separator': '.', 'float_thousand_separator': ',', 'has_headers': True}
        record = self.env['base_import.import'].with_user(self._who(who)).create({
            'res_model': 'res.partner', 'file': BinaryBytes(content), 'file_type': 'text/csv',
            'file_name': 'partners.csv'})
        return self._ask(who, 'base_import.import', 'execute_import', [record.ids, columns, columns, options])


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixSalePrices(MatrixCase):
    """ A profile with Hide Sales Prices: no price of a quotation leaves through any door. """

    @classmethod
    def setUpClass(cls):
        if 'sale.order' not in Registry(get_db_name()):
            raise unittest.SkipTest("sale is not installed")
        super().setUpClass()
        groups = 'base.group_user,base.group_allow_export,sales_team.group_sale_salesman'
        if cls.env.ref('account.group_account_readonly', raise_if_not_found=False):
            groups += ',account.group_account_readonly'
        cls.u = cls._user('mx_entry_sale_u', groups)
        cls.v = cls._user('mx_entry_sale_v', groups)
        cls.env['gec.access.profile'].create({
            'name': 'MX hidden sale prices', 'hide_sale_prices': True, 'user_ids': [Command.set(cls.u.ids)]})
        product = cls.env['product.product'].create({'name': 'MX Product', 'list_price': 100, 'standard_price': 40})
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.env['res.partner'].create({'name': 'MX Customer'}).id,
            'order_line': [Command.create({'product_id': product.id, 'product_uom_qty': 2, 'price_unit': 123.45})]})
        cls.line = cls.order.order_line
        cls.names = {name for model, name in SALE_PRICE_FIELDS if model in ('sale.order', 'sale.order.line')}

    def _cases(self):
        sale = partial(case, model='sale.order')
        order, line, prices = self.order, self.line, shows_values(self.names)
        dom, line_dom = [('id', '=', order.id)], [('id', '=', self.line.id)]
        amounts = ['amount_total', 'amount_untaxed', 'amount_tax', 'tax_totals']
        spec = {'name': {}, 'amount_total': {}, 'amount_untaxed': {}, 'order_line': {'fields': {
            'name': {}, 'price_unit': {}, 'price_subtotal': {}, 'price_total': {}}}}
        return [
            sale('read every field', 'read', [order.ids, self._readable(order)], {}, prices),
            sale('read', 'read', [order.ids, amounts], {}, prices, xmlrpc=True,
                 json2={'ids': order.ids, 'fields': amounts}),
            sale('web_read with order_line', 'web_read', [order.ids], {'specification': spec}, prices, xmlrpc=True,
                 json2={'ids': order.ids, 'specification': spec}),
            sale('search_read', 'search_read', [dom], {'fields': amounts}, prices, xmlrpc=True,
                 json2={'domain': dom, 'fields': amounts}),
            sale('web_search_read', 'web_search_read', [], {'domain': dom, 'specification': spec}, prices,
                 button=True, xmlrpc=True, json2={'domain': dom, 'specification': spec}),
            sale('web_read_group, sum of amount_total', 'web_read_group', [dom, ['partner_id']], {
                'aggregates': ['amount_total:sum']}, found, button=True),
            sale('formatted_read_group, sum of amount_total', 'formatted_read_group', [dom], {
                'groupby': ['partner_id'], 'aggregates': ['amount_total:sum']}, found, xmlrpc=True,
                 json2={'domain': dom, 'groupby': ['partner_id'], 'aggregates': ['amount_total:sum']}),
            sale('read_group, sum of amount_total', 'read_group', [dom], {
                'groupby': ['partner_id'], 'aggregates': ['amount_total:sum']}, found),
            sale('read_group, groupby amount_total', 'read_group', [dom], {
                'groupby': ['amount_total'], 'aggregates': ['__count']}, found),
            sale('export_data, amount_total', 'export_data', [order.ids, ['name', 'amount_total']], {}, exports_a_number,
                 xmlrpc=True, json2={'ids': order.ids, 'fields_to_export': ['name', 'amount_total']}),
            sale('export_data, order_line/price_unit', 'export_data', [order.ids, ['order_line/price_unit']], {},
                 exports_a_number),
            sale('search_count, domain on amount_total', 'search_count', [[('amount_total', '>', 0)]], {}, found,
                 xmlrpc=True, json2={'domain': [('amount_total', '>', 0)]}),
            sale('search, order by amount_total', 'search', [dom], {'order': 'amount_total desc'}, found),
            sale('fields_get', 'fields_get', [], {'attributes': ['string']}, lambda result: 'amount_total' in result),
            sale('line, read', 'read', [line.ids, ['price_unit', 'price_subtotal', 'price_total']], {}, prices,
                 model='sale.order.line'),
            sale('line, web_search_read', 'web_search_read', [], {
                'domain': line_dom, 'specification': {'price_unit': {}, 'price_subtotal': {}}}, prices,
                 model='sale.order.line', button=True),
            sale('line, read_group, sum of price_subtotal', 'read_group', [line_dom], {
                'groupby': ['order_id'], 'aggregates': ['price_subtotal:sum']}, found, model='sale.order.line'),
            sale('line, search_count, domain on price_unit', 'search_count', [[('price_unit', '>', 0)]], {}, found,
                 model='sale.order.line'),
            sale('line, export_data, price_subtotal', 'export_data', [line.ids, ['price_subtotal']], {}, exports_a_number,
                 model='sale.order.line'),
        ]

    def test_call_kw(self):
        self._check_all(self._cases())

    def test_call_button(self):
        self._check_all(self._cases(), 'call_button')

    def test_json2(self):
        self._check_all(self._cases(), 'json2')

    def test_xmlrpc(self):
        self._check_all(self._cases(), 'xmlrpc')


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixCosts(MatrixCase):
    """ A profile with Hide Costs: the cost of a product leaves through no door. """

    @classmethod
    def setUpClass(cls):
        if 'product.product' not in Registry(get_db_name()):
            raise unittest.SkipTest("product is not installed")
        super().setUpClass()
        groups = 'base.group_user,base.group_allow_export,sales_team.group_sale_salesman'
        for xmlid in ('account.group_account_readonly', 'stock.group_stock_user'):
            if cls.env.ref(xmlid, raise_if_not_found=False):
                groups += ',' + xmlid
        cls.u = cls._user('mx_entry_cost_u', groups)
        cls.v = cls._user('mx_entry_cost_v', groups)
        cls.env['gec.access.profile'].create({
            'name': 'MX hidden costs', 'hide_costs': True, 'user_ids': [Command.set(cls.u.ids)]})
        cls.product = cls.env['product.product'].create({'name': 'MX Costly', 'list_price': 100, 'standard_price': 40})
        cls.template = cls.product.product_tmpl_id
        cls.names = {name for model, name in COST_FIELDS if model in ('product.product', 'product.template')}

    def _cases(self):
        costly = partial(case, model='product.product')
        product, template, costs = self.product, self.template, shows_values(self.names)
        dom, template_dom = [('id', '=', product.id)], [('id', '=', self.template.id)]
        spec = {'name': {}, 'standard_price': {}}
        return [
            costly('read every field', 'read', [product.ids, self._readable(product)], {}, costs),
            costly('read', 'read', [product.ids, ['standard_price']], {}, costs, xmlrpc=True,
                 json2={'ids': product.ids, 'fields': ['standard_price']}),
            costly('web_read', 'web_read', [product.ids], {'specification': spec}, costs, xmlrpc=True,
                 json2={'ids': product.ids, 'specification': spec}),
            costly('search_read', 'search_read', [dom], {'fields': ['standard_price']}, costs, xmlrpc=True,
                 json2={'domain': dom, 'fields': ['standard_price']}),
            costly('web_search_read', 'web_search_read', [], {'domain': dom, 'specification': spec}, costs,
                 button=True, xmlrpc=True, json2={'domain': dom, 'specification': spec}),
            costly('export_data', 'export_data', [product.ids, ['name', 'standard_price']], {}, exports_a_number, xmlrpc=True,
                 json2={'ids': product.ids, 'fields_to_export': ['name', 'standard_price']}),
            costly('search_count, domain on standard_price', 'search_count', [[('standard_price', '>', 0)]], {}, found,
                 xmlrpc=True, json2={'domain': [('standard_price', '>', 0)]}),
            costly('search, order by standard_price', 'search', [dom], {'order': 'standard_price desc'}, found),
            costly('formatted_read_group, average of standard_price', 'formatted_read_group', [dom], {
                'groupby': ['categ_id'], 'aggregates': ['standard_price:avg']}, found, xmlrpc=True,
                 json2={'domain': dom, 'groupby': ['categ_id'], 'aggregates': ['standard_price:avg']}),
            costly('web_read_group, average of standard_price', 'web_read_group', [dom, ['categ_id']], {
                'aggregates': ['standard_price:avg']}, found, button=True),
            costly('fields_get', 'fields_get', [], {'attributes': ['string']},
                 lambda result: 'standard_price' in result),
            costly('template, read', 'read', [template.ids, ['standard_price']], {}, costs,
                 model='product.template'),
            costly('template, web_search_read', 'web_search_read', [], {
                'domain': template_dom, 'specification': spec}, costs, model='product.template', button=True),
            costly('template, export_data', 'export_data', [template.ids, ['name', 'standard_price']], {}, exports_a_number,
                 model='product.template'),
            costly('template, search_count, domain on standard_price', 'search_count', [[('standard_price', '>', 0)]],
                 {}, found, model='product.template'),
        ]

    def test_call_kw(self):
        self._check_all(self._cases())

    def test_call_button(self):
        self._check_all(self._cases(), 'call_button')

    def test_json2(self):
        self._check_all(self._cases(), 'json2')

    def test_xmlrpc(self):
        self._check_all(self._cases(), 'xmlrpc')


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixRenamedKeys(MatrixCase):
    """ A locked field, or a value outside a value filter, is judged on what the client sent, before the write or
    create of the model renames the keys (account.move.line turns debit into balance, hr.employee moves wage to its
    version). The web client's doors drop a locked value, the API doors refuse the call, as core refuses a field
    the user may not write. """

    # json2 first: the web session of the other doors makes core refuse the API key of another user
    ROUTES = ('json2', 'xmlrpc', 'call_kw', 'call_button')
    ENTRY = 'MX F3 new'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_user,base.group_partner_manager'
        if cls.env.ref('account.group_account_manager', raise_if_not_found=False):
            groups += ',account.group_account_manager'
        if cls.env.ref('sales_team.group_sale_salesman', raise_if_not_found=False):
            groups += ',sales_team.group_sale_salesman'
        if 'hr.employee' in cls.env:
            # the groups of the wage: hr_payroll replaces the ones of hr
            groups += ',hr.group_hr_manager,' + cls.env['hr.version']._fields['wage'].groups
        cls.u = cls._user('mx_f3_u', groups)
        cls.v = cls._user('mx_f3_v', groups)
        if 'account.move.line' in cls.env:
            cls.debit_account, cls.credit_account = cls.env['account.account'].create([
                {'name': 'MX F3 Debit', 'code': 'MXF31', 'account_type': 'asset_current',
                 'company_ids': [Command.set(cls.env.company.ids)]},
                {'name': 'MX F3 Credit', 'code': 'MXF32', 'account_type': 'liability_current',
                 'company_ids': [Command.set(cls.env.company.ids)]}])
            cls.move = cls.env['account.move'].create({'move_type': 'entry', 'line_ids': [
                Command.create({'account_id': cls.debit_account.id, 'name': 'MX F3', 'debit': 10.0}),
                Command.create({'account_id': cls.credit_account.id, 'name': 'MX F3', 'credit': 10.0})]})
            cls.line_d, cls.line_c = cls.move.line_ids.sorted('debit', reverse=True)
            cls.rec_account, cls.moved_to_account, cls.counter_account = cls.env['account.account'].create([
                {'name': 'MX F3 Rec', 'code': 'MXF33', 'account_type': 'asset_current', 'reconcile': True,
                 'company_ids': [Command.set(cls.env.company.ids)]},
                {'name': 'MX F3 Rec 2', 'code': 'MXF34', 'account_type': 'asset_current', 'reconcile': True,
                 'company_ids': [Command.set(cls.env.company.ids)]},
                {'name': 'MX F3 Counter', 'code': 'MXF35', 'account_type': 'liability_current',
                 'company_ids': [Command.set(cls.env.company.ids)]}])
        if 'hr.employee' in cls.env:
            cls.dept_in, cls.dept_out = cls.env['hr.department'].create([{'name': 'MX F3 In'}, {'name': 'MX F3 Out'}])
            cls.locked, cls.free = cls.env['hr.employee'].create([
                {'name': 'MX F3 Locked', 'wage': 1000.0}, {'name': 'MX F3 Free', 'wage': 1000.0}])

    def _need(self, model):
        if model not in self.env:
            self.skipTest(f"{model} is not installed")

    @staticmethod
    def _locked_answer(route):
        """ What a door answers the profile user who sends a locked value: the API refuses, the web client drops. """
        return 'odoo.exceptions.AccessError' if route in ('json2', 'xmlrpc') else None

    def _profile(self, *lines):
        return self.env['gec.access.profile'].create({
            'name': 'MX F3', 'user_ids': [Command.set(self.u.ids)], 'field_ids': list(lines)})

    def _send(self, route, who, model, method, values, ids=None, context=None):
        """ One write or create through a door of the client: the name of its error, or None. """
        kwargs = {'context': context} if context else {}
        body = {'vals_list' if method == 'create' else 'vals': values, **({'ids': ids} if ids else {}), **kwargs}
        return self._ask(who, model, method, ([ids] if ids else []) + [values], kwargs, route, body)[1]

    def _held(self, record, name):
        record.invalidate_recordset()
        return record[name]

    def _reconciled_lines(self):
        """ Two posted lines of one reconcilable account, reconciled with each other. """
        moves = self.env['account.move'].create([
            {'move_type': 'entry', 'line_ids': [
                Command.create({'account_id': self.rec_account.id, 'name': 'MX F3 rec', 'debit': 10.0}),
                Command.create({'account_id': self.counter_account.id, 'name': 'MX F3 rec', 'credit': 10.0})]},
            {'move_type': 'entry', 'line_ids': [
                Command.create({'account_id': self.rec_account.id, 'name': 'MX F3 rec', 'credit': 10.0}),
                Command.create({'account_id': self.counter_account.id, 'name': 'MX F3 rec', 'debit': 10.0})]}])
        moves.action_post()
        lines = moves.line_ids.filtered(lambda line: line.account_id == self.rec_account)
        lines.reconcile()
        return lines

    def _new_debits(self):
        return self.env['account.move.line'].search([('name', '=', self.ENTRY)]).mapped('debit')

    def _reset_lines(self):
        """ The two lines of the entry back to 10.0 each, the lines the calls created removed. """
        self.env['account.move.line'].search([('name', '=', self.ENTRY)]).with_context(
            check_move_validity=False).unlink()
        self.line_d.with_context(check_move_validity=False).write({'debit': 10.0, 'credit': 0.0})
        self.line_c.with_context(check_move_validity=False).write({'debit': 0.0, 'credit': 10.0})

    def test_a_locked_debit_and_credit_of_a_line_are_not_written(self):
        self._need('account.move.line')
        self._profile(self._field_line('account.move.line', 'debit', 'readonly'),
                      self._field_line('account.move.line', 'credit', 'readonly'))
        for route in self.ROUTES:
            for line, name in ((self.line_d, 'debit'), (self.line_c, 'credit')):
                with self.subTest(route=route, field=name):
                    values, context = {name: 4321.5}, {'check_move_validity': False}
                    self._reset_lines()
                    self.assertIsNone(self._send(route, 'v', 'account.move.line', 'write', values, line.ids, context))
                    self.assertEqual(self._held(line, name), 4321.5, "the control write changes nothing")
                    self._reset_lines()
                    self.assertEqual(self._send(route, 'u', 'account.move.line', 'write', values, line.ids, context),
                                     self._locked_answer(route))
                    self.assertEqual(self._held(line, name), 10.0)

    def test_a_locked_debit_is_not_created(self):
        self._need('account.move.line')
        self._profile(self._field_line('account.move.line', 'debit', 'readonly'))
        values = [{'move_id': self.move.id, 'account_id': self.debit_account.id, 'name': self.ENTRY, 'debit': 4321.5}]
        for route in self.ROUTES:
            with self.subTest(route=route):
                self._reset_lines()
                context = {'check_move_validity': False}
                self.assertIsNone(self._send(route, 'v', 'account.move.line', 'create', values, context=context))
                self.assertIn(4321.5, self._new_debits(), "the control create does not get the debit")
                self._reset_lines()
                self.assertEqual(self._send(route, 'u', 'account.move.line', 'create', values, context=context),
                                 self._locked_answer(route))
                self.assertNotIn(4321.5, self._new_debits())

    def test_a_locked_wage_is_not_written(self):
        self._need('hr.employee')
        self._profile(self._field_line('hr.employee', 'wage', 'readonly'))
        for route in self.ROUTES:
            with self.subTest(route=route):
                self.locked.write({'wage': 1000.0})
                self.assertIsNone(self._send(route, 'v', 'hr.employee', 'write', {'wage': 2000.0}, self.locked.ids))
                self.assertEqual(self._held(self.locked, 'wage'), 2000.0, "the control write changes nothing")
                self.locked.write({'wage': 1000.0})
                self.assertEqual(self._send(route, 'u', 'hr.employee', 'write', {'wage': 2000.0}, self.locked.ids),
                                 self._locked_answer(route))
                self.assertEqual(self._held(self.locked, 'wage'), 1000.0)

    def test_a_wage_locked_under_a_condition_is_judged_per_employee(self):
        self._need('hr.employee')
        self._profile(self._field_line('hr.employee', 'wage', 'readonly', condition="name == 'MX F3 Locked'"))
        both = self.locked | self.free
        for route in self.ROUTES:
            with self.subTest(route=route):
                both.write({'wage': 1000.0})
                self.assertIsNone(self._send(route, 'v', 'hr.employee', 'write', {'wage': 2000.0}, both.ids))
                self.assertEqual([self._held(self.locked, 'wage'), self._held(self.free, 'wage')], [2000.0, 2000.0])
                both.write({'wage': 1000.0})
                refusal = self._locked_answer(route)
                self.assertEqual(self._send(route, 'u', 'hr.employee', 'write', {'wage': 2000.0}, both.ids), refusal)
                self.assertEqual([self._held(self.locked, 'wage'), self._held(self.free, 'wage')],
                                 [1000.0, 1000.0 if refusal else 2000.0], "a refused call writes neither")

    def test_a_department_outside_the_value_filter_is_refused(self):
        self._need('hr.employee')
        self._profile(self._field_line('hr.employee', 'department_id', 'keep',
                                       field_domain=repr([('id', 'in', self.dept_in.ids)])))
        for route in self.ROUTES:
            with self.subTest(route=route):
                self.locked.write({'department_id': False})
                self.assertIsNone(self._send(
                    route, 'v', 'hr.employee', 'write', {'department_id': self.dept_out.id}, self.locked.ids))
                self.assertEqual(self._held(self.locked, 'department_id'), self.dept_out, "the control write changes nothing")
                self.locked.write({'department_id': False})
                self.assertEqual(self._send(
                    route, 'u', 'hr.employee', 'write', {'department_id': self.dept_out.id}, self.locked.ids),
                    'odoo.exceptions.AccessError')
                self.assertFalse(self._held(self.locked, 'department_id'))
                self.assertIsNone(self._send(
                    route, 'u', 'hr.employee', 'write', {'department_id': self.dept_in.id}, self.locked.ids))
                self.assertEqual(self._held(self.locked, 'department_id'), self.dept_in)

    def test_a_locked_email_is_not_set_by_name_create(self):
        self._profile(self._field_line('res.partner', 'email', 'readonly'))
        Partner = self.env['res.partner'].with_context(active_test=False)
        for route in self.ROUTES:
            with self.subTest(route=route):
                for who, email in (('v', 'mx-named@example.com'), ('u', False)):
                    Partner.search([('name', '=', 'MX Named')]).unlink()
                    refusal = self._ask(who, 'res.partner', 'name_create', ['MX Named <mx-named@example.com>'], {},
                                        route, {'name': 'MX Named <mx-named@example.com>'})[1]
                    self.assertIsNone(refusal)
                    self.assertEqual(Partner.search([('name', '=', 'MX Named')]).email, email, f"user {who}")

    def test_create_keeps_the_shape_of_the_client(self):
        self._profile(self._field_line('res.partner', 'email', 'readonly'))
        vals = {'name': 'MX F3 Shape', 'email': 'mx-shape@example.com'}
        one, _error = self._ask('u', 'res.partner', 'create', [vals])
        several, _error = self._ask('u', 'res.partner', 'create', [[vals, vals]])
        self.assertIsInstance(one, int)
        self.assertEqual(len(several), 2)
        partners = self.env['res.partner'].browse([one, *several])
        self.assertEqual(partners.mapped('email'), [False] * 3)

    def test_a_name_create_of_a_read_only_name_is_refused(self):
        self._need('hr.department')
        self._profile(self._field_line('hr.department', 'name', 'readonly'))
        Department = self.env['hr.department']
        for route in self.ROUTES:
            with self.subTest(route=route):
                for who in ('v', 'u'):
                    Department.search([('name', '=', 'MX F3 Quick')]).unlink()
                    refusal = self._ask(who, 'hr.department', 'name_create', ['MX F3 Quick'], {}, route,
                                        {'name': 'MX F3 Quick'})[1]
                    count = len(Department.search([('name', '=', 'MX F3 Quick')]))
                    if who == 'v':
                        self.assertIsNone(refusal, "user v")
                        self.assertEqual(count, 1, "user v")
                    else:
                        self.assertIn(refusal, REFUSALS, "user u")
                        self.assertEqual(count, 0, "user u")

    def test_a_write_with_a_condition_no_record_matches_stays_one_call(self):
        self._need('account.move.line')
        self._profile(self._field_line('account.move.line', 'name', 'readonly', condition="name == 'MX F3 never'"))
        values = {'account_id': self.moved_to_account.id, 'name': 'MX F3 renamed'}
        for route in self.ROUTES:
            for who in ('v', 'u'):
                with self.subTest(route=route, user=who):
                    lines = self._reconciled_lines()
                    self.assertIsNone(self._send(route, who, 'account.move.line', 'write', values, lines.ids))
                    lines.invalidate_recordset()
                    self.assertEqual(lines.account_id, self.moved_to_account)
                    self.assertEqual(lines.mapped('name'), ['MX F3 renamed'] * 2)
                    self.assertTrue(all(lines.mapped('matching_number')), "the reconciliation is kept")

    def test_a_locked_debit_is_not_written_through_ids_sent_as_floats(self):
        self._need('account.move.line')
        self._profile(self._field_line('account.move.line', 'debit', 'readonly'))
        floats = [float(record_id) for record_id in self.line_d.ids]
        values, context = {'debit': 4321.5}, {'check_move_validity': False}
        for route in self.ROUTES:
            with self.subTest(route=route):
                self._reset_lines()
                self.assertIsNone(self._send(route, 'v', 'account.move.line', 'write', values, floats, context))
                self.assertEqual(self._held(self.line_d, 'debit'), 4321.5, "the control write changes nothing")
                self._reset_lines()
                self.assertEqual(self._send(route, 'u', 'account.move.line', 'write', values, floats, context),
                                 self._locked_answer(route))
                self.assertEqual(self._held(self.line_d, 'debit'), 10.0)

    def test_a_locked_wage_is_not_written_by_the_gantt_methods(self):
        self._need('hr.employee')
        if not hasattr(self.env['hr.employee'], 'gantt_undo_drag_drop'):
            self.skipTest("web_gantt is not installed")
        self._profile(self._field_line('hr.employee', 'wage', 'readonly'))
        ids, values = self.locked.ids, {'wage': 2000.0}
        calls = {
            'gantt_undo_drag_drop': ([ids, 'reschedule', values], {'ids': ids, 'drag_action': 'reschedule',
                                                                  'data': values}),
            'action_rollback_scheduling': ([ids, {str(ids[0]): values}], {
                'ids': ids, 'old_vals_per_pill_id': {str(ids[0]): values}}),
        }
        for route in self.ROUTES:
            for method, (args, body) in calls.items():
                if route == 'xmlrpc' and method == 'action_rollback_scheduling':
                    continue  # it answers None, which XML-RPC cannot marshal
                with self.subTest(method=method, route=route):
                    self.locked.write({'wage': 1000.0})
                    self.assertIsNone(self._ask('v', 'hr.employee', method, args, {}, route, body)[1])
                    self.assertEqual(self._held(self.locked, 'wage'), 2000.0, "the control call changes nothing")
                    self.locked.write({'wage': 1000.0})
                    self.assertEqual(self._ask('u', 'hr.employee', method, args, {}, route, body)[1],
                                     self._locked_answer(route))
                    self.assertEqual(self._held(self.locked, 'wage'), 1000.0)
        judged = self.locked.with_user(self.u)._gec_client_values(
            'action_rollback_scheduling', {ids[0]: values, str(ids[0]): values})
        self.assertEqual(judged[0][1], {ids[0]: {}, str(ids[0]): {}}, "int and str keys are both judged")

    def test_a_web_save_of_two_lines_with_a_condition_no_line_matches_stays_one_call(self):
        self._need('account.move.line')
        self._profile(self._field_line('account.move.line', 'account_id', 'readonly',
                                       condition="name == 'MX F3 never'"))
        values = {'account_id': self.moved_to_account.id}
        for who in ('v', 'u'):
            with self.subTest(user=who):
                lines = self._reconciled_lines()
                self.assertIsNone(self._ask(who, 'account.move.line', 'web_save', [lines.ids, values, {}])[1])
                lines.invalidate_recordset()
                self.assertEqual(lines.account_id, self.moved_to_account)
                self.assertTrue(all(lines.mapped('matching_number')), "the reconciliation is kept")

    def test_accepted_limit_a_write_split_by_a_condition_is_made_record_by_record(self):
        """ Accepted limit: records a condition treats differently are written in separate calls, so what Odoo
        does only when it gets all the records at once (keep the reconciliation of the lines it moves to
        another account) does not happen. """
        self._need('account.move.line')
        self._profile(self._field_line('account.move.line', 'name', 'readonly', condition="name == 'MX Split A'"))
        line_a, line_b = lines = self._reconciled_lines()
        line_a.name, line_b.name = 'MX Split A', 'MX Split B'
        values = {'account_id': self.moved_to_account.id, 'name': 'MX Split'}
        self.assertIsNone(self._send('call_kw', 'u', 'account.move.line', 'write', values, lines.ids))
        lines.invalidate_recordset()
        self.assertEqual((line_a.name, line_b.name), ('MX Split A', 'MX Split'))
        self.assertEqual(lines.account_id, self.moved_to_account)
        self.assertFalse(any(lines.mapped('matching_number')), "the reconciliation is gone")

    def test_a_create_keeps_the_name_the_model_fills_when_the_name_is_locked(self):
        self._need('sale.order')
        self._profile(self._field_line('sale.order', 'name', 'readonly'))
        partner = self.env['res.partner'].create({'name': 'MX F3 Customer'})
        names = {}
        for who, forced in (('v', 'MX Forced'), ('u', 'MX Forced'), ('u', None)):
            vals = {'partner_id': partner.id, **({'name': forced} if forced else {})}
            order_id, refusal = self._ask(who, 'sale.order', 'create', [vals])
            self.assertIsNone(refusal, f"user {who}")
            names[who, forced] = self.env['sale.order'].browse(order_id).name
        self.assertEqual(names['v', 'MX Forced'], 'MX Forced', "the control create sets the name")
        self.assertNotIn(names['u', 'MX Forced'], ('New', 'MX Forced'), "the client cannot set the name")
        self.assertNotIn(names['u', None], ('New', 'MX Forced'), "the model's own create fills the name")

    def test_ids_sent_as_floats_do_not_pass_a_many2many_value_filter(self):
        tag_ok, tag_other = self.env['res.partner.category'].create([{'name': 'MX F3 Ok'}, {'name': 'MX F3 Other'}])
        partner = self.env['res.partner'].create({'name': 'MX F3 Tagged'})
        self._profile(self._field_line('res.partner', 'category_id', 'keep',
                                       field_domain=repr([('id', 'in', tag_ok.ids)])))
        other, ok = float(tag_other.id), float(tag_ok.id)
        for route in self.ROUTES:
            for label, value in (('link', [Command.link(other)]), ('set', [Command.set([other])]), ('plain', [other])):
                with self.subTest(route=route, command=label):
                    partner.category_id = False
                    self.assertIsNone(self._send(route, 'v', 'res.partner', 'write', {'category_id': value}, partner.ids))
                    self.assertEqual(self._held(partner, 'category_id'), tag_other, "the control write changes nothing")
                    partner.category_id = False
                    self.assertEqual(self._send(route, 'u', 'res.partner', 'write', {'category_id': value}, partner.ids),
                                     'odoo.exceptions.AccessError')
                    self.assertFalse(self._held(partner, 'category_id'))
            with self.subTest(route=route, command='allowed'):
                self.assertIsNone(self._send(
                    route, 'u', 'res.partner', 'write', {'category_id': [Command.set([ok])]}, partner.ids))
                self.assertEqual(self._held(partner, 'category_id'), tag_ok)

    def test_a_line_sent_with_a_float_id_keeps_its_condition_lock(self):
        self._profile(self._field_line('res.partner', 'phone', 'readonly', condition="name == 'MX F3 Child'"))
        parent = self.env['res.partner'].create({'name': 'MX F3 Parent'})
        child = self.env['res.partner'].create({'name': 'MX F3 Child', 'parent_id': parent.id, 'phone': '111-MX'})
        value = [Command.update(float(child.id), {'phone': '999-MX'})]
        for route in self.ROUTES:
            with self.subTest(route=route):
                child.phone = '111-MX'
                self.assertIsNone(self._send(route, 'v', 'res.partner', 'write', {'child_ids': value}, parent.ids))
                self.assertEqual(self._held(child, 'phone'), '999-MX', "the control write changes nothing")
                child.phone = '111-MX'
                self.assertEqual(self._send(route, 'u', 'res.partner', 'write', {'child_ids': value}, parent.ids),
                                 self._locked_answer(route))
                self.assertEqual(self._held(child, 'phone'), '111-MX')

    def test_a_locked_name_does_not_name_the_company_made_from_parent_name(self):
        self._profile(self._field_line('res.partner', 'name', 'readonly'))
        Partner = self.env['res.partner'].with_context(active_test=False)
        vals = [{'name': 'MX F4 Child', 'type': 'invoice', 'parent_name': 'MX F4 Parent Co'}]
        for route in self.ROUTES:
            with self.subTest(route=route):
                for who, named in (('v', True), ('u', False)):
                    Partner.search([('name', 'in', ['MX F4 Child', 'MX F4 Parent Co'])]).sudo().unlink()
                    refusal = self._send(route, who, 'res.partner', 'create', vals)
                    if who == 'v':
                        self.assertIsNone(refusal, "the control create works")
                    self.assertEqual(bool(Partner.search([('name', '=', 'MX F4 Parent Co')])), named, f"user {who}")
    def test_a_many2one_sent_as_a_float_is_judged_by_its_value_filter(self):
        country_ok, country_other = self.env['res.country'].search([], limit=2)
        self._profile(self._field_line('res.partner', 'country_id', 'keep',
                                       field_domain=repr([('id', 'in', country_ok.ids)])))
        Partner = self.env['res.partner']
        vals = [{'name': 'MX F4 Country', 'country_id': float(country_other.id)}]
        for route in self.ROUTES:
            with self.subTest(route=route):
                Partner.search([('name', '=', 'MX F4 Country')]).unlink()
                self.assertIsNone(self._send(route, 'v', 'res.partner', 'create', vals))
                self.assertEqual(Partner.search([('name', '=', 'MX F4 Country')]).country_id, country_other,
                                 "the control create changes nothing")
                Partner.search([('name', '=', 'MX F4 Country')]).unlink()
                self.assertEqual(self._send(route, 'u', 'res.partner', 'create', vals), 'odoo.exceptions.AccessError')
                self.assertFalse(Partner.search([('name', '=', 'MX F4 Country')]))

    def test_a_line_sent_with_a_float_id_is_judged_by_a_value_filter(self):
        tag_ok, tag_other = self.env['res.partner.category'].create([{'name': 'MX F4 Ok'}, {'name': 'MX F4 Other'}])
        self._profile(self._field_line('res.partner', 'category_id', 'keep',
                                       field_domain=repr([('id', 'in', tag_ok.ids)])))
        parent = self.env['res.partner'].create({'name': 'MX F4 Parent'})
        child = self.env['res.partner'].create({'name': 'MX F4 Line', 'parent_id': parent.id, 'phone': '111-MX'})
        line_id = float(child.id)
        for route in self.ROUTES:
            with self.subTest(route=route):
                child.write({'phone': '111-MX', 'category_id': [Command.clear()]})
                self.assertIsNone(self._send(route, 'u', 'res.partner', 'write', {
                    'child_ids': [Command.update(line_id, {'phone': '999-MX'})]}, parent.ids))
                self.assertEqual(self._held(child, 'phone'), '999-MX')
                self.assertEqual(self._send(route, 'u', 'res.partner', 'write', {
                    'child_ids': [Command.update(line_id, {'category_id': [Command.link(tag_other.id)]})]},
                    parent.ids), 'odoo.exceptions.AccessError')
                self.assertFalse(self._held(child, 'category_id'))

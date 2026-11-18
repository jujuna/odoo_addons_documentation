# Companies and access profiles: a profile follows the companies of the user, not the one they work in; a filter
# on company_ids acts like a core row; the core company rules still apply under any profile; the allowed
# journals and check_company are unchanged. Companies A (the main one), B and C are created here.
import re
from unittest import SkipTest

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

USER_GROUPS = ('base.group_user', 'base.group_partner_manager', 'sales_team.group_sale_salesman_all_leads')
OPERATIONS = ('read', 'write', 'create', 'unlink')
COMPANY_FILTER = "[('company_id', 'in', company_ids)]"


class CompanyHelpers:

    @classmethod
    def _groups(cls, *extra):
        return ','.join(xmlid for xmlid in (*USER_GROUPS, *extra) if cls.env.ref(xmlid, raise_if_not_found=False))

    @classmethod
    def _create_users(cls, groups):
        """ ``user_u`` in A and B, ``user_w`` in A only; the main company of both is A. """
        cls.user_u = new_test_user(
            cls.env, 'mx_mc_u', groups=groups, company_id=cls.company_a.id,
            company_ids=[Command.set((cls.company_a | cls.company_b).ids)])
        cls.user_w = new_test_user(cls.env, 'mx_mc_w', groups=groups, company_id=cls.company_a.id)

    def _profile(self, users, company=None, strictness='additive', lines=(), **values):
        """ A profile of ``users`` for ``company``; ``lines`` are (model, {perm_read...: bool, domain: text}). """
        return self.env['gec.access.profile'].create({
            'name': 'Matrix companies', 'user_ids': [Command.set(users.ids)], 'company_id': company.id if company else False,
            'strictness': strictness, 'model_ids': [
                Command.create({'model_id': self.env['ir.model']._get(model).id, **perms}) for model, perms in lines],
            **values})

    def _as(self, user, companies, model):
        """ ``model`` as ``user`` working in ``companies``. """
        return self.env[model].with_user(user).with_context(allowed_company_ids=[company.id for company in companies])

    def _can(self, user, companies, record, operation):
        return record.with_user(user).with_context(
            allowed_company_ids=[company.id for company in companies]).has_access(operation)

    def _seen(self, user, companies, records):
        """ The records among ``records`` that ``user`` finds by a search while working in ``companies``. """
        return self._as(user, companies, records._name).search([('id', 'in', records.ids)])

    def _result_of(self, call):
        try:
            return call()
        except AccessError:
            return 'refused'


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixCompanyProfiles(CompanyHelpers, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b, cls.company_c = cls.env['res.company'].create([
            {'name': 'MX Company B'}, {'name': 'MX Company C'}])
        cls._create_users(cls._groups())
        Partner = cls.env['res.partner']
        cls.partner = Partner.create({'name': 'MX Open Partner'})
        cls.partner_a, cls.partner_b, cls.partner_c = Partner.create([
            {'name': f'MX Partner of {company.name}', 'company_id': company.id}
            for company in (cls.company_a, cls.company_b, cls.company_c)])
        cls.partner_free = Partner.create({'name': 'MX Free Partner'})
        cls.partners = cls.partner_a | cls.partner_b | cls.partner_c | cls.partner_free
        cls.no_delete = [('res.partner', {'perm_unlink': False})]

    def setUp(self):
        super().setUp()
        self._rules = []

    def test_a_profile_of_company_a_applies_to_a_user_working_in_b(self):
        A, B = self.company_a, self.company_b
        for companies in ([B], [A], [A, B]):
            self.assertTrue(self._can(self.user_u, companies, self.partner, 'unlink'))
        self._profile(self.user_u | self.user_w, company=A, lines=self.no_delete)
        for companies in ([B], [A], [A, B]):
            with self.subTest(companies=companies.__repr__()):
                self.assertFalse(self._can(self.user_u, companies, self.partner, 'unlink'))
        self.assertFalse(self._can(self.user_w, [A], self.partner, 'unlink'))

    def test_a_profile_of_company_b_applies_to_a_user_of_b_not_to_a_user_of_a_only(self):
        A, B = self.company_a, self.company_b
        self._profile(self.user_u | self.user_w, company=B, lines=self.no_delete)
        self.assertFalse(self._can(self.user_u, [A, B], self.partner, 'unlink'))
        self.assertFalse(self._can(self.user_u, [A], self.partner, 'unlink'))
        self.assertTrue(self._can(self.user_w, [A], self.partner, 'unlink'))

    def test_a_profile_of_company_c_never_applies_to_a_user_outside_it(self):
        A, B = self.company_a, self.company_b
        self._profile(self.user_u | self.user_w, company=self.company_c, lines=self.no_delete)
        for companies in ([A], [B], [A, B]):
            with self.subTest(companies=repr(companies)):
                self.assertTrue(self._can(self.user_u, companies, self.partner, 'unlink'))
        self.assertTrue(self._can(self.user_w, [A], self.partner, 'unlink'))

    def test_removing_company_a_from_the_user_drops_the_profile_and_its_granted_groups(self):
        A, B = self.company_a, self.company_b
        granted = self.env['res.groups'].create({'name': 'MX Granted'})
        self.env['ir.model.data'].create({'module': 'gec_matrix_test', 'name': 'mx_granted',
                                          'model': 'res.groups', 'res_id': granted.id})
        self.assertFalse(self.user_u.has_group('gec_matrix_test.mx_granted'))
        self._profile(self.user_u | self.user_w, company=A, lines=self.no_delete, granted_group_ids=[Command.set(granted.ids)])
        self.assertTrue(self.user_u.has_group('gec_matrix_test.mx_granted'))
        self.assertFalse(self._can(self.user_u, [A, B], self.partner, 'unlink'))
        self.user_u.write({'company_id': B.id, 'company_ids': [Command.set(B.ids)]})
        self.user_u.invalidate_recordset()
        self.assertFalse(self.user_u.has_group('gec_matrix_test.mx_granted'))
        self.assertTrue(self._can(self.user_u, [B], self.partner, 'unlink'))
        self.assertTrue(self.user_w.has_group('gec_matrix_test.mx_granted'))
        self.user_u.write({'company_ids': [Command.link(A.id)]})
        self.user_u.invalidate_recordset()
        self.assertTrue(self.user_u.has_group('gec_matrix_test.mx_granted'))
        self.assertFalse(self._can(self.user_u, [A, B], self.partner, 'unlink'))

    def _restrict(self, mode, restrictions):
        for rule in self._rules:
            rule.unlink()
        self._rules = []
        if mode == 'profile':
            self._rules = [self._profile(self.user_u, lines=[(model, {'domain': domain}) for model, domain in restrictions.items()])]
        elif mode == 'core':
            self._rules = [self.env['ir.access'].create({
                'name': f'Matrix {model}', 'model_id': self.env['ir.model']._get(model).id,
                'group_id': False, 'operation': 'crud', 'domain': domain,
            }) for model, domain in restrictions.items()]
        self.env.invalidate_all()

    def test_a_company_filter_acts_like_a_core_row(self):
        A, B = self.company_a, self.company_b
        self._rules = []
        expected = {(A,): self.partner_a, (B,): self.partner_b, (A, B): self.partner_a | self.partner_b}
        baseline = {companies: self._seen(self.user_u, companies, self.partners) for companies in expected}
        self.assertIn(self.partner_free, baseline[(A,)])
        for mode in ('profile', 'core'):
            self._restrict(mode, {'res.partner': COMPANY_FILTER})
            for companies, records in expected.items():
                with self.subTest(mode=mode, companies=[company.name for company in companies]):
                    self.assertEqual(self._seen(self.user_u, companies, self.partners), records)

    def test_a_company_filter_on_write_acts_like_a_core_row(self):
        A, B = self.company_a, self.company_b
        self._rules = []
        for mode in ('profile', 'core'):
            self._restrict(mode, {'res.partner': COMPANY_FILTER})
            for companies, allowed in (((A,), self.partner_a), ((B,), self.partner_b), ((A, B), self.partner_a | self.partner_b)):
                with self.subTest(mode=mode, companies=[company.name for company in companies]):
                    can = self.partners.filtered(lambda partner: self._can(self.user_u, companies, partner, 'write'))
                    self.assertEqual(can, allowed)

    def test_an_open_profile_never_opens_the_records_of_company_c(self):
        if 'sale.order' not in self.env:
            self.skipTest("sale is not installed")
        A, B, C = self.company_a, self.company_b, self.company_c
        Order = self.env['sale.order']
        pairs = [(self.partner_a, self.partner_c), (
            Order.create({'partner_id': self.partner.id, 'company_id': A.id}),
            Order.create({'partner_id': self.partner.id, 'company_id': C.id}))]

        def scenario(mine, foreign):
            return (
                self._can(self.user_u, [A, B], mine, 'read'), self._can(self.user_u, [A, B], foreign, 'read'),
                self._result_of(lambda: foreign.with_user(self.user_u).with_context(
                    allowed_company_ids=[A.id, B.id]).read(['display_name'])),
                self._seen(self.user_u, [A, B], mine | foreign).ids)

        for mine, foreign in pairs:
            with self.subTest(model=mine._name):
                self.assertEqual(scenario(mine, foreign), (True, False, 'refused', mine.ids))
        self._profile(self.user_u, lines=[('res.partner', {'domain': '[]'}), ('sale.order', {'domain': '[]'})])
        for mine, foreign in pairs:
            with self.subTest(model=mine._name, profile=True):
                self.assertEqual(scenario(mine, foreign), (True, False, 'refused', mine.ids))

    def test_the_profiles_of_the_companies_of_the_user_combine_as_documented(self):
        A, B, C = self.company_a, self.company_b, self.company_c
        category = self.env['res.partner.category'].create({'name': 'MX Category'})
        read_only = {'perm_write': False, 'perm_create': False, 'perm_unlink': False}
        override = self._profile(self.user_u, company=A, strictness='override', lines=[('res.partner.category', read_only)])
        additive = self._profile(self.user_u, company=B, lines=[('res.partner.category', {})])
        allows = {override: dict.fromkeys(OPERATIONS, False) | {'read': True}, additive: dict.fromkeys(OPERATIONS, True)}
        for companies in ((A, B), (A,), (B,), (C,)):
            self.user_u.write({'company_id': companies[0].id, 'company_ids': [Command.set(sum(companies, A.browse()).ids)]})
            self.env.invalidate_all()
            applicable = [profile for profile in (override, additive) if profile.company_id in companies]
            for operation in OPERATIONS:
                overrides = [allows[profile][operation] for profile in applicable if profile.strictness == 'override']
                additives = [allows[profile][operation] for profile in applicable if profile.strictness == 'additive']
                expected = all(overrides) and (not additives or any(additives))
                with self.subTest(companies=[company.name for company in companies], operation=operation):
                    self.assertEqual(self._can(self.user_u, [companies[0]], category, operation), expected)

    def test_the_check_company_error_of_core_is_unchanged_under_a_profile(self):
        if 'sale.order' not in self.env:
            self.skipTest("sale is not installed")
        A, B = self.company_a, self.company_b
        partner_of_a = self.env['res.partner'].create({'name': 'MX Partner Of A Only', 'company_id': A.id})

        def create_order():
            return self._as(self.user_u, [B, A], 'sale.order').create({'partner_id': partner_of_a.id, 'company_id': B.id})

        def error():
            with self.assertRaises(UserError) as caught:
                create_order()
            return re.sub(r'S\d+', 'S', str(caught.exception))

        baseline = error()
        self.assertIn('belongs to another company', baseline)
        self._profile(self.user_u, lines=[('sale.order', {}), ('res.partner', {})])
        self._profile(self.user_u, company=B, lines=[('sale.order', {'domain': '[]'})])
        self.assertEqual(error(), baseline)


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixCompanyJournals(CompanyHelpers, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'account.journal' not in cls.env:
            raise SkipTest("account is not installed")
        cls.company_a = cls.env.company
        cls.company_b, cls.company_c = cls.env['res.company'].create([
            {'name': 'MX Journals B'}, {'name': 'MX Journals C'}])
        cls._create_users(cls._groups('account.group_account_invoice', 'account.group_account_readonly'))
        Journal = cls.env['account.journal']
        cls.sale_a = Journal.search([('company_id', '=', cls.company_a.id), ('type', '=', 'sale')], limit=1)
        cls.purchase_a = Journal.search([('company_id', '=', cls.company_a.id), ('type', '=', 'purchase')], limit=1)
        cls.accounts = {}
        cls.misc_b, cls.misc_c = cls._books(cls.company_b), cls._books(cls.company_c)
        cls.partner = cls.env['res.partner'].create({'name': 'MX Customer'})
        cls.invoice_a = cls._invoice('out_invoice', cls.sale_a)
        cls.bill_a = cls._invoice('in_invoice', cls.purchase_a)
        cls.entry_b = cls._entry(cls.misc_b)
        cls.entry_c = cls._entry(cls.misc_c)
        cls.moves = cls.invoice_a | cls.bill_a | cls.entry_b | cls.entry_c

    @classmethod
    def _books(cls, company):
        """ A general journal of ``company`` with two accounts: a company made here has no chart of accounts. """
        Account = cls.env['account.account'].with_company(company)
        debit, credit = Account.create([
            {'name': 'MX Debit', 'code': 'MX1000', 'account_type': 'asset_current', 'company_ids': [Command.set(company.ids)]},
            {'name': 'MX Credit', 'code': 'MX2000', 'account_type': 'liability_current', 'company_ids': [Command.set(company.ids)]}])
        journal = cls.env['account.journal'].create({
            'name': 'MX Misc', 'code': 'MXM', 'type': 'general', 'company_id': company.id})
        cls.accounts[company.id] = (debit.id, credit.id)
        return journal

    @classmethod
    def _entry_values(cls, journal):
        debit, credit = cls.accounts[journal.company_id.id]
        return {'move_type': 'entry', 'journal_id': journal.id, 'company_id': journal.company_id.id, 'date': '2026-10-01', 'line_ids': [
            Command.create({'account_id': debit, 'debit': 100.0, 'credit': 0.0}),
            Command.create({'account_id': credit, 'debit': 0.0, 'credit': 100.0})]}

    @classmethod
    def _entry(cls, journal):
        return cls.env['account.move'].with_company(journal.company_id).create(cls._entry_values(journal))

    @classmethod
    def _invoice_values(cls, move_type, journal):
        Account = cls.env['account.account'].with_company(journal.company_id)
        kind = 'income' if move_type == 'out_invoice' else 'expense'
        account = Account.search([('account_type', '=', kind)], limit=1)
        return {'move_type': move_type, 'partner_id': cls.partner.id, 'journal_id': journal.id,
                'company_id': journal.company_id.id, 'invoice_date': '2026-10-01',
                'invoice_line_ids': [Command.create({'name': 'MX line', 'price_unit': 100.0, 'quantity': 1,
                                                     'account_id': account.id})]}

    @classmethod
    def _invoice(cls, move_type, journal):
        return cls.env['account.move'].create(cls._invoice_values(move_type, journal))

    def _allow_sale_journal_of_a(self):
        return self.env['gec.access.profile'].create({
            'name': 'Only the sales journal of A', 'user_ids': [Command.set(self.user_u.ids)],
            'allowed_ids': [Command.create({'kind': 'journal', 'res_id': self.sale_a.id})]})

    def test_only_the_allowed_journal_and_its_moves_are_seen(self):
        A, B = self.company_a, self.company_b
        journals = self.sale_a | self.purchase_a | self.misc_b | self.misc_c
        self._allow_sale_journal_of_a()
        self.assertEqual(self._seen(self.user_u, [A, B], journals), self.sale_a)
        self.assertEqual(self._seen(self.user_u, [A, B], self.moves), self.invoice_a)
        self.assertEqual(self._seen(self.user_u, [A], self.moves), self.invoice_a)
        self.assertFalse(self._seen(self.user_u, [B], self.moves))
        every = self._as(self.user_u, [A, B], 'account.journal').search([])
        company_journals = self.env['res.company'].search([]).mapped('currency_exchange_journal_id') | \
            self.env['res.company'].search([]).mapped('tax_cash_basis_journal_id')
        self.assertLessEqual(every, self.sale_a | company_journals)
        self.assertFalse(every & (self.purchase_a | self.misc_b | self.misc_c))

    def test_an_invoice_is_created_and_posted_in_the_allowed_journal_only(self):
        A, B = self.company_a, self.company_b
        Move = self._as(self.user_u, [A, B], 'account.move')
        values = {
            'bill of A': self._invoice_values('in_invoice', self.purchase_a),
            'entry of B': self._entry_values(self.misc_b)}
        for name, vals in values.items():
            with self.subTest(before_the_profile=name):
                Move.with_company(self.env['res.company'].browse(vals['company_id'])).create(vals)
        self._allow_sale_journal_of_a()
        invoice = Move.create(self._invoice_values('out_invoice', self.sale_a))
        invoice.action_post()
        self.assertEqual(invoice.state, 'posted')
        for name, vals in values.items():
            with self.subTest(with_the_profile=name), self.assertRaises(AccessError):
                Move.with_company(self.env['res.company'].browse(vals['company_id'])).create(vals)
        with self.assertRaises(AccessError):
            self.bill_a.with_user(self.user_u).with_context(allowed_company_ids=[A.id, B.id]).write({'ref': 'MX'})

    def test_an_open_profile_never_opens_the_journals_and_moves_of_company_c(self):
        A, B = self.company_a, self.company_b
        pairs = [(self.sale_a, self.misc_c), (self.invoice_a, self.entry_c)]

        def scenario(mine, foreign):
            return (
                self._can(self.user_u, [A, B], mine, 'read'), self._can(self.user_u, [A, B], foreign, 'read'),
                self._result_of(lambda: foreign.with_user(self.user_u).with_context(
                    allowed_company_ids=[A.id, B.id]).read(['display_name'])),
                self._seen(self.user_u, [A, B], mine | foreign).ids)

        for mine, foreign in pairs:
            with self.subTest(model=mine._name):
                self.assertEqual(scenario(mine, foreign), (True, False, 'refused', mine.ids))
        self.env['gec.access.profile'].create({
            'name': 'Open', 'user_ids': [Command.set(self.user_u.ids)], 'model_ids': [
                Command.create({'model_id': self.env['ir.model']._get(model).id, 'domain': '[]'})
                for model in ('account.journal', 'account.move', 'account.move.line')]})
        for mine, foreign in pairs:
            with self.subTest(model=mine._name, profile=True):
                self.assertEqual(scenario(mine, foreign), (True, False, 'refused', mine.ids))

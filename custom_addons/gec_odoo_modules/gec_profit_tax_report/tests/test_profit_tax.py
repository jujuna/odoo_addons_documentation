from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProfitTax(TransactionCase):
    """The rs.ge instruction examples and the flows around them, on a company with the Georgian chart."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        georgia = cls.env.ref('base.ge')
        cls.company = cls.env['res.company'].create({
            'name': 'Profit Tax Test LLC', 'country_id': georgia.id, 'currency_id': cls.env.ref('base.GEL').id})
        cls.env.user.company_ids |= cls.company
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id]))
        cls.env['account.chart.template'].try_loading('ge', cls.company, install_demo=False)
        cls.company = cls.company.with_env(cls.env)
        cls.journal = cls.company.gec_cit_journal_id
        cls.bank = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'bank')], limit=1).default_account_id
        Partner = cls.env['res.partner']
        cls.person = Partner.create({'name': 'Shareholder Person'})
        cls.llc = Partner.create({'name': 'Georgian LLC', 'vat': '206322102', 'country_id': georgia.id,
                                  'gec_cit_status': 'enterprise'})
        cls.fiz = Partner.create({'name': 'FIZ Supplier', 'vat': '404000111', 'country_id': georgia.id,
                                  'gec_cit_status': 'exempt'})
        cls.charity = Partner.create({'name': 'Charity Fund', 'vat': '404000222', 'country_id': georgia.id,
                                      'gec_cit_charity': True})
        # Last year: income 300,000, expenses 200,000, net profit 100,000.
        cls._post('2025-06-30', [(cls._acc('611101'), 0, 300000, None), (cls.bank, 300000, 0, None)])
        cls._post('2025-06-30', [(cls._acc('740100'), 200000, 0, None), (cls.bank, 0, 200000, None)])

    @classmethod
    def _acc(cls, code):
        return cls.env['account.chart.template'].with_company(cls.company).ref(f'ge_account_{code}')

    @classmethod
    def _post(cls, date, lines):
        move = cls.env['account.move'].create({'journal_id': cls.journal.id, 'date': date, 'line_ids': [
            (0, 0, {'account_id': account.id, 'debit': debit, 'credit': credit, 'name': 'test',
                    'partner_id': partner.id if partner else False})
            for account, debit, credit, partner in lines]})
        move.action_post()
        return move

    def _declaration(self, month, **vals):
        declaration = self.env['rs.cit.declaration'].create(
            {'date_from': f'2026-{month:02d}-01', 'company_id': self.company.id, **vals})
        declaration.action_compute()
        return declaration

    def _amounts(self, declaration, column='amount'):
        return {line.code: line[column] for line in declaration.line_ids}

    def test_dividend_withholding_added_back_and_enterprise_left_out(self):
        """A dividend booked by the CIT wizard with 5% withholding counts gross; one to a Georgian LLC not."""
        wizard = self.env['l10n.ge.cit.wizard'].create({
            'journal_id': self.journal.id, 'date': '2026-01-20', 'partner_id': self.person.id, 'net_amount': 10000,
            'distribution_account_id': self._acc('530110').id, 'cit_account_id': self._acc('331110').id,
            'payable_account_id': self._acc('340120').id, 'apply_dividend_wht': True,
            'treasury_partner_id': self.env['res.partner'].create({'name': 'Treasury'}).id})
        accrual = self.env['account.move'].browse(wizard.action_post_cit()['res_id'])
        payment = self._post('2026-01-25', [(self._acc('340120'), 9500, 0, self.person), (self.bank, 0, 9500, None)])
        (accrual.line_ids | payment.line_ids).filtered(lambda l: l.account_id == self._acc('340120')).reconcile()
        self._post('2026-01-26', [(self._acc('340120'), 3000, 0, self.llc), (self.bank, 0, 3000, None)])
        declaration = self._declaration(1)
        amounts = self._amounts(declaration)
        self.assertEqual(amounts['16.1'], 10000)
        self.assertEqual(declaration.dividend_unmatched, 0)
        self.assertAlmostEqual(amounts['24'], 1764.71, places=2)
        self.assertAlmostEqual(declaration.booking_amount, 0.0, places=2, msg="the wizard already booked it")

    def test_representation_limit(self):
        """Instruction example 5 shape: limit 1% of last year's expenses or income, whichever is higher."""
        self._post('2026-01-05', [(self._acc('750300'), 2000, 0, None), (self.bank, 0, 2000, None)])
        january = self._declaration(1)
        self.assertEqual(self._amounts(january)['20'], 0)
        january.action_confirm()
        self._post('2026-02-05', [(self._acc('750300'), 2500, 0, None), (self.bank, 0, 2500, None)])
        february = self._declaration(2)
        self.assertEqual(self._amounts(february)['20'], 1500, "4,500 spent less the 3,000 limit")

    def test_charity_above_ten_percent(self):
        """Instruction example 4: 5,000 + 7,500 donated, limit 10,000 -> 2,500 in the second month."""
        self._post('2026-01-05', [(self._acc('820710'), 5000, 0, self.charity), (self.bank, 0, 5000, None)])
        january = self._declaration(1)
        self.assertEqual(self._amounts(january)['19'], 0)
        january.action_confirm()
        self._post('2026-02-05', [(self._acc('820710'), 7500, 0, self.charity), (self.bank, 0, 7500, None)])
        self.assertEqual(self._amounts(self._declaration(2))['19'], 2500)

    def test_market_price_exempt_supplier(self):
        """Instruction example 2: paid 10,000 to an exempt supplier for goods worth 8,000 -> 16.4.2 = 2,000."""
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.fiz.id, 'invoice_date': '2026-01-10',
            'invoice_line_ids': [(0, 0, {'name': 'goods', 'quantity': 1, 'price_unit': 10000,
                                         'tax_ids': [(6, 0, [])], 'gec_cit_market_value': 8000})]})
        bill.action_post()
        amounts = self._amounts(self._declaration(1))
        self.assertEqual(amounts['16.4.2'], 2000)
        self.assertEqual(amounts['16'], 2000)

    def test_loan_taxed_then_recovered(self):
        """A loan to an individual is taxed on 18.3; its repayment next month comes back on 27.2 (annex 1.2).
        A loan to a Georgian LLC counts nowhere."""
        self._post('2026-01-11', [(self._acc('140710'), 5000, 0, self.person), (self.bank, 0, 5000, None)])
        self._post('2026-01-12', [(self._acc('140710'), 7000, 0, self.llc), (self.bank, 0, 7000, None)])
        january = self._declaration(1)
        self.assertEqual(self._amounts(january)['18.3'], 5000)
        january.action_confirm()
        self._post('2026-02-06', [(self.bank, 2000, 0, None), (self._acc('140710'), 0, 2000, self.person)])
        february = self._declaration(2)
        amounts = self._amounts(february)
        self.assertEqual(amounts['27.2'], 2000)
        self.assertAlmostEqual(amounts['29'], 352.94, places=2)
        self.assertEqual(february.recovery_ids.taxed_code, '18.3')
        february.action_confirm()
        self.assertEqual(january.taxed_item_ids.remaining, 3000)
        with self.assertRaises(UserError):
            january.action_draft()

    def test_international_company_annex_16(self):
        """Instruction example 7: net profit 100,000, dividend 20,000, expenses 60,000 -> 16.1.3 = 8,000 at 5%."""
        self.company.gec_cit_company_status = 'international'
        declaration = self._declaration(3)
        self.env['rs.cit.annex.line'].create({'declaration_id': declaration.id, 'annex': '1.6', 'name': '2025',
                                              'amount1': 100000, 'amount2': 20000, 'amount3': 60000})
        amounts = self._amounts(declaration, 'amount3')
        self.assertEqual(amounts['16.1.3'], 8000)
        self.assertAlmostEqual(amounts['24'], 421.05, places=2)

    def test_special_status_goes_to_column_3(self):
        """An innovative startup keeps part I status Resident Enterprise; its objects go to column 3 at 15%."""
        self.company.gec_cit_special_status = 'startup'
        self._post('2026-01-05', [(self._acc('820510'), 500, 0, None), (self._acc('160110'), 0, 500, None)])
        declaration = self._declaration(1)
        self.assertEqual(declaration.company_status, 'resident')
        self.assertEqual(declaration.col3_rate, 0.15)
        self.assertEqual(self._amounts(declaration)['19.1'], 0)
        self.assertEqual(self._amounts(declaration, 'amount3')['19.1'], 500)
        self.assertAlmostEqual(self._amounts(declaration, 'amount3')['24'], 88.24, places=2)

    def test_annex_1_credit_capped(self):
        """Annex 1 line 5 = line 1 x line 2 / (line 3 - line 4); line 25.1 at most the tax on 16.1.1."""
        declaration = self._declaration(1, a1_2=50000, a1_3=400000)
        declaration.line_ids.filtered(lambda l: l.code == '16.1.1').amount_adjust = 20000
        self.assertEqual(declaration.a1_5, 2500)
        self.assertEqual(self._amounts(declaration)['25.1'], 2500)
        declaration.a1_2 = 500000
        self.assertAlmostEqual(self._amounts(declaration)['25.1'], 3529.41, places=2)

    def test_correction_posts_the_difference(self):
        """With booking on, a correction posts only what it adds to the earlier version."""
        self.company.gec_cit_post_entry = True
        self._post('2026-01-05', [(self._acc('820990'), 1700, 0, None), (self.bank, 0, 1700, None)])
        primary = self._declaration(1)
        primary.line_ids.filtered(lambda l: l.code == '17.2').amount_adjust = 1700
        primary.action_confirm()
        self.assertEqual(primary.booked_amount, 300)
        correction = self.env['rs.cit.declaration'].browse(primary.action_create_correction()['res_id'])
        self.assertEqual(correction.declaration_type, 'corrected')
        correction.line_ids.filtered(lambda l: l.code == '17.2').amount_adjust = 2550
        correction.action_confirm()
        self.assertEqual(correction.booked_amount, 150)
        with self.assertRaises(UserError):
            primary.action_draft()

    def test_annex_11_reads_the_month_typed(self):
        """Annex 1.1 part I: typing a month fills lines 25.1 and 16.1.1 of that month's confirmed declaration."""
        january = self._declaration(1, a1_2=50000, a1_3=400000)
        january.line_ids.filtered(lambda l: l.code == '16.1.1').amount_adjust = 20000
        january.action_confirm()
        february = self._declaration(2)
        line = self.env['rs.cit.annex.line'].create({'declaration_id': february.id, 'annex': '1.1', 'name': '01/2026'})
        self.assertEqual((line.amount1, line.amount2), (2500, 20000))
        line.name = '2026/03'
        self.assertEqual((line.amount1, line.amount2), (0, 0), "no confirmed March declaration")

    def test_annex_values_follow_until_typed(self):
        """Annex 1 line 1 follows line 16.1.1 until someone types it; then a change of 16.1.1 leaves it alone."""
        declaration = self._declaration(1, a1_2=50000, a1_3=400000)
        row = declaration.line_ids.filtered(lambda l: l.code == '16.1.1')
        row.amount_adjust = 20000
        self.assertEqual(declaration.a1_1, 20000)
        declaration.a1_1 = 10000
        row.amount_adjust = 30000
        self.assertEqual(declaration.a1_1, 10000)
        self.assertEqual(declaration.a1_5, 1250, "10,000 x 50,000 / 400,000")
        declaration.a1_1 = 30000
        row.amount_adjust = 40000
        self.assertEqual(declaration.a1_1, 40000, "typed back to Odoo's value: follows again")

    def test_annex_3_typed_rows_survive_recalculate(self):
        self._post('2026-01-11', [(self._acc('140710'), 5000, 0, self.person), (self.bank, 0, 5000, None)])
        declaration = self._declaration(1)
        loans = declaration.annex3_line_ids.filtered(lambda l: l.sequence == 1)
        self.assertEqual((loans.amount2, loans.amount6), (5000, 5000))
        loans.amount1 = 1000
        self.assertTrue(loans.manual)
        self.assertEqual(loans.amount6, 6000)
        declaration.action_compute()
        self.assertEqual((loans.amount1, loans.amount6), (1000, 6000))

    def test_gambling_part_iv(self):
        declaration = self._declaration(1, g1=1000, g2=1000)
        self.assertEqual(declaration.gambling_total, 270)
        self.assertEqual(declaration.tax_payable, 270)

    def test_confirmed_is_locked(self):
        declaration = self._declaration(1)
        declaration.action_confirm()
        with self.assertRaises(UserError):
            declaration.line_ids[0].amount_adjust = 5
        with self.assertRaises(UserError):
            declaration.action_compute()

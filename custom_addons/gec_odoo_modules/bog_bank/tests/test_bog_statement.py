import json
from datetime import date
from unittest.mock import patch

from odoo.tests.common import tagged

from .common import BogCommon

# One record shaped like BOG's api/v2/statement response.
STATEMENT_RECORD = {
    'entryId': 555001,
    'entryDate': '2026-01-18T16:26:53.4094325+04:00',
    'entryDocumentNumber': 'DOC-77',
    'entryAmountDebit': 0,
    'entryAmountCredit': 250.50,
    'entryComment': 'incoming',
    'documentNomination': 'Invoice 123 payment',
    'documentKey': 987654,
    'senderDetails': {'name': 'ACME LLC', 'inn': '405123456',
                      'accountNumber': 'GE29BG1111111111111111'},
    'beneficiaryDetails': {'name': 'Our Company',
                           'accountNumber': 'GE29BG7777777777777777'},
}


@tagged('post_install', '-at_install')
class TestBogStatement(BogCommon):
    """Statement mapping, deduplication and auto-matching."""

    def setUp(self):
        super().setUp()
        self.connection.store_token('tok-123', 3600)
        self.wizard = self.env['bog.statement.import.wizard'].create({
            'journal_id': self.journal.id,
            'start_date': date(2026, 1, 1),
            'end_date': date(2026, 1, 31),
        })

    def test_credit_is_positive_and_debit_negative(self):
        """BOG sends debit and credit separately, not a signed amount."""
        credit = self.wizard._record_to_line_vals(STATEMENT_RECORD)
        self.assertEqual(credit['amount'], 250.50)
        outgoing = dict(STATEMENT_RECORD, entryAmountCredit=0, entryAmountDebit=80.0)
        self.assertEqual(self.wizard._record_to_line_vals(outgoing)['amount'], -80.0)

    def test_counterparty_follows_direction(self):
        credit = self.wizard._record_to_line_vals(STATEMENT_RECORD)
        self.assertEqual(credit['partner_name'], 'ACME LLC')
        outgoing = dict(STATEMENT_RECORD, entryAmountCredit=0, entryAmountDebit=80.0)
        self.assertEqual(self.wizard._record_to_line_vals(outgoing)['partner_name'],
                         'Our Company')

    def test_date_keeps_the_local_calendar_day(self):
        """Converting a +04:00 stamp to UTC would move it back a day."""
        vals = self.wizard._record_to_line_vals(
            dict(STATEMENT_RECORD, entryDate='2026-01-18T01:15:00+04:00'))
        self.assertEqual(vals['date'], date(2026, 1, 18))

    def test_unique_import_id_is_scoped_to_the_journal(self):
        """The constraint is global, so a bare entry id would collide across journals."""
        vals = self.wizard._record_to_line_vals(STATEMENT_RECORD)
        self.assertEqual(vals['unique_import_id'], 'bogbank-%s-555001' % self.journal.id)

    def test_record_without_entry_id_is_skipped(self):
        self.assertFalse(self.wizard._record_to_line_vals({'entryAmountCredit': 5}))

    def test_pascal_case_payload_still_maps(self):
        """The XML form of the payload is PascalCase."""
        pascal = {'EntryId': 42, 'EntryAmountCredit': 10.0,
                  'EntryDate': '2026-01-18T00:00:00+04:00',
                  'SenderDetails': {'Name': 'ACME LLC'}}
        vals = self.wizard._record_to_line_vals(pascal)
        self.assertEqual(vals['amount'], 10.0)
        self.assertEqual(vals['partner_name'], 'ACME LLC')

    def test_import_creates_lines_once(self):
        body = json.dumps({'id': 1, 'count': 1, 'records': [STATEMENT_RECORD]})
        with patch('requests.request', return_value=self._response(200, body)):
            self.wizard.action_import()
            first = self.env['account.bank.statement.line'].search_count(
                [('journal_id', '=', self.journal.id)])
            self.wizard.action_import()
            second = self.env['account.bank.statement.line'].search_count(
                [('journal_id', '=', self.journal.id)])
        self.assertEqual(first, 1)
        self.assertEqual(second, 1, "a re-import must not duplicate lines")

    def test_match_keys_are_stored(self):
        vals = self.wizard._record_to_line_vals(STATEMENT_RECORD)
        self.assertIn('987654', vals['gec_bank_match_keys'])
        self.assertIn('DOC-77', vals['gec_bank_match_keys'])

    def test_statement_line_confirms_a_sent_payment(self):
        payment = self._new_payment()
        payment._gec_bank_write_result({'gec_bank_state': 'created', 'gec_bank_reference': '987654'})
        body = json.dumps({'id': 1, 'count': 1,
                           'records': [dict(STATEMENT_RECORD, entryAmountCredit=0,
                                            entryAmountDebit=100.0)]})
        with patch('requests.request', return_value=self._response(200, body)):
            self.wizard.action_import()
        self.assertEqual(payment.gec_bank_state, 'confirmed')
        self.assertEqual(payment.gec_bank_confirmed_source, 'statement')

    def test_unrelated_statement_line_leaves_payments_alone(self):
        payment = self._new_payment()
        payment._gec_bank_write_result({'gec_bank_state': 'created', 'gec_bank_reference': '111'})
        body = json.dumps({'id': 1, 'count': 1, 'records': [STATEMENT_RECORD]})
        with patch('requests.request', return_value=self._response(200, body)):
            self.wizard.action_import()
        self.assertEqual(payment.gec_bank_state, 'created')

    def test_summary_snapshot_uses_last_daily_balance(self):
        """BOG's summary has no closing balance; it is the last day's balance."""
        body = json.dumps({
            'globalSummary': {'creditSum': 500.0, 'debitSum': 200.0},
            'dailySummaries': [{'balance': 100.0, 'entryCount': 1},
                               {'balance': 400.0, 'entryCount': 2}],
        })
        with patch('requests.request', return_value=self._response(200, body)):
            snapshot = self.env['bog.statement']._fetch_and_store(
                self.connection, self.journal, date(2026, 1, 1), date(2026, 1, 31), 'period')
        self.assertEqual(snapshot.closing_balance, 400.0)
        self.assertEqual(snapshot.credit_sum, 500.0)
        self.assertEqual(snapshot.entry_count, 3)

    def test_statement_currency_is_the_journals(self):
        """The currency is the journal's and cannot be typed."""
        usd = self.env.ref('base.USD')
        usd.active = True
        self.journal.currency_id = usd
        self.wizard.invalidate_recordset(['currency_code'])
        self.assertEqual(self.wizard.currency_code, 'USD')
        self.assertTrue(self.wizard._fields['currency_code'].readonly)
        with patch.object(type(self.service), 'fetch_all_records', return_value=[]) as fetch:
            self.wizard.action_import()
        self.assertEqual(fetch.call_args.args[2], 'USD')

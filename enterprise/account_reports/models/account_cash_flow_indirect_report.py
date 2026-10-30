from odoo import models

from odoo.fields import Domain
from odoo.tools import SQL


class AccountCashFlowIndirectReportHandler(models.AbstractModel):
    _name = 'account.cash.flow.indirect.report.handler'
    _inherit = ['account.report.custom.handler']
    _description = 'Cash Flow Indirect Report Custom Handler'

    def action_audit_cell(self, options, params):
        report = self.env['account.report'].browse(options['report_id'])
        report_line = self.env['account.report.line'].browse(params['report_line_id'])

        action = report.action_audit_cell(options, params)

        if report_line.code == 'CF_NOT_RECON':
            column_group_options = report._get_column_group_options(options, params.get('column_group_index'))

            journals = self.env['account.journal'].search([
                ('type', 'in', ['bank', 'cash', 'credit']),
                ('suspense_account_id', '!=', False)
            ])

            if not journals:
                domain = [('id', '=', False)]
            else:
                domain = Domain.OR([Domain.AND([
                    Domain('journal_id', '=', journal.id),
                    Domain('account_id', '=', journal.suspense_account_id.id),
                ])] for journal in journals)

            action['domain'] = Domain.AND([
                report._get_options_domain(column_group_options, 'strict_range'),
                domain,
            ])

        return action

    def _report_engine_cash_flow_indirect_cash_variation(self, options, date_scope, formulas_dict, current_groupby, warnings=None):
        """
        Computes the cash and non cash variations due to variation of currency rates:
          - cash_variation: the part of the movement that corresponds to actual cash flows, each currency's
            movement being valued at ITS OWN average rate over the period.
            cash_variation = amount_currency * avg_rate
          - non_cash_variation: Variation - cash_variation. This is the portion of the movement that is
            only due to the exchange rate moving between the beginning and the end of the period, not
            to any real cash movement.
            non_cash_variation = balance - amount_currency * avg_rate

        This only matters when the cash & cash equivalent accounts hold balances in more than one currency.
        """
        report = self.env['account.report'].browse(options['report_id'])

        query = report._get_report_query(options, date_scope)

        query.add_join('JOIN', alias='journal', table='account_journal', condition=SQL('account_move_line.journal_id = journal.id'))

        query.add_where(SQL("journal.type IN %s", ('bank', 'cash', 'credit')))
        query.add_where(SQL("account_move_line.account_id = journal.suspense_account_id"))

        [(balance,)] = self.env.execute_query(query.select(SQL("SUM(account_move_line.balance) AS amount")))

        return {next(iter(formulas_dict.values())): {
            'not_reconciled': - balance if balance else 0.0,
            'cash_variation': 0.0,
            'non_cash_variation': 0.0,
        }}

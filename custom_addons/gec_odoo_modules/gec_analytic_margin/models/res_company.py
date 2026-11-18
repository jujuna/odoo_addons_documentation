import calendar
from datetime import date, timedelta

from odoo import models, fields, _


class ResCompany(models.Model):
    """When the company considers a period finished, and what to do about it."""
    _inherit = 'res.company'

    # A run fired on the 1st would allocate a month with unposted bills and block the period (double-allocation guard);
    # so the trigger is the company's own "period settled" statement, not the calendar.
    gec_allocation_cron_mode = fields.Selection(
        [('off', 'Off'),
         ('draft', 'Prepare a draft run'),
         ('generate', 'Prepare and generate it')],
        string='Monthly Allocation', default='off', required=True,
        help="What the monthly scheduled action should do with the last closed "
             "period.\n\n"
             "Off: nothing. Runs stay entirely manual.\n\n"
             "Prepare a draft run: the run appears in the list with its dates "
             "set, and somebody presses Preview and then Generate. This is the "
             "safe choice — the figures still go out over a human's signature.\n\n"
             "Prepare and generate it: the allocation is computed as well. Only "
             "worth it once you have watched the same rules produce the right "
             "answer for a few months.",
    )
    gec_allocation_cron_basis = fields.Selection(
        [('lock', 'Accounting lock date'),
         ('delay', 'A number of days after the month ends')],
        string='A Period Is Closed When', default='lock', required=True,
        help="How the scheduled action decides a month will not change again.\n\n"
             "Accounting lock date: the honest signal. If the books are locked "
             "to 31 August, August is settled — the company said so. Nothing "
             "happens until a lock date exists.\n\n"
             "Days after the month ends: for companies that do not lock. A "
             "guess, but an explicit one.",
    )
    # Per company: a company that reports by nature must not see its P&L reshaped on upgrade.
    gec_pl_mode = fields.Selection(
        [('nature', 'By nature — what the money bought'),
         ('function', 'By function — what the money was for')],
        string='P&L Presentation', default='nature', required=True,
        help="By nature: costs are read from the GL account — Personnel, "
             "Overhead, Depreciation.\n\n"
             "By function: Personnel and Overhead are regrouped by the job the "
             "money did — Cost of Sales, R&D, Sales & Marketing, G&A — taken "
             "from the activity a cost was charged through, otherwise from the "
             "cost centre it sits on. Revenue, direct cost, depreciation, "
             "finance and tax are read the same way in both.",
    )
    gec_allocation_cron_delay_days = fields.Integer(
        string='Days After Month End', default=10,
        help="Used when a period is closed by elapsed days rather than by a "
             "lock date. Ten days is a common close.",
    )

    def _gec_closed_through(self):
        """The last date this company treats as settled, or None."""
        self.ensure_one()
        if self.gec_allocation_cron_basis == 'delay':
            days = max(self.gec_allocation_cron_delay_days, 0)
            return fields.Date.context_today(self) - timedelta(days=days)
        locks = [
            lock for lock in (self.fiscalyear_lock_date, self.hard_lock_date)
            if lock
        ]
        return max(locks) if locks else None

    def _gec_last_closed_month(self):
        """``(first, last)`` of the latest settled month; a month still moving (locked to the 15th) is skipped."""
        self.ensure_one()
        closed = self._gec_closed_through()
        if not closed:
            return None
        end = date(
            closed.year, closed.month,
            calendar.monthrange(closed.year, closed.month)[1],
        )
        if end > closed:
            end = closed.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end

    def _gec_cron_run_name(self, start):
        return _("%(month)s allocation", month=start.strftime('%B %Y'))

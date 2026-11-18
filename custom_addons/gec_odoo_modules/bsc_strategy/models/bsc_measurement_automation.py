# -*- coding: utf-8 -*-
"""Where an automated figure may land or is refused; the guards live in ``_refresh_automated``.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import mute_logger

_logger = logging.getLogger(__name__)

AUTO_CONTEXT_KEY = 'bsc_automated_write'
# Written by the automation only; a typed figure must not look machine-produced.
AUTO_FIELDS = {'is_automated', 'auto_state', 'auto_message', 'auto_record_count',
               'auto_synced_on', 'auto_pending_value', 'source_note',
               'auto_deviation_confirmed'}


class BscMeasurement(models.Model):
    _inherit = 'bsc.measurement'

    is_automated = fields.Boolean(
        string='Automated', readonly=True, copy=False,
        help="This figure was produced by a data source, not typed in.")
    auto_state = fields.Selection(
        [('ok', 'Synchronised'),
         ('no_data', 'No Records Matched'),
         ('deviation', 'Held for Confirmation'),
         ('error', 'Source Error'),
         ('manual', 'Manually Overridden')],
        string='Sync Status', readonly=True, copy=False)
    auto_message = fields.Char(string='Sync Note', readonly=True, copy=False)
    auto_record_count = fields.Integer(string='Records Matched', readonly=True, copy=False)
    auto_synced_on = fields.Datetime(string='Synchronised On', readonly=True, copy=False)
    auto_pending_value = fields.Float(
        string='Held Figure', readonly=True, copy=False,
        help="A figure the source produced but that deviates too far from the "
             "previous period to be published without a human saying so.")
    source_note = fields.Char(
        string='Source Trail', readonly=True, copy=False,
        help="Which source produced this figure, over how many records, on which "
             "date field and window. The audit trail lives on the row itself.")
    # A human confirmed the held figure; cleared when the figure is cleared or the source changes.
    auto_deviation_confirmed = fields.Boolean(string='Jump Confirmed', readonly=True, copy=False)
    auto_needs_attention = fields.Boolean(
        compute='_compute_auto_needs_attention', store=True,
        help="Used to surface the rows a person has to look at.")

    @api.depends('auto_state')
    def _compute_auto_needs_attention(self):
        for record in self:
            record.auto_needs_attention = record.auto_state in ('deviation', 'error', 'no_data')

    @api.constrains('status', 'comment')
    def _check_variance_comment(self):
        """Automated rows are exempt here and checked when the period closes, as the cron cannot comment.
        The decorator must be repeated: without ``_constrains`` the override unregisters the rule for every record."""
        manual = self.filtered(lambda m: not m.is_automated)
        return super(BscMeasurement, manual)._check_variance_comment()

    @api.model_create_multi
    def create(self, vals_list):
        """Refuse the synchronisation fields on create, like write(), so a typed row cannot look machine-produced."""
        if not self.env.su and any(AUTO_FIELDS & set(vals) for vals in vals_list):
            raise AccessError(_("The synchronisation fields are written by the automation only."))
        return super().create(vals_list)

    def write(self, vals):
        """Guard the automation fields; typing a figure or switching "Reported" on makes the row 'manual'.
        Clearing the figure hands it back to the source."""
        automated = self.env.su and self.env.context.get(AUTO_CONTEXT_KEY)
        if not self.env.su and AUTO_FIELDS & set(vals):
            raise AccessError(_("The synchronisation fields are written by the automation only."))
        if ('actual_value_set' in vals and not vals['actual_value_set']
                and not automated):
            # Clearing the figure hands the row back to the source; the next refresh refills it.
            result = super().write(vals)
            super(BscMeasurement, self.sudo()).write({
                'is_automated': False, 'auto_state': False,
                'auto_message': False, 'auto_pending_value': 0.0,
                'auto_deviation_confirmed': False})
            return result
        if ('actual_value' in vals or vals.get('actual_value_set')) and not automated:
            overridden = self.filtered(lambda m: m.is_automated and m.auto_state != 'manual')
            result = super().write(vals)
            if overridden:
                super(BscMeasurement, overridden.sudo()).write({
                    'auto_state': 'manual',
                    'auto_message': _("Overridden by %s. The source no longer writes "
                                      "to this row.", self.env.user.display_name),
                    'auto_pending_value': 0.0,
                })
            return result
        return super().write(vals)

    def _refresh_automated(self):
        """Pull the figure for every automated row in ``self`` that may be written.
        Returns the rows actually updated. A published figure is withdrawn when the source later matches nothing."""
        updated = self.browse()
        # A figure typed before the KPI was connected is not overwritten silently; mark why.
        typed = self.filtered(lambda m: (
            m.kpi_id.data_source == 'odoo' and not m.is_automated
            and m.actual_value_set and m.auto_state != 'manual'
            and m.period_id.state == 'open'))
        for record in typed:
            record._write_auto({
                'auto_state': 'manual',
                'auto_message': _("Typed in before the KPI was connected to Odoo data. "
                                  "The source leaves it alone; clear the figure to let "
                                  "the source fill it."),
            })
        candidates = self.filtered(lambda m: (
            m.kpi_id.data_source == 'odoo'
            and m.kpi_id.source_id
            # A closed period is never written to, by anyone, cron included.
            and m.period_id.state == 'open'
            and m.state != 'validated'
            and m.auto_state != 'manual'
        ))
        for record in candidates:
            kpi = record.kpi_id
            try:
                with self.env.cr.savepoint(), mute_logger('odoo.sql_db'):
                    value, count = kpi._fetch_for_period(record.period_id)
            except Exception as error:  # noqa: BLE001 - recorded, never raised at the cron
                _logger.warning("BSC source failed for KPI %s: %s", kpi.display_name, error)
                record._write_auto({
                    'auto_state': 'error',
                    'auto_message': _("The source failed: %s", error),
                    'auto_synced_on': fields.Datetime.now(),
                })
                kpi.sudo().auto_last_error = str(error)[:255]
                continue
            kpi.sudo().write({
                'auto_last_error': False,
                'auto_last_run': fields.Datetime.now(),
            })
            if value is None:
                # An empty result set is not a zero: publishing one would drag the score down silently.
                vals = {
                    'auto_state': 'no_data',
                    'auto_message': _("The query matched no records. The figure was "
                                      "left empty rather than reported as zero."),
                    'auto_record_count': 0,
                    'auto_synced_on': fields.Datetime.now(),
                    'source_note': False,
                    'auto_pending_value': 0.0,
                }
                # A figure already reported on a no_data row was typed by a person; withdraw only a published one.
                if (record.is_automated and record.actual_value_set
                        and record.auto_state != 'no_data'):
                    vals.update(record._withdrawn_vals())
                record._write_auto(vals)
                record._notify_owner('no_data', record.auto_message)
                continue
            deviation = (None if record.auto_deviation_confirmed
                         else record._deviation_against_previous(value))
            if deviation is not None:
                vals = {
                    'auto_state': 'deviation',
                    'auto_pending_value': value,
                    'auto_record_count': count,
                    'auto_synced_on': fields.Datetime.now(),
                    'auto_message': _(
                        "The source returned %(value)s, which is %(change)s%% away from "
                        "last period. Held back until somebody confirms it.",
                        value=round(value, 2), change=round(deviation, 1)),
                }
                if (record.is_automated and record.actual_value_set
                        and record.auto_state == 'ok'):
                    vals.update(record._withdrawn_vals())
                record._write_auto(vals)
                record._notify_owner('deviation', record.auto_message)
                continue
            record._publish(value, count)
            updated |= record
        return updated

    def _withdrawn_vals(self):
        """Values that empty a figure the source published, so it is not shown beside a hold."""
        return {
            'actual_value_set': False, 'actual_value': 0.0,
            'entered_by_id': False, 'entry_date': False, 'state': 'draft',
            'auto_deviation_confirmed': False,
        }

    def _publish(self, value, count):
        """Write the figure and leave an audit trail on the row; publishing closes its "Confirm the figure" to-do."""
        self.ensure_one()
        was_held = self.auto_state == 'deviation'
        had_no_data = self.auto_state == 'no_data'
        source = self.kpi_id.source_id
        note = _("%(source)s: %(count)s record(s) on %(field)s between %(start)s and "
                 "%(end)s.",
                 source=source.name, count=count, field=source.date_field,
                 start=self.period_id.date_from, end=self.period_id.date_to)
        self._write_auto({
            'actual_value': value,
            'actual_value_set': True,
            'is_automated': True,
            'auto_state': 'ok',
            'auto_message': False,
            'auto_pending_value': 0.0,
            'auto_record_count': count,
            'auto_synced_on': fields.Datetime.now(),
            'source_note': note,
        })
        if was_held:
            self._close_owner_todo('deviation')
        if had_no_data:
            self._close_owner_todo('no_data')
        return True

    def _write_auto(self, vals):
        """Write as the automation, so the manual-override guard does not trip."""
        vals.setdefault('is_automated', True)
        return self.sudo().with_context(**{AUTO_CONTEXT_KEY: True}).write(vals)

    def _deviation_against_previous(self, value):
        """Percentage change against the previous period, or None if acceptable; a running period is not checked."""
        self.ensure_one()
        limit = self.kpi_id.auto_deviation_limit
        if limit <= 0.0 or self.period_id.date_to >= fields.Date.context_today(self):
            return None
        previous = self._previous_measurement()
        if not previous or not previous.actual_value_set or not previous.actual_value:
            # Nothing to compare against. A first figure is never suspicious.
            return None
        change = abs(value - previous.actual_value) / abs(previous.actual_value) * 100.0
        return change if change > limit else None

    def _owner_todos(self, reason):
        """The summary and open to-dos of this row's KPI owner; ``reason`` is 'no_data' or 'deviation'.
        The summary is in the owner's language, so the same reminder is recognised whoever refreshes."""
        self.ensure_one()
        owner = self.kpi_id.owner_id
        localized = self.with_context(lang=owner.lang or 'en_US')
        names = {'kpi': localized.kpi_id.name, 'period': localized.period_id.name}
        if reason == 'no_data':
            summary = localized.env._("No data for %(kpi)s in %(period)s", **names)
        else:
            summary = localized.env._("Confirm the figure for %(kpi)s in %(period)s", **names)
        activities = self.env['mail.activity'].sudo().search([
            ('res_model_id', '=', self.env['ir.model']._get_id('bsc.scorecard')),
            ('res_id', '=', self.period_id.scorecard_id.id),
            ('user_id', '=', owner.id),
            ('activity_type_id', '=', self.env.ref('mail.mail_activity_data_todo').id),
            ('date_deadline', '=', self.period_id.date_to),
            ('summary', '=', summary),
        ])
        return summary, activities

    def _notify_owner(self, reason, note):
        """Ask the data owner to look, once per period and per subject."""
        self.ensure_one()
        owner = self.kpi_id.owner_id
        scorecard = self.period_id.scorecard_id
        if not owner or not scorecard:
            return False
        summary, already = self._owner_todos(reason)
        if already:
            return False
        scorecard.sudo().activity_schedule(
            act_type_xmlid='mail.mail_activity_data_todo',
            user_id=owner.id,
            summary=summary,
            note=note,
            date_deadline=self.period_id.date_to,
        )
        return True

    def _close_owner_todo(self, reason):
        """Mark the reminder of this row and reason as done, if open.
        Found whatever the assignee or language. A reminder shared by same-named KPIs in a period
stays open while one still needs it."""
        self.ensure_one()
        scorecard = self.period_id.scorecard_id
        if not scorecard:
            return
        still_needed = self.search_count([
            ('id', '!=', self.id), ('period_id', '=', self.period_id.id),
            ('kpi_id.name', '=', self.kpi_id.name), ('auto_state', '=', reason)])
        if still_needed:
            return
        summaries = set()
        for lang, __ in self.env['res.lang'].get_installed():
            localized = self.with_context(lang=lang)
            names = {'kpi': localized.kpi_id.name, 'period': localized.period_id.name}
            if reason == 'no_data':
                summaries.add(localized.env._("No data for %(kpi)s in %(period)s", **names))
            else:
                summaries.add(localized.env._(
                    "Confirm the figure for %(kpi)s in %(period)s", **names))
        self.env['mail.activity'].sudo().search([
            ('res_model_id', '=', self.env['ir.model']._get_id('bsc.scorecard')),
            ('res_id', '=', scorecard.id),
            ('activity_type_id', '=', self.env.ref('mail.mail_activity_data_todo').id),
            ('date_deadline', '=', self.period_id.date_to),
            ('summary', 'in', list(summaries)),
        ]).action_feedback()

    def _apply_target_rule(self):
        """Let the KPI propose the target on a freshly created row, once; it stays editable."""
        for record in self:
            kpi = record.kpi_id
            if not kpi or kpi.target_rule == 'carry':
                continue
            previous = record._previous_measurement()
            target = kpi._proposed_target(previous, record.target_value)
            if target != record.target_value:
                record.target_value = target
        return True

    def action_accept_pending(self):
        """Publish a held figure, on a human's say-so."""
        # The write runs as superuser, so the caller's own right to change the row is checked first.
        self.check_access('write')
        for record in self:
            if record.auto_state != 'deviation':
                raise UserError(_("There is no held figure on '%s'.", record.display_name))
            if record.period_id.state != 'open':
                raise UserError(_("Period '%s' is closed.", record.period_id.name))
            if record.state == 'validated':
                raise UserError(_("'%s' has been validated; a held figure can no longer "
                                  "replace it.", record.display_name))
            held = record.auto_pending_value
            record._publish(held, record.auto_record_count)
            record._write_auto({'auto_deviation_confirmed': True})
            record.period_id.scorecard_id.sudo().message_post(body=_(
                "%(user)s confirmed the held figure %(value)s for %(kpi)s (%(period)s).",
                user=self.env.user.display_name,
                value=round(held, 2),
                kpi=record.kpi_id.name, period=record.period_id.name))
        return True

    def action_discard_pending(self):
        """Reject a held figure and leave the cell empty for a human to fill."""
        self.check_access('write')
        for record in self:
            if record.auto_state != 'deviation':
                raise UserError(_("There is no held figure on '%s'.", record.display_name))
            if record.period_id.state != 'open':
                raise UserError(_("Period '%s' is closed.", record.period_id.name))
            record._write_auto({
                'auto_state': 'manual',
                'auto_pending_value': 0.0,
                'auto_message': _("Held figure rejected by %s. Enter the figure by hand.",
                                  self.env.user.display_name),
            })
            record._close_owner_todo('deviation')
        return True

    def action_refresh_automated(self):
        self.check_access('write')
        self._refresh_automated()
        return True

    @api.model
    def _cron_refresh_automated(self):
        """Daily pull for every open period of an active scorecard that has started."""
        measurements = self.search([
            ('period_id.state', '=', 'open'),
            ('period_id.date_from', '<=', fields.Date.context_today(self)),
            ('scorecard_id.state', '=', 'active'),
            ('kpi_id.data_source', '=', 'odoo'),
        ])
        measurements._refresh_automated()
        return True

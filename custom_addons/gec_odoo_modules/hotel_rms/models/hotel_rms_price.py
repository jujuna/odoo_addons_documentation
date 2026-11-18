from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools.misc import format_date, formatLang
from odoo.tools.translate import _lt

from ..engine import pricing as pricing_engine

STEP_LABELS = {
    'base': _lt("Base"),
    'weekday': _lt("Weekday"),
    'event': _lt("Event"),
    'demand': _lt("Demand"),
    'pace': _lt("Booking pace"),
    'last_minute': _lt("Last minute"),
    'season_limit': _lt("Season limit"),
    'protect': _lt("Protect current price"),
    'max_step': _lt("Maximum change"),
    'rounding': _lt("Rounding"),
    'hold': _lt("Keep current price"),
    'derived': _lt("Room type difference"),
    'recommended': _lt("Recommended"),
}
GUARD_SENTENCES = {
    'protect': _lt("The night is almost full, so the current price is not lowered."),
    'max_step': _lt("The change is limited to the maximum change from the current price."),
    'rounding': _lt("The price is rounded to the price step."),
    'hold': _lt("The change is too small, so the current price stays."),
}


class HotelRmsPrice(models.Model):
    _name = 'hotel.rms.price'
    _description = "Nightly Price"
    _order = 'stay_date, room_type_id, id'
    _check_company_auto = True

    _night_room_unique = models.Constraint('UNIQUE(property_id, stay_date, room_type_id)', "A night has one price per room type.")

    property_id = fields.Many2one('hotel.rms.property', string="Hotel", required=True, ondelete='cascade',
                                  check_company=True, help="The hotel of this price.")
    company_id = fields.Many2one(related='property_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    stay_date = fields.Date(string="Night", required=True, index=True, help="The night this price is for.")
    room_type_id = fields.Many2one('hotel.rms.room.type', string="Room Type", required=True, ondelete='restrict', check_company=True,
        domain="[('property_id', '=', property_id)]", help="The room type this price is for.")
    forecast_id = fields.Many2one('hotel.rms.forecast', string="Forecast", ondelete='set null', check_company=True,
                                  help="The forecast this recommendation is based on.")
    published_rate = fields.Monetary(string="Current price", currency_field='currency_id', copy=False,
                                     aggregator=None, help="The price that is live now.")
    exported_rate = fields.Monetary(string="Exported price", currency_field='currency_id', copy=False,
                                    help="The last price that was sent out of this app.")
    to_export = fields.Boolean(string="To Publish", compute='_compute_to_export', store=True,
                               help="The current price changed and was not published yet.")
    raw_target_rate = fields.Monetary(string="Model target, before safety rules", currency_field='currency_id',
                                      help="The price the model wanted, before the season limits and the other safety rules.")
    recommended_rate = fields.Monetary(string="Recommended price", currency_field='currency_id', aggregator=None,
                                       help="The price the engine recommends for this night.")
    action = fields.Selection([('new', "New"), ('up', "Raise"), ('down', "Lower"), ('hold', "Keep")],
                              help="How the recommendation compares with the current price.")
    state = fields.Selection([
        ('pending', "Needs decision"),
        ('hold', "No change suggested"),
        ('accepted', "Accepted"),
        ('edited', "Own price"),
        ('rejected', "Rejected"),
    ], default='pending', required=True, index=True,
        help="Needs decision: waiting for you. Accepted: you took the recommendation. Own price: you set another price. Rejected: you kept the "
        "current price.")
    decided_rate = fields.Monetary(string="My price", currency_field='currency_id', help="The price you want instead of the recommendation.")
    note = fields.Char(help="A note saved in the history with your decision.")
    decided_by = fields.Many2one('res.users', string="Decided By", ondelete='set null', help="Who made the last decision.")
    decided_at = fields.Datetime(string="Decided On", help="When the last decision was made.")
    locked = fields.Boolean(help="The engine does not change a locked price.")
    reason_json = fields.Json(string="Reasons")
    run_id = fields.Many2one('hotel.rms.run', string="Engine Run", ondelete='set null', check_company=True,
                             help="The engine run that made this recommendation.")
    explanation_html = fields.Html(compute='_compute_explanation_html', sanitize=False)
    can_undo = fields.Boolean(compute='_compute_can_undo')
    audit_ids = fields.One2many('hotel.rms.price.audit', 'price_id', string="History")
    forecast_occ = fields.Float(related='forecast_id.forecast_occ', string="Forecast occupancy %", help="Forecast occupancy of this night.")
    otb_occ = fields.Float(related='forecast_id.otb_occ', string="Already booked %", help="Share of the rooms already booked for this night.")
    otb_rooms = fields.Integer(related='forecast_id.otb_rooms', string="Already booked rooms", help="Rooms already booked for this night.")
    expected_otb = fields.Float(related='forecast_id.expected_otb', string="Usually booked rooms",
                                help="Rooms usually booked by now for a night like this.")
    pace = fields.Float(related='forecast_id.pace', string="Booking pace", help="Booked rooms divided by usually booked rooms.")
    confidence_score = fields.Integer(related='forecast_id.confidence_score', string="Confidence", help="0 to 100: how much to trust the forecast.")
    confidence_level = fields.Selection(related='forecast_id.confidence_level', string="Confidence level", help="How much to trust the forecast.")

    @api.depends('room_type_id.name', 'stay_date')
    def _compute_display_name(self):
        for price in self:
            price.display_name = f"{price.room_type_id.name or ''} · {format_date(self.env, price.stay_date)}"

    @api.depends('published_rate', 'exported_rate', 'currency_id')
    def _compute_to_export(self):
        for price in self:
            price.to_export = bool(price.currency_id.compare_amounts(price.published_rate, price.exported_rate))

    @api.depends('audit_ids', 'to_export')
    def _compute_can_undo(self):
        for price in self:
            last = price.audit_ids.sorted('id')[-1:]
            price.can_undo = bool(last) and (last.action == 'reject' or (last.action in ('accept', 'edit') and price.to_export))

    @api.depends_context('lang')
    @api.depends('reason_json', 'recommended_rate')
    def _compute_explanation_html(self):
        for price in self:
            sentences, rows = price._get_explanation()
            if not rows:
                price.explanation_html = Markup("<p>%s</p>") % sentences[0]
                continue
            lines = [(row['label'],
                ('+' if row['kind'] == 'step' and row['amount'] >= 0 else '') + formatLang(self.env, row['amount'])) for row in rows]
            price.explanation_html = Markup("<ul>%s</ul><table class=\"table table-sm w-auto\">%s</table>") % (
                Markup("").join(Markup("<li>%s</li>") % sentence for sentence in sentences),
                Markup("").join(Markup("<tr><td>%s</td><td class=\"text-end\">%s</td></tr>") % line
                                for line in lines),
            )

    def _get_explanation(self):
        """The plain-language sentences and the waterfall rows (label, amount, kind) of this price."""
        self.ensure_one()
        reason = self.reason_json
        if not reason:
            return [self.env._("No recommendation for this night: it has no season or no forecast.")], []
        sentences = [self.env._("Forecast occupancy %s%%", round(reason['forecast_occ']))]
        if reason['method'] == 'coldstart_v1':
            sentences.append(self.env._("There is no booking history yet: the forecast uses the expected occupancy of the season."))
        if reason['pace'] is not None:
            pace_pct = round((reason['pace'] - 1) * 100)
            if pace_pct > 0:
                sentences.append(self.env._("Bookings are %s%% ahead of usual.", pace_pct))
            elif pace_pct < 0:
                sentences.append(self.env._("Bookings are %s%% behind usual.", -pace_pct))
        if reason['lead'] == 0:
            sentences.append(self.env._("The night is today."))
        elif reason['lead'] == 1:
            sentences.append(self.env._("The night is tomorrow."))
        else:
            sentences.append(self.env._("%s days left.", reason['lead']))
        if reason['event']:
            sentences.append(self.env._("Event: %(name)s (%(pct)s%%).", name=reason['event'], pct=f"{reason['event_pct']:+g}"))
        for guard in reason['guards']:
            if guard['code'] == 'season_limit':
                sentences.append(self.env._("Limited by your season maximum.") if guard['after'] < guard['before']
                                 else self.env._("Limited by your season minimum."))
            else:
                sentence = GUARD_SENTENCES[guard['code']]
                sentences.append(self.env._(sentence))
        labels = {code: self.env._(label) for code, label in STEP_LABELS.items()}
        rows = [{'code': 'base', 'label': labels['base'], 'amount': reason['base'], 'kind': 'base'}]
        rows += [{'code': step['code'], 'label': labels[step['code']], 'amount': step['amount'], 'kind': 'step'} for step in reason['waterfall']]
        rows.append({'code': 'recommended', 'label': labels['recommended'], 'amount': self.recommended_rate, 'kind': 'total'})
        return sentences, rows

    def _get_top_reason(self):
        """The one-line reason of the strongest price factor, or False when no factor moved the price."""
        self.ensure_one()
        factors = [f for f in (self.reason_json or {}).get('factors', []) if f['pct']]
        if not factors:
            return False
        top = max(factors, key=lambda f: abs(f['pct']))
        pct, rising = f"{top['pct']:+g}%", top['pct'] > 0
        if top['code'] == 'demand':
            return self.env._("Demand is high: %s", pct) if rising else self.env._("Demand is low: %s", pct)
        if top['code'] == 'pace':
            return (self.env._("Bookings are ahead of usual: %s", pct) if rising else self.env._("Bookings are behind usual: %s", pct))
        label = STEP_LABELS[top['code']]
        return self.env._("%(factor)s: %(pct)s", factor=self.env._(label), pct=pct)

    def _calendar_cell(self):
        self.ensure_one()
        season = self.property_id._get_season(self.stay_date)
        return {
            'id': self.id,
            'room_type_id': self.room_type_id.id,
            'date': fields.Date.to_string(self.stay_date),
            'recommended': self.recommended_rate,
            'published': self.published_rate,
            'action': self.action or False,
            'state': self.state,
            'locked': self.locked,
            'reason': self._get_top_reason(),
            'current': self.exported_rate,
            'to_export': self.to_export,
            'has_season': bool(season),
            'season_min': season.min_rate,
            'season_max': season.max_rate,
        }

    def get_panel_data(self):
        self.ensure_one()
        sentences, rows = self._get_explanation()
        forecast = self.forecast_id
        earlier_forecasts = self.env['hotel.rms.forecast'].search(
            [('property_id', '=', self.property_id.id), ('stay_date', '=', self.stay_date)], order='run_date')
        pace = (self.reason_json or {}).get('pace')
        is_manager = self.env.user.has_group('hotel_rms.group_hotel_rms_revenue_manager')
        audit_labels = dict(self.env['hotel.rms.price.audit']._fields['action']._description_selection(self.env))
        return {
            **self._calendar_cell(),
            'property': self.property_id.name,
            'room_type': self.room_type_id.name,
            'decided_rate': self.decided_rate,
            'note': self.note or '',
            'target': self.raw_target_rate,
            'sentences': sentences,
            'base': rows[0]['amount'] if rows else 0,
            'steps': [row for row in rows if row['kind'] == 'step'],
            'total': self.recommended_rate,
            'pace_points': [{
                'days_before': (self.stay_date - earlier.run_date).days,
                'booked': earlier.otb_rooms,
                'usual': earlier.expected_otb,
            } for earlier in earlier_forecasts],
            'forecast': {
                'otb_rooms': forecast.otb_rooms,
                'capacity': forecast.capacity,
                'forecast_occ': forecast.forecast_occ,
                'pace_pct': round((pace - 1) * 100) if pace is not None else None,
                'lead_days': forecast.lead_days,
                'confidence_level': forecast.confidence_level,
            } if forecast else None,
            'actions': {
                'accept': is_manager and bool(self.recommended_rate) and not self.locked and self.state != 'accepted',
                'use_my_price': is_manager and not self.locked,
                'reject': is_manager and not self.locked and self.state != 'rejected',
                'undo': is_manager and self.can_undo,
                'lock': is_manager and not self.locked,
                'unlock': is_manager and self.locked,
            },
            'history': [{
                'action': audit_labels[audit.action],
                'user': audit.user_id.name,
                'date': fields.Datetime.to_string(audit.create_date),
                'old_rate': audit.old_rate,
                'new_rate': audit.new_rate,
            } for audit in self.audit_ids],
        }

    def _engine_skip_write(self, today):
        self.ensure_one()
        if self.locked:
            return True
        if not self.decided_at:
            return False
        return self.property_id._get_local_today(self.decided_at) == today

    def _log_audit(self, action, old_rates=None):
        """Sudo: no group may create audit rows; write access on the prices is checked first."""
        self.check_access('write')
        old_rates = old_rates or {}
        self.env['hotel.rms.price.audit'].sudo().create([{
            'price_id': price.id,
            'action': action,
            'old_rate': old_rates.get(price.id, price.published_rate),
            'new_rate': price.published_rate,
            'recommended_rate': price.recommended_rate,
            'note': price.note,
            'user_id': self.env.uid,
        } for price in self])

    def _mark_exported(self, action):
        """Record that the published prices left the system: exported = published, one audit row each."""
        old_rates = {price.id: price.exported_rate for price in self}
        for rate, prices in self.grouped('published_rate').items():
            prices.exported_rate = rate
        self._log_audit(action, old_rates)

    def _decide(self, action, state, rate_field):
        """Audit rows keep the note, which is then cleared."""
        old_rates = {price.id: price.published_rate for price in self}
        now = fields.Datetime.now()
        for price in self:
            price.write({
                'published_rate': price[rate_field],
                'state': state,
                'decided_by': self.env.uid,
                'decided_at': now,
            })
        self._log_audit(action, old_rates)
        self.note = False

    def action_accept(self):
        self.filtered(lambda p: p.recommended_rate and not p.locked and p.state != 'accepted')._decide('accept', 'accepted', 'recommended_rate')

    def action_use_my_price(self):
        """A price already published as this own price is skipped and its note dropped: a second audit row with old = new would break Undo."""
        rows = self.filtered(lambda p: p.decided_rate and not p.locked)
        repeated = rows.filtered(lambda p: p.state == 'edited' and not p.currency_id.compare_amounts(p.published_rate, p.decided_rate))
        repeated.note = False
        (rows - repeated)._decide('edit', 'edited', 'decided_rate')

    def action_quick_price(self, pct=None):
        """List buttons pass pct in the context as quick_pct."""
        pct = self.env.context.get('quick_pct') if pct is None else pct
        rows = self.filtered(lambda p: p.recommended_rate and not p.locked)
        for price in rows:
            prop = price.property_id
            season = prop._get_season(price.stay_date)
            rate = price.recommended_rate * (1 + pct / 100)
            if season and prop.price_step > 0:
                rate = pricing_engine._step_value(rate, prop.price_step, season.min_rate, season.max_rate) or rate
            price.decided_rate = round(rate, 2)
        rows.action_use_my_price()

    def action_reject(self):
        """Keep the exported price: an accepted price not yet exported is dropped."""
        self.filtered(lambda p: not p.locked and p.state != 'rejected')._decide('reject', 'rejected', 'exported_rate')

    def action_undo(self):
        """Revert the last decision; undoing a rejection restores the state only."""
        rows = self.filtered('can_undo')
        old_rates = {price.id: price.published_rate for price in rows}
        for price in rows:
            last = price.audit_ids.sorted('id')[-1:]
            vals = {'state': 'hold' if price.action == 'hold' else 'pending', 'decided_by': False, 'decided_at': False}
            if last.action != 'reject':
                vals['published_rate'] = last.old_rate
            price.write(vals)
        rows._log_audit('undo', old_rates)

    def action_lock(self):
        rows = self.filtered(lambda p: not p.locked)
        rows.write({'locked': True})
        rows._log_audit('lock')

    def action_unlock(self):
        rows = self.filtered('locked')
        rows.write({'locked': False})
        rows._log_audit('unlock')

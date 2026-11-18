import math

from .forecast import FORECAST_VERSION

PRICE_VERSION = 'price_v1'

EPSILON = 1e-9


def _factors(ctx):
    """Price factors as [(code, pct)], in the order they are applied."""
    forecast_occ = ctx['forecast_occ']
    demand_pct = 0
    for occ_from, pct in sorted(ctx['demand_curve']):
        if occ_from <= forecast_occ:
            demand_pct = pct
    pace_pct = 0
    pace = ctx['pace']
    if pace is not None and abs(pace - 1) * 100 > ctx['pace_threshold_pct']:
        pace_pct = ctx['pace_adj_pct'] if pace > 1 else -ctx['pace_adj_pct']
        if ctx['method'] == FORECAST_VERSION:
            pace_pct /= 2
    lastmin_pct = 0
    if ctx['lead'] <= ctx['lastmin_days'] and forecast_occ < ctx['lastmin_occ_pct'] and ctx['event_pct'] <= 0:
        lastmin_pct = ctx['lastmin_pct']
    return [('weekday', ctx['dow_pct']), ('event', ctx['event_pct']), ('demand', demand_pct), ('pace', pace_pct), ('last_minute', lastmin_pct)]


def _clamp(value, low, high):
    return max(low, min(high, value))


def _step_value(rate, step, low, high):
    """Nearest step multiple to rate inside [low, high] (half-up); None when the range holds none."""
    first = math.ceil(low / step - EPSILON)
    last = math.floor(high / step + EPSILON)
    if first > last:
        return None
    number = _clamp(math.floor(rate / step + 0.5 + EPSILON), first, last)
    return round(number * step, 6)


def _round_to_step_free(rate, step):
    return round(math.floor(rate / step + 0.5 + EPSILON) * step, 6)


def _waterfall(steps, total):
    """Rounds each step to cents; the last non-zero step takes the rounding difference so the steps sum to total."""
    cents = [[code, round(amount * 100)] for code, amount in steps]
    last = next((row for row in reversed(cents) if row[1]), cents[-1])
    last[1] += round(total * 100) - sum(c for _code, c in cents)
    return [{'code': code, 'amount': c / 100} for code, c in cents]


def _action(rate, current_rate):
    if not current_rate:
        return 'new'
    diff = round(rate - current_rate, 2)
    if diff > 0:
        return 'up'
    return 'down' if diff < 0 else 'hold'


def price_v1(ctx):
    """Recommended price of the reference room, with its raw target, guard adjustments and waterfall."""
    base = ctx['base']
    factors = _factors(ctx)
    steps = []
    running = base
    for code, pct in factors:
        new = running * (1 + pct / 100)
        steps.append((code, new - running))
        running = new
    raw_target = running

    current = ctx['current_rate'] or None
    min_rate, max_rate = ctx['min_rate'], ctx['max_rate']
    step = ctx['price_step']
    guards = []

    def guard(code, before, after):
        if abs(after - before) > EPSILON:
            guards.append({'code': code, 'before': round(before, 2), 'after': round(after, 2)})
            steps.append((code, round(after, 2) - round(before, 2)))
        return after

    rate = guard('season_limit', raw_target, _clamp(raw_target, min_rate, max_rate))
    if (current and ctx['lead'] <= ctx['protect_days'] and ctx['forecast_occ'] >= ctx['protect_occ_pct'] and rate < current):
        rate = guard('protect', rate, current)
    band_low, band_high = min_rate, max_rate
    if current:
        step_low = current * (1 - ctx['max_step_pct'] / 100)
        step_high = current * (1 + ctx['max_step_pct'] / 100)
        rate = guard('max_step', rate, _clamp(rate, step_low, step_high))
        rate = guard('season_limit', rate, _clamp(rate, min_rate, max_rate))
        band_low, band_high = max(min_rate, step_low), min(max_rate, step_high)
    if step > 0:
        rounded = None
        if band_low <= band_high:
            rounded = _step_value(rate, step, band_low, band_high)
        if rounded is None:
            rounded = _step_value(rate, step, min_rate, max_rate)
        if rounded is not None:
            rate = guard('rounding', rate, rounded)
    if current and min_rate <= current <= max_rate and abs(rate - current) / current * 100 < ctx['min_change_pct']:
        rate = guard('hold', rate, current)

    recommended = round(rate, 2)
    return {
        'raw_target': round(raw_target, 2),
        'recommended': recommended,
        'action': _action(recommended, current),
        'factors': [{'code': code, 'pct': pct} for code, pct in factors],
        'guards': guards,
        'waterfall': _waterfall(steps, recommended - base),
    }


def derive(ref_result, derivation, value, current_rate, price_step, min_change_pct):
    """Price of a derived room from the reference result, with its own hold rule."""
    def apply(rate):
        return rate + value if derivation == 'amount' else rate * (1 + value / 100)

    raw_target = round(apply(ref_result['raw_target']), 2)
    before_hold = apply(ref_result['recommended'])
    if price_step > 0:
        before_hold = _round_to_step_free(before_hold, price_step)
    before_hold = round(before_hold, 2)
    current = current_rate or None
    recommended = before_hold
    guards = list(ref_result['guards'])
    steps = [(w['code'], w['amount']) for w in ref_result['waterfall']]
    steps.append(('derived', before_hold - ref_result['recommended']))
    if current and abs(before_hold - current) > 0.005 and abs(before_hold - current) / current * 100 < min_change_pct:
        recommended = round(current, 2)
        guards.append({'code': 'hold', 'before': before_hold, 'after': recommended})
        steps.append(('hold', recommended - before_hold))
    ref_cents = sum(round(w['amount'] * 100) for w in ref_result['waterfall'])
    total = (ref_cents + round(recommended * 100) - round(ref_result['recommended'] * 100)) / 100
    return {
        'raw_target': raw_target,
        'recommended': recommended,
        'action': _action(recommended, current),
        'factors': ref_result['factors'],
        'guards': guards,
        'waterfall': _waterfall(steps, total),
    }

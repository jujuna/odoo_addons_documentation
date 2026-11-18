# -*- coding: utf-8 -*-
"""Shared scoring helpers, free of ORM access so they can be unit tested alone."""

# Default parameters, overridable through ir.config_parameter.
PARAM_ACHIEVEMENT_CAP = 'bsc.achievement_cap'
PARAM_THRESHOLD_GREEN = 'bsc.objective_threshold_green'
PARAM_THRESHOLD_AMBER = 'bsc.objective_threshold_amber'
PARAM_QUALITATIVE_GREEN = 'bsc.qualitative_score_green'
PARAM_QUALITATIVE_AMBER = 'bsc.qualitative_score_amber'
PARAM_QUALITATIVE_RED = 'bsc.qualitative_score_red'

DEFAULT_ACHIEVEMENT_CAP = 150.0
DEFAULT_THRESHOLD_GREEN = 95.0
DEFAULT_THRESHOLD_AMBER = 80.0
DEFAULT_QUALITATIVE = {'green': 100.0, 'amber': 85.0, 'red': 50.0}

TREND_FLAT_TOLERANCE = 0.02


def weighted_average(pairs):
    """Weighted average of ``(weight, value)`` pairs, ``None`` values dropped from both sums.
    Returns ``None`` if nothing is measurable; the plain mean when every weight is zero or negative."""
    clean = [(w or 0.0, v) for w, v in pairs if v is not None]
    if not clean:
        return None
    total_weight = sum(w for w, _v in clean if w > 0.0)
    if total_weight <= 0.0:
        return sum(v for _w, v in clean) / len(clean)
    weighted = [(w, v) for w, v in clean if w > 0.0]
    return sum(w * v for w, v in weighted) / total_weight


def achievement(direction, target, actual, target_min=0.0, target_max=0.0, cap=DEFAULT_ACHIEVEMENT_CAP):
    """Achievement percentage: a ratio for non-negative figures, else distance from target over ``abs(target)``.
    Returns ``None`` when not computable (e.g. higher-is-better, target zero); callers map it to ``no_data``."""
    if direction == 'higher_better':
        if not target:
            return None
        if target > 0.0:
            value = actual / target * 100.0
        else:
            value = (1.0 + (actual - target) / abs(target)) * 100.0
    elif direction == 'lower_better':
        # Zero is the perfect outcome for a "less is better" measure.
        if target >= 0.0 and actual >= 0.0:
            value = 100.0 if actual == 0.0 else target / actual * 100.0
        elif target == 0.0:
            value = 100.0
        else:
            value = (1.0 + (target - actual) / abs(target)) * 100.0
    elif direction == 'target_range':
        if not target_min and not target_max:
            return None
        if target_min <= actual <= target_max:
            value = 100.0
        elif actual < target_min:
            if target_min > 0.0 and actual >= 0.0:
                value = actual / target_min * 100.0
            else:
                scale = abs(target_min) or (target_max - target_min)
                value = (1.0 - (target_min - actual) / scale) * 100.0 if scale else None
        else:
            if target_max > 0.0 and actual > 0.0:
                value = target_max / actual * 100.0
            else:
                scale = abs(target_max) or (target_max - target_min)
                value = (1.0 - (actual - target_max) / scale) * 100.0 if scale else None
        if value is None:
            return None
    else:
        return None
    if value < 0.0:
        value = 0.0
    if cap and value > cap:
        value = cap
    return value


def rag_status(value, threshold_green, threshold_amber):
    """Traffic-light status for an achievement percentage."""
    if value is None:
        return 'no_data'
    if value >= threshold_green:
        return 'green'
    if value >= threshold_amber:
        return 'amber'
    return 'red'


def trend(current, previous):
    """Direction of travel. Note: 'up' does not mean 'good'."""
    if previous is None or current is None:
        return 'flat'
    if previous == 0.0:
        return 'flat' if current == 0.0 else ('up' if current > 0.0 else 'down')
    change = (current - previous) / abs(previous)
    if abs(change) < TREND_FLAT_TOLERANCE:
        return 'flat'
    return 'up' if change > 0.0 else 'down'


def computed_selection_search(model, field_name, operator, value):
    """Make a non-stored selection field filterable by searching in Python over records the user may see.
    Scores depend on the current period, which no @api.depends can express; fine for tens of objectives."""
    if operator not in ('=', '!=', 'in', 'not in'):
        raise ValueError('Unsupported operator %s for %s' % (operator, field_name))
    # The value can arrive as an OrderedSet, not a list: accept any non-string iterable.
    if isinstance(value, str) or not hasattr(value, '__iter__'):
        values = [value]
    else:
        values = list(value)
    negate = operator in ('!=', 'not in')
    candidates = model.with_context(active_test=False).search([])
    matched = candidates.filtered(
        lambda record: ((record[field_name] in values) != negate))
    return [('id', 'in', matched.ids)]

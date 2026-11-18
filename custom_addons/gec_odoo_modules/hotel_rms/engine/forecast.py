from datetime import timedelta
from statistics import median

FORECAST_VERSION = 'forecast_v1'
COLDSTART_VERSION = 'coldstart_v1'

CONFIDENCE_COLDSTART = 30
CONFIDENCE_BASE = 60
CONFIDENCE_PER_REF = 3
CONFIDENCE_MAX_REFS = 10
CONFIDENCE_PER_STALE_DAY = 10
CONFIDENCE_LOW = 40
CONFIDENCE_MEDIUM = 70
CURVE_HISTORY_DAYS = 365


def night_index(reservations):
    """Map every night to its bookings: (booking_date, cancel_date, rooms, revenue_per_night)."""
    index = {}
    for res in reservations:
        nights = (res['departure'] - res['arrival']).days
        if nights <= 0:
            continue
        per_night = res['revenue'] / nights
        entry = (res['booking_date'], res['cancel_date'], res['rooms'], per_night)
        for i in range(nights):
            index.setdefault(res['arrival'] + timedelta(days=i), []).append(entry)
    return index


def otb(index, night, as_of):
    """Rooms and revenue on the books for a night as they stood on as_of."""
    rooms = revenue = 0
    for booking_date, cancel_date, res_rooms, per_night in index.get(night, ()):
        if booking_date <= as_of and (cancel_date is None or cancel_date > as_of):
            rooms += res_rooms
            revenue += per_night
    return rooms, revenue


def comparable_dates(night, today, window_days, years, recent_weeks):
    """Past nights on the same weekday: around the same night of previous years and the latest weeks."""
    found = set()
    for year in range(1, years + 1):
        centre = night - timedelta(days=364 * year)
        for offset in range(-window_days, window_days + 1):
            day = centre + timedelta(days=offset)
            if day.weekday() == night.weekday():
                found.add(day)
    latest = today - timedelta(days=(today.weekday() - night.weekday()) % 7 or 7)
    for week in range(recent_weeks):
        found.add(latest - timedelta(days=7 * week))
    return sorted(day for day in found if day < today)


def forecast_v1(index, night, today, capacity, refs, min_refs, history_start):
    """Forecast from comparable nights; None when too few of them have booking history."""
    lead = (night - today).days
    if not history_start:
        return None
    kept = [ref for ref in refs if ref - timedelta(days=lead) >= history_start]
    if len(kept) < min_refs:
        return None
    finals = [otb(index, ref, ref)[0] for ref in kept]
    at_lead = [otb(index, ref, ref - timedelta(days=lead))[0] for ref in kept]
    rooms, revenue = otb(index, night, today)
    expected_pickup = max(median(f - a for f, a in zip(finals, at_lead)), 0)
    expected_otb = median(at_lead)
    return {
        'method': FORECAST_VERSION,
        'otb': rooms,
        'otb_revenue': revenue,
        'expected_otb': expected_otb,
        'forecast_rooms': min(capacity, rooms + expected_pickup),
        'pace': rooms / expected_otb if expected_otb >= 1 else None,
        'refs': len(kept),
    }


def curve_share(curve, lead):
    """Fraction (0..1) of the final rooms already booked at this lead time (days before the night)."""
    if lead <= curve[0][0]:
        return curve[0][1]
    for (lead_a, share_a), (lead_b, share_b) in zip(curve, curve[1:]):
        if lead <= lead_b:
            return share_a + (share_b - share_a) * (lead - lead_a) / (lead_b - lead_a)
    return curve[-1][1]


def coldstart_v1(otb_today, otb_revenue, capacity, expected_occ, lead, curve):
    """Forecast without history, from the season's expected occupancy as a fraction of capacity."""
    expected_final = capacity * expected_occ
    expected_otb = expected_final * curve_share(curve, lead)
    return {
        'method': COLDSTART_VERSION,
        'otb': otb_today,
        'otb_revenue': otb_revenue,
        'expected_otb': expected_otb,
        'forecast_rooms': min(capacity, max(otb_today, expected_final)),
        'pace': otb_today / expected_otb if expected_otb >= 1 else None,
        'refs': 0,
    }


def learn_curve(index, today, leads, min_nights):
    """Booking curve [(lead, share)] from past nights; None when fewer than min_nights nights qualify."""
    shares = {lead: [] for lead in leads}
    nights = 0
    for i in range(1, CURVE_HISTORY_DAYS + 1):
        night = today - timedelta(days=i)
        final = otb(index, night, night)[0]
        if final <= 0:
            continue
        nights += 1
        for lead in leads:
            shares[lead].append(otb(index, night, night - timedelta(days=lead))[0] / final)
    if nights < min_nights:
        return None
    curve = []
    previous = 1.0
    for lead in sorted(leads):
        share = 1.0 if lead == 0 else min(median(shares[lead]), previous)
        curve.append((lead, share))
        previous = share
    return curve


def confidence(method, refs, data_age_days):
    """Confidence score 0..100 and its level (low, medium, high)."""
    if method == COLDSTART_VERSION:
        score = CONFIDENCE_COLDSTART
    else:
        score = CONFIDENCE_BASE + CONFIDENCE_PER_REF * min(refs, CONFIDENCE_MAX_REFS)
    score -= CONFIDENCE_PER_STALE_DAY * max(data_age_days - 1, 0)
    score = max(0, min(100, score))
    if score < CONFIDENCE_LOW:
        return score, 'low'
    if score < CONFIDENCE_MEDIUM:
        return score, 'medium'
    return score, 'high'

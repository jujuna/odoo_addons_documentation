const { DateTime } = luxon;

export function getPeriodRange(periodStart) {
    const today = DateTime.local().endOf("day");
    const start = (periodStart || today).startOf("month");
    const periodEnd = start.endOf("month");
    const stop = DateTime.min(today, periodEnd);
    return {
        start: start,
        stop: stop,
    }
}

/** @odoo-module **/
/** Georgian weekday and month names without Intl ("small-icu" Chromium resolves ka-GE to en-US, dates stay English).
 * Substituted only when the user's language is Georgian and the browser cannot resolve it. */
import { patch } from "@web/core/utils/patch";
import { CalendarCommonRenderer } from "@web/views/calendar/calendar_common/calendar_common_renderer";
import { CalendarController } from "@web/views/calendar/calendar_controller";
import { DateTimePicker } from "@web/core/datetime/datetime_picker";
import {
    WEEKDAY_SHORT,
    WEEKDAY_LONG,
    WEEKDAY_NARROW,
    MONTH_LONG,
    georgianNamesMissing,
} from "@gec_i18n_base/georgian_names";

patch(CalendarCommonRenderer.prototype, {
    headerTemplateProps(date) {
        const props = super.headerTemplateProps(...arguments);
        if (!georgianNamesMissing()) {
            return props;
        }
        // Month scale uses a tz-less date, so read UTC like Odoo does.
        const jsDay =
            this.props.model.scale === "month" ? date.getUTCDay() : date.getDay();
        const index = (jsDay + 6) % 7; // JS 0=Sunday -> 0=Monday
        return {
            ...props,
            weekdayShort: WEEKDAY_SHORT[index],
            weekdayLong: WEEKDAY_LONG[index],
        };
    },
});

patch(CalendarController.prototype, {
    get dayHeader() {
        if (!georgianNamesMissing()) {
            return super.dayHeader;
        }
        const d = this.date;
        return `${d.day} ${MONTH_LONG[d.month - 1]} ${d.year}`;
    },
    get weekHeader() {
        if (!georgianNamesMissing()) {
            return super.weekHeader;
        }
        const { rangeStart: a, rangeEnd: b } = this.model;
        if (a.year !== b.year) {
            return `${MONTH_LONG[a.month - 1]} ${a.year} - ${MONTH_LONG[b.month - 1]} ${b.year}`;
        }
        if (a.month !== b.month) {
            return `${MONTH_LONG[a.month - 1]} - ${MONTH_LONG[b.month - 1]} ${a.year}`;
        }
        return `${MONTH_LONG[a.month - 1]} ${a.year}`;
    },
});


/** The calendar side-panel date picker builds its own labels (datetime_picker.js). PRECISION_LEVELS is
 * module-private: wrap the getter that exposes it and replace the two functions that produce visible text. */
patch(DateTimePicker.prototype, {
    get activePrecisionLevel() {
        const level = super.activePrecisionLevel;
        if (!georgianNamesMissing() || !level) {
            return level;
        }
        return {
            ...level,
            getTitle: (date, options) =>
                date && date.month
                    ? `${MONTH_LONG[date.month - 1]} ${date.year}`
                    : level.getTitle(date, options),
            getItems: (...args) => {
                const items = level.getItems(...args);
                for (const item of items || []) {
                    if (!item || !item.daysOfWeek || !item.weeks || !item.weeks[0]) {
                        continue;
                    }
                    // Read the weekday from the data: the first column depends on the language's week_start.
                    const days = item.weeks[0].days || [];
                    // daysOfWeek may carry a leading week-number column with no day.
                    const offset = item.daysOfWeek.length - days.length;
                    days.forEach((day, i) => {
                        const entry = item.daysOfWeek[offset + i];
                        const weekday = day && day.range && day.range[0] && day.range[0].weekday;
                        if (!entry || !weekday) {
                            return;
                        }
                        entry[0] = WEEKDAY_SHORT[weekday - 1];
                        entry[1] = WEEKDAY_LONG[weekday - 1];
                        entry[2] = WEEKDAY_NARROW[weekday - 1];
                    });
                }
                return items;
            },
        };
    },
});

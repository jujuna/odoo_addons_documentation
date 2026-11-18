/** @odoo-module **/
/** Georgian grid column headers: web_grid builds them with Intl, which returns English without Georgian ICU data.
 * Keeps the shape "<first>\n<second>" for day and month steps; other steps, or a ka-GE browser, use the original. */
import { patch } from "@web/core/utils/patch";
import { GridModel } from "@web_grid/views/grid_model";
import {
    WEEKDAY_SHORT,
    MONTH_LONG,
    MONTH_SHORT,
    georgianNamesMissing,
} from "@gec_i18n_base/georgian_names";

patch(GridModel.prototype, {
    _getDateColumnTitle(date) {
        if (!georgianNamesMissing()) {
            return super._getDateColumnTitle(...arguments);
        }
        const granularity = this.navigationInfo.range.step;
        // `date` is a Luxon DateTime: weekday 1 = Monday, month 1 = January.
        if (granularity === "day") {
            return `${WEEKDAY_SHORT[date.weekday - 1]}\n${date.day} ${MONTH_SHORT[date.month - 1]}`;
        }
        if (granularity === "month") {
            return `${MONTH_LONG[date.month - 1]}\n${date.year}`;
        }
        return super._getDateColumnTitle(...arguments);
    },
});

import { patch } from "@web/core/utils/patch";
import { HrHolidaysGanttModel } from "@hr_holidays_gantt/views/gantt/hr_holidays_gantt_model";
import { HrHolidaysGanttRenderer } from "@hr_holidays_gantt/views/gantt/hr_holidays_gantt_renderer";

patch(HrHolidaysGanttModel.prototype, {
    /**
     * @override
     */
    _getFields(metaData) {
        const result = super._getFields(...arguments);
        if (metaData.resModel === "hr.leave" && metaData.fields?.payslip_state) {
            result.push("payslip_state");
        }
        return result;
    },
});

patch(HrHolidaysGanttRenderer.prototype, {
    /**
     * @override
     */
    enrichPill(pill) {
        const enrichedPill = super.enrichPill(pill);
        const { record } = enrichedPill;
        if (record.payslip_state) {
            enrichedPill.isDeferred = record.payslip_state === "blocked";
            enrichedPill.isLocked = record.payslip_state === "done";
        }
        return enrichedPill;
    },
});

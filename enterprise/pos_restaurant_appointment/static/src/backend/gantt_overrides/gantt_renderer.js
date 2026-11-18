/* global posmodel */

import { POSAppointmentBookingGanttRenderer } from "@pos_appointment/app/gantt_overrides/gantt_renderer";
import { patch } from "@web/core/utils/patch";

patch(POSAppointmentBookingGanttRenderer, {
    rowContentTemplate: "pos_gantt.GanttRenderer.RowContent",
});

patch(POSAppointmentBookingGanttRenderer.prototype, {
    setup() {
        super.setup();
        this.orders = posmodel.models["pos.order"].getAll();
    },

    isBooked(column, row) {
        return (
            column.isToday &&
            this.orders.some(
                (o) =>
                    o.table_id?.appointment_resource_id?.id === row.resId &&
                    !o.finalized &&
                    o.isBooked
            )
        );
    },
});

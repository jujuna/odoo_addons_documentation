import { patch } from "@web/core/utils/patch";

import { TaskStatusBarDurationField } from "@timesheet_grid/widgets/task_status_bar_duration_field";

patch(TaskStatusBarDurationField.prototype, {
    _isTimesheetRecord(record) {
        return (
            super._isTimesheetRecord(record)
            && record.data.allow_billable || false
        );
    },
});

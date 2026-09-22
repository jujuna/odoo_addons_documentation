import { AvatarCard } from "@mail/core/web/avatar_card/avatar_card";
import { avatarProps } from "@mail/views/web/fields/avatar/avatar";
import { GanttEmployeeAvatar } from "@hr_gantt/hr_gantt_employee_avatar";
import { usePopover } from "@web/core/popover/popover_hook";
import { ORM } from "@web/core/orm_plugin";
import { usePlugin, t, useProps } from "@odoo/owl";

export class HrHolidaysGanttAvatarCard extends AvatarCard {
    static template = "hr_holidays_gantt.AvatarCard";

    setup() {
        super.setup(...arguments);
        this.props = useProps({
            close: t.function([]),
            id: t.number(),
            model: t.selection(AvatarCard.allowedModels),
            scale: t.string().optional(),
        });
        this.orm = usePlugin(ORM);
    }

    get leaveSummary() {
        return this.employee?.avatar_leave_summary || [];
    }

    get workingScheduleLabel() {
        const hours = this.employee?.avatar_hours_per_week;
        return hours ? `${hours}h / Week` : null;
    }

    get dashboardScale() {
        const scale = this.props.scale;
        return !scale || scale === "quarter" ? "year" : scale;
    }

    async onTimeOffClick() {
        const employeeId = this.employee?.id;
        if (!employeeId) {
            return;
        }
        const action = await this.orm.call(
            "hr.employee",
            "action_time_off_dashboard",
            [[employeeId]],
            { scale: this.dashboardScale }
        );
        if (action) {
            await this.actionService.doAction(action);
        }
    }

    get hasFooter() {
        return false;
    }
}

export class HrHolidaysGanttEmployeeAvatar extends GanttEmployeeAvatar {
    props = useProps({ ...avatarProps, scale: t.string().optional() });

    setup() {
        super.setup(...arguments);
        this.avatarCard = usePopover(HrHolidaysGanttAvatarCard);
    }

    openCard(ev) {
        if (this.uiService.isSmall || !this.props.resId) {
            return;
        }
        const target = ev.currentTarget;
        if (!this.avatarCard.isOpen) {
            this.avatarCard.open(target, {
                id: this.props.resId,
                model: this.props.resModel,
                scale: this.props.scale,
            });
        }
    }
}

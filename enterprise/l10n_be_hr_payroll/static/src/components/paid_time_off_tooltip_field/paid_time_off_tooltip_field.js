import { Component, useProps, t } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { usePopover } from "@web/core/popover/popover_hook";
import { FloatField, floatField } from "@web/views/fields/float/float_field";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate } from "@web/core/l10n/dates";
import { formatFloat } from "@web/views/fields/formatters";


export class PaidTimeOffPopover extends Component {
    static template = "l10n_be_hr_payroll.PaidTimeOffPopover";
    props = useProps({
        details: t.object(),
        close: t.function(),
    });
}


export class PaidTimeOffTooltipField extends FloatField {
    static template = "l10n_be_hr_payroll.PaidTimeOffTooltipField";

    setup() {
        super.setup();
        this.popover = usePopover(PaidTimeOffPopover, {
            position: "right",
        });
    }

    formatPeriodDate(date) {
        return date ? deserializeDate(date).toLocaleString({
              day: "2-digit",
              month: "2-digit",
          })
        : "";
    }

    formatDaysHours(days, hours) {
        return _t("%(days)s days (%(hours)s hours)", {
            days: formatFloat(days, { digits: [false, 2] }),
            hours: formatFloat(hours, { digits: [false, 2] }),
        });
    }

    get details() {
        const data = this.props.record.data;
        const nextCalendar = data.resource_calendar_id;
        const hasScheduleChange =
            nextCalendar &&
            nextCalendar.id !== data.current_resource_calendar_id?.id;

        return {
            worked: this.formatDaysHours(
                data.accrued_days_from_work,
                data.accrued_hours_from_work
            ),
            periods: (data.worked_periods || []).map((period) => ({
                start: this.formatPeriodDate(period.date_start),
                end: this.formatPeriodDate(period.date_end),
                calendar: period.calendar_name,
                hours: formatFloat(period.hours, { digits: [false, 2] }),
            })),
            attest: data.accrued_days_from_holiday_attest > 0
                ? formatFloat(
                    data.accrued_days_from_holiday_attest,
                    { digits: [false, 2] }
                )
                : false,
            scheduleChange: hasScheduleChange && {
                from: data.current_resource_calendar_id.display_name,
                to: nextCalendar.display_name,
                before: this.formatDaysHours(
                    data.total_accrued_days,
                    data.total_accrued_hours
                ),
                after: this.formatDaysHours(
                    data.expected_paid_time_off_to_allocate,
                    data.expected_hours_to_allocate
                ),
            },
        };
    }

    onClick(ev) {
        ev.stopPropagation();

        if (this.popover.isOpen) {
            this.popover.close();
        } else {
            this.popover.open(ev.currentTarget, {
                details: this.details,
            });
        }
    }
}


registry.category("fields").add("paid_time_off_tooltip", {
    ...floatField,
    component: PaidTimeOffTooltipField,
});

import { t, useProps } from "@odoo/owl";

import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { useEnv } from "@web/owl2/utils";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

import { AttendeeCalendarSidePanel } from "@calendar/views/attendee_calendar/side_panel/attendee_calendar_side_panel";

Object.assign(AttendeeCalendarSidePanel.components, {
    AutoComplete,
});


patch(AttendeeCalendarSidePanel.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.appointmentOptionsCollapsed = false;
        this.env = useEnv();
        this.uiService = useService("ui");
        this.appointmentProps = useProps({
            setEditingAppointmentId: t.function(),
            openAppointmentForm: t.function(),
            openAppointmentEditWizard: t.function(),
            copyAppointmentURL: t.function(),
        });
    },

    /**
     * Values of the default appointment, if one is set and it is in the list
     */
    get defaultAppointment() {
        const model = this.props.model;
        if (model.meta.context.default_appointment_type_id) {
            return this.props.model.data.userAppointmentsData.get(
                model.meta.context.default_appointment_type_id
            );
        }
        return undefined;
    },

    /**
     * Appointment types added to the sidebar "Booking Pages" list.
     */
    get listedUserAppointments() {
        const listedIds = this.props.model.listedAppointmentTypeIds;
        return Array.from(this.props.model.data.userAppointmentsData.values()).filter(
            (appointment) => listedIds.includes(appointment.id)
        );
    },

    get bookingPagesAutoCompleteProps() {
        return {
            autoSelect: true,
            resetOnSelect: true,
            placeholder: _t("+ Add Booking Pages"),
            sources: [
                {
                    options: (request) => this.loadBookingPageOptions(request),
                },
            ],
            class: "mt-1",
        };
    },

    async loadBookingPageOptions(request) {
        // search staff appointments the user manages, excluding ids already in the list
        const domain = [
            ["schedule_based_on", "=", "users"],
            ["staff_user_ids", "in", [user.userId]],
            ["category", "!=", "anytime"],
            ["id", "not in", this.props.model.listedAppointmentTypeIds],
        ];
        if (request) {
            domain.push(["display_name", "ilike", request]);
        }
        const { records } = await this.props.model.orm.webSearchRead("appointment.type", domain, {
            specification: { name: {} },
            limit: 8,
        });
        const options = records.map((appointment) => ({
            label: appointment.name,
            onSelect: () => this.props.model.toggleAppointmentInList(appointment.id),
        }));
        const search = request.toLowerCase();
        if (!search || !records.some((appointment) => appointment.name.toLowerCase() === search)) {
            options.push({
                cssClass: "o_calendar_dropdown_option",
                label: request ? _t('Create "%s"', request) : _t("Create New"),
                onSelect: () => this.appointmentProps.openAppointmentEditWizard(false, request),
            });
        }
        return options;
    },

    get editingAppointmentValues() {
        return this.props.model.slotsAppointmentData();
    },

    toggleAppointmentOptions() {
        // disabled while editing as toggle caret disappears
        if (!this.editingAppointmentValues) {
            this.state.appointmentOptionsCollapsed = !this.state.appointmentOptionsCollapsed;
        }
    },

    setSlotEditionMode(mode) {
        this.env.calendarState.mode = mode;
    },

    get userTimezone() {
        return user.tz;
    },

    get userTimezoneLocalized() {
        // Usually UTC+2 (or local variant) but can occasionally be something like "CET" etc..
        return luxon.DateTime.now().setZone(this.userTimezone).offsetNameShort;
    },
});

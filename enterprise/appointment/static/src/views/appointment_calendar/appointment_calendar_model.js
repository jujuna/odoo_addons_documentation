import { proxy, signal } from "@odoo/owl";

import { AttendeeCalendarModel } from "@calendar/views/attendee_calendar/attendee_calendar_model";
import { deserializeDateTime, serializeDateTime } from "@web/core/l10n/dates";
import { Cache } from "@web/core/utils/cache";
import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";
import { rpc } from "@web/core/network/rpc";

export class AppointmentAttendeeCalendarModel extends AttendeeCalendarModel {
    setup() {
        super.setup(...arguments);
        this.data.availableSlots = [];
        this._availableSlotsCache = new Cache(
            (data) => this.fetchAvailableSlots(data),
            (data) => `${serializeDateTime(data.range.start)},${serializeDateTime(data.range.end)}`
        );
    }

    // Do not display any user activity in the appointment attendee calendar.
    get userActivitiesEnabled() {
        return false;
    }

    async updateData(data) {
        await super.updateData(data);
        data.availableSlots = await this._availableSlotsCache.read(data);
    }

    fetchAvailableSlots(data) {
        if (
            !["day", "week"].includes(this.scale) ||
            this.meta.context.active_model !== "appointment.type" ||
            !this.meta.context.active_id
        ) {
            return [];
        }

        return this.orm.call("appointment.type", "calendar_get_available_slots", [
            this.meta.context.active_id,
            serializeDateTime(data.range.start),
            serializeDateTime(data.range.end),
        ]);
    }
}



/**
 * Appointment slot editor - data overview
 *
 * The slot editor lets a user edit the availability slots of one of their appointment
 * types directly from the attendee calendar.
 *
 * `env.calendarState.mode`:
 *  - "default": regular calendar
 *  - "slots-creation": drag to create slots
 *  - "slots-deletion": click to delete slots
 *
 * `model.data` are things that are fetched for every full data reload
 * `model.data.slots`: values of slots of the appointment type being edited.
 * `model.data.userAppointmentsData`: list of appointment types available in the "Booking Pages" list.
 *
 * `model.slotsAppointmentData`: values of the appointment type being edited, `undefined` when not editing.
 * This if fetched when switching which appointment is being edited, mostly to determine how slots should be generated and their values.
 *
 * `model.sidebarAppointmentData`: list of appointments actually shown in the "Booking Pages" list.
 * This data lives purely in local storage to determine which appointment types to list in the sidebar
 */

patch(AttendeeCalendarModel.prototype, {
    /**
     * @override
     */
    setup() {
        super.setup(...arguments);
        this.data.userAppointmentsData = proxy(new Map());
        this.data.slots = {};
        // Relevant data of the appointment being edited in view, such as: id, duration and invite url
        // See `_updateSlotsAppointment` for the exact structure
        this.slotsAppointmentData = signal(undefined);
        // indicates if the appointment was loaded once, to know whether calendar_editing_custom_appointment_id should be used
        // if that context key is set, that appointment should be set as the appointment being edited at load time.
        // This is used to immediately enable edit mode when clicking the "slots" smart button in the appointment form.
        this.wasSlotsAppointmentLoaded = false;

        // Data relevant to sidebar features
        let sidebarAppointmentData;
        try {
            sidebarAppointmentData = JSON.parse(
                localStorage.getItem("appointment.sidebar_appointment_data")
            );
        } catch {
            sidebarAppointmentData = null;
        }
        this.sidebarAppointmentData = proxy({
            // appointment types added to the sidebar "Booking Pages" list
            listedAppointmentTypeIds: [],
            ...sidebarAppointmentData,
        });
    },

    /**
     * @override
     * Hide events not related to the appointment type being edited
     */
    computeDomain(data) {
        const domain = super.computeDomain(data);
        const appointmentData = this.slotsAppointmentData();
        if (appointmentData) {
            domain.push(["appointment_type_id", "=", appointmentData.id]);
        }
        return domain;
    },

    async _updateSlotsAppointment(appointmentTypeId) {
        this.wasSlotsAppointmentLoaded = true;
        if (!appointmentTypeId) {
            this.slotsAppointmentData.set(undefined);
            return;
        }
        const appointmentInfo = await rpc(
            "/appointment/appointment_type/get_calendar_slot_editor_info",
            {
                appointment_type_id: appointmentTypeId,
                ...this._getInviteParams(),
            }
        );
        const appointmentData = {
            ...appointmentInfo.appointment_type,
            // booking window for punctual appointment types
            startDatetime: appointmentInfo.appointment_type.start_datetime
                ? deserializeDateTime(appointmentInfo.appointment_type.start_datetime)
                : null,
            endDatetime: appointmentInfo.appointment_type.end_datetime
                ? deserializeDateTime(appointmentInfo.appointment_type.end_datetime)
                : null,
            url: appointmentInfo.invite_url,
        };
        this.slotsAppointmentData.set(appointmentData);
    },

    /**
     * Editor-only slot duration (in hours) for non-recurring slots.
     * Defaults to 30 minutes, matching the edition form.
     */
    getLocalStorageDuration(appointmentId) {
        let localData;
        try {
            localData = JSON.parse(
                localStorage.getItem(`appointment.slot.editor.data.${appointmentId}`)
            );
        } catch {
            localData = null;
        }
        return localData?.appointmentDuration ?? 0.5;
    },

    /**
     * Ensure we force the week view
     * @override
     */
    async load(params = {}) {
        const scale = params.scale || this.meta.scale;
        // if opened from an appointment, editing will start immediately and week view should be used
        if (
            !this.wasSlotsAppointmentLoaded &&
            params.context?.calendar_editing_custom_appointment_id &&
            scale !== "week"
        ) {
            params.scale = "week";
        }
        return super.load(params);
    },

    /**
     * @override
     */
    async updateData(data) {
        // set the default edition appointment first as the search domains depends on it
        if (
            !this.wasSlotsAppointmentLoaded &&
            this.meta.context.calendar_editing_custom_appointment_id
        ) {
            await this._updateSlotsAppointment(
                this.meta.context.calendar_editing_custom_appointment_id
            );
        }
        await Promise.all([super.updateData(data), this.updateAllAppointmentData(data)]);
    },

    async updateAllAppointmentData(data) {
        if (data === undefined) {
            data = this.data;
        }
        return Promise.all([
            this.updateCustomSlotData(data),
            this.updateUserAppointmentsData(data),
        ]);
    },

    async updateCustomSlotData(data) {
        const appointmentData = this.slotsAppointmentData();
        if (!this.slotsAppointmentData()) {
            data.slots = {};
            return;
        }

        const domain = [["appointment_type_id", "=", appointmentData.id]];

        const slots = await this.orm.webSearchRead("appointment.slot", domain, {
            specification: {
                slot_type: {},
                start_datetime: {},
                end_datetime: {},
                allday: {},
                weekday: {},
                start_hour: {},
                end_hour: {},
                appointment_type_id: { fields: { name: {} } },
            },
        });

        data.slots = {};
        for (const slot of slots.records) {
            const slotVals = {
                ...slot,
                colorIndex: 2,
                slotId: slot.id,
            };
            if (slot.slot_type === "unique") {
                slotVals.start = deserializeDateTime(slot.start_datetime);
                slotVals.end = deserializeDateTime(slot.end_datetime);
                slotVals.isAllDay = slot.allday;
            }
            data.slots[slot.id] = slotVals;
        }
    },

    async updateUserAppointmentsData(data) {
        data = data ?? this.data;

        // add some ids that we'll definitely want even if they don't match the "user appointment" domain
        const forcedIds = [
            this.slotsAppointmentData()?.id, // we always want details for currently edited for the sidebar options
            this.meta.context.calendar_editing_custom_appointment_id, // in case it's not loaded yet
            this.meta.context.default_appointment_type_id, // we always want to be able to enter edition mode for the default type
        ].filter(Boolean);

        const appointmentValues = await this.orm.webSearchRead(
            "appointment.type",
            [
                "|",
                ["id", "in", forcedIds],
                "&",
                "&",
                "&",
                ["id", "in", this.listedAppointmentTypeIds],
                ["schedule_based_on", "=", "users"],
                ["staff_user_ids", "in", [user.userId]],
                ["category", "!=", "anytime"],
            ],
            {
                specification: {
                    name: {},
                    category: {},
                    category_slot_scheduling: {},
                    user_can_manage_slots: {},
                },
            }
        );
        // use map to preserve ordering, update inplace to preserve proxy
        data.userAppointmentsData.clear();
        for (const appointment of appointmentValues.records) {
            data.userAppointmentsData.set(appointment.id, appointment);
        }
    },

    /**
     * Set the current appointment type being edited and refresh the view.
     */
    async setEditingAppointmentId(appointmentTypeId) {
        const params = appointmentTypeId && (!this.meta || this.meta.scale !== "week")
            ? { scale: "week" }
            : {};
        // reload even if unchanged, as it might have changed since; a full load
        // is required as entering/leaving edition changes the events domain
        await this._updateSlotsAppointment(appointmentTypeId);
        await this.load(params);
        this.notify();
    },

    /**
     * @override
     */
    makeContextDefaults(rawRecord) {
        const context = super.makeContextDefaults(rawRecord);
        if (this.slotsAppointmentData()) {
            context.default_appointment_type_id = this.slotsAppointmentData().id;
        }
        return context;
    },

    /**
     * @override
     * Properly take into account the duration from the context.
     * Only when the user makes a click on the calendar (when there's no end) or when the end is invalid.
     */
    buildRawRecord(partialRecord, options) {
        if ('default_duration' in this.meta.context) {
            const defaultDuration = this.meta.context.default_duration;
            if (partialRecord.start && (!partialRecord.end || !partialRecord.end.isValid) && !partialRecord.isAllDay) {
                partialRecord.end = partialRecord.start.plus({ hours: defaultDuration });
            }
        }
        return super.buildRawRecord(...arguments);
    },

    processPartialSlotRecord(record) {
        let defaultDuration = 30;
        const appointmentData = this.slotsAppointmentData();
        const localStorageDuration = this.getLocalStorageDuration(appointmentData.id);
        if (appointmentData.category === "custom" && localStorageDuration) {
            defaultDuration = localStorageDuration * 60;
        } else if (appointmentData.appointment_duration) {
            defaultDuration = appointmentData.appointment_duration * 60;
        }

        if (!record.end || !record.end.isValid) {
            if (record.isAllDay) {
                record.end = record.start;
            } else {
                record.end = record.start.plus({ minutes: defaultDuration });
            }
        }
    },

    async createSlot(record) {
        return this.createSlots([record]);
    },

    _slotCreateVals(appointment, record) {
        this.processPartialSlotRecord(record);
        if (appointment.category_slot_scheduling !== "weekly") {
            return {
                appointment_type_id: appointment.id,
                start_datetime: serializeDateTime(record.start),
                end_datetime: serializeDateTime(record.end),
                allday: record.isAllDay,
                slot_type: "unique",
            };
        }
        // Start and end are relative to the appointment tz, values are assumed valid after conversion
        const start = record.start.setZone(appointment.appointment_tz);
        const end = record.end.setZone(appointment.appointment_tz);
        // an end falling exactly on midnight is 24:00 of the previous day (stored as end_hour 0),
        // so it still belongs to the start's day rather than spilling into the next one
        const endWeekday = end.equals(end.startOf("day"))
            ? end.minus({ days: 1 }).weekday
            : end.weekday;
        if (start.weekday !== endWeekday) {
            throw new Error("Cannot create a slot over multiple days.");
        }
        return {
            appointment_type_id: appointment.id,
            weekday: start.weekday,
            start_hour: start.hour + start.minute / 60,
            end_hour: end.hour + end.minute / 60,
            slot_type: "recurring",
        };
    },

    async createSlots(records) {
        const appointmentData = this.slotsAppointmentData();
        if (!appointmentData) {
            return;
        }
        const valsList = records.map((record) => this._slotCreateVals(appointmentData, record));
        try {
            await this.orm.create("appointment.slot", valsList);
        } finally {
            await this.updateAllAppointmentData();
            this.notify();
        }
    },

    async updateSlot(eventRecord, extraSlotRecords = []) {
        const appointmentData = this.slotsAppointmentData();
        this.processPartialSlotRecord(eventRecord);
        let vals;
        // as recurring slots inherently depend on the timezone of the appointment
        // we need to convert them manually
        if (eventRecord.slotType === "recurring") {
            const start = eventRecord.start.setZone(appointmentData.appointment_tz);
            const end = eventRecord.end.setZone(appointmentData.appointment_tz);
            vals = {
                weekday: start.weekday,
                start_hour: start.hour + start.minute / 60,
                end_hour: end.hour + end.minute / 60,
            };
        } else {
            vals = {
                start_datetime: serializeDateTime(eventRecord.start),
                end_datetime: serializeDateTime(eventRecord.end),
                allday: eventRecord.isAllDay,
            };
        }
        try {
            await this.orm.write("appointment.slot", [eventRecord.slotId], vals);
            // extending a slot may split it into several back-to-back subslots:
            // the original slot becomes the first one, the rest are created
            if (extraSlotRecords.length) {
                await this.orm.create(
                    "appointment.slot",
                    extraSlotRecords.map((record) => this._slotCreateVals(appointmentData, record))
                );
            }
        } finally {
            await this.updateAllAppointmentData();
            this.notify();
        }
    },

    async removeSlot(slotId) {
        try {
            await this.orm.unlink("appointment.slot", [slotId]);
        } finally {
            await this.updateAllAppointmentData();
            this.notify();
        }
    },


    // SIDEBAR DATA HELPERS

    /**
     * Appointment types listed in the sidebar "Booking Pages" list.
     */
    get listedAppointmentTypeIds() {
        return this.sidebarAppointmentData.listedAppointmentTypeIds;
    },

    /**
     * Add/remove an appointment type line in the sidebar "Booking Pages" list.
     */
    async toggleAppointmentInList(appointmentTypeId) {
        const listedIds = this.sidebarAppointmentData.listedAppointmentTypeIds;
        this.sidebarAppointmentData.listedAppointmentTypeIds = listedIds.includes(appointmentTypeId)
            ? listedIds.filter((listedId) => listedId !== appointmentTypeId)
            : [...listedIds, appointmentTypeId];
        localStorage.setItem(
            "appointment.sidebar_appointment_data",
            JSON.stringify(this.sidebarAppointmentData)
        );
        // refresh sidebar data to include the new one
        await this.updateUserAppointmentsData();
    },

    // CONTEXT HELPERS

    /**
     * Context to pass to routes creating an invite.
     * Overridden in modules that need to somehow propagate values to invites
     */
    _getInviteParams() {
        return {};
    },
});

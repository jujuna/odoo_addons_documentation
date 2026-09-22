import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { advanceTime, animationFrame, mockDate, mockTimeZone } from "@odoo/hoot-mock";

import { session } from "@web/session";
import { togglePartnerFilter } from "@calendar/../tests/calendar_test_helpers";
import {
    clickAllDaySlot,
    moveEventToTime,
    resizeEventToTime,
    selectTimeRange,
} from "@web/../tests/views/calendar/calendar_test_helpers";
import {
    contains,
    defineActions,
    MockServer,
    mountView,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";

import { AppointmentType, CalendarEvent, defineAppointmentModels } from "./appointment_tests_common";

describe.current.tags("desktop");
defineAppointmentModels();

let userId = session.user_id[0];

// the sidebar "Booking Pages" autocomplete opens this action to create/edit an
// appointment type; give it a minimal form
AppointmentType._views = {
    form: `<form>
        <field name="name"/>
        <field name="staff_user_ids" widget="many2many_tags"/>
        <field name="category" invisible="1"/>
        <field name="slot_duration"/>
    </form>`,
};
defineActions([
    {
        xml_id: "appointment.appointment_edit_slots_action",
        name: "Configure Appointment",
        res_model: "appointment.type",
        target: "new",
        view_mode: "form",
        views: [[false, "form"]],
        // make sure newly-created appointment types have values that would include them in the sidebar
        // custom + current user included + scheduled by user (which is already the default on the model)
        context: { default_category: "custom", default_staff_user_ids: [userId] },
    },
]);

async function createBookingPageFromSidebar(name, { slotDuration } = {}) {
    await contains(`.o-autocomplete--input[placeholder="+ Add Booking Pages"]`).edit(name, {
        confirm: false,
    });
    // wait for autocomplete debounce
    await advanceTime(300);
    await contains(".o-autocomplete--dropdown-item:contains(Create)").click();
    if (slotDuration !== undefined) {
        await contains(".o_field_widget[name='slot_duration'] input").edit(String(slotDuration));
    }
    await contains("button.o_form_button_save").click();
    await animationFrame();
}

async function listBookingPageFromSidebar(name) {
    const bookingPagesAutocomplete = `.o-autocomplete:has(.o-autocomplete--input[placeholder="+ Add Booking Pages"])`;
    await contains(`${bookingPagesAutocomplete} .o-autocomplete--input`).edit(name, {
        confirm: false,
    });
    await advanceTime(300);
    await contains(`${bookingPagesAutocomplete} .o-autocomplete--dropdown-item:not(:contains(Create))`).click();
}

const baseTestAppointmentStaffUsers = AppointmentType._records[1].staff_user_ids;
beforeEach(function () {
    userId = session.user_id[0];
    // add user to "Test Appointment"
    AppointmentType._records[1].staff_user_ids = [userId];
    mockDate("2022-01-05 00:00:00");
});
afterEach(function () {
    AppointmentType._records[1].staff_user_ids = baseTestAppointmentStaffUsers;
});

onRpc("res.partner", "get_attendee_detail", () => []);

onRpc("res.users", "has_group", () => true);

onRpc("res.users", "get_calendar_model_data", () => ({
    credential_status: {},
    sync_status: {},
    sync_email: false,
    default_duration: 1,
}));

// one calendar arch for every test; filter_field enables the partner filter that only the
// "only the edited type's events" test toggles (harmless everywhere else)
const CALENDAR_ARCH = `<calendar js_class="attendee_calendar" all_day="allday" date_start="start" date_stop="stop" color="partner_ids">
        <field name="name"/>
        <field name="partner_ids" write_model="calendar.filters" write_field="partner_id" filter_field="active"/>
    </calendar>`;

describe("appointment slot splitting", () => {
    /**
     * return a list of create vals that's expanded as more orm create calls are made
     */
    function captureSlotCreate() {
        const created = [];
        onRpc("appointment.slot", "create", ({ args: [valsList] }) => {
            created.push(...valsList);
        });
        return created;
    }

    /**
     * Create a weekly appointment type (optionally in a specific `appointment_tz`) and enter its
     * slot-edition mode, ready for a drag. Use captureSlotCreate() for the assertions.
     */
    async function editWeeklyType(name, extraVals = {}) {
        await mountView({ type: "calendar", resModel: "calendar.event", arch: CALENDAR_ARCH });
        MockServer.env["appointment.type"].create({
            name,
            category: "website",
            staff_user_ids: [userId],
            schedule_based_on: "users",
            user_can_manage_slots: true,
            ...extraVals,
        });
        await listBookingPageFromSidebar(name);
        await contains(`.o_cw_filter_title:contains(${name})`).click();
        await animationFrame();
    }

    test("custom slots split by the duration set in the wizard", async () => {
        const created = captureSlotCreate();

        await mountView({ type: "calendar", resModel: "calendar.event", arch: CALENDAR_ARCH });

        // with slot duration, when dragging the length should be subdivided in (length / duration) (+ 1 unless exactly divisible)
        await createBookingPageFromSidebar("Custom Duration Meeting", { slotDuration: 1 });

        await selectTimeRange("2022-01-05 09:00:00", "2022-01-05 11:30:00");
        await animationFrame();

        expect(created).toHaveLength(3);
        expect(created.every((slot) => slot.slot_type === "unique")).toBe(true);
        const spans = created.map((slot) => ({
            start: luxon.DateTime.fromSQL(slot.start_datetime),
            end: luxon.DateTime.fromSQL(slot.end_datetime),
        }));
        // each slot lasts the configured 1h and they are contiguous
        expect(spans.every((s) => s.end.diff(s.start, "hours").hours === 1)).toBe(true);
        expect(spans[1].start.toISO()).toBe(spans[0].end.toISO());
        expect(spans[2].start.toISO()).toBe(spans[1].end.toISO());
    });

    test("custom slots with a zero duration are not subdivided", async () => {
        const created = captureSlotCreate();

        await mountView({ type: "calendar", resModel: "calendar.event", arch: CALENDAR_ARCH });

        // a custom booking page whose slot duration is 0 => no automatic subdivision
        await createBookingPageFromSidebar("Custom No Duration Meeting", { slotDuration: 0 });

        // a 3h drag stays a single slot spanning the whole range
        await selectTimeRange("2022-01-05 09:00:00", "2022-01-05 12:00:00");
        await animationFrame();

        expect(created).toHaveLength(1);
        expect(created[0].slot_type).toBe("unique");
        const start = luxon.DateTime.fromSQL(created[0].start_datetime);
        const end = luxon.DateTime.fromSQL(created[0].end_datetime);
        expect(end.diff(start, "hours").hours).toBe(3);
    });

    test("extending a slot across the appointment's midnight splits it", async () => {
        // the appointment tz (Honolulu, UTC-10) puts its midnight at the viewer's noon (viewer is
        // UTC+2), so the slot and the boundary it splits at both stay mid-grid, off the flaky edges
        mockTimeZone(2);
        await editWeeklyType("Weekly Meeting", { appointment_tz: "Pacific/Honolulu" });
        // viewer Wed 09:00-11:00 == Honolulu Tue 21:00-23:00: a 2h slot within a single day
        await selectTimeRange("2022-01-05 09:00:00", "2022-01-05 11:00:00");
        await animationFrame();
        const eventId = queryOne(".o_calendar_slot").dataset.eventId;

        const created = captureSlotCreate();
        const writes = [];
        onRpc("appointment.slot", "write", ({ args: [ids] }) => writes.push(ids));

        // drag the end down to viewer 14:00 == Honolulu Wed 02:00, crossing midnight:
        // Tuesday 21:00-24:00 is written, Wednesday 00:00-02:00 is created
        await resizeEventToTime(eventId, "2022-01-05 14:00:00");
        await animationFrame();
        expect(writes).toHaveLength(1);
        expect(created).toHaveLength(1);
        expect(created[0].slot_type).toBe("recurring");
    });

    test("moving a slot across the appointment's midnight splits it", async () => {
        // same Honolulu/viewer-noon setup as the extend test, so the drag stays mid-grid
        mockTimeZone(2);
        await editWeeklyType("Weekly Meeting", { appointment_tz: "Pacific/Honolulu" });
        // viewer Wed 09:00-11:00 == Honolulu Tue 21:00-23:00: a 2h slot within a single day
        await selectTimeRange("2022-01-05 09:00:00", "2022-01-05 11:00:00");
        await animationFrame();
        const eventId = queryOne(".o_calendar_slot").dataset.eventId;

        const created = captureSlotCreate();
        const writes = [];
        onRpc("appointment.slot", "write", ({ args: [ids] }) => writes.push(ids));

        // slide it down 2h so viewer 11:00-13:00 == Honolulu 23:00-01:00, crossing midnight:
        // Tuesday 23:00-24:00 is written, Wednesday 00:00-01:00 is created
        await moveEventToTime(eventId, "2022-01-05 11:00:00");
        await animationFrame();
        expect(writes).toHaveLength(1);
        expect(created).toHaveLength(1);
        expect(created[0].slot_type).toBe("recurring");
    });

    test("the day-boundary split follows the appointment timezone, not the viewer's", async () => {
        const created = captureSlotCreate();
        // appointment midnight = user noon
        mockTimeZone(2);
        await editWeeklyType("Honolulu Meeting", { appointment_tz: "Pacific/Honolulu" });

        // split on crossing midnight, even if it's the middle of the day for the user
        await selectTimeRange("2022-01-05 11:00:00", "2022-01-05 13:00:00");
        await animationFrame();
        expect(created).toHaveLength(2);
        expect(created.every((slot) => slot.slot_type === "recurring")).toBe(true);
        expect(created.map((slot) => slot.weekday)).toEqual([2, 3]);

        // crosses midnight in user tz yet it is not split
        created.length = 0;
        await selectTimeRange("2022-01-05 13:00:00", "2022-01-05 15:00:00");
        await animationFrame();
        expect(created).toHaveLength(1);
        expect(created[0].weekday).toBe(3);
    });
});

describe("booking pages sidebar", () => {
    test("clicking the copy button copies the appointment type's url", async () => {
        expect.assertions(2);

        patchWithCleanup(navigator, {
            clipboard: {
                writeText: (value) => {
                    expect(value).toBe(
                        `http://amazing.odoo.com/appointment/2?filter_staff_user_ids=%5B${userId}%5D`
                    );
                },
            },
        });

        onRpc("/appointment/appointment_type/get_calendar_slot_editor_info", () => {
            expect.step("/appointment/appointment_type/get_calendar_slot_editor_info");
        });

        await mountView({
            type: "calendar",
            resModel: "calendar.event",
            arch: CALENDAR_ARCH,
        });

        await listBookingPageFromSidebar("Test Appointment");
        queryOne(
            '.o_calendar_filter_item:contains("Test Appointment") button[title="Copy invite url to clipboard"]'
        ).click();
        await animationFrame();

        expect.verifySteps(["/appointment/appointment_type/get_calendar_slot_editor_info"]);
    });

    test("create/search anytime appointment type", async () => {
        expect.assertions(6);

        patchWithCleanup(session, { "web.base.url": "http://amazing.odoo.com" });
        patchWithCleanup(navigator, {
            clipboard: {
                writeText: (value) => {
                    expect(value).toBe(
                        `http://amazing.odoo.com/appointment/3?filter_staff_user_ids=%5B${userId}%5D`
                    );
                },
            },
        });

        onRpc("/appointment/appointment_type/search_create_anytime", () => {
            expect.step("/appointment/appointment_type/search_create_anytime");
        });

        await mountView({
            type: "calendar",
            resModel: "calendar.event",
            arch: CALENDAR_ARCH,
        });
        await contains('button:contains("Share my calendar")').click();
        await animationFrame();

        expect.verifySteps(["/appointment/appointment_type/search_create_anytime"]);
        expect(MockServer.env["appointment.type"]).toHaveLength(3, {
            message: "Create a new appointment type",
        });

        await contains('button:contains("Share my calendar")').click();
        await animationFrame();

        expect.verifySteps(["/appointment/appointment_type/search_create_anytime"]);
        expect(MockServer.env["appointment.type"]).toHaveLength(3, {
            message: "Does not create a new appointment type",
        });
    });

    test("verify share button and booking pages sidebar are displayed", async () => {
        await mountView({
            type: "calendar",
            resModel: "calendar.event",
            arch: CALENDAR_ARCH,
        });

        expect('button:contains("Share my calendar")').toHaveCount(1);
        expect('.o_cw_filter_label:contains("Booking Pages")').toHaveCount(1);
    });
});

describe("recurring slot rendering", () => {
    async function startEditRecurringSlots({ aptVals = {}, slotValsAll = [] } = {}) {
        await mountView({ type: "calendar", resModel: "calendar.event", arch: CALENDAR_ARCH });
        const appointmentTypeId = MockServer.env["appointment.type"].create({
            name: "Recurring Meeting",
            staff_user_ids: [userId],
            schedule_based_on: "users",
            category: "website",
            user_can_manage_slots: true,
            ...aptVals,
        });
        slotValsAll = slotValsAll.map((vals) => ({
            appointment_type_id: appointmentTypeId,
            slot_type: "recurring",
            weekday: "1",
            ...vals,
        }));
        MockServer.env["appointment.slot"].create(slotValsAll);
        await listBookingPageFromSidebar("Recurring Meeting");
        await contains('.o_cw_filter_title:contains("Recurring Meeting")').click();
        await animationFrame();
    }

    test("a recurring slot crossing midnight in the viewer tz renders as two day segments", async () => {
        expect.assertions(3);
        mockTimeZone(2);
        await startEditRecurringSlots({
            aptVals: { appointment_tz: "UTC", appointment_duration: 1, slot_creation_interval: 1 },
            slotValsAll: [{ start_hour: 21, end_hour: 23 }], // straddles midnight in UTC+2
        });

        expect(".o_calendar_slot").toHaveCount(2);
        // FullCalendar keeps it a single event split at midnight: one segment holds the event's
        // start (Wednesday), the other its end (Thursday) - two separate events would carry both
        expect(".o_calendar_slot.fc-event-start:not(.fc-event-end)").toHaveCount(1);
        expect(".o_calendar_slot.fc-event-end:not(.fc-event-start)").toHaveCount(1);
    });

    test("subslots straddling midnight render as partials on both days", async () => {
        expect.assertions(4);
        mockTimeZone(2);
        await startEditRecurringSlots({
            aptVals: { appointment_tz: "UTC", appointment_duration: 1, slot_creation_interval: 1 },
            slotValsAll: [{ start_hour: 20.5, end_hour: 23.5 }], // appear to go over 2 days in UTC+2
        });

        // the start segment ends at midnight (Wed), the end segment begins at midnight (Thu)
        const startSeg = queryOne(".o_calendar_slot.fc-event-start");
        const endSeg = queryOne(".o_calendar_slot.fc-event-end");
        const startSubslots = queryAll(".o_calendar_subslot", { root: startSeg });
        const endSubslots = queryAll(".o_calendar_subslot", { root: endSeg });
        // the straddling slot is drawn as a partial at the bottom of Wed and the top of Thu
        expect(startSubslots).toHaveLength(2);
        expect(endSubslots).toHaveLength(2);
        // ...but both partials reference the same underlying bookable slot
        expect(startSubslots.at(-1).dataset.subslotStart).toBe(
            endSubslots.at(0).dataset.subslotStart
        );
        expect(startSubslots.at(-1).dataset.subslotEnd).toBe(endSubslots.at(0).dataset.subslotEnd);
    });
});

describe("slot editing", () => {
    test("create slots for custom appointment type", async () => {
        expect.assertions(4);
        patchWithCleanup(navigator, {
            clipboard: {
                writeText: (value) => {
                    expect(value).toBe(
                        `http://amazing.odoo.com/appointment/3?filter_staff_user_ids=%5B${userId}%5D`
                    );
                },
            },
        });
        onRpc("appointment.slot", "create", () => {
            expect.step("create slot");
        });

        await mountView({ type: "calendar", resModel: "calendar.event", arch: CALENDAR_ARCH });
        await createBookingPageFromSidebar("Test Online Meeting");

        await clickAllDaySlot("2022-01-08");
        await animationFrame();
        expect(".o_calendar_slot").toHaveCount(1);
        expect.verifySteps(["create slot"]);

        await contains('button[title="Save Slots"]').click();
        expect(MockServer.env["appointment.slot"]).toHaveLength(1);
    });

    test("days outside a punctual appointment's date range are greyed out", async () => {
        expect.assertions(4);
        AppointmentType._records = [
            ...AppointmentType._records,
            {
                id: 10,
                name: "Punctual Meeting",
                staff_user_ids: [userId],
                schedule_based_on: "users",
                category: "website",
                start_datetime: "2022-01-06 10:00:00",
                end_datetime: "2022-01-07 15:00:00",
            },
        ];

        await mountView({
            type: "calendar",
            resModel: "calendar.event",
            arch: CALENDAR_ARCH,
        });

        await listBookingPageFromSidebar("Punctual Meeting");
        await contains('.o_cw_filter_title:contains("Punctual Meeting")').click();
        await animationFrame();


        // "slot selection" is the greyed out part
        // normally 1 for the "allday" grid and one for the regular one = 2
        expect('.fc-day[data-date="2022-01-05"].o_calendar_slot_selection').toHaveCount(2);
        expect('.fc-day[data-date="2022-01-06"].o_calendar_slot_selection').toHaveCount(0);
        expect('.fc-day[data-date="2022-01-07"].o_calendar_slot_selection').toHaveCount(0);
        expect('.fc-day[data-date="2022-01-08"].o_calendar_slot_selection').toHaveCount(2);
    });

    test("deletion mode removes a slot", async () => {
        expect.assertions(2);
        await mountView({ type: "calendar", resModel: "calendar.event", arch: CALENDAR_ARCH });
        await createBookingPageFromSidebar("Test Online Meeting");

        await clickAllDaySlot("2022-01-08");
        await animationFrame();
        expect(".o_calendar_slot").toHaveCount(1);

        await contains('button[title="Enable Slot Deletion"]').click();
        await contains(".o_calendar_slot").click();
        await animationFrame();
        expect(".o_calendar_slot").toHaveCount(0);
    });

    test("only the edited type's events show while editing, and are restored on save", async () => {
        expect.assertions(5);
        // have an event for the appointment type we'll be editing
        CalendarEvent._records = [
            ...CalendarEvent._records,
            {
                id: 10,
                active: true,
                user_id: 214,
                partner_id: 214,
                name: "Linked Event",
                start: "2022-01-05 10:00:00",
                stop: "2022-01-05 11:00:00",
                allday: false,
                appointment_status: "booked",
                partner_ids: [214],
                appointment_type_id: 2,
            },
        ];

        await mountView({ type: "calendar", resModel: "calendar.event", arch: CALENDAR_ARCH });
        // add the attendee filter so we can actually see the event
        await togglePartnerFilter("partner_ids", "Partner 214");
        expect(".fc-event").toHaveCount(3);

        await listBookingPageFromSidebar("Test Appointment");
        await contains('.o_cw_filter_title:contains("Test Appointment")').click();
        await animationFrame();
        // now we only see the event linked to the appointment type
        expect(".fc-event").toHaveCount(1);

        // removing the filter still updated the domain properly
        await togglePartnerFilter("partner_ids", "Partner 214");
        expect(".fc-event").toHaveCount(0);
        await togglePartnerFilter("partner_ids", "Partner 214");
        expect(".fc-event").toHaveCount(1);

        // saving returns to the original domain
        await contains('button[title="Save Slots"]').click();
        expect(".fc-event").toHaveCount(3);
    });
});

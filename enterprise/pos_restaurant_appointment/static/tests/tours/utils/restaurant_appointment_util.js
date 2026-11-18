import { negate } from "@point_of_sale/../tests/generic_helpers/utils";
import { rpcBus } from "@web/core/network/rpc";

export function appointmentLabel(table_num, appointment_name) {
    return [
        {
            content: `Appointment label ${appointment_name}, is present underneath table ${table_num}`,
            trigger: `.floor-map .table:has(.label:contains("${table_num}")):has(.appointment-label:contains("${appointment_name}"))`,
        },
    ];
}

export function checkTableOption(tableText) {
    return {
        content: `Check that table option ${tableText} is present`,
        trigger: `.o_form_renderer .o-autocomplete--dropdown-menu li a.dropdown-item:contains("${tableText}")`,
    };
}

export function selectTable(tableText) {
    return {
        content: `Select table option containing ${tableText}`,
        trigger: `.o_form_renderer .o-autocomplete--dropdown-menu li a.dropdown-item:contains("${tableText}")`,
        run: "click",
    };
}

export function checkAppointment(appointmentName) {
    return {
        content: `Check that appointment ${appointmentName} is visible in Kanban`,
        trigger: `.o_kanban_record:contains("${appointmentName}")`,
    };
}

export function checkAppointmentNotVisible(appointmentName) {
    return {
        content: `Check that appointment ${appointmentName} is not visible`,
        trigger: negate(`.o_kanban_record:contains("${appointmentName}")`),
    };
}

export function checkAppointmentLabelNotPresent(table_num, appointment_name) {
    return [
        {
            content: `Appointment "${appointment_name}" should NOT appear under table ${table_num}`,
            trigger: negate(
                `.appointment-label:contains("${appointment_name}")`,
                `.table:has(.label:contains("${table_num}"))`
            ),
        },
    ];
}

function setSeats(seats) {
    return {
        content: `Set the number of seats to ${seats} and wait for the onchange`,
        trigger: `.o_form_renderer .o_field_widget[name='waiting_list_capacity'] input`,
        async run(helpers) {
            // Listen before editing, so the onchange response can't be missed
            const { promise, resolve, reject } = Promise.withResolvers();
            const onResponse = ({ detail }) => {
                const params = detail.data.params;
                // onchange(ids, values, field_names, fields_spec)
                if (
                    params?.method === "onchange" &&
                    params.args[2]?.includes("waiting_list_capacity")
                ) {
                    resolve();
                }
            };
            const timeout = setTimeout(
                () => reject(new Error(`No onchange after setting the seats to ${seats}`)),
                5000
            );
            rpcBus.addEventListener("RPC:RESPONSE", onResponse);
            try {
                await helpers.edit(`${seats}`);
                // Leave the input to commit the value
                await helpers.click(".o_form_renderer .o_field_widget[name='name'] input");
                await promise;
            } finally {
                clearTimeout(timeout);
                rpcBus.removeEventListener("RPC:RESPONSE", onResponse);
            }
            await new Promise((resolve) => requestAnimationFrame(resolve));
        },
    };
}

/**
 * Fill the booking form. Only the given keys are set, in this order:
 * @param {Object} values
 * @param {string} [values.name] - booking name
 * @param {string[]} [values.removeTables] - names of the tables to remove
 * @param {string[]} [values.addTables] - names of the tables to add
 * @param {number} [values.seats] - number of seats, waits for the onchange
 */
export function setFormBooking({ name, removeTables = [], addTables = [], seats } = {}) {
    const steps = [];
    if (name !== undefined) {
        steps.push({
            content: `Set the booking name to ${name}`,
            trigger: `.o_form_renderer .o_field_widget[name='name'] input`,
            run: `edit ${name}`,
        });
    }
    for (const tableName of removeTables) {
        steps.push({
            content: `Remove table ${tableName} from the booking`,
            trigger: `.o_form_renderer .o_field_widget[name='resource_ids'] .o_tag:contains("${tableName}") .o_delete`,
            run: "click",
        });
    }
    for (const tableName of addTables) {
        steps.push(
            {
                content: `Search table ${tableName}`,
                trigger: `.o_form_renderer .o_field_widget[name='resource_ids'] input`,
                run: `edit ${tableName}`,
            },
            {
                content: `Add table ${tableName} to the booking`,
                trigger: `.o_form_renderer .o-autocomplete--dropdown-menu li a.dropdown-item:contains("${tableName}")`,
                run: "click",
            }
        );
    }
    if (seats !== undefined) {
        steps.push(setSeats(seats));
    }
    return steps;
}

/**
 * Check the booking form. Only the given keys are checked:
 * @param {Object} values
 * @param {string} [values.name] - booking name
 * @param {string[]} [values.tables] - exact list of assigned tables ([] for none)
 * @param {number} [values.seats] - number of seats
 * @param {number} [values.availableSeats] - available seats shown next to the seats
 */
export function checkFormBooking({ name, tables, seats, availableSeats } = {}) {
    const steps = [];
    if (name !== undefined) {
        steps.push({
            content: `Check that the booking name is ${name}`,
            trigger: `.o_form_renderer .o_field_widget[name='name'] input:value("${name}")`,
        });
    }
    if (tables !== undefined) {
        const field = `.o_form_renderer .o_field_widget[name='resource_ids']`;
        const hasTables = tables.map((tableName) => `:has(.o_tag:contains("${tableName}"))`);
        steps.push({
            content: `Check that the booking tables are exactly: ${tables.join(", ") || "none"}`,
            trigger: tables.length
                ? `${field}${hasTables.join("")} .o_tag:count(${tables.length})`
                : negate(".o_tag", field),
        });
    }
    if (seats !== undefined) {
        steps.push({
            content: `Check that the booking has ${seats} seats`,
            trigger: `.o_form_renderer .o_field_widget[name='waiting_list_capacity'] input:value(${seats})`,
        });
    }
    if (availableSeats !== undefined) {
        steps.push({
            content: `Check that ${availableSeats} seats are available`,
            trigger: `.o_form_renderer .o_field_widget[name='available_capacity']:text(${availableSeats})`,
        });
    }
    return steps;
}

export function saveBooking(name) {
    return [
        {
            content: "Save the booking",
            trigger: ".o_dialog .o_form_button_save",
            run: "click",
        },
        {
            content: `Wait for ${name} to be shown in the gantt`,
            trigger: `.o_gantt_pill:contains("${name}")`,
        },
    ];
}

/**
 * Click on the gantt cell of the given table row to create a booking on that table.
 * The cell is the one of the hour following the current time.
 */
export function clickGanttCell(tableName) {
    return {
        content: `Click on the gantt cell of ${tableName}`,
        trigger: `.o_gantt_row_header:contains("${tableName}")`,
        async run(helpers) {
            const nextHour = luxon.DateTime.now().plus({ hours: 1 }).startOf("hour");
            // Header cells and row cells are both rendered once per column, in the same order.
            const columnIndex = [...document.querySelectorAll(".o_gantt_header_cell")].findIndex(
                (cell) => cell.title === nextHour.toFormat("DDDD, t")
            );
            const rowId = helpers.anchor.dataset.rowId;
            const cell = [...document.querySelectorAll(".o_gantt_cell")].filter(
                (cell) => cell.dataset.rowId === rowId
            )[columnIndex];
            if (!cell) {
                throw new Error(
                    `No gantt cell for ${tableName} at ${nextHour.toFormat("DDDD, t")}`
                );
            }
            await helpers.click(cell);
        },
    };
}

export function checkInFromPopover() {
    return {
        content: "Click on Check In in the booking popover",
        trigger:
            ".o_appointment_calendar_event_popover .o_appointment_calendar_popover_status_btn:contains('Check In')",
        run: "click",
    };
}

export function editFromPopover() {
    return {
        content: "Click on Edit in the booking popover",
        trigger: ".o_appointment_calendar_event_popover .o_appointment_calendar_popover_edit",
        run: "click",
    };
}

export function setStatusFromForm(statusLabel) {
    return [
        {
            content: `Click on ${statusLabel} in the booking form`,
            trigger: `.o_dialog .o_appointment_status_btns_container button:contains("${statusLabel}")`,
            run: "click",
        },
        {
            content: "Wait for the booking form to be saved and closed",
            trigger: "body:not(:has(.o_dialog))",
        },
    ];
}

export function checkAssignedNotification(tableNames) {
    return {
        content: `Check the table assignment notification for ${tableNames.join(", ")}`,
        trigger:
            `.o_notification:has(.o_notification_bar.bg-success):contains("Assigned to")` +
            tableNames.map((tableName) => `:contains("${tableName}")`).join(""),
    };
}

/**
 * Freeze luxon's clock (DateTime.now and DateTime.local) while running the given steps.
 * Chrome.withTimeFreeze only patches DateTime.now, while the gantt focus date uses DateTime.local.
 */
export function withLuxonTimeFreeze(millis, steps) {
    let originalNow;
    return [
        {
            content: `Freeze luxon time to ${millis}`,
            trigger: "body",
            run: () => {
                originalNow = luxon.Settings.now;
                luxon.Settings.now = () => millis;
            },
        },
        ...steps.flat(),
        {
            content: "Unfreeze luxon time",
            trigger: "body",
            run: () => {
                luxon.Settings.now = originalNow;
            },
        },
    ];
}

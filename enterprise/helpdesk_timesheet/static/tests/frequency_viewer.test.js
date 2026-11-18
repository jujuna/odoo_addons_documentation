import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import { getService, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { WebClient } from "@web/webclient/webclient";

import { defineHelpdeskTimesheetModels } from "./helpdesk_timesheet_models";

describe.current.tags("desktop");
defineHelpdeskTimesheetModels();

test("the frequency viewer resolves the ticket of a learnt match", async () => {
    localStorage.clear();
    localStorage.setItem(
        "aw_timesheet_suggestion_project_matching",
        JSON.stringify([
            {
                suggestion: "Printer - Odoo",
                data: { helpdesk_ticket_id: 2 },
                datetime: "2026-01-01T10:00:00.000Z",
            },
        ])
    );

    await mountWithCleanup(WebClient);
    await getService("action").doAction({ type: "ir.actions.client", tag: "frequency_viewer" });

    expect(".o_data_row").toHaveCount(1);
    expect(queryAllTexts(".o_data_row .o_data_cell")).toInclude("Ticket 2");
});

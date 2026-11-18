import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame } from "@odoo/hoot-mock";
import { contains, getService, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { WebClient } from "@web/webclient/webclient";
import { defineTimesheetModels } from "@timesheet_grid/../tests/hr_timesheet_models";
import { setupTimesheetEnvironment } from "@timesheet_grid/../tests/timesheet_timer_helpers";

describe.current.tags("desktop");
defineTimesheetModels();

async function openAssistant() {
    await getService("action").doAction({
        type: "ir.actions.client",
        tag: "hr_timesheet_activitywatch_action",
    });
}

const env = setupTimesheetEnvironment();
let pyEnv;

beforeEach(async () => {
    ({ pyEnv } = env);
    await mountWithCleanup(WebClient);
    localStorage.clear();
});

test("Timesheet Assistant: AI summary prompt includes the category of each activity", async () => {
    const today = luxon.DateTime.now().startOf("day").plus({ hours: 10 });

    // Both rules share the same template, so their descriptions get merged into a single
    // "Working on ..." line: only the category tells the AI what kind of work each one was.
    pyEnv["aw.rule"].create([
        {
            name: "GitHub",
            regex: "(.*) · Pull Request #\\d+ · .*\\|https:\\/\\/github\\.com",
            type: "development",
            template: "Working on $1",
            always_active: false,
        },
        {
            name: "Google Slides",
            regex: "(.*) - Google Slides\\|https:\\/\\/docs\\.google\\.com\\/presentation",
            type: "presentation",
            template: "Working on $1",
            always_active: false,
        },
    ]);

    onRpc("account.analytic.line", "get_assistant_data", ({ parent }) => ({
        ...parent(),
        is_agent_available: true,
    }));
    onRpc("http://localhost:5600/api/0/buckets/", () => ({
        web: { type: "web.tab.current", id: "web", client: "aw-watcher-web" },
    }));
    onRpc("http://localhost:5600/api/0/buckets/web/events", () => [
        {
            timestamp: today.toISO(),
            duration: 1800,
            data: {
                title: "[FIX] ai_timesheet_grid: add category · Pull Request #1 · odoo/enterprise",
                url: "https://github.com/odoo/enterprise/pull/1",
            },
        },
        {
            timestamp: today.plus({ minutes: 30 }).toISO(),
            duration: 1800,
            data: {
                title: "Assistant timesheet - Google Slides",
                url: "https://docs.google.com/presentation/d/1",
            },
        },
    ]);
    onRpc("/ai/get_direct_response", async (request) => {
        const { params } = await request.json();
        expect.step("get_direct_response");
        expect(params.interface_key).toBe("timesheet_assistant_ai");
        expect(params.prompt).toInclude(
            "- [development] Working on [FIX] ai_timesheet_grid: add category\n" +
                "- [presentation] Working on Assistant timesheet"
        );
        return "Fixed the AI timesheet category and prepared the Assistant presentation";
    });

    await openAssistant();
    expect(".o_suggestions_suggestion").toHaveCount(2);

    await contains(".o_suggestions_suggestion:eq(0)").click();
    await contains(".o_suggestions_suggestion:eq(1)").click();
    await animationFrame();
    expect(".o_activitywatch_sync_timesheet_creation_form .field-description textarea").toHaveValue(
        "Working on [FIX] ai_timesheet_grid: add category and Assistant timesheet"
    );
    expect.verifySteps([]);

    await advanceTime(800);
    await animationFrame();
    expect.verifySteps(["get_direct_response"]);
    expect(".o_activitywatch_sync_timesheet_creation_form .field-description textarea").toHaveValue(
        "Fixed the AI timesheet category and prepared the Assistant presentation"
    );
});

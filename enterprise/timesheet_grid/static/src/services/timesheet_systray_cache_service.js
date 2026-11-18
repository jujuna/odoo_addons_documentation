import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { registry } from "@web/core/registry";
import { proxy } from "@odoo/owl";

export const timesheetSystrayCacheService = {
    dependencies: ["lazy_session"],

    start(env, { lazy_session: lazySession }) {
        let fetchPromise = null;
        let preFilledFormValue = null;

        const state = proxy({
            timesheets: [],
            pre_filled_form: {},
            loaded: false,
            employee: false,
        });

        lazySession.getValue("timesheets_today", (value) => {
            if (value) {
                state.timesheets = value.records;
            }
            state.loaded = true;
        });
        lazySession.getValue("timesheet_systray_employee_data", (value) => {
            state.employee = value;
        });

        return {
            get state() {
                return state;
            },

            async fetchTimesheets() {
                if (fetchPromise) {
                    return fetchPromise;
                }

                fetchPromise = (async () => {
                    try {
                        const data = await rpc("/timesheet_grid/timesheet_systray_user_data", {
                            context: user.context,
                        });
                        const newRecords = data.timesheets?.records || [];

                        if (JSON.stringify(state.timesheets) !== JSON.stringify(newRecords)) {
                            state.timesheets = newRecords;
                        }
                        if (data.employee) {
                            state.employee = data.employee;
                        }
                        state.loaded = true;
                    } finally {
                        fetchPromise = null;
                    }
                })();

                return fetchPromise;
            },

            fetchPreFilledForm() {
                preFilledFormValue = localStorage.getItem("timesheet.preFilledForm");
                state.pre_filled_form = JSON.parse(preFilledFormValue || "{}");
                return state.pre_filled_form;
            },

            /**
             * Drops the stored task/ticket the server refused to prefill, unless
             * another one has been visited since it was read.
             */
            discardStalePreFilledForm() {
                if (localStorage.getItem("timesheet.preFilledForm") === preFilledFormValue) {
                    localStorage.removeItem("timesheet.preFilledForm");
                }
            },

            clearPreFilledForm() {
                localStorage.removeItem("timesheet.preFilledForm");
                state.pre_filled_form = {};
            },

            addTimesheet(timesheet) {
                state.timesheets.unshift(timesheet);
            },

            updateTimesheet(timesheet) {
                const index = state.timesheets.findIndex((ts) => ts.id === timesheet.id);
                if (index !== -1) {
                    state.timesheets[index] = timesheet;
                }
            },

            removeTimesheet(timesheetId) {
                state.timesheets = state.timesheets.filter((ts) => ts.id !== timesheetId);
            },
        };
    },
};

registry.category("services").add("timesheet_systray_cache", timesheetSystrayCacheService);

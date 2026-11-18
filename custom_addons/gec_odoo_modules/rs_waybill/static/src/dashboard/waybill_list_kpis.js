/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useBus, useService } from "@web/core/utils/hooks";
import { onWillStart, proxy, status } from "@odoo/owl";
import { serializeDateTime } from "@web/core/l10n/dates";

const { DateTime } = luxon;


// KPI card key -> the search-view filter (by its XML `name`) it toggles.
// The Total card has no entry: clicking it just clears the state filters.
const KPI_FILTERS = {
    active: "filter_active",
    completed: "filter_completed",
    cancelled: "filter_cancelled",
};

class WaybillListKpisController extends ListController {
    static template = "rs_waybill.WaybillListKpisView";
    setup() {
        super.setup();
        this.orm = useService("orm")

        this.kpis = proxy({
            total: 0,        totalToday: 0,
            active: 0,       activeToday: 0,
            cancelled: 0,    cancelledToday: 0,
            completed: 0,    completedToday: 0,
            activeKey: "total",   // which card is currently selected (highlight)
        });

        onWillStart(() => {
            this.refreshKpisInBackground();
        });

        // Refresh the KPIs after every model load (filter, sort, page). Listening on the bus, not wrapping model.load,
        // keeps the RPCs out of the list's render path, so a rejection cannot take the list down.
        useBus(this.model.bus, "update", () => this.refreshKpisInBackground());
    }

    // Fire-and-forget: never blocks or rejects into the caller's render. Serialised: "update" can fire several times
    // per interaction, so a refresh requested while one is in flight re-runs once at the end.
    refreshKpisInBackground() {
        if (this._kpiLoading) {
            this._kpiStale = true;
            return;
        }
        this._kpiLoading = true;
        (async () => {
            try {
                do {
                    this._kpiStale = false;
                    await this.refreshKpis();
                } while (this._kpiStale && status(this) !== "destroyed");
            } catch (error) {
                console.warn("rs_waybill: KPI refresh failed", error);
            } finally {
                this._kpiLoading = false;
            }
        })();
    }

    async refreshKpis() {
        // model.config.domain is the FULL domain: neutralize the state clauses these cards manage (else Active zeroes
        // the others): swap leaves for [1, "=", 1], never remove them: a removed leaf orphans a prefix operator.
        const STATE_VALUES = new Set(["active", "cancelled", "completed"]);
        const domain = (this.model.config?.domain || []).map((clause) => {
            if (
                Array.isArray(clause) &&
                clause[0] === "state" &&
                clause[1] === "=" &&
                STATE_VALUES.has(clause[2])
            ) {
                return [1, "=", 1];   // identity replacement, neutralizes the filter
            }
            return clause;
        });

        // Start of today in the user's timezone, serialized to the UTC string
        // the ORM domain expects (the date fields are stored UTC Datetimes).
        const todayStart = serializeDateTime(DateTime.local().startOf("day"));

        const {
            total, active, cancelled, completed,
            totalToday, activeToday, cancelledToday, completedToday,
        } = await this.orm.call("rs.waybill", "rs_list_kpis", [domain, todayStart]);
        const sm = this.env.searchModel;
        let activeKey = "total";
        for (const [key, name] of Object.entries(KPI_FILTERS)) {
            const item = sm.getSearchItems((i) => i.name === name)[0];
            if (item && sm.query.some((q) => q.searchItemId === item.id)) {
                activeKey = key;
                break;
            }
        }

        // The refresh is fire-and-forget, so the component may be gone when the RPCs land.
        if (status(this) === "destroyed") {
            return;
        }
        Object.assign(this.kpis, {
            total, active, cancelled, completed,
            totalToday, activeToday, cancelledToday, completedToday,
            activeKey,
        });
    }

    onKpiClick(key) {
        const sm = this.env.searchModel;
        const findItem = (name) => sm.getSearchItems((i) => i.name === name)[0];
        const isActive = (id) => sm.query.some((q) => q.searchItemId === id);

        const clickedItem = KPI_FILTERS[key] ? findItem(KPI_FILTERS[key]) : null;
        const clickedWasActive = clickedItem ? isActive(clickedItem.id) : false;

        for (const name of Object.values(KPI_FILTERS)) {
            const item = findItem(name);
            if (item && isActive(item.id)) {
                sm.toggleSearchItem(item.id);
            }
        }
        if (clickedItem && !clickedWasActive) {
            sm.toggleSearchItem(clickedItem.id);
        }
    }
}

registry.category("views").add("rs_waybill_list_kpis", {...listView, Controller: WaybillListKpisController,});

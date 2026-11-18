import { describe, expect, test } from "@odoo/hoot";
import { registries } from "@odoo/o-spreadsheet";
import { ALL_PERIODS } from "@spreadsheet_edition/assets/pivot_view/pivot_view";

const { pivotRegistry } = registries;

describe.current.tags("headless");

test("ALL_PERIODS covers every granularity an Odoo pivot can be grouped by", function () {
    // datetimeGranularities is the superset: dateGranularities + hour/minute/second
    const granularities = pivotRegistry.get("ODOO").datetimeGranularities;
    expect(granularities.length).toBeGreaterThan(0);

    const missing = granularities.filter((granularity) => !(granularity in ALL_PERIODS));
    expect(missing).toEqual([], {
        message: `Missing Odoo pivot granularities in ALL_PERIODS: ${JSON.stringify(missing)}`,
    });
});

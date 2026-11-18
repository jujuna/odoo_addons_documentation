import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate } from "@web/core/l10n/dates";
import { useChart } from "@web/core/utils/chart_hook";
import { axis, baseOptions, chartTheme } from "../../utils/chart_utils";

export class YearPaceChart extends Component {
    static template = "hotel_rms.YearPaceChart";
    props = useProps({ days: t.array(t.object()) });
    chart = useChart(() => this.getConfig());

    /** Rooms on the books for each night now, against the same weekday nights a year ago on the same day. */
    getConfig() {
        const theme = chartTheme();
        const options = baseOptions(theme);
        const series = (key) => this.props.days.map((day) => ({ x: day.date, y: day[key] }));
        const line = { pointRadius: 0, pointHoverRadius: 4, tension: 0 };
        return {
            type: "line",
            data: {
                datasets: [
                    {
                        ...line,
                        label: _t("Booked now"),
                        data: series("booked"),
                        borderColor: theme.accent,
                        backgroundColor: theme.accentSoft,
                        fill: "origin",
                        borderWidth: 2,
                        pointStyle: "rectRounded",
                    },
                    {
                        ...line,
                        label: _t("Same nights last year"),
                        data: series("last_year"),
                        borderColor: theme.muted,
                        borderDash: [4, 3],
                        borderWidth: 1.5,
                        pointStyle: "line",
                    },
                ],
            },
            options: {
                ...options,
                plugins: {
                    ...options.plugins,
                    tooltip: {
                        ...options.plugins.tooltip,
                        callbacks: {
                            title: (items) => deserializeDate(this.props.days[items[0].dataIndex].date).toFormat("ccc d MMM"),
                            label: (item) => _t("%(series)s: %(rooms)s rooms", { series: item.dataset.label, rooms: item.parsed.y }),
                        },
                    },
                },
                scales: {
                    x: {
                        ...axis(theme, { grid: { display: false } }),
                        type: "time",
                        time: { unit: "week", displayFormats: { week: "d MMM" } },
                    },
                    y: { ...axis(theme), beginAtZero: true, ticks: { ...axis(theme).ticks, precision: 0 } },
                },
            },
        };
    }
}

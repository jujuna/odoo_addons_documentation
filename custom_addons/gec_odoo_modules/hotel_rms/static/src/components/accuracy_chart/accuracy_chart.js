import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate } from "@web/core/l10n/dates";
import { useChart } from "@web/core/utils/chart_hook";
import { axis, baseOptions, chartTheme } from "../../utils/chart_utils";

export class AccuracyChart extends Component {
    static template = "hotel_rms.AccuracyChart";
    props = useProps({ weeks: t.array(t.object()), leads: t.array(t.number()) });
    chart = useChart(() => this.getConfig());

    get labels() {
        return [...new Set(this.props.weeks.map((row) => row.week))].sort();
    }

    /** Rooms off per week, one line for each number of days ahead: the nearest in the accent, the others muted. */
    getConfig() {
        const theme = chartTheme();
        const options = baseOptions(theme);
        const colors = [theme.accent, theme.muted];
        const rows = (lead) => this.props.weeks.filter((row) => row.lead_days === lead);
        return {
            type: "line",
            data: {
                labels: this.labels,
                datasets: this.props.leads.map((lead, index) => ({
                    label: _t("%s days ahead", lead),
                    data: this.labels.map((week) => rows(lead).find((row) => row.week === week)?.rooms ?? null),
                    borderColor: colors[index],
                    backgroundColor: colors[index],
                    borderWidth: 2,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    tension: 0.25,
                    pointStyle: "rectRounded",
                })),
            },
            options: {
                ...options,
                plugins: {
                    ...options.plugins,
                    tooltip: {
                        ...options.plugins.tooltip,
                        callbacks: {
                            title: (items) => _t("Week of %s", deserializeDate(this.labels[items[0].dataIndex]).toFormat("d MMM")),
                            label: (item) =>
                                _t("%(days)s days ahead: %(rooms)s rooms off", {
                                    days: this.props.leads[item.datasetIndex],
                                    rooms: item.parsed.y.toFixed(1),
                                }),
                        },
                    },
                },
                scales: {
                    x: {
                        ...axis(theme, { grid: { display: false } }),
                        ticks: {
                            ...axis(theme).ticks,
                            callback: (value) => deserializeDate(this.labels[value]).toFormat("d MMM"),
                        },
                    },
                    y: { ...axis(theme), beginAtZero: true },
                },
            },
        };
    }
}

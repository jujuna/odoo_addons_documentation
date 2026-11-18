import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useChart } from "@web/core/utils/chart_hook";
import { axis, baseOptions, chartTheme } from "../../utils/chart_utils";

export class PaceChart extends Component {
    static template = "hotel_rms.PaceChart";
    props = useProps({
        points: t.array(t.object({ days_before: t.number(), booked: t.number(), usual: t.number() })),
    });
    chart = useChart(() => this.getConfig());

    getConfig() {
        const theme = chartTheme();
        const options = baseOptions(theme);
        const series = (key) => this.props.points.map((point) => ({ x: point.days_before, y: point[key] }));
        const datasets = [
            { label: _t("Booked"), data: series("booked"), borderColor: theme.accent, backgroundColor: theme.accent },
        ];
        if (this.props.points.some((point) => point.usual)) {
            datasets.push({
                label: _t("Usual"),
                data: series("usual"),
                borderColor: theme.muted,
                backgroundColor: theme.muted,
                borderDash: [4, 3],
                borderWidth: 1.5,
            });
        }
        return {
            type: "line",
            data: { datasets: datasets.map((dataset) => ({ pointRadius: 2, tension: 0.3, ...dataset })) },
            options: {
                ...options,
                plugins: {
                    ...options.plugins,
                    tooltip: {
                        ...options.plugins.tooltip,
                        callbacks: { title: (items) => _t("%s days before", items[0].parsed.x) },
                    },
                },
                scales: {
                    x: {
                        ...axis(theme, { grid: { display: false } }),
                        type: "linear",
                        reverse: true,
                        ticks: { ...axis(theme).ticks, callback: (value) => _t("%s d", value), maxTicksLimit: 5 },
                    },
                    y: { ...axis(theme), beginAtZero: true, ticks: { ...axis(theme).ticks, precision: 0, maxTicksLimit: 4 } },
                },
            },
        };
    }
}

import { Component, signal, t, useListener, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate } from "@web/core/l10n/dates";
import { useChart } from "@web/core/utils/chart_hook";
import { axis, baseOptions, chartTheme } from "../../utils/chart_utils";
import { formatPrice } from "../../utils/pricing_utils";

const DAY = 86400000;
const AXIS_WIDTH = 44;
const PIN_SIZE = 5;
const PIN_GAP = 6;

export class NightsChart extends Component {
    static template = "hotel_rms.NightsChart";
    props = useProps({
        days: t.array(t.object()),
        events: t.array(t.object()).optional(() => []),
        currency: t.object(),
        onNightClick: t.function().optional(() => () => {}),
    });
    root = signal.ref();
    chart = useChart(() => this.getConfig());
    strip = useChart(() => this.getStripConfig());

    setup() {
        this.hover = null;
        this.drag = null;
        this.tapped = null;
        useListener(() => this.root(), "pointerdown", (ev) => this.onDown(ev));
        useListener(window, "pointermove", (ev) => this.onMove(ev));
        useListener(window, "pointerup", () => this.onUp());
        useListener(window, "pointercancel", () => (this.drag = null));
    }

    /** The nights as times and weekend flags, read again each time a chart is built from new props. */
    prepare() {
        this.times = this.props.days.map((day) => deserializeDate(day.date).toMillis());
        this.weekends = this.props.days.map((day) => deserializeDate(day.date).weekday >= 6);
    }

    get hasPrices() {
        return this.props.days.some((day) => day.price);
    }

    eventNames(day) {
        return this.props.events
            .filter((event) => day.date >= event.date_from && day.date <= event.date_to)
            .map((event) => event.name);
    }

    tooltipLines(day) {
        const lines = [
            _t("Already booked %(booked)s of %(capacity)s rooms", { booked: day.booked, capacity: day.capacity }),
        ];
        if (day.forecast !== null) {
            lines.push(
                _t("Forecast %(rooms)s rooms, %(share)s", {
                    rooms: Math.round(day.forecast),
                    share: `${day.capacity ? Math.round((day.forecast / day.capacity) * 100) : 0}%`,
                })
            );
        }
        if (day.price) {
            lines.push(_t("Recommended price %s", formatPrice(day.price, this.props.currency)));
        }
        return [...lines, ...this.eventNames(day)];
    }

    tooltip(theme, options) {
        const { days } = this.props;
        return {
            ...options.plugins.tooltip,
            displayColors: false,
            filter: (item) => item.datasetIndex === 0,
            callbacks: {
                title: (items) => deserializeDate(days[items[0].dataIndex].date).toFormat("ccc d MMM"),
                label: (item) => this.tooltipLines(days[item.dataIndex]),
            },
        };
    }

    nightIndex(chart, x) {
        const index = Math.round((chart.scales.x.getValueForPixel(x) - this.times[0]) / DAY);
        return Math.max(0, Math.min(this.times.length - 1, index));
    }

    /** The chart under the pointer when it is inside the plot area: the legend and the axes do not count. */
    plotAt(ev) {
        const chart = [this.chart, this.strip].map((item) => item.instance()).find((item) => item?.canvas === ev.target);
        if (!chart) {
            return null;
        }
        const rect = chart.canvas.getBoundingClientRect();
        const { left, right, top, bottom } = chart.chartArea;
        const [x, y] = [ev.clientX - rect.left, ev.clientY - rect.top];
        return x >= left && x <= right && y >= top && y <= bottom ? { chart, x } : null;
    }

    redraw() {
        [this.chart, this.strip].forEach((item) => item.instance()?.draw());
    }

    onHover(event, chart) {
        const { left, right, top, bottom } = chart.chartArea;
        const inside = event.type !== "mouseout" && event.x >= left && event.x <= right && event.y >= top && event.y <= bottom;
        this.hover = inside ? this.nightIndex(chart, event.x) : null;
        event.native.target.style.cursor = inside ? "pointer" : "";
        this.redraw();
    }

    onDown(ev) {
        const plot = ev.button ? null : this.plotAt(ev);
        if (plot) {
            const index = this.nightIndex(plot.chart, plot.x);
            this.drag = {
                from: index,
                to: index,
                chart: plot.chart,
                left: plot.chart.canvas.getBoundingClientRect().left,
                touch: ev.pointerType === "touch",
            };
        }
    }

    onMove(ev) {
        if (this.drag) {
            this.drag.to = this.nightIndex(this.drag.chart, ev.clientX - this.drag.left);
            this.redraw();
        }
    }

    /** On touch, the first tap on a night only shows its tooltip; the second opens the calendar. */
    onUp() {
        if (this.drag) {
            const { from, to, touch } = this.drag;
            this.drag = null;
            this.redraw();
            if (touch && from === to && this.tapped !== from) {
                this.tapped = from;
                return;
            }
            this.tapped = null;
            this.props.onNightClick(this.props.days[Math.min(from, to)].date);
        }
    }

    xScale(theme, extra = {}) {
        return {
            ...axis(theme, { grid: { display: false } }),
            type: "time",
            min: this.times[0],
            max: this.times.at(-1),
            time: { unit: "week", displayFormats: { week: "d MMM" } },
            ...extra,
        };
    }

    yScale(theme, extra = {}) {
        return { ...axis(theme), afterFit: (scale) => (scale.width = AXIS_WIDTH), ...extra };
    }

    plugins(theme, withPins) {
        const pixel = (chart, index) => chart.scales.x.getPixelForValue(this.times[index]);
        const half = (chart) => (this.times.length > 1 ? (pixel(chart, 1) - pixel(chart, 0)) / 2 : 12);
        const band = (chart, from, to, color) => {
            const { left, right, top, bottom } = chart.chartArea;
            const start = Math.max(left, pixel(chart, from) - half(chart));
            const end = Math.min(right, pixel(chart, to) + half(chart));
            chart.ctx.fillStyle = color;
            chart.ctx.fillRect(start, top, end - start, bottom - top);
        };
        return [
            {
                id: "rmsBands",
                beforeDatasetsDraw: (chart) => {
                    chart.ctx.save();
                    this.weekends.forEach((weekend, index) => weekend && band(chart, index, index, theme.weekend));
                    chart.ctx.restore();
                },
                afterDatasetsDraw: (chart) => {
                    const { ctx, chartArea } = chart;
                    ctx.save();
                    if (this.drag && this.drag.from !== this.drag.to) {
                        band(chart, Math.min(this.drag.from, this.drag.to), Math.max(this.drag.from, this.drag.to), theme.accentMid);
                    }
                    if (this.hover !== null) {
                        const x = pixel(chart, this.hover);
                        ctx.strokeStyle = theme.muted;
                        ctx.lineWidth = 1;
                        ctx.beginPath();
                        ctx.moveTo(x, chartArea.top);
                        ctx.lineTo(x, chartArea.bottom);
                        ctx.stroke();
                    }
                    if (withPins) {
                        this.drawPins(chart, theme, pixel);
                    }
                    ctx.restore();
                },
            },
        ];
    }

    drawPins(chart, theme, pixel) {
        const { ctx, chartArea } = chart;
        const { days } = this.props;
        const base = chartArea.top - PIN_GAP;
        let free = chartArea.left;
        ctx.font = `${theme.font.size - 1}px ${theme.font.family}`;
        ctx.textBaseline = "middle";
        for (const event of this.props.events) {
            const index = days.findIndex((day) => day.date >= event.date_from && day.date <= event.date_to);
            if (index < 0) {
                continue;
            }
            const x = pixel(chart, index);
            ctx.fillStyle = theme.accent;
            ctx.beginPath();
            ctx.moveTo(x - PIN_SIZE, base - PIN_SIZE * 1.6);
            ctx.lineTo(x + PIN_SIZE, base - PIN_SIZE * 1.6);
            ctx.lineTo(x, base);
            ctx.fill();
            const width = ctx.measureText(event.name).width;
            const left = x + PIN_SIZE + 4;
            if (x >= free && left + width <= chart.width) {
                ctx.fillStyle = theme.muted;
                ctx.fillText(event.name, left, base - PIN_SIZE * 0.8);
                free = left + width + PIN_GAP;
            }
        }
    }

    getConfig() {
        this.prepare();
        const theme = chartTheme();
        const { days } = this.props;
        const options = baseOptions(theme);
        const line = { pointRadius: 0, pointHoverRadius: 4, tension: 0 };
        const series = (key) => days.map((day) => ({ x: day.date, y: day[key] }));
        return {
            type: "line",
            data: {
                datasets: [
                    {
                        ...line,
                        label: _t("Already booked"),
                        data: series("booked"),
                        fill: "origin",
                        backgroundColor: theme.accent,
                        borderColor: theme.surface,
                        borderWidth: 2,
                        stack: "rooms",
                        pointStyle: "rectRounded",
                    },
                    {
                        ...line,
                        label: _t("Expected to book"),
                        data: days.map((day) => ({
                            x: day.date,
                            y: day.forecast === null ? null : Math.max(0, day.forecast - day.booked),
                        })),
                        fill: "-1",
                        backgroundColor: theme.accentMid,
                        borderColor: "transparent",
                        stack: "rooms",
                        pointStyle: "rectRounded",
                    },
                    {
                        ...line,
                        label: _t("All rooms"),
                        data: series("capacity"),
                        borderColor: theme.muted,
                        borderDash: [4, 3],
                        borderWidth: 1,
                        stack: "capacity",
                        pointStyle: "line",
                    },
                ],
            },
            options: {
                ...options,
                layout: { padding: { top: 22, right: 24 } },
                onHover: (event, _active, chart) => this.onHover(event, chart),
                plugins: { ...options.plugins, tooltip: this.tooltip(theme, options) },
                scales: {
                    x: this.xScale(theme, { ticks: { display: false } }),
                    y: this.yScale(theme, { stacked: true, beginAtZero: true, ticks: { ...axis(theme).ticks, precision: 0 } }),
                },
            },
            plugins: this.plugins(theme, true),
        };
    }

    /** The recommended price of the reference room on its own small chart, under the same nights. */
    getStripConfig() {
        this.prepare();
        const theme = chartTheme();
        const { days } = this.props;
        const options = baseOptions(theme);
        return {
            type: "line",
            data: {
                datasets: [
                    {
                        label: _t("Recommended price"),
                        data: days.map((day) => ({ x: day.date, y: day.price })),
                        borderColor: theme.text,
                        backgroundColor: theme.text,
                        borderWidth: 2,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        tension: 0,
                    },
                ],
            },
            options: {
                ...options,
                layout: { padding: { top: 6, right: 24 } },
                onHover: (event, _active, chart) => this.onHover(event, chart),
                plugins: { legend: { display: false }, tooltip: this.tooltip(theme, options) },
                scales: {
                    x: this.xScale(theme),
                    y: this.yScale(theme, {
                        grace: "15%",
                        ticks: { ...axis(theme).ticks, maxTicksLimit: 3, callback: (value) => Math.round(value) },
                    }),
                },
            },
            plugins: this.plugins(theme, false),
        };
    }
}

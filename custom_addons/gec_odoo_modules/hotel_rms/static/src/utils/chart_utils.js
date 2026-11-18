import { browser } from "@web/core/browser/browser";

const ANIMATION = { duration: 400, easing: "easeOutQuart" };

export function reducedMotion() {
    return browser.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Read when a chart is built, so dark mode is followed. */
export function chartTheme() {
    const root = getComputedStyle(document.documentElement);
    const body = getComputedStyle(document.body);
    const color = (name) => root.getPropertyValue(`--rms-${name}`).trim();
    return {
        accent: color("accent"),
        accentMid: color("accent-mid"),
        accentSoft: color("accent-soft"),
        success: color("success"),
        info: color("info"),
        muted: color("muted"),
        border: color("border"),
        subtle: color("subtle"),
        surface: color("surface"),
        weekend: color("weekend"),
        text: body.color,
        font: { family: body.fontFamily, size: 12 },
    };
}

export function baseOptions(theme) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: reducedMotion() ? false : ANIMATION,
        interaction: { mode: "index", intersect: false },
        plugins: {
            legend: {
                position: "bottom",
                labels: { usePointStyle: true, boxWidth: 8, boxPadding: 6, padding: 16, color: theme.muted, font: theme.font },
            },
            tooltip: {
                backgroundColor: theme.surface,
                titleColor: theme.text,
                bodyColor: theme.text,
                borderColor: theme.border,
                borderWidth: 1,
                padding: 8,
                usePointStyle: true,
                titleFont: theme.font,
                bodyFont: theme.font,
            },
        },
    };
}

export function axis(theme, extra = {}) {
    return {
        border: { display: false },
        grid: { color: theme.subtle, drawTicks: false },
        ticks: { color: theme.muted, font: theme.font, padding: 8 },
        ...extra,
    };
}

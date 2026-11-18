import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { getCurrency } from "@web/core/currency";
import { formatFloat } from "@web/core/utils/numbers";

export const QUICK_PCTS = [-10, -5, 5, 10];
export const BULK_PCTS = [-5, 5];

export const STATE_LABELS = {
    pending: _t("Needs decision"),
    hold: _t("No change suggested"),
    accepted: _t("Accepted"),
    edited: _t("Own price"),
    rejected: _t("Rejected"),
};

export const DONE_MESSAGES = {
    action_accept: [_t("Price accepted"), _t("%s prices accepted")],
    action_use_my_price: [_t("Your price is published"), _t("%s prices updated")],
    action_quick_price: [_t("Your price is published"), _t("%s prices updated")],
    action_reject: [_t("Price rejected"), _t("%s prices rejected")],
    action_undo: [_t("Decision undone"), _t("%s decisions undone")],
    action_lock: [_t("Price locked"), _t("%s prices locked")],
    action_unlock: [_t("Price unlocked"), _t("%s prices unlocked")],
};
export const UNDOABLE = ["action_accept", "action_use_my_price", "action_quick_price", "action_reject"];

/** Decimals of the row's currency as { decimals } (2 when unknown), the shape the price components take. */
export function recordCurrency(record) {
    return { decimals: getCurrency(record.data.currency_id?.id)?.digits?.[1] ?? 2 };
}

export function formatPrice(value, currency) {
    return value ? formatFloat(value, { digits: [69, currency.decimals] }) : "—";
}

export function daysLeftText(days) {
    const left = Math.max(0, Math.round(days));
    return left === 0 ? _t("Today") : left === 1 ? _t("Tomorrow") : _t("%s days left", left);
}

export function formatPct(pct) {
    return `${pct > 0 ? "+" : ""}${pct}%`;
}

export function shownPrice(cell) {
    return cell.state === "edited" ? cell.published : cell.recommended;
}

export function clampPct(value) {
    return Math.max(0, Math.min(value || 0, 100));
}

export const LEVEL_STEPS = 5;

/** Null when there is nothing to show: a zero value or an empty range. */
export function levelPct(value, min, max) {
    if (!value || !(max > min)) {
        return null;
    }
    return clampPct(((value - min) / (max - min)) * 100);
}

/** Nearest of the five steps 0, 25, 50, 75 and 100. */
export function levelStep(pct) {
    return Math.round(pct / (100 / (LEVEL_STEPS - 1)));
}

export function loadSetting(key, fallback) {
    try {
        return browser.localStorage.getItem(key) ?? fallback;
    } catch {
        return fallback;
    }
}

export function saveSetting(key, value) {
    try {
        browser.localStorage.setItem(key, value);
    } catch {
        // storage is not available: the choice is forgotten with the page
    }
}

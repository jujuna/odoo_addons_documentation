/** @odoo-module **/
/** Georgian weekday and month names, and the test whether the browser can supply them itself.
 * "small-icu" Chromium resolves ka-GE to en-US; consumers use ours only if the language is Georgian and Intl fails. */
import { user } from "@web/core/user";

// Luxon/ISO weekday order, Monday first
export const WEEKDAY_SHORT = ["ორშ", "სამ", "ოთხ", "ხუთ", "პარ", "შაბ", "კვი"];
export const WEEKDAY_LONG = [
    "ორშაბათი", "სამშაბათი", "ოთხშაბათი", "ხუთშაბათი", "პარასკევი", "შაბათი", "კვირა",
];
export const WEEKDAY_NARROW = ["ორ", "სა", "ოთ", "ხუ", "პა", "შა", "კვ"];
export const MONTH_LONG = [
    "იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი",
    "ივლისი", "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი",
];
export const MONTH_SHORT = [
    "იან", "თებ", "მარ", "აპრ", "მაი", "ივნ",
    "ივლ", "აგვ", "სექ", "ოქტ", "ნოე", "დეკ",
];

let needsPatch = null;

/** True when the user is on Georgian and the browser cannot resolve it itself. */
export function georgianNamesMissing() {
    if (needsPatch === null) {
        const isGeorgian = (user.lang || "").toLowerCase().startsWith("ka");
        let intlWorks = false;
        if (isGeorgian) {
            try {
                intlWorks = new Intl.DateTimeFormat("ka-GE")
                    .resolvedOptions()
                    .locale.toLowerCase()
                    .startsWith("ka");
            } catch {
                intlWorks = false;
            }
        }
        needsPatch = isGeorgian && !intlWorks;
    }
    return needsPatch;
}

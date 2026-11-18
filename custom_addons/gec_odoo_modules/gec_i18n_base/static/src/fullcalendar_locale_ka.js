/** @odoo-module ignore */
// "ignore": must run as a plain script; the transpiler would register this file as an ES module without executing it.
/* Georgian (ka) locale for FullCalendar, which bundles none and falls back to English.
 * Loaded into `web.fullcalendar_lib` after locales-all.global.js, which defines FullCalendar.globalLocales. */
(function () {
    "use strict";

    const fc = window.FullCalendar;
    if (!fc || !Array.isArray(fc.globalLocales)) {
        // FullCalendar missing or changed: stay silent instead of breaking the calendar.
        return;
    }
    if (fc.globalLocales.some((locale) => locale && locale.code === "ka")) {
        return; // already registered, or upstream shipped one
    }

    const georgian = {
        code: "ka",
        week: {
            dow: 1, // week starts on Monday
            doy: 4, // ISO-8601: the week containing Jan 4th is week 1
        },
        direction: "ltr",
        buttonText: {
            prev: "წინა",
            next: "შემდეგი",
            today: "დღეს",
            year: "წელი",
            month: "თვე",
            week: "კვირა",
            day: "დღე",
            list: "დღის წესრიგი",
        },
        weekText: "კვ",
        weekTextLong: "კვირა",
        allDayText: "მთელი დღე",
        moreLinkText: (n) => `+ კიდევ ${n}`,
        noEventsText: "ღონისძიებები არ არის",
    };

    // Odoo passes `ka-GE`; register both tags so we do not depend on FullCalendar shortening it.
    fc.globalLocales.push(georgian);
    fc.globalLocales.push({ ...georgian, code: "ka-ge" });

    if (typeof console !== "undefined" && console.debug) {
        console.debug("[gec] Georgian FullCalendar locale registered");
    }
})();

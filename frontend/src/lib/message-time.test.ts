import { describe, expect, it } from "vitest";
import {
  dayNumber,
  daysAgo,
  formatDayLabel,
  formatFull,
  formatStamp,
  formatTime,
  isoInstant,
  startsNewDay,
} from "./message-time";

const NY = { locale: "en-US", timeZone: "America/New_York" };
const UTC = { locale: "en-US", timeZone: "UTC" };

/** Seconds for a wall-clock instant given as UTC. */
const at = (iso: string): number => Date.parse(iso) / 1000;
// "Now" is Wed 2026-11-04 17:30 in New York (EST, UTC-5).
const NOW = new Date("2026-11-04T22:30:00Z");

describe("formatStamp", () => {
  it("shows the time alone for today", () => {
    expect(formatStamp(at("2026-11-04T22:06:00Z"), NOW, NY)).toBe("5:06 PM");
  });

  it("flips at local midnight, not at 24 hours", () => {
    expect(formatStamp(at("2026-11-04T05:00:00Z"), NOW, NY)).toBe("12:00 AM");
    expect(formatStamp(at("2026-11-04T04:59:00Z"), NOW, NY)).toBe("Yesterday 11:59 PM");
  });

  it("says Yesterday for the previous calendar day", () => {
    expect(formatStamp(at("2026-11-03T22:06:00Z"), NOW, NY)).toBe("Yesterday 5:06 PM");
  });

  it("uses the weekday through six days back and the date from seven", () => {
    expect(formatStamp(at("2026-11-02T22:06:00Z"), NOW, NY)).toBe("Mon 5:06 PM");
    expect(formatStamp(at("2026-10-29T22:06:00Z"), NOW, NY)).toBe("Thu 6:06 PM");
    expect(formatStamp(at("2026-10-28T22:06:00Z"), NOW, NY)).toBe("Oct 28, 6:06 PM");
  });

  it("drops the year within this year and keeps it for an earlier one", () => {
    expect(formatStamp(at("2026-01-02T22:06:00Z"), NOW, NY)).toBe("Jan 2, 5:06 PM");
    expect(formatStamp(at("2025-11-02T22:06:00Z"), NOW, NY)).toBe("Nov 2, 2025, 5:06 PM");
  });

  it("treats a year change as a date change even a day apart", () => {
    const newYear = new Date("2027-01-01T15:00:00Z");
    expect(formatStamp(at("2026-12-31T22:00:00Z"), newYear, NY)).toBe("Yesterday 5:00 PM");
    expect(formatStamp(at("2026-12-20T22:00:00Z"), newYear, NY)).toBe("Dec 20, 2026, 5:00 PM");
  });

  it("follows the viewer's time zone", () => {
    const sent = at("2026-11-03T01:30:00Z");
    expect(formatStamp(sent, NOW, UTC)).toBe("Yesterday 1:30 AM");
    expect(formatStamp(sent, NOW, NY)).toBe("Mon 8:30 PM");
  });

  it("uses the browser locale and zone by default", () => {
    expect(formatStamp(at("2026-11-04T22:06:00Z"), NOW)).toBe(formatTime(at("2026-11-04T22:06:00Z")));
  });
});

describe("formatDayLabel", () => {
  it("names today and yesterday", () => {
    expect(formatDayLabel(at("2026-11-04T22:06:00Z"), NOW, NY)).toBe("Today");
    expect(formatDayLabel(at("2026-11-03T22:06:00Z"), NOW, NY)).toBe("Yesterday");
  });

  it("spells the weekday and date for older days, with the year only when it differs", () => {
    expect(formatDayLabel(at("2026-11-02T22:06:00Z"), NOW, NY)).toBe("Monday, Nov 2");
    expect(formatDayLabel(at("2025-11-03T22:06:00Z"), NOW, NY)).toBe("Monday, Nov 3, 2025");
  });

  it("localises the relative words", () => {
    expect(formatDayLabel(at("2026-11-04T22:06:00Z"), NOW, { locale: "de", timeZone: "UTC" })).toBe("Heute");
  });
});

describe("calendar-day comparison across DST", () => {
  // US clocks spring forward on 2026-03-08 (a 23-hour day) and fall back on 2026-11-01 (25 hours).
  it("counts a 23-hour day as one day", () => {
    const sundayNoon = new Date("2026-03-08T16:00:00Z"); // 12:00 EDT
    const saturdayLate = at("2026-03-08T04:30:00Z"); // 23:30 EST on Saturday, 16.5h earlier
    expect(formatDayLabel(saturdayLate, sundayNoon, NY)).toBe("Yesterday");
    const saturdayNight = at("2026-03-08T05:00:00Z"); // 00:00 EST on Sunday
    expect(formatDayLabel(saturdayNight, sundayNoon, NY)).toBe("Today");
  });

  it("counts a 25-hour day as one day", () => {
    const sundayLate = new Date("2026-11-02T04:30:00Z"); // 23:30 EST on Sunday Nov 1
    expect(formatDayLabel(at("2026-11-01T04:30:00Z"), sundayLate, NY)).toBe("Today"); // 00:30 EDT
    expect(formatDayLabel(at("2026-11-01T03:59:00Z"), sundayLate, NY)).toBe("Yesterday"); // 23:59 EDT Sat
  });

  it("keeps the six-day window exact across a DST change", () => {
    const now = new Date("2026-03-10T16:00:00Z"); // Tue Mar 10, after spring forward
    expect(formatStamp(at("2026-03-04T17:00:00Z"), now, NY)).toBe("Wed 12:00 PM");
    expect(formatStamp(at("2026-03-03T17:00:00Z"), now, NY)).toBe("Mar 3, 12:00 PM");
  });

  it("numbers days by calendar date", () => {
    const sat = new Date("2026-03-08T04:30:00Z");
    const sun = new Date("2026-03-08T05:00:00Z");
    expect(dayNumber(sun, NY) - dayNumber(sat, NY)).toBe(1);
  });
});

describe("locales that write dates differently", () => {
  const noon = at("2026-11-04T12:00:00Z");
  const now = new Date("2026-11-04T22:30:00Z");

  it.each(["ar-EG", "fa-IR", "th-TH", "ja-JP-u-ca-japanese", "he-IL-u-ca-hebrew"])(
    "%s still compares calendar days correctly",
    (locale) => {
      const options = { locale, timeZone: "UTC" };
      expect(Number.isNaN(dayNumber(new Date(noon * 1000), options))).toBe(false);
      expect(startsNewDay(noon, noon, options)).toBe(false);
      expect(startsNewDay(noon, noon + 86_400, options)).toBe(true);
      expect(formatStamp(noon, now, options)).toBe(formatTime(noon, options));
      expect(formatStamp(noon - 86_400, now, options)).not.toBe(formatTime(noon - 86_400, options));
    },
  );

  it("keeps the Arabic and Persian stamp on the time-only form for today", () => {
    for (const locale of ["ar-EG", "fa-IR"]) {
      expect(formatStamp(noon, now, { locale, timeZone: "UTC" })).toBe(
        formatTime(noon, { locale, timeZone: "UTC" }),
      );
    }
  });

  it("keeps leap day and 1 March apart for Thai viewers", () => {
    const options = { locale: "th-TH", timeZone: "UTC" };
    const leapDay = at("2024-02-29T12:00:00Z");
    const march = new Date("2024-03-01T12:00:00Z");
    expect(daysAgo(new Date(leapDay * 1000), march, options)).toBe(1);
    expect(startsNewDay(leapDay, at("2024-03-01T12:00:00Z"), options)).toBe(true);
    expect(formatDayLabel(leapDay, march, options)).not.toBe(
      formatDayLabel(at("2024-03-01T12:00:00Z"), march, options),
    );
  });
});

describe("startsNewDay", () => {
  it("is true for the first message and across local midnight only", () => {
    expect(startsNewDay(undefined, at("2026-11-04T22:00:00Z"), NY)).toBe(true);
    expect(startsNewDay(at("2026-11-04T05:00:00Z"), at("2026-11-05T04:59:00Z"), NY)).toBe(false);
    expect(startsNewDay(at("2026-11-04T04:59:00Z"), at("2026-11-04T05:00:00Z"), NY)).toBe(true);
  });
});

describe("full stamps", () => {
  it("spells the whole date and time for the tooltip", () => {
    expect(formatFull(at("2026-11-04T22:06:09Z"), NY)).toBe("Wednesday, November 4, 2026 at 5:06:09 PM");
  });

  it("gives an ISO instant for the time element", () => {
    expect(isoInstant(at("2026-11-04T22:06:09Z"))).toBe("2026-11-04T22:06:09.000Z");
  });
});

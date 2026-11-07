/**
 * Human-friendly message times, in the viewer's locale and time zone.
 *
 * Every function takes `now` explicitly so callers decide what "today" is and
 * tests can fake it. `options.locale` / `options.timeZone` default to the
 * viewer's; tests pin them so the expected strings do not depend on the host.
 */

export interface TimeOptions {
  locale?: string | undefined;
  timeZone?: string | undefined;
}

const DAY_MS = 86_400_000;
const WEEK_DAYS = 6;

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(options: TimeOptions, shape: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = JSON.stringify([options.locale ?? "", options.timeZone ?? "", shape]);
  let found = formatters.get(key);
  if (!found) {
    found = new Intl.DateTimeFormat(options.locale, { ...shape, timeZone: options.timeZone });
    formatters.set(key, found);
  }
  return found;
}

/**
 * Day arithmetic must not depend on how the viewer's locale writes dates: Arabic
 * and Persian use other digits, Thai counts Buddhist years. Parts for arithmetic
 * therefore always come from the Gregorian calendar in Latin digits; only the
 * viewer's time zone carries over. Display strings still use the viewer's locale.
 */
const ARITHMETIC_LOCALE = "en-US-u-ca-gregory-nu-latn";

/** The calendar day of an instant in the viewer's zone, as a whole-day number. */
export function dayNumber(date: Date, options: TimeOptions = {}): number {
  const parts = formatter(
    { locale: ARITHMETIC_LOCALE, timeZone: options.timeZone },
    { year: "numeric", month: "numeric", day: "numeric" },
  ).formatToParts(date);
  const part = (type: string): number => Number(parts.find((entry) => entry.type === type)?.value);
  // Calendar components, not elapsed milliseconds: a DST day is 23 or 25 hours
  // long, and subtracting instants would put 11 pm and 1 am on the wrong side.
  return Date.UTC(part("year"), part("month") - 1, part("day")) / DAY_MS;
}

/** Whole calendar days from `date` back to `now` (0 = same day). */
export function daysAgo(date: Date, now: Date, options: TimeOptions = {}): number {
  return dayNumber(now, options) - dayNumber(date, options);
}

function sameYear(date: Date, now: Date, options: TimeOptions): boolean {
  const year = (value: Date): string =>
    formatter({ locale: ARITHMETIC_LOCALE, timeZone: options.timeZone }, { year: "numeric" }).format(value);
  return year(date) === year(now);
}

function words(options: TimeOptions): Intl.RelativeTimeFormat {
  return new Intl.RelativeTimeFormat(options.locale, { numeric: "auto" });
}

function capitalise(text: string): string {
  return text.charAt(0).toLocaleUpperCase() + text.slice(1);
}

/** "5:06 PM": the clock face alone. */
export function formatTime(seconds: number, options: TimeOptions = {}): string {
  return formatter(options, { hour: "numeric", minute: "2-digit" }).format(new Date(seconds * 1000));
}

/**
 * The stamp beside a sender: time only today, then "Yesterday 5:06 PM",
 * "Tue 5:06 PM" inside the last six days, "Nov 2, 5:06 PM", and the year once
 * it is not this one.
 */
export function formatStamp(seconds: number, now: Date, options: TimeOptions = {}): string {
  const date = new Date(seconds * 1000);
  const time = formatTime(seconds, options);
  const ago = daysAgo(date, now, options);
  if (ago <= 0) return time;
  if (ago === 1) return `${capitalise(words(options).format(-1, "day"))} ${time}`;
  if (ago <= WEEK_DAYS) {
    return `${formatter(options, { weekday: "short" }).format(date)} ${time}`;
  }
  const shape: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  if (!sameYear(date, now, options)) shape.year = "numeric";
  return `${formatter(options, shape).format(date)}, ${time}`;
}

/** The divider above a day's first message: "Today", "Yesterday", "Tuesday, Nov 3". */
export function formatDayLabel(seconds: number, now: Date, options: TimeOptions = {}): string {
  const date = new Date(seconds * 1000);
  const ago = daysAgo(date, now, options);
  if (ago <= 0) return capitalise(words(options).format(0, "day"));
  if (ago === 1) return capitalise(words(options).format(-1, "day"));
  const shape: Intl.DateTimeFormatOptions = { weekday: "long", month: "short", day: "numeric" };
  if (!sameYear(date, now, options)) shape.year = "numeric";
  return formatter(options, shape).format(date);
}

/** The complete date and time, for a tooltip and the `<time>` title. */
export function formatFull(seconds: number, options: TimeOptions = {}): string {
  return formatter(options, { dateStyle: "full", timeStyle: "medium" }).format(new Date(seconds * 1000));
}

/** Machine-readable instant for `<time datetime>`. */
export function isoInstant(seconds: number): string {
  return new Date(seconds * 1000).toISOString();
}

/** True when two messages sit on different calendar days. */
export function startsNewDay(
  previous: number | undefined,
  current: number,
  options: TimeOptions = {},
): boolean {
  if (previous === undefined) return true;
  return dayNumber(new Date(previous * 1000), options) !== dayNumber(new Date(current * 1000), options);
}

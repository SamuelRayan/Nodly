import { serverNow } from '@/api/client';
import i18n from '@/i18n';

/** "8:14 AM" in `timeZone` (an elder's time is always shown in their own zone, CLAUDE.md §5). */
export function clockTime(iso: string | Date, timeZone: string): string {
  return new Intl.DateTimeFormat(i18n.language, {
    hour: 'numeric',
    minute: '2-digit',
    timeZone,
  }).format(new Date(iso));
}

/** "25 Sep, 8:09 AM" in `timeZone`. */
export function dateTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat(i18n.language, {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
    timeZone,
  }).format(new Date(iso));
}

/** Today's date in `timeZone` as YYYY-MM-DD (the family clock's "today"), on the server's clock. */
export function localDateIn(timeZone: string, at: Date = new Date(serverNow())): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone }).format(at);
}

/** "Saturday, 26 September" for today in `timeZone`. */
export function longDate(timeZone: string, at: Date = new Date(serverNow())): string {
  return new Intl.DateTimeFormat(i18n.language, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    timeZone,
  }).format(at);
}

/** The hour (0–23) right now in `timeZone`. */
export function localHour(timeZone: string, at: Date = new Date(serverNow())): number {
  const hour = new Intl.DateTimeFormat('en-GB', { hour: 'numeric', hourCycle: 'h23', timeZone })
    .formatToParts(at)
    .find((part) => part.type === 'hour');
  return Number(hour?.value ?? 12);
}

export type DayPart = 'morning' | 'afternoon' | 'evening';

export function dayPart(timeZone: string): DayPart {
  const hour = localHour(timeZone);
  return hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening';
}

/** "Priya", "Priya and Arjun", "Priya, Arjun and Meera". */
export function joinNames(names: string[], and: string): string {
  if (names.length <= 1) {
    return names[0] ?? '';
  }
  return `${names.slice(0, -1).join(', ')} ${and} ${names[names.length - 1]}`;
}

/** One-letter weekday for a local date ("2026-09-26" -> "S"). */
export function weekdayInitial(localDate: string): string {
  const [year, month, day] = localDate.split('-').map(Number);
  return new Intl.DateTimeFormat(i18n.language, { weekday: 'narrow', timeZone: 'UTC' }).format(
    new Date(Date.UTC(year, month - 1, day)),
  );
}

/** "just now", "12 minutes ago", "4 hours ago", on the server's clock. Hermes on Android has
 * no Intl.RelativeTimeFormat (nor PluralRules, which i18next plurals need), so the singular or
 * plural string is picked here. */
export function timeAgo(iso: string): string {
  const minutes = Math.max(0, Math.round((serverNow() - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) {
    return i18n.t('time.just_now');
  }
  if (minutes < 60) {
    return i18n.t(minutes === 1 ? 'time.minute_ago' : 'time.minutes_ago', { n: minutes });
  }
  const hours = Math.round(minutes / 60);
  return i18n.t(hours === 1 ? 'time.hour_ago' : 'time.hours_ago', { n: hours });
}

/** A recording's length: "0:07", "1:42". */
export function duration(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/** Minutes east of UTC for `timeZone` at `at` (e.g. 330 for +05:30). */
function offsetMinutes(timeZone: string, at: Date): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(at);
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? 0);
  const asIfUtc = Date.UTC(
    get('year'),
    get('month') - 1,
    get('day'),
    get('hour'),
    get('minute'),
    get('second'),
  );
  return Math.round((asIfUtc - at.getTime()) / 60_000);
}

/** Milliseconds left until local midnight in `timeZone` — the end of "today" on the family
 * clock (§10). An approximation from the current UTC offset: fine for a display hint (it can
 * be an hour off on the very day the clock changes); the server alone decides what counts. */
export function msUntilLocalMidnight(timeZone: string, at: Date = new Date(serverNow())): number {
  const offset = offsetMinutes(timeZone, at);
  const [year, month, day] = localDateIn(timeZone, at).split('-').map(Number);
  const nextMidnightUtc = Date.UTC(year, month - 1, day + 1, 0, 0, 0) - offset * 60_000;
  return Math.max(0, nextMidnightUtc - at.getTime());
}

/** "6h left today", "45m left today" — how long until the family-clock day ends. */
export function timeLeftToday(timeZone: string, at: Date = new Date(serverNow())): string {
  const ms = msUntilLocalMidnight(timeZone, at);
  const hours = Math.floor(ms / 3_600_000);
  const minutes = Math.max(1, Math.round((ms % 3_600_000) / 60_000));
  return hours > 0
    ? i18n.t('moments.time_left_hours', { h: hours })
    : i18n.t('moments.time_left_minutes', { m: minutes });
}

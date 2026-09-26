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

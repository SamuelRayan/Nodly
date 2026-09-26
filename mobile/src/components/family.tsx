import { useTranslation } from 'react-i18next';
import { Linking, View } from 'react-native';

import type { components } from '@/api/schema';
import { useCheckinAction, useCheckinStatus } from '@/api/hooks';
import { Icon, type IconName } from '@/components/icons';
import { Avatar, Button, Card, ErrorNote, Pill, T } from '@/components/ui';
import { clockTime, dateTime, timeAgo, weekdayInitial } from '@/lib/format';
import { useTheme } from '@/theme';

type Elder = components['schemas']['ElderOut'];
type Status = components['schemas']['CheckinStatusOut'];

/** How the family refers to the elder ("Amma"), or their name. */
export function elderName(elder: Elder): string {
  return elder.relation_label ?? elder.display_name;
}

function StatusPill({ status }: { status: Status['status'] }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const looks: Record<Status['status'], { bg: string; fg: string; icon?: IconName }> = {
    okay: { bg: colors.okTint, fg: colors.okText, icon: 'check' },
    waiting: { bg: colors.neutralTint, fg: colors.textMuted, icon: 'clock' },
    late: { bg: colors.sand, fg: colors.onSand, icon: 'clock' },
    active: { bg: colors.sand, fg: colors.onSand },
    missed: { bg: colors.helpTint, fg: colors.helpText, icon: 'help' },
    paused: { bg: colors.neutralTint, fg: colors.textMuted },
    no_phone: { bg: colors.neutralTint, fg: colors.textMuted },
    starts_tomorrow: { bg: colors.okTintSoft, fg: colors.okText },
  };
  const look = looks[status];
  return (
    <Pill
      label={t(`checkin.status_${status}`)}
      background={look.bg}
      color={look.fg}
      icon={look.icon}
    />
  );
}

/** The last 7 days: filled = okay, dashed = missed, today ringed. */
function WeekStrip({ week }: { week: Status['week'] }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  return (
    <View style={{ gap: 8 }}>
      <T size={14} weight="bold" color={colors.textMuted}>
        {t('checkin.this_week')}
      </T>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        {week.map((day, index) => {
          const today = index === week.length - 1;
          return (
            <View
              key={day.local_date}
              accessible
              accessibilityLabel={`${day.local_date}: ${t(`checkin.day_${day.state}`)}`}
              style={{ alignItems: 'center', gap: 5, flex: 1 }}
            >
              <T size={13} weight={today ? 'bold' : 'normal'} color={today ? colors.text : colors.textMuted}>
                {weekdayInitial(day.local_date)}
              </T>
              <View
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: 14,
                  alignItems: 'center',
                  justifyContent: 'center',
                  backgroundColor: day.state === 'okay' ? colors.ok : 'transparent',
                  borderWidth: day.state === 'okay' ? 0 : 2,
                  borderStyle: day.state === 'missed' ? 'dashed' : 'solid',
                  borderColor: day.state === 'missed' ? colors.dashed : colors.border,
                  outlineColor: colors.ok,
                  outlineWidth: today ? 2 : 0,
                  outlineOffset: 3,
                }}
              >
                {day.state === 'okay' ? (
                  <Icon name="check" size={16} color={colors.onOk} strokeWidth={3} />
                ) : null}
              </View>
            </View>
          );
        })}
      </View>
    </View>
  );
}

function TimelineItem({ done, label, time }: { done: boolean; label: string; time: string }) {
  const { colors } = useTheme();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
      <View
        style={{
          width: 22,
          height: 22,
          borderRadius: 11,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: done ? colors.onSand : 'transparent',
          borderWidth: done ? 0 : 2,
          borderColor: colors.onSand,
        }}
      >
        {done ? <Icon name="check" size={13} color={colors.sand} strokeWidth={3} /> : null}
      </View>
      <T size={15} weight={done ? 'bold' : 'normal'} color={colors.onSand} style={{ flex: 1 }}>
        {label}
      </T>
      <T size={15} color={colors.onSand}>
        {time}
      </T>
    </View>
  );
}

/** One elder's day for the family (design F2 okay, F9 late, F10 missed). */
export function ElderCard({ elder }: { elder: Elder }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const status = useCheckinStatus(elder.id);
  const markOkay = useCheckinAction(elder.id, 'mark-okay');
  const ack = useCheckinAction(elder.id, 'alert/ack');
  const name = elderName(elder);
  const tz = elder.timezone;
  const s = status.data;

  return (
    <Card>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <Avatar name={elder.display_name} size={52} background={colors.okTint} color={colors.okText} />
        <View style={{ flex: 1, gap: 1 }}>
          <T size={21} weight="bold">
            {name}
          </T>
          <T size={15} color={colors.textMuted}>
            {t('checkin.their_time', { time: clockTime(new Date(), tz), name })}
          </T>
        </View>
        {s ? <StatusPill status={s.status} /> : null}
      </View>

      <ErrorNote error={status.error ?? markOkay.error ?? ack.error} />
      {s ? <TodayPanel status={s} name={name} tz={tz} /> : null}
      {s && s.status !== 'no_phone' ? <WeekStrip week={s.week} /> : null}

      {s?.status === 'missed' && !s.alert?.acked_at ? (
        <Button variant="help" label={t('checkin.on_it')} busy={ack.isPending} onPress={() => ack.mutate()} />
      ) : null}
      <View style={{ flexDirection: 'row', gap: 10 }}>
        {elder.phone_e164 ? (
          <Button
            variant="secondary"
            icon="phone"
            label={t('checkin.call')}
            onPress={() => void Linking.openURL(`tel:${elder.phone_e164}`)}
          />
        ) : null}
        {s && ['late', 'missed', 'active', 'waiting'].includes(s.status) ? (
          <Button
            variant="ink"
            icon="check"
            label={t('checkin.mark_okay')}
            busy={markOkay.isPending}
            onPress={() => markOkay.mutate()}
            style={{ flex: 1 }}
          />
        ) : null}
      </View>
    </Card>
  );
}

function TodayPanel({ status, name, tz }: { status: Status; name: string; tz: string }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const time = (iso: string) => clockTime(iso, tz);

  if (status.status === 'okay' && status.checkin) {
    const checkin = status.checkin;
    const byFamily = checkin.source === 'family';
    return (
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: 12,
          padding: 14,
          borderRadius: 18,
          backgroundColor: colors.okPanel,
        }}
      >
        <View
          style={{
            width: 42,
            height: 42,
            borderRadius: 21,
            backgroundColor: colors.ok,
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Icon name="check" size={22} color={colors.onOk} strokeWidth={2.8} />
        </View>
        <View style={{ flex: 1, gap: 1 }}>
          <T size={18} weight="bold">
            {byFamily
              ? t('checkin.marked_by', { who: checkin.marked_by_name ?? '', time: time(checkin.checked_in_at) })
              : t('checkin.checked_in_at', { time: time(checkin.checked_in_at) })}
          </T>
          <T size={15} color={colors.textMuted}>
            {t('checkin.their_time_ago', { name, ago: timeAgo(checkin.checked_in_at) })}
          </T>
        </View>
      </View>
    );
  }

  if (status.status === 'missed' && status.alert) {
    return (
      <View style={{ gap: 6, padding: 14, borderRadius: 18, backgroundColor: colors.helpTint }}>
        <T size={18} weight="bold" color={colors.helpText}>
          {t('checkin.missed_title', { name })}
        </T>
        <T size={15} color={colors.helpText}>
          {t('checkin.missed_detail', { due: time(status.schedule.due_at), name })}
        </T>
        {status.alert.acked_by_name ? (
          <T size={15} weight="bold" color={colors.helpText}>
            {t('checkin.acked_by', { who: status.alert.acked_by_name })}
          </T>
        ) : null}
        {status.last_checkin ? (
          <T size={15} color={colors.helpText}>
            {t('checkin.last_checkin', { when: dateTime(status.last_checkin.checked_in_at, tz) })}
          </T>
        ) : null}
      </View>
    );
  }

  if (status.status === 'late' || status.status === 'active' || status.status === 'waiting') {
    const reminders = status.reminders;
    const first = reminders.find((r) => r.kind === 'remind');
    const second = reminders.find((r) => r.kind === 'due_remind');
    return (
      <View style={{ gap: 10, padding: 14, borderRadius: 18, backgroundColor: colors.sand }}>
        <T size={16} weight="bold" color={colors.onSand}>
          {status.status === 'active'
            ? t('checkin.active_title', { name })
            : status.status === 'late'
              ? t('checkin.late_title', { due: time(status.schedule.due_at) })
              : t('checkin.waiting_title', { due: time(status.schedule.due_at) })}
        </T>
        <TimelineItem
          done={Boolean(first)}
          label={t('checkin.step_remind', { name })}
          time={time(first?.at ?? status.schedule.remind_at)}
        />
        <TimelineItem
          done={Boolean(second)}
          label={t('checkin.step_remind_again')}
          time={time(second?.at ?? status.schedule.due_at)}
        />
        <TimelineItem
          done={false}
          label={t('checkin.step_alert')}
          time={time(status.schedule.alert_at)}
        />
      </View>
    );
  }

  const explain =
    status.status === 'paused'
      ? 'checkin.explain_paused'
      : status.status === 'starts_tomorrow'
        ? 'checkin.explain_starts_tomorrow'
        : 'checkin.explain_no_phone';
  return (
    <T size={15} color={colors.textMuted}>
      {t(explain, { name, due: time(status.schedule.due_at) })}
    </T>
  );
}

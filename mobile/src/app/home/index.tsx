import * as Haptics from 'expo-haptics';
import { router } from 'expo-router';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { View } from 'react-native';

import { serverNow } from '@/api/client';
import { useCheckIn, useDeviceMe, useDeviceToday } from '@/api/hooks';
import { DoneCircle, HelpBar, OkayButton } from '@/components/elder';
import { Avatar, Button, ErrorNote, Loading, Screen, T, Title } from '@/components/ui';
import { applyLanguage } from '@/i18n';
import { clockTime, dayPart, joinNames, longDate } from '@/lib/format';
import { useAppStore } from '@/state/app';
import { useTheme } from '@/theme';

/**
 * The elder's home (design E2, E3, E7, E11, E12): one big "I'm okay" a day, then "Done for
 * today". Past the due time it gently asks; once the family was alerted it says so.
 */
export default function ElderHome() {
  const { t } = useTranslation();
  const { colors, scale } = useTheme();
  const me = useDeviceMe();
  const today = useDeviceToday();
  const checkIn = useCheckIn();
  const justPaired = useAppStore((state) => state.justPaired);
  const clearJustPaired = useAppStore((state) => state.clearJustPaired);

  // The family chooses the elder's app language on their profile.
  const language = me.data?.elder.language;
  useEffect(() => {
    applyLanguage(language);
  }, [language]);

  if (me.isPending || today.isPending) {
    return <Loading />;
  }
  if (me.isError || today.isError) {
    return (
      <Screen>
        <ErrorNote error={me.error ?? today.error} />
        <Button
          label={t('common.retry')}
          onPress={() => {
            void me.refetch();
            void today.refetch();
          }}
        />
      </Screen>
    );
  }

  const elder = me.data.elder;
  const tz = elder.timezone;
  const day = today.data;
  const names = joinNames(day.family_names, t('common.and'));

  if (justPaired) {
    return (
      <Screen>
        <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', gap: 24 }}>
          <View style={{ flexDirection: 'row' }}>
            {day.family_names.slice(0, 3).map((name, index) => (
              <View
                key={`${name}-${index}`}
                style={{
                  marginLeft: index === 0 ? 0 : -16,
                  borderRadius: 48,
                  borderWidth: 4,
                  borderColor: colors.background,
                }}
              >
                <Avatar
                  name={name}
                  size={88}
                  background={index === 0 ? colors.sand : colors.blueTint}
                  color={index === 0 ? colors.onSand : colors.onBlue}
                />
              </View>
            ))}
          </View>
          <Title center>{t('elder.connected_title', { names })}</Title>
          <T center color={colors.textMuted}>
            {t('elder.connected_line', { names })}
          </T>
        </View>
        <Button label={t('elder.start')} icon="arrowRight" iconAfter onPress={clearJustPaired} />
      </Screen>
    );
  }

  const tap = () =>
    checkIn.mutate('app', {
      onSuccess: () => {
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        router.push('/home/thanks');
      },
    });

  const done = day.checked_in_at !== null;
  const alerted = !done && day.family_alerted_at !== null;
  const late =
    !done &&
    !alerted &&
    day.watched_today &&
    serverNow() >= new Date(day.schedule.due_at).getTime();

  let heading = (
    <Title>
      {t(`elder.greeting_${dayPart(tz)}`)}
      {'\n'}
      {elder.display_name}
    </Title>
  );
  let line = t('elder.let_know', { names });
  if (done) {
    line = t('elder.done_line', { names });
  } else if (alerted) {
    heading = <Title>{t('elder.alerted_title')}</Title>;
    line = t('elder.alerted_tap');
  } else if (late) {
    heading = <Title>{t('elder.nudge_title', { name: elder.display_name })}</Title>;
    line = `${t('elder.nudge_line')} ${t('elder.nudge_when', {
      time: clockTime(day.schedule.alert_at, tz),
      names,
    })}`;
  } else if (day.marked_okay_by_family) {
    line = t('elder.marked_line', { name: day.family_names[0] ?? '' });
  }

  return (
    <Screen>
      <View style={{ gap: 6 }}>
        <T size={20} color={colors.textMuted}>
          {longDate(tz)}
        </T>
        {heading}
        {alerted ? (
          <T color={colors.textMuted}>
            {t('elder.alerted_line', {
              names,
              time: clockTime(day.family_alerted_at ?? day.schedule.alert_at, tz),
            })}
          </T>
        ) : null}
      </View>

      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 24 }}>
        {done ? (
          <DoneCircle
            title={t('elder.done_title')}
            detail={t('elder.done_at', { time: clockTime(day.checked_in_at ?? '', tz) })}
          />
        ) : (
          <OkayButton
            label={t('elder.okay')}
            hint={t('elder.tap_once')}
            busy={checkIn.isPending}
            onPress={tap}
          />
        )}
        <T center color={colors.textMuted} style={{ maxWidth: 320 }}>
          {line}
        </T>
        <ErrorNote error={checkIn.error} />
      </View>

      <View style={{ gap: 12 }}>
        <HelpBar
          label={t('elder.help')}
          hint={t('elder.help_hint')}
          onPress={() => router.push('/home/help')}
        />
        <Button
          variant="plain"
          label={t('elder.this_phone')}
          onPress={() => router.push('/home/leave')}
          style={{ minHeight: scale.buttonHeight - 16 }}
        />
      </View>
    </Screen>
  );
}

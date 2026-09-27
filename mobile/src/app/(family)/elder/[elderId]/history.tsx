import { Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { View } from 'react-native';

import { ApiError } from '@/api/errors';
import { useAccess, useCheckinHistory, useElder } from '@/api/hooks';
import { elderName } from '@/components/family';
import { PlusSheet } from '@/components/plus';
import { Button, Card, ErrorNote, Loading, Pill, Screen, T, Title } from '@/components/ui';
import { dateTime, weekdayInitial } from '@/lib/format';
import { useTheme } from '@/theme';

/**
 * An elder's check-ins by day. The last 7 days are free; the last 30 are the sprint's Plus
 * feature (§10), which the server gates (403 plus_required). Locked, it opens the Plus sheet.
 */
export default function History() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const { elderId } = useLocalSearchParams<{ elderId: string }>();
  const elder = useElder(elderId);
  const familyId = elder.data?.family_id;
  const access = useAccess(familyId);
  // Only an answer from after this screen opened decides how far back to ask: a cached one
  // may be minutes old, and Plus can start or end at any minute.
  const [openedAt] = useState(() => Date.now());
  const fresh = access.isSuccess && access.dataUpdatedAt >= openedAt;
  const plus = fresh && access.data.has_plus;
  const history = useCheckinHistory(elderId, plus ? 30 : 7, fresh);
  const [sheet, setSheet] = useState(false);

  // Asking for the month without Plus opens the sheet once, straight away (design F8).
  const [offered, setOffered] = useState(false);
  if (!offered && fresh && !access.data.has_plus) {
    setOffered(true);
    setSheet(true);
  }

  // Plus ended in between and the server said so: ask again, which shows the locked view.
  const staleGrant = history.error instanceof ApiError && history.error.code === 'plus_required';
  if (staleGrant && !access.isFetching) {
    void access.refetch();
  }
  if (elder.isError || access.isError || (history.isError && !staleGrant)) {
    return (
      <Screen>
        <ErrorNote error={elder.error ?? access.error ?? history.error} />
      </Screen>
    );
  }
  if (elder.isPending || !fresh || history.isPending || staleGrant) {
    return <Loading />;
  }
  const name = elderName(elder.data);
  const tz = access.data.today.timezone ?? elder.data.timezone;
  const days = history.data?.days ?? [];
  const okay = days.filter((day) => day.state === 'okay').length;
  const until = access.data.plus_until ? dateTime(access.data.plus_until, tz) : '';
  const source = access.data.sources.includes('subscription')
    ? t('plus.on_subscription')
    : access.data.sources.includes('day_pass')
      ? t('plus.on_day_pass', { time: until })
      : access.data.sources.includes('moment')
        ? t('plus.on_moment')
        : t('plus.on_goodwill', { time: until });

  return (
    <Screen>
      <Stack.Screen options={{ title: t('history.title') }} />
      <View style={{ gap: 6 }}>
        <Title size={30}>{name}</Title>
        <T color={colors.textMuted}>{plus ? t('history.month') : t('history.week')}</T>
      </View>
      {plus ? (
        <View style={{ gap: 6, alignItems: 'flex-start' }}>
          <Pill icon="star" label={t('plus.on')} background={colors.okTint} color={colors.okText} />
          <T size={15} color={colors.textMuted}>
            {source}
          </T>
        </View>
      ) : null}

      <Card>
        <T weight="bold">{t('history.summary', { n: okay, total: days.length })}</T>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', rowGap: 14 }}>
          {days.map((day, index) => {
            const today = index === days.length - 1;
            return (
              <View
                key={day.local_date}
                accessible
                accessibilityLabel={`${day.local_date}: ${t(`checkin.day_${day.state}`)}`}
                style={{ width: `${100 / 7}%`, alignItems: 'center', gap: 4 }}
              >
                <T size={12} color={colors.textMuted}>
                  {weekdayInitial(day.local_date)}
                </T>
                <View
                  style={{
                    width: 34,
                    height: 34,
                    borderRadius: 17,
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
                  <T size={13} weight="bold" color={day.state === 'okay' ? colors.onOk : colors.textMuted}>
                    {Number(day.local_date.slice(8))}
                  </T>
                </View>
              </View>
            );
          })}
        </View>
      </Card>

      {!plus && familyId ? (
        <Card>
          <T color={colors.textMuted}>{t('plus.month_locked_line')}</T>
          <Button icon="star" label={t('plus.unlock_month')} onPress={() => setSheet(true)} />
        </Card>
      ) : null}

      {familyId ? (
        <PlusSheet
          familyId={familyId}
          title={t('plus.history_title', { name })}
          visible={sheet}
          onClose={() => setSheet(false)}
          onUnlocked={() => setSheet(false)}
        />
      ) : null}
    </Screen>
  );
}

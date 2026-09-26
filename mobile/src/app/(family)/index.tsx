import { router, Stack } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Pressable, View } from 'react-native';

import type { components } from '@/api/schema';
import { useFamilies, useFamily, useFamilyHelp } from '@/api/hooks';
import { useMe } from '@/auth/session';
import { Icon } from '@/components/icons';
import { ElderCard } from '@/components/family';
import { Avatar, Body, Button, Card, ErrorNote, Loading, Screen, T, Title } from '@/components/ui';
import { dayPart, longDate } from '@/lib/format';
import { deviceTimezone } from '@/components/pickers';
import { useTheme } from '@/theme';

type FamilySummary = components['schemas']['FamilySummary'];

/** Live Help alerts, loud and first (they open the full-screen alert, F7). */
function HelpBanners({ familyId }: { familyId: string }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const live = useFamilyHelp(familyId);
  return (
    <>
      {live.data?.map((help) => (
        <Pressable
          key={help.id}
          accessibilityRole="button"
          accessibilityLabel={`${t('help.banner', { name: help.elder_name })}. ${t('help.open')}`}
          onPress={() => router.push({ pathname: '/help/[requestId]', params: { requestId: help.id } })}
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: 14,
            padding: 16,
            borderRadius: 20,
            backgroundColor: colors.alert,
          }}
        >
          <Icon name="help" size={30} color={colors.onAlert} />
          <View style={{ flex: 1 }}>
            <T weight="bold" color={colors.onAlert}>
              {help.is_test ? `${t('help.test_label')}: ` : ''}
              {help.status === 'acknowledged' && help.acked_by_name
                ? t('help.handled_by', { who: help.acked_by_name })
                : t('help.banner', { name: help.elder_name })}
            </T>
          </View>
          <T weight="bold" color={colors.onAlert}>
            {t('help.open')}
          </T>
        </Pressable>
      ))}
    </>
  );
}

/** Each family's elders, with today's check-in (design F2, F9, F10). */
function FamilySection({ family, showName }: { family: FamilySummary; showName: boolean }) {
  const { t } = useTranslation();
  const detail = useFamily(family.id);
  if (detail.isPending) {
    return <Loading />;
  }
  if (detail.isError) {
    return <ErrorNote error={detail.error} />;
  }
  return (
    <View style={{ gap: 16 }}>
      <HelpBanners familyId={family.id} />
      {showName ? <T weight="bold">{family.name}</T> : null}
      {detail.data.elders.map((elder) => (
        <ElderCard key={elder.id} elder={elder} />
      ))}
      {detail.data.elders.length === 0 ? (
        <Card>
          <Body>{t('family.no_elders_yet')}</Body>
          <Button
            label={t('family.add_elder')}
            onPress={() =>
              router.push({ pathname: '/family/[familyId]/add-elder', params: { familyId: family.id } })
            }
          />
        </Card>
      ) : null}
    </View>
  );
}

export default function FamilyDashboard() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const me = useMe().data;
  const families = useFamilies();
  const tz = me?.timezone ?? deviceTimezone() ?? 'UTC';
  const firstName = me?.display_name?.split(' ')[0] ?? '';

  return (
    <Screen>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <View style={{ flex: 1, gap: 2 }}>
          <T size={15} color={colors.textMuted}>
            {longDate(tz)}
          </T>
          <Title>{t(`family.greeting_${dayPart(tz)}`, { name: firstName })}</Title>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t('family.account')}
          onPress={() => router.push('/families')}
          hitSlop={8}
        >
          <Avatar name={firstName || '?'} />
        </Pressable>
      </View>

      {families.isPending ? <Loading /> : null}
      <ErrorNote error={families.error} />
      {families.data?.map((family) => (
        <FamilySection key={family.id} family={family} showName={(families.data?.length ?? 0) > 1} />
      ))}
      {families.data?.length === 0 ? (
        <Card>
          <Body>{t('family.none')}</Body>
          <Button label={t('family.create')} onPress={() => router.push('/create-family')} />
          <Button variant="secondary" label={t('family.join')} onPress={() => router.push('/join')} />
        </Card>
      ) : null}
    </Screen>
  );
}

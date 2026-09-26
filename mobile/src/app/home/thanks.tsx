import { router } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { View } from 'react-native';

import { useDeviceMe, useDeviceToday } from '@/api/hooks';
import { Icon } from '@/components/icons';
import { Button, Loading, Pill, Screen, T, Title } from '@/components/ui';
import { clockTime, joinNames } from '@/lib/format';
import { useTheme } from '@/theme';

/** Right after "I'm okay" (design E4). The new-moments card arrives with moments (Phase 6). */
export default function Thanks() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const me = useDeviceMe();
  const today = useDeviceToday();
  if (!me.data || !today.data) {
    return <Loading />;
  }
  const names = joinNames(today.data.family_names, t('common.and'));
  const at = today.data.checked_in_at;
  return (
    <Screen>
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 20 }}>
        <View
          style={{
            width: 128,
            height: 128,
            borderRadius: 64,
            backgroundColor: colors.ok,
            alignItems: 'center',
            justifyContent: 'center',
            borderWidth: 14,
            borderColor: colors.okTint,
            marginBottom: 14,
          }}
        >
          <Icon name="check" size={60} color={colors.onOk} strokeWidth={2.8} />
        </View>
        <Title center>{t('elder.thanks_title', { name: me.data.elder.display_name })}</Title>
        <T center color={colors.textMuted} style={{ maxWidth: 320 }}>
          {t('elder.thanks_line', { names })}
        </T>
        {at ? (
          <Pill
            icon="clock"
            label={t('elder.checked_at', { time: clockTime(at, me.data.elder.timezone) })}
            background={colors.okTint}
            color={colors.okText}
          />
        ) : null}
      </View>
      <Button label={t('elder.back_home')} icon="home" onPress={() => router.back()} />
    </Screen>
  );
}

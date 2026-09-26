import { router, useLocalSearchParams } from 'expo-router';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Linking, Pressable, View } from 'react-native';

import { useCancelHelp, useDeviceHelp, useDeviceMe } from '@/api/hooks';
import { Icon } from '@/components/icons';
import { Avatar, Button, ErrorNote, Loading, Screen, T, Title } from '@/components/ui';
import { emergencyNumber } from '@/data/emergency';
import { joinNames } from '@/lib/format';
import { useTheme } from '@/theme';

/**
 * Help, step 2 (design E9, E10): who got the alert, then "Priya is on it". Always shows the
 * local emergency number: Nodly is not an emergency service (CLAUDE.md §1).
 */
export default function HelpSent() {
  const { t } = useTranslation();
  const { colors, scale } = useTheme();
  const { kind } = useLocalSearchParams<{ kind?: string }>();
  const me = useDeviceMe();
  const help = useDeviceHelp(3_000);
  const cancel = useCancelHelp();
  const request = help.data;

  // Closed by a family member: back home.
  const closed = help.isSuccess && request === null;
  useEffect(() => {
    if (closed) {
      router.replace('/home');
    }
  }, [closed]);

  if (help.isPending || me.isPending || !request) {
    return <Loading />;
  }
  const number = emergencyNumber(me.data?.elder.country_code);
  const names = request.recipients.map((person) => person.name?.split(' ')[0] ?? '');
  const acked = request.status === 'acknowledged' && request.acked_by_name;
  const helper = request.acked_by_name?.split(' ')[0] ?? '';

  const emergency = (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
      <Icon name="phone" size={22} color={colors.textMuted} />
      {number ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${t('help.emergency')} ${number}`}
          onPress={() => void Linking.openURL(`tel:${number}`)}
          style={{ flex: 1 }}
        >
          <T size={20} color={colors.textMuted}>
            {t('help.emergency')}{' '}
            <T size={20} weight="bold" color={colors.helpText} style={{ textDecorationLine: 'underline' }}>
              {number}
            </T>
          </T>
        </Pressable>
      ) : (
        <T size={20} color={colors.textMuted} style={{ flex: 1 }}>
          {t('help.emergency_local')}
        </T>
      )}
    </View>
  );

  if (acked) {
    return (
      <Screen background={colors.helpPage}>
        <View style={{ flex: 1, justifyContent: 'center', gap: 18 }}>
          <Avatar name={helper} size={96} />
          <Title size={40}>{t('help.on_it_title', { name: helper })}</Title>
          <T color={colors.textMuted}>{t('help.on_it_line')}</T>
        </View>
        {emergency}
        {request.acked_by_phone_e164 ? (
          <Button
            icon="phone"
            label={t('help.call_person', { name: helper })}
            onPress={() => void Linking.openURL(`tel:${request.acked_by_phone_e164}`)}
          />
        ) : null}
        <ErrorNote error={cancel.error} />
        <Button
          variant="secondary"
          label={t('help.okay_now_short')}
          busy={cancel.isPending}
          onPress={() => cancel.mutate(undefined, { onSuccess: () => router.replace('/home') })}
          style={{ borderColor: colors.text }}
        />
      </Screen>
    );
  }

  return (
    <Screen background={colors.helpPage}>
      <View
        style={{
          width: 88,
          height: 88,
          borderRadius: 44,
          backgroundColor: colors.help,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Icon name="bell" size={40} color={colors.onHelp} />
      </View>
      <View style={{ gap: 12 }}>
        <Title size={40}>
          {kind === 'call_me' || request.kind === 'call_me'
            ? t('help.call_me_sent', { names: joinNames(names, t('common.and')) })
            : t('help.sent_title')}
        </Title>
        <T color={colors.textMuted}>{t('help.sent_line')}</T>
      </View>

      <View
        style={{
          backgroundColor: colors.surface,
          borderRadius: 24,
          borderWidth: 1.5,
          borderColor: colors.helpTintBorder,
        }}
      >
        {request.recipients.map((person, index) => (
          <View
            key={person.user_id}
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: 14,
              padding: 16,
              borderTopWidth: index === 0 ? 0 : 1.5,
              borderTopColor: colors.helpTint,
            }}
          >
            <Avatar
              name={person.name ?? '?'}
              size={52}
              background={index === 0 ? colors.sand : colors.blueTint}
              color={index === 0 ? colors.onSand : colors.onBlue}
            />
            <View style={{ gap: 2 }}>
              <T size={22} weight="bold">
                {person.name?.split(' ')[0] ?? ''}
              </T>
              <T size={scale.small - 2} color={person.delivered ? colors.okText : colors.textMuted}>
                {person.delivered ? t('help.delivered') : t('help.sending')}
              </T>
            </View>
          </View>
        ))}
      </View>
      <T weight="bold" color={colors.helpText}>
        {t('help.waiting')}
      </T>

      <View style={{ flex: 1 }} />
      {emergency}
      <T size={16} color={colors.textMuted}>
        {t('help.not_emergency')}
      </T>
      <ErrorNote error={cancel.error} />
      <Button
        variant="secondary"
        label={t('help.okay_now')}
        busy={cancel.isPending}
        onPress={() => cancel.mutate(undefined, { onSuccess: () => router.replace('/home') })}
        style={{ minHeight: scale.buttonHeight + 4, borderColor: colors.text }}
      />
    </Screen>
  );
}

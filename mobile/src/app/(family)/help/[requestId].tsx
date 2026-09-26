import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Linking, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useElder, useHelpAction, useHelpRequest } from '@/api/hooks';
import { Icon } from '@/components/icons';
import { Avatar, Button, ErrorNote, Loading, T, Title } from '@/components/ui';
import { clockTime, dateTime, timeAgo } from '@/lib/format';
import { useTheme } from '@/theme';

/** The family's full-screen Help alert (design F7). Stays usable at half height (split screen). */
export default function HelpAlert() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const { requestId } = useLocalSearchParams<{ requestId: string }>();
  const request = useHelpRequest(requestId);
  const elder = useElder(request.data?.elder_id ?? '');
  const ack = useHelpAction(requestId, 'ack');
  const resolve = useHelpAction(requestId, 'resolve');

  if (request.isPending) {
    return <Loading />;
  }
  if (request.isError) {
    return (
      <SafeAreaView style={{ flex: 1, padding: 24, backgroundColor: colors.background }}>
        <ErrorNote error={request.error} />
      </SafeAreaView>
    );
  }
  const help = request.data;
  const name = help.elder_name;
  const tz = elder.data?.timezone ?? 'UTC';
  const live = help.status === 'open' || help.status === 'acknowledged';
  const white = colors.onAlert;
  const soft = colors.onAlertMuted;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.alert }}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={{ flex: 1, padding: 24, gap: 20 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
          <View
            style={{
              width: 56,
              height: 56,
              borderRadius: 28,
              backgroundColor: white,
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Icon name="help" size={30} color={colors.alert} />
          </View>
          <T size={15} weight="bold" color={white} style={{ letterSpacing: 2 }}>
            {(help.is_test ? t('help.test_label') : t('help.alert_label')).toUpperCase()}
          </T>
        </View>

        <View style={{ gap: 10 }}>
          <Title size={42} color={white}>
            {help.kind === 'call_me' ? t('help.asked_call', { name }) : t('help.pressed', { name })}
          </Title>
          <T size={19} color={soft}>
            {t('help.when', {
              time: clockTime(help.created_at, tz),
              name,
              ago: timeAgo(help.created_at),
            })}
          </T>
          {help.status === 'acknowledged' && help.acked_by_name ? (
            <T size={19} weight="bold" color={white}>
              {t('help.handled_by', { who: help.acked_by_name })}
            </T>
          ) : null}
          {help.status === 'cancelled' ? (
            <T size={19} weight="bold" color={white}>
              {t('help.cancelled', { name })}
            </T>
          ) : null}
          {help.status === 'resolved' ? (
            <T size={19} weight="bold" color={white}>
              {t('help.resolved')}
            </T>
          ) : null}
        </View>

        <View style={{ borderRadius: 20, backgroundColor: colors.alertPanel }}>
          {help.recipients.map((person) => (
            <View
              key={person.user_id}
              style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14 }}
            >
              <Avatar name={person.name ?? '?'} size={40} background={colors.blueTint} color={colors.onBlue} />
              <View style={{ flex: 1 }}>
                <T size={17} weight="bold" color={white}>
                  {person.name ?? ''}
                </T>
                <T size={15} color={soft}>
                  {person.delivered ? t('help.delivered') : t('help.not_delivered')}
                </T>
              </View>
            </View>
          ))}
          {help.last_checkin_at ? (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14 }}>
              <Icon name="clock" size={24} color={white} />
              <T size={17} weight="bold" color={white}>
                {t('help.last_checkin', { when: dateTime(help.last_checkin_at, tz) })}
              </T>
            </View>
          ) : null}
          {help.battery_percent !== null ? (
            <View style={{ padding: 14, paddingTop: 0 }}>
              <T size={15} color={soft}>
                {t('help.battery', { percent: help.battery_percent })}
              </T>
            </View>
          ) : null}
        </View>

        <View style={{ flex: 1 }} />
        <ErrorNote error={ack.error ?? resolve.error} />
        {help.elder_phone_e164 ? (
          <Button
            variant="secondary"
            icon="phone"
            label={t('help.call_elder', { name })}
            onPress={() => void Linking.openURL(`tel:${help.elder_phone_e164}`)}
            style={{ backgroundColor: white, borderWidth: 0 }}
          />
        ) : null}
        {help.status === 'open' ? (
          <>
            <Button
              label={t('help.on_it')}
              busy={ack.isPending}
              onPress={() => ack.mutate()}
              style={{ backgroundColor: colors.alertButton }}
            />
            <T size={15} center color={soft}>
              {t('help.on_it_hint', { name })}
            </T>
          </>
        ) : null}
        {live && help.status === 'acknowledged' ? (
          <Button
            label={t('help.resolve')}
            busy={resolve.isPending}
            onPress={() => resolve.mutate()}
            style={{ backgroundColor: colors.alertButton }}
          />
        ) : null}
        {!live ? (
          <Button
            label={t('help.back_home')}
            onPress={() => router.replace('/')}
            style={{ backgroundColor: colors.alertButton }}
          />
        ) : null}
      </View>
    </SafeAreaView>
  );
}

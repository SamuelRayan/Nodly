import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Alert, View } from 'react-native';

import { api, unwrap } from '@/api/client';
import { keys, useDevices, useElder } from '@/api/hooks';
import { Body, Button, ErrorNote, Heading, Loading, Row, Screen } from '@/components/ui';

/** One elder, from the family side: their connected phone(s), disconnect, set up a phone. */
export default function ElderDetail() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { elderId } = useLocalSearchParams<{ elderId: string }>();
  const elder = useElder(elderId);
  const devices = useDevices(elderId);

  const testAlert = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/v1/elders/{elder_id}/help/test', { params: { path: { elder_id: elderId } } }),
      ),
    onSuccess: (help) =>
      router.push({ pathname: '/help/[requestId]', params: { requestId: help.id } }),
  });

  const disconnect = useMutation({
    mutationFn: (deviceId: string) =>
      unwrap(
        api.DELETE('/v1/elders/{elder_id}/devices/{device_id}', {
          params: { path: { elder_id: elderId, device_id: deviceId } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.devices(elderId) }),
  });

  if (elder.isPending || devices.isPending) {
    return <Loading />;
  }
  if (elder.isError || devices.isError) {
    return (
      <Screen>
        <ErrorNote error={elder.error ?? devices.error} />
      </Screen>
    );
  }
  const name = elder.data.display_name;
  const active = devices.data.filter((device) => !device.revoked_at);
  const when = (iso: string) => new Date(iso).toLocaleDateString(i18n.language, { dateStyle: 'medium' });
  const confirmDisconnect = (deviceId: string) =>
    Alert.alert(t('elderPhone.confirm_title'), t('elderPhone.confirm_body', { name }), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('elderPhone.disconnect'),
        style: 'destructive',
        onPress: () => disconnect.mutate(deviceId),
      },
    ]);

  return (
    <Screen>
      <Stack.Screen options={{ title: name }} />
      <Heading>{t('elderPhone.heading')}</Heading>
      {active.length === 0 ? <Body muted>{t('elderPhone.none', { name })}</Body> : null}
      {active.map((device) => (
        <View key={device.id} style={{ gap: 6 }}>
          <Row
            title={device.device_model ?? t('elderPhone.unknown_model')}
            subtitle={t('elderPhone.connected_since', { when: when(device.paired_at) })}
          />
          <Button
            variant="secondary"
            label={t('elderPhone.disconnect')}
            busy={disconnect.isPending && disconnect.variables === device.id}
            onPress={() => confirmDisconnect(device.id)}
          />
        </View>
      ))}
      <ErrorNote error={disconnect.error} />
      <Button
        variant={active.length === 0 ? 'primary' : 'secondary'}
        label={active.length === 0 ? t('family.pair_phone') : t('elderPhone.pair_another')}
        onPress={() => router.push({ pathname: '/elder/[elderId]/pair', params: { elderId } })}
      />

      <Heading>{t('help.title')}</Heading>
      <Body muted>{t('help.test_explain')}</Body>
      <ErrorNote error={testAlert.error} />
      <Button
        variant="secondary"
        icon="bell"
        label={t('help.test_send')}
        busy={testAlert.isPending}
        onPress={() => testAlert.mutate()}
      />
    </Screen>
  );
}

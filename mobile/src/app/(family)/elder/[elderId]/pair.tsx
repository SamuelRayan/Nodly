import { useMutation } from '@tanstack/react-query';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Text, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

import { api, serverNow, unwrap } from '@/api/client';
import { useDevices, useElder } from '@/api/hooks';
import { Body, Button, ErrorNote, Loading, Screen, Title } from '@/components/ui';
import { APP_NAME } from '@/config';
import { useTheme } from '@/theme';

function useSecondsLeft(until: string | undefined): number {
  const [now, setNow] = useState(serverNow);
  useEffect(() => {
    const timer = setInterval(() => setNow(serverNow()), 1000);
    return () => clearInterval(timer);
  }, []);
  return until ? Math.max(0, Math.floor((new Date(until).getTime() - now) / 1000)) : 0;
}

/** Show a 15-minute pairing code (and QR) for the elder's phone, and wait for it to connect. */
export default function PairElder() {
  const { t } = useTranslation();
  const { colors, scale } = useTheme();
  const { elderId } = useLocalSearchParams<{ elderId: string }>();
  const elder = useElder(elderId);
  const code = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/v1/elders/{elder_id}/pairing-codes', {
          params: { path: { elder_id: elderId } },
        }),
      ),
  });
  // When the current code was requested: a phone paired after that is "the" phone.
  const [since, setSince] = useState(serverNow);
  const { mutate: newCode } = code;
  useEffect(() => {
    newCode();
  }, [newCode]);

  const secondsLeft = useSecondsLeft(code.data?.expires_at);
  const waiting = code.isSuccess && secondsLeft > 0;
  // While a code is live, watch for a phone that paired after it was made.
  const devices = useDevices(elderId, waiting ? 3000 : undefined);
  const paired = devices.data?.some(
    (device) => !device.revoked_at && new Date(device.paired_at).getTime() >= since - 5000,
  );

  const name = elder.data?.display_name ?? '';
  if (elder.isPending) {
    return <Loading />;
  }
  return (
    <Screen>
      <Stack.Screen options={{ title: t('pairing.title', { name }) }} />
      {paired ? (
        <>
          <Title>{t('pairing.paired', { name })}</Title>
          <Button label={t('pairing.done')} onPress={() => router.back()} />
        </>
      ) : (
        <>
          <Body>{t('pairing.steps', { name, app: APP_NAME })}</Body>
          <ErrorNote error={code.error} />
          {code.data && secondsLeft > 0 ? (
            <View style={{ alignItems: 'center', gap: scale.space }}>
              <View style={{ padding: 16, backgroundColor: colors.surface, borderRadius: scale.radius }}>
                <QRCode
                  value={code.data.qr_payload}
                  size={220}
                  color={colors.text}
                  backgroundColor={colors.surface}
                />
              </View>
              <Text
                accessibilityLabel={`${t('pairing.code_label')}: ${code.data.code.split('').join(' ')}`}
                selectable
                style={{ color: colors.text, fontSize: 40, fontWeight: '700', letterSpacing: 4 }}
              >
                {code.data.code}
              </Text>
              <Body muted>
                {t('pairing.expires_in', {
                  minutes: Math.floor(secondsLeft / 60),
                  seconds: String(secondsLeft % 60).padStart(2, '0'),
                })}
              </Body>
              <Body muted>{t('pairing.waiting')}</Body>
            </View>
          ) : null}
          {code.isSuccess && secondsLeft === 0 ? <Body>{t('pairing.expired')}</Body> : null}
          <Button
            variant={secondsLeft === 0 ? 'primary' : 'secondary'}
            label={t('pairing.new_code')}
            busy={code.isPending}
            onPress={() => {
              setSince(serverNow());
              code.mutate();
            }}
          />
        </>
      )}
    </Screen>
  );
}

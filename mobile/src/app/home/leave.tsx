import { useMutation } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, unwrap } from '@/api/client';
import { useDeviceMe } from '@/api/hooks';
import { Body, Button, ErrorNote, Field, Screen, Title } from '@/components/ui';
import { APP_NAME } from '@/config';
import { useAppStore } from '@/state/app';

/** Taking this phone out of elder mode needs the family PIN (or the family disconnects it). */
export default function Leave() {
  const { t } = useTranslation();
  const me = useDeviceMe();
  const resetToWelcome = useAppStore((state) => state.resetToWelcome);
  const [pin, setPin] = useState('');

  const leave = useMutation({
    mutationFn: () => unwrap(api.POST('/v1/device/leave', { body: { pin } })),
    onSuccess: () => resetToWelcome('left_elder_mode'),
  });

  const hasPin = me.data?.family_has_pin ?? false;
  return (
    <Screen>
      <Title>{t('elder.leave_title')}</Title>
      {hasPin ? (
        <>
          <Field
            label={t('elder.leave_pin')}
            value={pin}
            onChangeText={setPin}
            keyboardType="number-pad"
            secureTextEntry
            maxLength={8}
          />
          <ErrorNote error={leave.error} />
          <Button
            label={t('elder.leave')}
            disabled={pin.length < 4}
            busy={leave.isPending}
            onPress={() => leave.mutate()}
          />
        </>
      ) : (
        <Body>{t('elder.leave_no_pin', { app: APP_NAME })}</Body>
      )}
      <Button variant="secondary" label={t('common.back')} onPress={() => router.back()} />
    </Screen>
  );
}

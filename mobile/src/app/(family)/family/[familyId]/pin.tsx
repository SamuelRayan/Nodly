import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, unwrap } from '@/api/client';
import { keys, useFamily } from '@/api/hooks';
import { Body, Button, ErrorNote, Field, Screen } from '@/components/ui';

const PIN = /^[0-9]{4,8}$/;

/** Organizer only: the family PIN that takes an elder's phone out of elder mode. */
export default function FamilyPin() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { familyId } = useLocalSearchParams<{ familyId: string }>();
  const family = useFamily(familyId);
  const [pin, setPin] = useState('');
  const [confirm, setConfirm] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const path = { params: { path: { family_id: familyId } } };
  const done = () => {
    void queryClient.invalidateQueries({ queryKey: keys.family(familyId) });
    router.back();
  };

  const save = useMutation({
    mutationFn: () => unwrap(api.PUT('/v1/families/{family_id}/pin', { ...path, body: { pin } })),
    onSuccess: done,
  });
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE('/v1/families/{family_id}/pin', path)),
    onSuccess: done,
  });

  const submit = () => {
    if (!PIN.test(pin)) {
      setProblem(t('pin.invalid'));
    } else if (pin !== confirm) {
      setProblem(t('pin.mismatch'));
    } else {
      setProblem(null);
      save.mutate();
    }
  };

  const hasPin = family.data?.has_pin ?? false;
  return (
    <Screen>
      <Stack.Screen options={{ title: t('pin.title') }} />
      <Body>{t('pin.intro')}</Body>
      <Body muted>{hasPin ? t('pin.is_set') : t('pin.not_set')}</Body>
      <Field
        label={t('pin.pin_label')}
        value={pin}
        onChangeText={setPin}
        keyboardType="number-pad"
        secureTextEntry
        maxLength={8}
      />
      <Field
        label={t('pin.confirm_label')}
        value={confirm}
        onChangeText={setConfirm}
        keyboardType="number-pad"
        secureTextEntry
        maxLength={8}
      />
      <ErrorNote error={problem ?? save.error ?? remove.error} />
      <Button label={t('pin.save')} busy={save.isPending} onPress={submit} />
      {hasPin ? (
        <Button
          variant="secondary"
          label={t('pin.remove')}
          busy={remove.isPending}
          onPress={() => remove.mutate()}
        />
      ) : null}
    </Screen>
  );
}

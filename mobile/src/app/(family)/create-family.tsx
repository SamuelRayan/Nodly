import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router, Stack } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, unwrap } from '@/api/client';
import { keys } from '@/api/hooks';
import { Button, ErrorNote, Field, Screen } from '@/components/ui';

export default function CreateFamily() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState('');

  const create = useMutation({
    mutationFn: () => unwrap(api.POST('/v1/families', { body: { name: name.trim() } })),
    onSuccess: (family) => {
      void queryClient.invalidateQueries({ queryKey: keys.families });
      router.replace({ pathname: '/family/[familyId]', params: { familyId: family.id } });
    },
  });

  return (
    <Screen>
      <Stack.Screen options={{ title: t('createFamily.title') }} />
      <Field
        label={t('createFamily.name_label')}
        placeholder={t('createFamily.name_placeholder')}
        value={name}
        onChangeText={setName}
        maxLength={100}
      />
      <ErrorNote error={create.error} />
      <Button
        label={t('createFamily.create')}
        disabled={name.trim().length === 0}
        busy={create.isPending}
        onPress={() => create.mutate()}
      />
    </Screen>
  );
}

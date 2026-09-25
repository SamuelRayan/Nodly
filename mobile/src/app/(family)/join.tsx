import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, unwrap } from '@/api/client';
import { keys } from '@/api/hooks';
import { Body, Button, ErrorNote, Field, Screen } from '@/components/ui';

/** Join a family with an invite code (typed, or from a nodly://invite/<code> link). */
export default function Join() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const params = useLocalSearchParams<{ code?: string }>();
  const [code, setCode] = useState(params.code ?? '');

  const preview = useMutation({
    mutationFn: (value: string) => unwrap(api.POST('/v1/invites/preview', { body: { code: value } })),
  });
  const accept = useMutation({
    mutationFn: () => unwrap(api.POST('/v1/invites/accept', { body: { code: code.trim() } })),
    onSuccess: (family) => {
      void queryClient.invalidateQueries({ queryKey: keys.families });
      router.replace({ pathname: '/family/[familyId]', params: { familyId: family.id } });
    },
  });

  // A link brings the code with it: check it straight away.
  const { mutate: check } = preview;
  useEffect(() => {
    if (params.code) {
      check(params.code);
    }
  }, [params.code, check]);

  const invite = preview.data;
  return (
    <Screen>
      <Stack.Screen options={{ title: t('join.title') }} />
      <Field
        label={t('join.code_label')}
        value={code}
        onChangeText={(value) => {
          setCode(value);
          preview.reset();
        }}
        autoCapitalize="characters"
        autoCorrect={false}
        maxLength={20}
      />
      <ErrorNote error={preview.error ?? accept.error} />
      {invite ? (
        <>
          <Body>
            {invite.invited_by
              ? t('join.invited_by', { inviter: invite.invited_by, family: invite.family_name })
              : t('join.invited', { family: invite.family_name })}
          </Body>
          {invite.already_member ? (
            <Body muted>{t('join.already_member', { family: invite.family_name })}</Body>
          ) : (
            <Button
              label={t('join.accept', { family: invite.family_name })}
              busy={accept.isPending}
              onPress={() => accept.mutate()}
            />
          )}
        </>
      ) : (
        <Button
          label={t('join.check')}
          disabled={code.trim().length === 0}
          busy={preview.isPending}
          onPress={() => preview.mutate(code.trim())}
        />
      )}
    </Screen>
  );
}

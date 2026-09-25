import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Share, Text, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

import { api, unwrap } from '@/api/client';
import { keys, useInvites } from '@/api/hooks';
import { Body, Button, ErrorNote, Heading, Row, Screen } from '@/components/ui';
import { APP_NAME } from '@/config';
import { useTheme } from '@/theme';

/** Invite family members: a single-use code, link and QR (48 hours), plus open invites. */
export default function Invites() {
  const { t, i18n } = useTranslation();
  const { colors, scale } = useTheme();
  const queryClient = useQueryClient();
  const { familyId } = useLocalSearchParams<{ familyId: string }>();
  const invites = useInvites(familyId);
  const path = { params: { path: { family_id: familyId } } };

  const create = useMutation({
    mutationFn: () => unwrap(api.POST('/v1/families/{family_id}/invites', path)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.invites(familyId) }),
  });
  const revoke = useMutation({
    mutationFn: (inviteId: string) =>
      unwrap(
        api.DELETE('/v1/families/{family_id}/invites/{invite_id}', {
          params: { path: { family_id: familyId, invite_id: inviteId } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.invites(familyId) }),
  });

  const created = create.data;
  const when = (iso: string) =>
    new Date(iso).toLocaleString(i18n.language, { dateStyle: 'medium', timeStyle: 'short' });

  return (
    <Screen>
      <Stack.Screen options={{ title: t('invites.title') }} />
      <Body muted>{t('invites.intro')}</Body>
      {created ? (
        <View style={{ alignItems: 'center', gap: scale.space }}>
          <View style={{ padding: 16, backgroundColor: colors.surface, borderRadius: scale.radius }}>
            <QRCode value={created.qr_payload} size={200} color={colors.text} backgroundColor={colors.surface} />
          </View>
          <Text selectable style={{ color: colors.text, fontSize: 34, fontWeight: '700', letterSpacing: 3 }}>
            {created.code}
          </Text>
          <Button
            label={t('common.share')}
            onPress={() =>
              void Share.share({
                message: t('invites.share_message', { app: APP_NAME, link: created.link, code: created.code }),
              })
            }
          />
        </View>
      ) : null}
      <ErrorNote error={create.error ?? revoke.error} />
      <Button
        variant={created ? 'secondary' : 'primary'}
        label={t('invites.create')}
        busy={create.isPending}
        onPress={() => create.mutate()}
      />

      <Heading>{t('invites.open')}</Heading>
      {invites.data?.length === 0 ? <Body muted>{t('invites.none')}</Body> : null}
      {invites.data?.map((invite) => (
        <View key={invite.id} style={{ gap: 6 }}>
          <Row
            title={invite.created_by_name ?? '—'}
            subtitle={t('invites.expires', { when: when(invite.expires_at) })}
          />
          <Button
            variant="secondary"
            label={t('invites.revoke')}
            busy={revoke.isPending && revoke.variables === invite.id}
            onPress={() => revoke.mutate(invite.id)}
          />
        </View>
      ))}
    </Screen>
  );
}

import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useTranslation } from 'react-i18next';

import { useDevices, useFamily } from '@/api/hooks';
import type { components } from '@/api/schema';
import { useMe } from '@/auth/session';
import { Body, Button, ErrorNote, Heading, Loading, Row, Screen } from '@/components/ui';

function ElderRow({ elder }: { elder: components['schemas']['ElderOut'] }) {
  const { t } = useTranslation();
  const devices = useDevices(elder.id);
  const connected = devices.data?.some((device) => !device.revoked_at);
  let subtitle: string | undefined;
  if (elder.pause.paused) {
    subtitle = t('family.paused');
  } else if (devices.isSuccess) {
    subtitle = connected ? t('family.phone_connected') : t('family.phone_not_set_up');
  }
  return (
    <Row
      title={elder.relation_label ? `${elder.display_name} · ${elder.relation_label}` : elder.display_name}
      subtitle={subtitle}
      onPress={() => router.push({ pathname: '/elder/[elderId]', params: { elderId: elder.id } })}
    />
  );
}

/** One family: the clock, members and elders (placeholder layout). */
export default function FamilyDetail() {
  const { t } = useTranslation();
  const { familyId } = useLocalSearchParams<{ familyId: string }>();
  const family = useFamily(familyId);
  const me = useMe().data;

  if (family.isPending) {
    return <Loading />;
  }
  if (family.isError) {
    return (
      <Screen>
        <ErrorNote error={family.error} />
      </Screen>
    );
  }
  const data = family.data;
  const organizer = data.my_role === 'organizer';
  return (
    <Screen>
      <Stack.Screen options={{ title: data.name }} />
      {data.clock ? <Body muted>{t('family.clock', { timezone: data.clock.timezone })}</Body> : null}

      <Heading>{t('family.elders')}</Heading>
      {data.elders.length === 0 ? <Body muted>{t('family.no_elders')}</Body> : null}
      {data.elders.map((elder) => (
        <ElderRow key={elder.id} elder={elder} />
      ))}
      <Button
        label={t('family.add_elder')}
        onPress={() =>
          router.push({ pathname: '/family/[familyId]/add-elder', params: { familyId } })
        }
      />

      <Heading>{t('family.members')}</Heading>
      {data.members.map((member) => (
        <Row
          key={member.user_id}
          title={`${member.display_name ?? '—'}${member.user_id === me?.id ? ` ${t('common.you')}` : ''}`}
          subtitle={
            member.role === 'organizer' ? t('family.role_organizer') : t('family.role_member')
          }
        />
      ))}
      <Button
        variant="secondary"
        label={t('family.invite')}
        onPress={() => router.push({ pathname: '/family/[familyId]/invites', params: { familyId } })}
      />
      {organizer ? (
        <Button
          variant="secondary"
          label={t('family.pin')}
          onPress={() => router.push({ pathname: '/family/[familyId]/pin', params: { familyId } })}
        />
      ) : null}
    </Screen>
  );
}

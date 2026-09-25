import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useTranslation } from 'react-i18next';

import { useFamily } from '@/api/hooks';
import { useMe } from '@/auth/session';
import { Body, Button, ErrorNote, Heading, Loading, Row, Screen } from '@/components/ui';

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
        <Row
          key={elder.id}
          title={elder.relation_label ? `${elder.display_name} · ${elder.relation_label}` : elder.display_name}
          subtitle={elder.pause.paused ? t('family.paused') : t('family.pair_phone')}
          onPress={() =>
            router.push({ pathname: '/elder/[elderId]/pair', params: { elderId: elder.id } })
          }
        />
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

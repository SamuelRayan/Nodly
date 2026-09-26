import { router, Stack } from 'expo-router';
import { useTranslation } from 'react-i18next';

import { useFamilies } from '@/api/hooks';
import { useMe, useSession } from '@/auth/session';
import { Body, Button, ErrorNote, Loading, Row, Screen, Title } from '@/components/ui';

/** Your families (create, join, open one) and signing out. */
export default function Families() {
  const { t } = useTranslation();
  const { signOut } = useSession();
  const me = useMe().data;
  const families = useFamilies();

  return (
    <Screen>
      <Stack.Screen options={{ title: t('family.account') }} />
      <Title>{t('family.home_title')}</Title>
      {me?.display_name ? <Body muted>{me.email}</Body> : null}
      {families.isPending ? <Loading /> : null}
      <ErrorNote error={families.error} />
      {families.data?.length === 0 ? <Body>{t('family.none')}</Body> : null}
      {families.data?.map((family) => (
        <Row
          key={family.id}
          title={family.name}
          subtitle={
            family.my_role === 'organizer' ? t('family.role_organizer') : t('family.role_member')
          }
          onPress={() =>
            router.push({ pathname: '/family/[familyId]', params: { familyId: family.id } })
          }
        />
      ))}
      <Button label={t('family.create')} onPress={() => router.push('/create-family')} />
      <Button variant="secondary" label={t('family.join')} onPress={() => router.push('/join')} />
      <Button variant="secondary" label={t('family.sign_out')} onPress={() => void signOut()} />
    </Screen>
  );
}

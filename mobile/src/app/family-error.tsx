import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { useMe, useSession } from '@/auth/session';
import { Button, ErrorNote, Screen, Title } from '@/components/ui';
import { APP_NAME } from '@/config';

/** Signed in, but the profile couldn't be loaded (usually no connection to the API). */
export default function FamilyError() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { signOut } = useSession();
  const me = useMe();
  return (
    <Screen>
      <Title>{APP_NAME}</Title>
      <ErrorNote error={me.error} />
      <Button
        label={t('common.retry')}
        busy={me.isFetching}
        onPress={() => void queryClient.invalidateQueries({ queryKey: ['me'] })}
      />
      <Button variant="secondary" label={t('family.sign_out')} onPress={() => void signOut()} />
    </Screen>
  );
}

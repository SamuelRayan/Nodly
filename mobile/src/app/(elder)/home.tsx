import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { View } from 'react-native';

import { useDeviceMe } from '@/api/hooks';
import { Body, Button, ErrorNote, Loading, Screen, Title } from '@/components/ui';
import { applyLanguage } from '@/i18n';

/** Elder home (stub): a greeting and the big "I'm okay" button (wired up in Phase 4). */
export default function ElderHome() {
  const { t } = useTranslation();
  const me = useDeviceMe();
  const [thanked, setThanked] = useState(false);

  // The family chooses the elder's app language on their profile.
  const language = me.data?.elder.language;
  useEffect(() => {
    applyLanguage(language);
  }, [language]);

  if (me.isPending) {
    return <Loading />;
  }
  if (me.isError) {
    return (
      <Screen>
        <ErrorNote error={me.error} />
        <Button label={t('common.retry')} onPress={() => void me.refetch()} />
      </Screen>
    );
  }
  return (
    <Screen>
      <View style={{ flex: 1, justifyContent: 'center', gap: 24 }}>
        <Title>{t('elder.hello', { name: me.data.elder.display_name })}</Title>
        <Body muted>{t('elder.family_line', { family: me.data.family.name })}</Body>
        <Button large label={t('elder.okay')} onPress={() => setThanked(true)} />
        {thanked ? <Body>{t('elder.okay_thanks')}</Body> : null}
      </View>
      <Button variant="secondary" label={t('elder.this_phone')} onPress={() => router.push('/leave')} />
    </Screen>
  );
}

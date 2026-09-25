import { useTranslation } from 'react-i18next';
import { View } from 'react-native';

import { Body, Button, Screen, Title } from '@/components/ui';
import { APP_NAME } from '@/config';
import { useAppStore } from '@/state/app';

/** First launch: who is this phone for? Plain words, big buttons. */
export default function Welcome() {
  const { t } = useTranslation();
  const { notice, chooseMode } = useAppStore();

  return (
    <Screen>
      <View style={{ flex: 1, justifyContent: 'center', gap: 24 }}>
        <Title>{t('welcome.title', { app: APP_NAME })}</Title>
        <Body muted>{t('welcome.tagline')}</Body>
        {notice === 'device_revoked' ? <Body>{t('welcome.revoked')}</Body> : null}
        {notice === 'left_elder_mode' ? <Body>{t('welcome.left')}</Body> : null}
        <View style={{ gap: 8 }}>
          <Button
            label={t('welcome.elder')}
            onPress={() => void chooseMode('elder')}
          />
          <Body muted>{t('welcome.elder_hint')}</Body>
        </View>
        <View style={{ gap: 8 }}>
          <Button
            variant="secondary"
            label={t('welcome.family', { app: APP_NAME })}
            onPress={() => void chooseMode('family')}
          />
          <Body muted>{t('welcome.family_hint')}</Body>
        </View>
      </View>
    </Screen>
  );
}

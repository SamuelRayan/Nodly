import { router } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { supabase } from '@/auth/supabase';
import { Body, Button, ErrorNote, Field, Screen, Title } from '@/components/ui';
import { useAppStore } from '@/state/app';

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Family sign-in, step 1: email. Supabase emails a one-time code (no password). */
export default function SignIn() {
  const { t } = useTranslation();
  const chooseMode = useAppStore((state) => state.chooseMode);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    const address = email.trim().toLowerCase();
    if (!EMAIL.test(address)) {
      setError(t('errors.email_invalid'));
      return;
    }
    setBusy(true);
    setError(null);
    const { error: failure } = await supabase.auth.signInWithOtp({
      email: address,
      options: { shouldCreateUser: true },
    });
    setBusy(false);
    if (failure) {
      setError(failure.status === 429 ? t('errors.rate_limited') : t('errors.generic'));
      return;
    }
    router.push({ pathname: '/verify', params: { email: address } });
  };

  return (
    <Screen>
      <Title>{t('signIn.title')}</Title>
      <Body muted>{t('signIn.intro')}</Body>
      <Field
        label={t('signIn.email_label')}
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        autoComplete="email"
        keyboardType="email-address"
        textContentType="emailAddress"
        onSubmitEditing={() => void send()}
      />
      <ErrorNote error={error} />
      <Button label={t('signIn.send_code')} busy={busy} onPress={() => void send()} />
      <Button
        variant="secondary"
        label={t('signIn.not_family')}
        onPress={() => void chooseMode(null)}
      />
    </Screen>
  );
}

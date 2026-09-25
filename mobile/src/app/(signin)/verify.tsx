import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { OTP_PATTERN, supabase } from '@/auth/supabase';
import { Body, Button, ErrorNote, Field, Screen, Title } from '@/components/ui';

/** Family sign-in, step 2: the 6–8 digit code from the email. On success the root layout
 * moves on by itself (to onboarding or the family app). */
export default function Verify() {
  const { t } = useTranslation();
  const { email } = useLocalSearchParams<{ email: string }>();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const verify = async () => {
    const token = code.replace(/\s/g, '');
    if (!OTP_PATTERN.test(token)) {
      setError(t('errors.otp_invalid'));
      return;
    }
    setBusy(true);
    setError(null);
    const { error: failure } = await supabase.auth.verifyOtp({ email, token, type: 'email' });
    setBusy(false);
    if (failure) {
      setError(failure.status === 429 ? t('errors.rate_limited') : t('errors.otp_invalid'));
    }
  };

  const resend = async () => {
    setError(null);
    const { error: failure } = await supabase.auth.signInWithOtp({ email });
    if (failure) {
      setError(failure.status === 429 ? t('errors.rate_limited') : t('errors.generic'));
    }
  };

  return (
    <Screen>
      <Title>{t('signIn.code_title')}</Title>
      <Body muted>{t('signIn.code_sent', { email })}</Body>
      <Field
        label={t('signIn.code_label')}
        value={code}
        onChangeText={setCode}
        keyboardType="number-pad"
        autoComplete="one-time-code"
        textContentType="oneTimeCode"
        maxLength={10}
        onSubmitEditing={() => void verify()}
      />
      <ErrorNote error={error} />
      <Button label={t('signIn.verify')} busy={busy} onPress={() => void verify()} />
      <Button variant="secondary" label={t('signIn.resend')} onPress={() => void resend()} />
      <Button variant="secondary" label={t('signIn.other_email')} onPress={() => router.back()} />
    </Screen>
  );
}

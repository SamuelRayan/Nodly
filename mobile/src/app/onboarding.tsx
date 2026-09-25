import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Switch, View } from 'react-native';

import { api, unwrap } from '@/api/client';
import { useMe, useSession } from '@/auth/session';
import { CountryPicker, TimezonePicker } from '@/components/pickers';
import { Body, Button, ErrorNote, Field, Screen, Title } from '@/components/ui';
import { useTheme } from '@/theme';

/** Name, country, timezone (picked, never defaulted) and the 16+ confirmation. */
export default function Onboarding() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const queryClient = useQueryClient();
  const { signOut } = useSession();
  const me = useMe().data;
  const [name, setName] = useState(me?.display_name ?? '');
  const [country, setCountry] = useState<string | null>(me?.country_code ?? null);
  const [timezone, setTimezone] = useState<string | null>(me?.timezone ?? null);
  const [adult, setAdult] = useState(me?.age_confirmed ?? false);

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH('/v1/me', {
          body: {
            display_name: name.trim(),
            country_code: country,
            timezone,
            confirm_age_16_plus: adult ? true : undefined,
          },
        }),
      ),
    // The root layout moves on once /v1/me says onboarding is complete.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['me'] }),
  });

  const ready = name.trim().length > 0 && country !== null && timezone !== null && adult;

  return (
    <Screen>
      <Title>{t('onboarding.title')}</Title>
      <Body muted>{t('onboarding.intro')}</Body>
      <Field
        label={t('onboarding.name_label')}
        value={name}
        onChangeText={setName}
        autoComplete="name"
        maxLength={80}
      />
      <CountryPicker label={t('onboarding.country_label')} value={country} onChange={setCountry} />
      <TimezonePicker label={t('onboarding.timezone_label')} value={timezone} onChange={setTimezone} />
      <Body muted>{t('onboarding.timezone_hint')}</Body>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <Switch
          accessibilityLabel={t('onboarding.age')}
          value={adult}
          onValueChange={setAdult}
          trackColor={{ true: colors.ok, false: colors.border }}
        />
        <Body>{t('onboarding.age')}</Body>
      </View>
      <ErrorNote error={save.error} />
      <Button
        label={t('onboarding.save')}
        disabled={!ready}
        busy={save.isPending}
        onPress={() => save.mutate()}
      />
      <Button variant="secondary" label={t('family.sign_out')} onPress={() => void signOut()} />
    </Screen>
  );
}

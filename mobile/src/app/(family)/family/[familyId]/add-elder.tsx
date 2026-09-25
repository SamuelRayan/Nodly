import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, Text, View } from 'react-native';

import { api, unwrap } from '@/api/client';
import { keys } from '@/api/hooks';
import { CountryPicker, TimezonePicker } from '@/components/pickers';
import { Body, Button, ErrorNote, Field, Screen } from '@/components/ui';
import { SUPPORTED_LANGUAGES } from '@/i18n';
import { useTheme } from '@/theme';

const LANGUAGE_NAMES: Record<string, string> = { en: 'English' };

/** Add an elder: who they are, where they live, their timezone (picked), their app language. */
export default function AddElder() {
  const { t } = useTranslation();
  const { colors, scale } = useTheme();
  const queryClient = useQueryClient();
  const { familyId } = useLocalSearchParams<{ familyId: string }>();
  const [name, setName] = useState('');
  const [relation, setRelation] = useState('');
  const [country, setCountry] = useState<string | null>(null);
  const [timezone, setTimezone] = useState<string | null>(null);
  const [language, setLanguage] = useState<string | null>(null);

  const add = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/v1/families/{family_id}/elders', {
          params: { path: { family_id: familyId } },
          body: {
            display_name: name.trim(),
            relation_label: relation.trim() || null,
            country_code: country ?? '',
            timezone: timezone ?? '',
            language,
          },
        }),
      ),
    onSuccess: (elder) => {
      void queryClient.invalidateQueries({ queryKey: keys.family(familyId) });
      router.replace({ pathname: '/elder/[elderId]/pair', params: { elderId: elder.id } });
    },
  });

  const languages: (string | null)[] = [null, ...SUPPORTED_LANGUAGES];
  const ready = name.trim().length > 0 && country !== null && timezone !== null;
  return (
    <Screen>
      <Stack.Screen options={{ title: t('addElder.title') }} />
      <Field label={t('addElder.name_label')} value={name} onChangeText={setName} maxLength={80} />
      <Field
        label={t('addElder.relation_label')}
        placeholder={t('addElder.relation_placeholder')}
        value={relation}
        onChangeText={setRelation}
        maxLength={40}
      />
      <CountryPicker label={t('addElder.country_label')} value={country} onChange={setCountry} />
      <TimezonePicker label={t('addElder.timezone_label')} value={timezone} onChange={setTimezone} />
      <View style={{ gap: 6 }}>
        <Text style={{ color: colors.text, fontSize: scale.small, fontWeight: '600' }}>
          {t('addElder.language_label')}
        </Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {languages.map((option) => {
            const selected = option === language;
            return (
              <Pressable
                key={option ?? 'phone'}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                onPress={() => setLanguage(option)}
                style={{
                  minHeight: 44,
                  paddingHorizontal: 14,
                  justifyContent: 'center',
                  borderRadius: scale.radius,
                  borderWidth: 2,
                  borderColor: selected ? colors.ok : colors.border,
                  backgroundColor: colors.surface,
                }}
              >
                <Text style={{ color: colors.text, fontSize: scale.body }}>
                  {option ? (LANGUAGE_NAMES[option] ?? option) : t('addElder.language_phone')}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>
      <Body muted>{t('addElder.checkin_note', { remind: '09:00', due: '12:00' })}</Body>
      <ErrorNote error={add.error} />
      <Button
        label={t('addElder.save')}
        disabled={!ready}
        busy={add.isPending}
        onPress={() => add.mutate()}
      />
    </Screen>
  );
}

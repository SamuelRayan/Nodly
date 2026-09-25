import { useQuery } from '@tanstack/react-query';
import { getCalendars } from 'expo-localization';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FlatList, Modal, Pressable, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { api, unwrap } from '@/api/client';
import type { components } from '@/api/schema';
import { useTheme } from '@/theme';

import { Body, Button } from './ui';

type Country = components['schemas']['CountryOut'];
type Timezone = components['schemas']['TimezoneOut'];
type Suggestion = components['schemas']['TimezoneSuggestionOut'];

interface Item {
  key: string;
  label: string;
  detail?: string;
}

/** A button that opens a searchable list in a full-screen modal. */
function SearchPicker({
  label,
  placeholder,
  valueLabel,
  items,
  pinned,
  pinnedTitle,
  onChange,
}: {
  label: string;
  placeholder: string;
  valueLabel: string | undefined;
  items: Item[];
  pinned?: Item[];
  pinnedTitle?: string;
  onChange: (key: string) => void;
}) {
  const { t } = useTranslation();
  const { colors, scale } = useTheme();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const needle = search.trim().toLowerCase();
  const matches = (item: Item) =>
    !needle ||
    item.label.toLowerCase().includes(needle) ||
    item.key.toLowerCase().includes(needle);
  const shownPinned = needle ? [] : (pinned ?? []);
  const data = [...shownPinned, ...items.filter(matches)];

  const choose = (key: string) => {
    onChange(key);
    setOpen(false);
    setSearch('');
  };

  return (
    <View style={{ gap: 6 }}>
      <Text style={{ color: colors.text, fontSize: scale.small, fontWeight: '600' }}>{label}</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label}: ${valueLabel ?? placeholder}`}
        onPress={() => setOpen(true)}
        style={{
          minHeight: scale.buttonHeight,
          borderWidth: 2,
          borderColor: colors.border,
          borderRadius: scale.radius,
          paddingHorizontal: 12,
          justifyContent: 'center',
          backgroundColor: colors.surface,
        }}
      >
        <Text style={{ color: valueLabel ? colors.text : colors.textMuted, fontSize: scale.body }}>
          {valueLabel ?? placeholder}
        </Text>
      </Pressable>
      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <SafeAreaView style={{ flex: 1, backgroundColor: colors.background, padding: scale.space, gap: 12 }}>
          <TextInput
            accessibilityLabel={t('pickers.search')}
            placeholder={t('pickers.search')}
            placeholderTextColor={colors.textMuted}
            value={search}
            onChangeText={setSearch}
            autoFocus
            style={{
              minHeight: scale.buttonHeight,
              borderWidth: 2,
              borderColor: colors.border,
              borderRadius: scale.radius,
              paddingHorizontal: 12,
              color: colors.text,
              backgroundColor: colors.surface,
              fontSize: scale.body,
            }}
          />
          {shownPinned.length > 0 && pinnedTitle ? <Body muted>{pinnedTitle}</Body> : null}
          <FlatList
            data={data}
            keyExtractor={(item, index) => `${index < shownPinned.length ? 'pin' : 'all'}-${item.key}`}
            keyboardShouldPersistTaps="handled"
            ListEmptyComponent={<Body muted>{t('pickers.no_results')}</Body>}
            renderItem={({ item }) => (
              <Pressable
                accessibilityRole="button"
                onPress={() => choose(item.key)}
                style={{ minHeight: scale.buttonHeight, justifyContent: 'center', paddingVertical: 6, borderBottomWidth: 1, borderColor: colors.border }}
              >
                <Text style={{ color: colors.text, fontSize: scale.body }}>{item.label}</Text>
                {item.detail ? (
                  <Text style={{ color: colors.textMuted, fontSize: scale.small }}>{item.detail}</Text>
                ) : null}
              </Pressable>
            )}
          />
          <Button variant="secondary" label={t('common.close')} onPress={() => setOpen(false)} />
        </SafeAreaView>
      </Modal>
    </View>
  );
}

export function useCountries() {
  return useQuery({
    queryKey: ['meta', 'countries'],
    queryFn: () => unwrap(api.GET('/v1/meta/countries')),
    staleTime: Infinity,
  });
}

function countryLabel(country: Country) {
  return `${country.flag} ${country.name}`;
}

export function CountryPicker({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | null;
  onChange: (code: string) => void;
}) {
  const { t } = useTranslation();
  const data = useCountries().data;
  const countries = useMemo(() => data?.countries ?? [], [data]);
  const selected = countries.find((country) => country.code === value);
  const items = useMemo(
    () => countries.map((country) => ({ key: country.code, label: countryLabel(country) })),
    [countries],
  );
  return (
    <SearchPicker
      label={label}
      placeholder={t('pickers.choose_country')}
      valueLabel={selected ? countryLabel(selected) : undefined}
      items={items}
      onChange={onChange}
    />
  );
}

/** The phone's own timezone setting (a suggestion only; never applied silently). */
export function deviceTimezone(): string | undefined {
  return getCalendars()[0]?.timeZone ?? undefined;
}

function timezoneItem(zone: Timezone, detail?: string): Item {
  return { key: zone.id, label: `${zone.label} (UTC${zone.utc_offset})`, detail: detail ?? zone.id };
}

export function TimezonePicker({
  label,
  value,
  onChange,
  phone,
}: {
  label: string;
  value: string | null;
  onChange: (zone: string) => void;
  /** An E.164 number to base extra suggestions on (e.g. the elder's). */
  phone?: string;
}) {
  const { t } = useTranslation();
  const device = deviceTimezone();
  const all = useQuery({
    queryKey: ['meta', 'timezones'],
    queryFn: () => unwrap(api.GET('/v1/meta/timezones')),
    staleTime: 60 * 60 * 1000,
  });
  const suggestions = useQuery({
    queryKey: ['meta', 'timezones', 'suggest', device, phone],
    queryFn: () =>
      unwrap(
        api.GET('/v1/meta/timezones/suggest', {
          params: { query: { device_timezone: device, phone: phone || undefined } },
        }),
      ),
    staleTime: Infinity,
  });
  const zones = all.data?.timezones ?? [];
  const reasons: Record<Suggestion['reason'], string> = {
    device: t('pickers.reason_device'),
    phone_number: t('pickers.reason_phone_number'),
    phone_country: t('pickers.reason_phone_country'),
  };
  const pinned = (suggestions.data?.suggestions ?? []).map((s) => timezoneItem(s, reasons[s.reason]));
  const selected = zones.find((zone) => zone.id === value);
  return (
    <SearchPicker
      label={label}
      placeholder={t('pickers.choose_timezone')}
      valueLabel={selected ? timezoneItem(selected).label : (value ?? undefined)}
      items={zones.map((zone) => timezoneItem(zone))}
      pinned={pinned}
      pinnedTitle={t('pickers.suggested')}
      onChange={onChange}
    />
  );
}

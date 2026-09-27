import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Image, Pressable, View } from 'react-native';

import { useFamilyMoments } from '@/api/hooks';
import { Icon } from '@/components/icons';
import { Body, Button, ErrorNote, Loading, Pill, Screen, T } from '@/components/ui';
import { duration } from '@/lib/format';
import { mediaUrl } from '@/moments/prepare';
import { useMomentQueue } from '@/moments/queue';
import { useTheme } from '@/theme';

/** Everything the family has shared, newest first (a grid; tap one to open it). */
export default function Moments() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const { familyId } = useLocalSearchParams<{ familyId: string }>();
  const moments = useFamilyMoments(familyId);
  // Still on their way from this phone. (Select the stored list and filter here: a selector
  // that builds a new array each call makes zustand v5 re-render forever.)
  const queued = useMomentQueue((state) => state.items);
  const sending = queued.filter(
    (item) => item.familyId === familyId && item.state !== 'posted' && item.state !== 'rejected',
  );

  if (moments.isPending) {
    return <Loading />;
  }
  const items = (moments.data?.items ?? []).filter((moment) => moment.status === 'published');
  return (
    <Screen>
      <Stack.Screen options={{ title: t('moments.title') }} />
      <ErrorNote error={moments.error} />
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Button
          icon="photo"
          label={t('moments.photo')}
          onPress={() => router.push({ pathname: '/share', params: { familyId } })}
          style={{ flex: 1 }}
        />
        <Button
          variant="secondary"
          icon="mic"
          label={t('moments.voice')}
          onPress={() => router.push({ pathname: '/share', params: { familyId, mode: 'voice' } })}
          style={{ flex: 1 }}
        />
      </View>
      {sending.map((item) => (
        <View
          key={item.localId}
          style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, borderRadius: 16, backgroundColor: colors.sand }}
        >
          {item.kind === 'voice' ? (
            <View style={{ width: 48, height: 48, borderRadius: 10, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.surface }}>
              <Icon name="mic" size={24} color={colors.onSand} />
            </View>
          ) : (
            <Image source={{ uri: item.fileUri }} style={{ width: 48, height: 48, borderRadius: 10 }} />
          )}
          <T size={15} color={colors.onSand} style={{ flex: 1 }}>
            {item.waiting ? t('moments.offline_title') : t(`moments.state_${item.state}` as 'moments.state_queued', { name: '' })}
          </T>
        </View>
      ))}
      {items.length === 0 && sending.length === 0 ? <Body muted>{t('moments.empty')}</Body> : null}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
        {items.map((moment) => (
          <Pressable
            key={moment.id}
            accessibilityRole="button"
            accessibilityLabel={
              moment.kind === 'voice'
                ? `${t('moments.voice_note')}, ${t('moments.from', { name: moment.author_name ?? '' })}`
                : t('moments.from', { name: moment.author_name ?? '' })
            }
            onPress={() => router.push({ pathname: '/moment/[momentId]', params: { momentId: moment.id } })}
            style={{ width: '31.5%', aspectRatio: 1, borderRadius: 14, overflow: 'hidden', backgroundColor: colors.neutralTint }}
          >
            {moment.kind === 'voice' ? (
              <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 6, backgroundColor: colors.sand }}>
                <Icon name="mic" size={30} color={colors.onSand} />
                <T size={14} weight="bold" color={colors.onSand}>
                  {duration(moment.duration_ms ?? 0)}
                </T>
              </View>
            ) : (
              <Image source={{ uri: mediaUrl(moment.thumbnail_url) }} style={{ flex: 1 }} resizeMode="cover" />
            )}
            {moment.hearts > 0 ? (
              <View style={{ position: 'absolute', left: 6, bottom: 6 }}>
                <Pill icon="heart" label={String(moment.hearts)} background={colors.surface} color={colors.helpText} />
              </View>
            ) : null}
            {moment.qualifies ? (
              <View style={{ position: 'absolute', right: 6, top: 6, backgroundColor: colors.ok, borderRadius: 12, padding: 3 }}>
                <Icon name="check" size={14} color={colors.onOk} strokeWidth={3} />
              </View>
            ) : null}
          </Pressable>
        ))}
      </View>
    </Screen>
  );
}

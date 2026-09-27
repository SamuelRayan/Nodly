import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Image, Pressable, View } from 'react-native';

import { useFamilyMoments } from '@/api/hooks';
import { Icon } from '@/components/icons';
import { Body, Button, ErrorNote, Loading, Pill, Screen, T } from '@/components/ui';
import { mediaUrl } from '@/moments/prepare';
import { useMomentQueue } from '@/moments/queue';
import { useTheme } from '@/theme';

/** Everything the family has shared, newest first (a grid; tap one to open it). */
export default function Moments() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const { familyId } = useLocalSearchParams<{ familyId: string }>();
  const moments = useFamilyMoments(familyId);
  // Still on their way from this phone.
  const sending = useMomentQueue((state) =>
    state.items.filter(
      (item) => item.familyId === familyId && item.state !== 'posted' && item.state !== 'rejected',
    ),
  );

  if (moments.isPending) {
    return <Loading />;
  }
  const items = (moments.data?.items ?? []).filter((moment) => moment.status === 'published');
  return (
    <Screen>
      <Stack.Screen options={{ title: t('moments.title') }} />
      <ErrorNote error={moments.error} />
      <Button
        icon="photo"
        label={t('moments.take_photo')}
        onPress={() => router.push({ pathname: '/share', params: { familyId } })}
      />
      {sending.map((item) => (
        <View
          key={item.localId}
          style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, borderRadius: 16, backgroundColor: colors.sand }}
        >
          <Image source={{ uri: item.fileUri }} style={{ width: 48, height: 48, borderRadius: 10 }} />
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
            accessibilityLabel={`${t('moments.from', { name: moment.author_name ?? '' })}`}
            onPress={() => router.push({ pathname: '/moment/[momentId]', params: { momentId: moment.id } })}
            style={{ width: '31.5%', aspectRatio: 1, borderRadius: 14, overflow: 'hidden', backgroundColor: colors.neutralTint }}
          >
            <Image source={{ uri: mediaUrl(moment.thumbnail_url) }} style={{ flex: 1 }} resizeMode="cover" />
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

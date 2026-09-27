import * as Haptics from 'expo-haptics';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Image, View } from 'react-native';

import { useDeviceMe, useDeviceMoments, useMomentActions } from '@/api/hooks';
import { Avatar, Button, ErrorNote, Loading, PillButton, Screen, T, Title } from '@/components/ui';
import { VoicePlayer } from '@/components/voice';
import { dateTime } from '@/lib/format';
import { pickPhoto } from '@/moments/pick';
import { mediaUrl, preparePhoto } from '@/moments/prepare';
import { enqueuePhoto } from '@/moments/queue';
import { useTheme } from '@/theme';

/**
 * The elder's moments (design E5, E6): one at a time, new ones first, huge Previous/Next
 * buttons (never swipe-only, CLAUDE.md §9), "Send love", and a big camera button at the end.
 */
export default function ElderMoments() {
  const { t } = useTranslation();
  const { colors, scale } = useTheme();
  const me = useDeviceMe();
  const feed = useDeviceMoments();
  const { heart, view } = useMomentActions(true);
  const [index, setIndex] = useState(0);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const published = (feed.data?.items ?? []).filter(
    (moment) => moment.status === 'published' && !moment.is_mine,
  );
  // New ones first (oldest new first, so the story reads in order), then the rest. The order
  // is fixed when the feed first loads, so marking one seen doesn't reshuffle the list.
  const [order, setOrder] = useState<string[] | null>(null);
  if (order === null && feed.data) {
    const unseen = published.filter((moment) => !moment.viewed_by_me).reverse();
    const seen = published.filter((moment) => moment.viewed_by_me);
    setOrder([...unseen, ...seen].map((moment) => moment.id));
  }
  const list = order ?? [];
  const current = published.find((moment) => moment.id === list[index]);

  const { mutate: markViewed } = view;
  const currentId = current?.id;
  const currentSeen = current?.viewed_by_me;
  useEffect(() => {
    if (currentId && currentSeen === false) {
      markViewed(currentId);
    }
  }, [currentId, currentSeen, markViewed]);

  if (feed.isPending || me.isPending) {
    return <Loading />;
  }
  const tz = me.data?.elder.timezone ?? 'UTC';

  const share = async () => {
    setError(null);
    const photo = await pickPhoto('camera');
    if (photo === 'denied') {
      setError(t('moments.camera_denied'));
      return;
    }
    if (photo) {
      enqueuePhoto(await preparePhoto(photo.uri, photo.width, photo.height), null);
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      setSent(true);
    }
  };

  const close = <PillButton label={t('moments.close')} icon="close" onPress={() => router.back()} />;

  if (!current) {
    return (
      <Screen>
        {close}
        <View style={{ flex: 1, justifyContent: 'center', gap: 16 }}>
          <Title>{sent ? t('moments.elder_sent') : t('moments.all_seen_title')}</Title>
          <T color={colors.textMuted}>{t('moments.all_seen_line')}</T>
        </View>
        <ErrorNote error={error} />
        {index > 0 ? (
          <Button
            variant="secondary"
            icon="arrowLeft"
            label={t('moments.previous')}
            onPress={() => setIndex(index - 1)}
          />
        ) : null}
        <Button icon="photo" label={t('moments.elder_share')} onPress={() => void share()} />
      </Screen>
    );
  }

  return (
    <Screen scroll={false}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        {close}
        <T size={20} color={colors.textMuted}>
          {t('moments.of', { index: index + 1, total: list.length })}
        </T>
      </View>
      {current.kind === 'voice' && current.url ? (
        <View style={{ flex: 1, justifyContent: 'center' }}>
          <VoicePlayer
            key={current.id}
            url={mediaUrl(current.url)}
            durationMs={current.duration_ms}
            label={t('moments.play_from', { name: current.author_name?.split(' ')[0] ?? '' })}
            big
          />
        </View>
      ) : (
        <View style={{ flex: 1, borderRadius: 28, overflow: 'hidden', backgroundColor: colors.neutralTint }}>
          <Image source={{ uri: mediaUrl(current.url) }} style={{ flex: 1 }} resizeMode="cover" />
        </View>
      )}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
        <Avatar name={current.author_name ?? '?'} size={56} />
        <View style={{ flex: 1 }}>
          <T size={26} weight="bold">
            {t('moments.from', { name: current.author_name?.split(' ')[0] ?? '' })}
          </T>
          <T size={scale.small - 1} color={colors.textMuted}>
            {current.published_at ? dateTime(current.published_at, tz) : ''}
          </T>
        </View>
      </View>
      <ErrorNote error={heart.error} />
      <View style={{ flexDirection: 'row', gap: 12 }}>
        <Button
          variant="secondary"
          icon="heart"
          label={current.hearted_by_me ? t('moments.love_sent') : t('moments.send_love')}
          busy={heart.isPending}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            heart.mutate({ id: current.id, on: !current.hearted_by_me });
          }}
          style={{ flex: 1, backgroundColor: colors.sand, borderWidth: 0, minHeight: 76 }}
        />
        <Button
          variant="ink"
          icon="arrowRight"
          iconAfter
          label={t('moments.next')}
          onPress={() => setIndex(index + 1)}
          style={{ flex: 1, minHeight: 76 }}
        />
      </View>
      {index > 0 ? (
        <Button
          variant="plain"
          icon="arrowLeft"
          label={t('moments.previous')}
          onPress={() => setIndex(index - 1)}
        />
      ) : null}
    </Screen>
  );
}

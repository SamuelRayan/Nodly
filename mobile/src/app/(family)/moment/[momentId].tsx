import { useQuery } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Image, View } from 'react-native';

import { api, unwrap } from '@/api/client';
import { keys, useMomentActions } from '@/api/hooks';
import { Avatar, Button, ErrorNote, Loading, Pill, Screen, T } from '@/components/ui';
import { dateTime } from '@/lib/format';
import { mediaUrl } from '@/moments/prepare';
import { useTheme } from '@/theme';

/** One moment, full size, with its hearts. */
export default function MomentViewer() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const { momentId } = useLocalSearchParams<{ momentId: string }>();
  const moment = useQuery({
    queryKey: keys.moment(momentId),
    queryFn: () =>
      unwrap(api.GET('/v1/moments/{moment_id}', { params: { path: { moment_id: momentId } } })),
  });
  const { heart, view } = useMomentActions(false);
  const { mutate: markViewed } = view;
  const seen = moment.data?.viewed_by_me;

  useEffect(() => {
    if (seen === false) {
      markViewed(momentId);
    }
  }, [seen, markViewed, momentId]);

  if (moment.isPending) {
    return <Loading />;
  }
  if (moment.isError) {
    return (
      <Screen>
        <ErrorNote error={moment.error} />
      </Screen>
    );
  }
  const data = moment.data;
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return (
    <Screen>
      <Stack.Screen options={{ title: t('moments.from', { name: data.author_name ?? '' }) }} />
      <View style={{ flex: 1, minHeight: 360, borderRadius: 24, overflow: 'hidden', backgroundColor: colors.neutralTint }}>
        <Image source={{ uri: mediaUrl(data.url) }} style={{ flex: 1 }} resizeMode="contain" />
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <Avatar name={data.author_name ?? '?'} />
        <View style={{ flex: 1 }}>
          <T weight="bold">{data.author_name ?? ''}</T>
          <T size={14} color={colors.textMuted}>
            {data.published_at ? dateTime(data.published_at, tz) : ''}
          </T>
        </View>
        {data.qualifies ? (
          <Pill icon="check" label={t('moments.counts')} background={colors.okTint} color={colors.okText} />
        ) : null}
      </View>
      <ErrorNote error={heart.error} />
      <Button
        variant={data.hearted_by_me ? 'secondary' : 'primary'}
        icon="heart"
        label={
          data.hearts > 0
            ? `${data.hearted_by_me ? t('moments.love_sent') : t('moments.send_love')} · ${data.hearts}`
            : t('moments.send_love')
        }
        busy={heart.isPending}
        onPress={() =>
          heart.mutate(
            { id: data.id, on: !data.hearted_by_me },
            { onSuccess: () => void moment.refetch() },
          )
        }
      />
    </Screen>
  );
}

import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Image, Pressable, View } from 'react-native';

import { useFamily } from '@/api/hooks';
import { elderName } from '@/components/family';
import { type IconName, Icon } from '@/components/icons';
import { Button, ErrorNote, Pill, Screen, T, Title } from '@/components/ui';
import { VOICE_COUNTS_FROM_MS, VoicePlayer, VoiceRecorder } from '@/components/voice';
import { type PickedPhoto, pickPhoto } from '@/moments/pick';
import { preparePhoto } from '@/moments/prepare';
import { enqueuePhoto, enqueueVoice, type QueueItem, useMomentQueue } from '@/moments/queue';
import { useTheme } from '@/theme';

const STEPS = ['queued', 'uploading', 'checking', 'posted'] as const;

type Mode = 'photo' | 'voice';

interface Recording {
  uri: string;
  durationMs: number;
}

/** Share a moment (design F3 → F4 → F5, or F6 when offline): a photo or a voice note. */
export default function Share() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const { familyId, mode: startMode } = useLocalSearchParams<{ familyId: string; mode?: Mode }>();
  const family = useFamily(familyId);
  const [mode, setMode] = useState<Mode>(startMode === 'voice' ? 'voice' : 'photo');
  const [picked, setPicked] = useState<PickedPhoto | null>(null);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [localId, setLocalId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const item = useMomentQueue((state) => state.items.find((entry) => entry.localId === localId));

  const primary = family.data?.elders.find((elder) => elder.is_primary) ?? family.data?.elders[0];
  const name = primary ? elderName(primary) : (family.data?.name ?? '');

  const choose = async (source: 'camera' | 'library') => {
    setError(null);
    const photo = await pickPhoto(source);
    if (photo === 'denied') {
      setError(t('moments.camera_denied'));
    } else if (photo) {
      setPicked(photo);
    }
  };

  const send = async () => {
    setBusy(true);
    try {
      if (mode === 'voice' && recording) {
        setLocalId(enqueueVoice(recording.uri, familyId, recording.durationMs).localId);
      } else if (picked) {
        const prepared = await preparePhoto(picked.uri, picked.width, picked.height);
        setLocalId(enqueuePhoto(prepared, familyId).localId);
      }
    } catch {
      setError(t('errors.generic'));
    } finally {
      setBusy(false);
    }
  };

  const header = (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
      <Button
        variant="secondary"
        icon="close"
        label={t('common.close')}
        onPress={() => router.back()}
        style={{ minHeight: 46, paddingHorizontal: 14 }}
      />
      <Title size={24}>{t('moments.share_title', { name })}</Title>
    </View>
  );

  if (item) {
    return (
      <Screen>
        <Stack.Screen options={{ headerShown: false }} />
        {header}
        <Progress item={item} name={name} preview={item.kind === 'photo' ? picked?.uri : undefined} />
        {item.state === 'posted' || item.state === 'rejected' ? (
          <View style={{ gap: 10 }}>
            <Button variant="ink" label={t('moments.done')} onPress={() => router.back()} />
            <Button
              variant="secondary"
              label={t('moments.share_another')}
              onPress={() => {
                setPicked(null);
                setRecording(null);
                setLocalId(null);
              }}
            />
          </View>
        ) : (
          <T center size={15} color={colors.textMuted}>
            {t('moments.leave_ok')}
          </T>
        )}
      </Screen>
    );
  }

  return (
    <Screen>
      <Stack.Screen options={{ headerShown: false }} />
      {header}
      <View style={{ flexDirection: 'row', gap: 4, padding: 4, borderRadius: 16, backgroundColor: colors.neutralTint }}>
        <ModeTab icon="photo" label={t('moments.photo')} on={mode === 'photo'} onPress={() => setMode('photo')} />
        <ModeTab icon="mic" label={t('moments.voice')} on={mode === 'voice'} onPress={() => setMode('voice')} />
      </View>

      {mode === 'voice' ? (
        recording ? (
          <View style={{ flex: 1, minHeight: 320, justifyContent: 'center', gap: 16 }}>
            <VoicePlayer
              key={recording.uri}
              url={recording.uri}
              durationMs={recording.durationMs}
              label={t('moments.play_yours')}
              big
            />
            <Button
              variant="secondary"
              icon="refresh"
              label={t('moments.record_again')}
              onPress={() => setRecording(null)}
            />
          </View>
        ) : (
          <VoiceRecorder
            onRecorded={(uri, durationMs) => {
              setError(null);
              setRecording({ uri, durationMs });
            }}
            onError={setError}
          />
        )
      ) : picked ? (
        <View style={{ flex: 1, minHeight: 320, borderRadius: 24, overflow: 'hidden' }}>
          <Image source={{ uri: picked.uri }} style={{ flex: 1 }} resizeMode="cover" />
          <View style={{ position: 'absolute', right: 14, bottom: 14 }}>
            <Button
              variant="secondary"
              icon="refresh"
              label={t('moments.change')}
              onPress={() => void choose('library')}
              style={{ minHeight: 44, borderWidth: 0 }}
            />
          </View>
        </View>
      ) : (
        <View style={{ flex: 1, justifyContent: 'center', gap: 12 }}>
          <Button icon="photo" label={t('moments.take_photo')} onPress={() => void choose('camera')} />
          <Button
            variant="secondary"
            label={t('moments.choose_photo')}
            onPress={() => void choose('library')}
          />
        </View>
      )}

      <ErrorNote error={error} />
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: 12,
          padding: 14,
          borderRadius: 16,
          backgroundColor: colors.sand,
        }}
      >
        <Icon name="checkCircle" size={22} color={colors.onSand} />
        <T size={15} color={colors.onSand} style={{ flex: 1 }}>
          {mode === 'voice' && recording && recording.durationMs < VOICE_COUNTS_FROM_MS
            ? t('moments.voice_short_note')
            : t('moments.counts_note')}
        </T>
      </View>
      {(mode === 'photo' && picked) || (mode === 'voice' && recording) ? (
        <Button
          label={t('moments.send_to', { name })}
          icon="arrowRight"
          iconAfter
          busy={busy}
          onPress={() => void send()}
        />
      ) : null}
    </Screen>
  );
}

function ModeTab({
  icon,
  label,
  on,
  onPress,
}: {
  icon: IconName;
  label: string;
  on: boolean;
  onPress: () => void;
}) {
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityState={{ selected: on }}
      onPress={onPress}
      style={{
        flex: 1,
        height: 44,
        borderRadius: 12,
        backgroundColor: on ? colors.ink : 'transparent',
        flexDirection: 'row',
        gap: 7,
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Icon name={icon} size={20} color={on ? colors.onInk : colors.textMuted} />
      <T size={16} weight="bold" color={on ? colors.onInk : colors.textMuted}>
        {label}
      </T>
    </Pressable>
  );
}

function Progress({ item, name, preview }: { item: QueueItem; name: string; preview?: string }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const done = item.state === 'posted';

  if (item.state === 'rejected') {
    return (
      <View style={{ flex: 1, justifyContent: 'center', gap: 16 }}>
        <ErrorNote error={t(`moments.rejected_${item.rejectReason ?? 'upload_missing'}` as 'moments.rejected_upload_missing')} />
      </View>
    );
  }
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 18 }}>
      {preview ? (
        <View style={{ width: 216, height: 264, borderRadius: 24, overflow: 'hidden', transform: [{ rotate: '-3deg' }], borderWidth: 6, borderColor: colors.surface }}>
          <Image source={{ uri: preview }} style={{ flex: 1 }} resizeMode="cover" />
        </View>
      ) : item.kind === 'voice' ? (
        <View style={{ width: 168, height: 168, borderRadius: 84, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.sand }}>
          <Icon name="mic" size={64} color={colors.onSand} strokeWidth={2} />
        </View>
      ) : null}
      {done ? (
        <>
          <Title center size={36}>
            {t('moments.sent_title', { name })}
          </Title>
          {item.qualifies ? (
            <View style={{ alignSelf: 'center' }}>
              <Pill icon="check" label={t('moments.counts')} background={colors.ok} color={colors.onOk} />
            </View>
          ) : null}
          <T center size={17} color={colors.textMuted} style={{ maxWidth: 300 }}>
            {item.qualifies || !item.notQualifyingReason
              ? t('moments.sent_line', { name })
              : t(`moments.not_counting_${item.notQualifyingReason}` as 'moments.not_counting_late')}
          </T>
        </>
      ) : item.waiting ? (
        <>
          <Title center size={28}>
            {t('moments.offline_title')}
          </Title>
          <T center size={17} color={colors.textMuted} style={{ maxWidth: 300 }}>
            {t('moments.offline_line')}
          </T>
        </>
      ) : (
        <>
          <Title center size={28}>
            {t(`moments.state_${item.state}` as 'moments.state_queued', { name })}
          </Title>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            {STEPS.map((step) => {
              const reached = STEPS.indexOf(step) <= STEPS.findIndex((s) => s === item.state);
              return (
                <View
                  key={step}
                  style={{
                    width: 48,
                    height: 8,
                    borderRadius: 4,
                    backgroundColor: reached ? colors.ok : colors.border,
                  }}
                />
              );
            })}
          </View>
        </>
      )}
    </View>
  );
}

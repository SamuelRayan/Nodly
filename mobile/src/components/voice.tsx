import {
  type RecordingOptions,
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioPlayer,
  useAudioPlayerStatus,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import * as Haptics from 'expo-haptics';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, View } from 'react-native';

import { Icon } from '@/components/icons';
import { T } from '@/components/ui';
import { duration } from '@/lib/format';
import { useTheme } from '@/theme';

/** §9: voice notes up to 5 minutes; §10: they count for the day from 10 seconds. The server
 * measures and decides both; these only guide the person recording. */
export const VOICE_MAX_MS = 5 * 60 * 1000;
export const VOICE_COUNTS_FROM_MS = 10 * 1000;

// Mono AAC in .m4a at 64 kbps: clear for a voice, about 2.4 MB for 5 minutes. Metering drives
// the live waveform while recording.
const VOICE_PRESET: RecordingOptions = {
  ...RecordingPresets.HIGH_QUALITY,
  numberOfChannels: 1,
  bitRate: 64_000,
  isMeteringEnabled: true,
};

// The design's waveform (decorative: the real sound isn't analysed).
const BARS = [10, 18, 26, 14, 22, 30, 18, 12, 24, 16, 28, 20, 10, 22, 16, 26, 12, 18, 8];

function Waveform({
  heights,
  scale = 1,
  played = 0,
  color,
  dim,
}: {
  heights: number[];
  scale?: number;
  /** 0–1: bars before this point are drawn in `color`, the rest in `dim`. */
  played?: number;
  color: string;
  dim?: string;
}) {
  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{ flexDirection: 'row', alignItems: 'center', gap: 3 * scale, height: 30 * scale }}
    >
      {heights.map((height, index) => (
        <View
          key={index}
          style={{
            width: 4 * scale,
            height: Math.max(4, height) * scale,
            borderRadius: 2 * scale,
            backgroundColor: dim && index / heights.length >= played ? dim : color,
          }}
        />
      ))}
    </View>
  );
}

function PlayCircle({
  playing,
  size,
  label,
  onPress,
}: {
  playing: boolean;
  size: number;
  label: string;
  onPress: () => void;
}) {
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => ({
        width: size + 20,
        height: size + 20,
        borderRadius: (size + 20) / 2,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: `${colors.onSand}26`,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <View
        style={{
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: colors.ink,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Icon name={playing ? 'pause' : 'play'} size={size * 0.42} color={colors.onInk} />
      </View>
    </Pressable>
  );
}

/**
 * A voice note on its sand card (design E5/F9): a big play/pause button, the waveform filling
 * as it plays, and the time. Give it a `key` per moment: the link is read once, so the signed
 * URL changing on a refetch doesn't restart what's playing.
 */
export function VoicePlayer({
  url,
  durationMs,
  label,
  big = false,
}: {
  url: string;
  durationMs: number | null | undefined;
  /** What the button says to a screen reader, e.g. "Play voice note from Priya". */
  label: string;
  /** The elder's size (§15). */
  big?: boolean;
}) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const [source] = useState(() => ({ uri: url }));
  const player = useAudioPlayer(source, { updateInterval: 250 });
  const status = useAudioPlayerStatus(player);

  useEffect(() => {
    // Play through the speaker even with the ringer off (iOS); harmless on Android.
    void setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false });
  }, []);
  const total = status.duration > 0 ? status.duration * 1000 : (durationMs ?? 0);
  const at = status.currentTime * 1000;
  const atEnd = total > 0 && at >= total - 150;

  const toggle = () => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    if (status.playing) {
      player.pause();
      return;
    }
    if (atEnd || status.didJustFinish) {
      void player.seekTo(0).then(() => player.play());
      return;
    }
    player.play();
  };

  const showing = status.playing || (at > 0 && !atEnd) ? at : total;
  return (
    <View
      style={{
        flexDirection: big ? 'column' : 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: big ? 22 : 16,
        padding: big ? 24 : 18,
        borderRadius: 28,
        backgroundColor: colors.sand,
      }}
    >
      <PlayCircle
        playing={status.playing}
        size={big ? 104 : 72}
        label={status.playing ? t('moments.pause') : label}
        onPress={toggle}
      />
      <View style={{ gap: 8, alignItems: big ? 'center' : 'flex-start', flexShrink: 1 }}>
        <Waveform
          heights={BARS}
          scale={big ? 1.5 : 1}
          played={total > 0 ? at / total : 0}
          color={colors.onSand}
          dim={status.playing || at > 0 ? `${colors.onSand}55` : undefined}
        />
        <T size={big ? 22 : 16} weight="bold" color={colors.onSand}>
          {t('moments.voice_length', { time: duration(showing) })}
        </T>
      </View>
    </View>
  );
}

/**
 * Record a voice note: tap to start, tap to stop (never hold-to-talk). Shows the time, a live
 * waveform, and whether it's long enough to count for today. Stops by itself at 5 minutes.
 */
export function VoiceRecorder({
  onRecorded,
  onError,
}: {
  onRecorded: (uri: string, durationMs: number) => void;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const recorder = useAudioRecorder(VOICE_PRESET);
  const state = useAudioRecorderState(recorder, 100);
  const [starting, setStarting] = useState(false);
  const stopping = useRef(false);
  const recording = state.isRecording;

  // The live waveform: one bar per status poll, newest on the right. Metering is in dBFS
  // (-60 quiet … 0 loud). Updated while rendering, once per new poll.
  const [wave, setWave] = useState({ at: -1, levels: BARS.map(() => 6) });
  if (recording && state.metering !== undefined && state.durationMillis !== wave.at) {
    const loud = Math.min(1, Math.max(0, (state.metering + 60) / 60));
    setWave({ at: state.durationMillis, levels: [...wave.levels.slice(1), 6 + loud * 26] });
  }
  const levels = wave.levels;

  const start = async () => {
    setStarting(true);
    try {
      const permission = await requestRecordingPermissionsAsync();
      if (!permission.granted) {
        onError(t('moments.mic_denied'));
        return;
      }
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
      stopping.current = false;
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    } catch {
      onError(t('errors.generic'));
    } finally {
      setStarting(false);
    }
  };

  const stop = async () => {
    if (stopping.current) {
      return;
    }
    stopping.current = true;
    const length = recorder.getStatus().durationMillis;
    try {
      await recorder.stop();
      await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      if (recorder.uri) {
        onRecorded(recorder.uri, length);
      } else {
        onError(t('errors.generic'));
      }
    } catch {
      onError(t('errors.generic'));
    }
  };

  // Stop just inside the limit, so the file is never over it.
  const elapsed = state.durationMillis;
  useEffect(() => {
    if (recording && elapsed >= VOICE_MAX_MS - 1000) {
      void stop();
    }
  });

  const longEnough = elapsed >= VOICE_COUNTS_FROM_MS;
  return (
    <View
      style={{
        flex: 1,
        minHeight: 320,
        borderRadius: 24,
        backgroundColor: colors.sand,
        alignItems: 'center',
        justifyContent: 'center',
        gap: 20,
        padding: 20,
      }}
    >
      <T size={44} weight="bold" color={colors.onSand} style={{ fontVariant: ['tabular-nums'] }}>
        {duration(elapsed)}
      </T>
      <Waveform heights={recording ? levels : BARS} scale={1.4} color={colors.onSand} />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={recording ? t('moments.record_stop') : t('moments.record_start')}
        disabled={starting}
        onPress={() => void (recording ? stop() : start())}
        style={({ pressed }) => ({
          width: 112,
          height: 112,
          borderRadius: 56,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: recording ? colors.ink : colors.ok,
          borderWidth: 10,
          borderColor: `${colors.onSand}26`,
          opacity: pressed || starting ? 0.85 : 1,
        })}
      >
        <Icon
          name={recording ? 'stop' : 'mic'}
          size={recording ? 36 : 44}
          color={recording ? colors.onInk : colors.onOk}
          strokeWidth={2.4}
        />
      </Pressable>
      <T center size={16} weight="bold" color={colors.onSand}>
        {recording ? t('moments.recording') : t('moments.record_start')}
      </T>
      <T center size={15} color={colors.onSand} style={{ maxWidth: 280 }}>
        {!recording
          ? t('moments.record_hint')
          : longEnough
            ? t('moments.record_long_enough')
            : t('moments.record_keep_going')}
      </T>
    </View>
  );
}

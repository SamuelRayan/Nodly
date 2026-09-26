import { useNetInfo } from '@react-native-community/netinfo';
import * as Haptics from 'expo-haptics';
import { router } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Text, View } from 'react-native';
import Svg, { Circle } from 'react-native-svg';

import { useAskHelp, useDeviceToday } from '@/api/hooks';
import { Button, ErrorNote, Screen, T, Title } from '@/components/ui';
import { joinNames } from '@/lib/format';
import { useTheme } from '@/theme';
import { fonts } from '@/theme/tokens';

// CLAUDE.md §8: a 5-second countdown with a huge Cancel, then it sends by itself, so an elder
// who can't tap again still gets help. (The design draws 3; D71.)
const COUNTDOWN_SECONDS = 5;
const RING = 244;
const STROKE = 14;

/** Help, step 1 (design E8): the countdown. */
export default function HelpCountdown() {
  const { t } = useTranslation();
  const { colors, scale } = useTheme();
  const today = useDeviceToday();
  const ask = useAskHelp();
  const net = useNetInfo();
  const [left, setLeft] = useState(COUNTDOWN_SECONDS * 10); // tenths of a second
  const sent = useRef(false);

  const { mutate } = ask;
  const network = net.type;
  const send = useCallback(
    (kind: 'help' | 'call_me') => {
      if (sent.current) {
        return;
      }
      sent.current = true;
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      mutate(
        { kind, network: network ?? undefined },
        {
          onSuccess: () => router.replace({ pathname: '/home/help-sent', params: { kind } }),
          onError: () => {
            sent.current = false;
          },
        },
      );
    },
    [mutate, network],
  );

  useEffect(() => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    const timer = setInterval(() => setLeft((value) => Math.max(0, value - 1)), 100);
    return () => clearInterval(timer);
  }, []);
  // Time's up: send by itself (the sent-once guard makes re-running this harmless).
  useEffect(() => {
    if (left === 0) {
      send('help');
    }
  }, [left, send]);

  const names = joinNames(today.data?.family_names ?? [], t('common.and'));
  const radius = (RING - STROKE) / 2;
  const circumference = 2 * Math.PI * radius;
  const seconds = Math.ceil(left / 10);

  return (
    <Screen background={colors.helpPage}>
      <View style={{ gap: 8 }}>
        <T size={17} weight="bold" color={colors.helpText} style={{ letterSpacing: 2 }}>
          {t('help.title').toUpperCase()}
        </T>
        <Title size={40}>{t('help.alerting')}</Title>
      </View>

      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 24 }}>
        <View style={{ width: RING, height: RING }}>
          <Svg width={RING} height={RING}>
            <Circle
              cx={RING / 2}
              cy={RING / 2}
              r={radius}
              stroke={colors.helpTintBorder}
              strokeWidth={STROKE}
              fill="none"
            />
            <Circle
              cx={RING / 2}
              cy={RING / 2}
              r={radius}
              stroke={colors.help}
              strokeWidth={STROKE}
              strokeLinecap="round"
              fill="none"
              strokeDasharray={`${circumference} ${circumference}`}
              strokeDashoffset={circumference * (1 - left / (COUNTDOWN_SECONDS * 10))}
              transform={`rotate(-90 ${RING / 2} ${RING / 2})`}
            />
          </Svg>
          <View
            accessibilityRole="timer"
            accessibilityLiveRegion="polite"
            accessibilityLabel={`${seconds} ${t('help.seconds')}`}
            style={{
              position: 'absolute',
              inset: 0,
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Text
              style={{
                fontFamily: fonts.heading,
                fontSize: 112,
                lineHeight: 112,
                fontWeight: '600',
                color: colors.helpText,
              }}
            >
              {seconds}
            </Text>
            <T size={20} weight="bold" color={colors.helpText}>
              {t('help.seconds')}
            </T>
          </View>
        </View>
        {names ? (
          <T center color={colors.textMuted} style={{ maxWidth: 320 }}>
            {t('help.will_get', { names })}
          </T>
        ) : null}
        <ErrorNote error={ask.error} />
      </View>

      <View style={{ gap: 12 }}>
        <Button
          variant="help"
          label={t('help.send_now')}
          busy={ask.isPending}
          onPress={() => send('help')}
        />
        <Button
          variant="secondary"
          icon="close"
          label={t('help.cancel_okay')}
          onPress={() => router.back()}
          style={{ minHeight: scale.buttonHeight + 8, borderColor: colors.text }}
        />
        <Button variant="plain" label={t('help.call_me')} onPress={() => send('call_me')} />
      </View>
    </Screen>
  );
}

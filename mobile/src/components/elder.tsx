import { useEffect } from 'react';
import { ActivityIndicator, Pressable, Text, View } from 'react-native';
import Animated, {
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import { Icon, type IconName } from '@/components/icons';
import { T } from '@/components/ui';
import { useTheme } from '@/theme';
import { fonts } from '@/theme/tokens';

// Elder-home pieces from the design (E3, E7, E11, E12): the big round "I'm okay", its "done"
// twin, tiles and the Help bar. Sizes follow the design's 390-wide phone.

const SIZE = 264;

/** The giant "I'm okay" (E3). A soft pulsing ring invites the tap; still under reduced motion. */
export function OkayButton({
  label,
  hint,
  onPress,
  busy,
}: {
  label: string;
  hint: string;
  onPress: () => void;
  busy: boolean;
}) {
  const { colors } = useTheme();
  const reduceMotion = useReducedMotion();
  const pulse = useSharedValue(0);
  useEffect(() => {
    if (!reduceMotion) {
      pulse.value = withRepeat(withTiming(1, { duration: 2600, easing: Easing.out(Easing.quad) }), -1);
    }
  }, [pulse, reduceMotion]);
  const halo = useAnimatedStyle(() => ({
    opacity: 0.7 * (1 - pulse.value),
    transform: [{ scale: 1 + 0.18 * pulse.value }],
  }));

  return (
    <View style={{ width: SIZE + 32, height: SIZE + 32, alignItems: 'center', justifyContent: 'center' }}>
      <View
        style={{
          position: 'absolute',
          width: SIZE + 32,
          height: SIZE + 32,
          borderRadius: (SIZE + 32) / 2,
          backgroundColor: colors.okTint,
        }}
      />
      {reduceMotion ? null : (
        <Animated.View
          style={[
            {
              position: 'absolute',
              width: SIZE,
              height: SIZE,
              borderRadius: SIZE / 2,
              borderWidth: 3,
              borderColor: colors.ok,
            },
            halo,
          ]}
        />
      )}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityHint={hint}
        accessibilityState={{ busy }}
        disabled={busy}
        onPress={onPress}
        style={({ pressed }) => ({
          width: SIZE,
          height: SIZE,
          borderRadius: SIZE / 2,
          backgroundColor: colors.ok,
          alignItems: 'center',
          justifyContent: 'center',
          gap: 8,
          transform: [{ scale: pressed ? 0.97 : 1 }],
          elevation: 8,
        })}
      >
        {busy ? (
          <ActivityIndicator size="large" color={colors.onOk} />
        ) : (
          <>
            <Text
              style={{
                color: colors.onOk,
                fontFamily: fonts.heading,
                fontSize: 50,
                fontWeight: '600',
                letterSpacing: -0.5,
              }}
            >
              {label}
            </Text>
            <T size={20} color={colors.onOkMuted}>
              {hint}
            </T>
          </>
        )}
      </Pressable>
    </View>
  );
}

/** "Done for today, at 8:14 AM" in place of the button (E7). */
export function DoneCircle({ title, detail }: { title: string; detail: string }) {
  const { colors } = useTheme();
  return (
    <View
      accessible
      accessibilityLabel={`${title}, ${detail}`}
      style={{ width: SIZE + 32, height: SIZE + 32, alignItems: 'center', justifyContent: 'center' }}
    >
      <View
        style={{
          position: 'absolute',
          width: SIZE + 32,
          height: SIZE + 32,
          borderRadius: (SIZE + 32) / 2,
          backgroundColor: colors.okTintSoft,
        }}
      />
      <View
        style={{
          width: SIZE,
          height: SIZE,
          borderRadius: SIZE / 2,
          backgroundColor: colors.okTint,
          borderWidth: 3,
          borderColor: colors.ok,
          alignItems: 'center',
          justifyContent: 'center',
          gap: 6,
        }}
      >
        <Icon name="check" size={56} color={colors.okText} strokeWidth={2.6} />
        <Text
          style={{
            color: colors.okText,
            fontFamily: fonts.heading,
            fontSize: 36,
            fontWeight: '600',
            textAlign: 'center',
          }}
        >
          {title}
        </Text>
        <T size={20} color={colors.okText}>
          {detail}
        </T>
      </View>
    </View>
  );
}

/** A big square-ish tile with an icon, a label and an optional badge ("2 new"). */
export function Tile({
  icon,
  label,
  detail,
  badge,
  onPress,
}: {
  icon: IconName;
  label: string;
  detail?: string;
  badge?: string;
  onPress: () => void;
}) {
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={[label, badge, detail].filter(Boolean).join(', ')}
      onPress={onPress}
      style={({ pressed }) => ({
        flex: 1,
        minHeight: 104,
        padding: 16,
        paddingHorizontal: 18,
        borderRadius: 24,
        backgroundColor: colors.surface,
        borderWidth: 1.5,
        borderColor: colors.border,
        justifyContent: 'space-between',
        gap: 10,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
        <Icon name={icon} size={30} />
        {badge ? (
          <View
            style={{
              paddingVertical: 4,
              paddingHorizontal: 10,
              borderRadius: 999,
              backgroundColor: colors.accent,
            }}
          >
            <T size={16} weight="bold" color={colors.onAccent}>
              {badge}
            </T>
          </View>
        ) : null}
      </View>
      <View style={{ gap: 2 }}>
        <T size={24} weight="bold">
          {label}
        </T>
        {detail ? (
          <T size={20} color={colors.textMuted}>
            {detail}
          </T>
        ) : null}
      </View>
    </Pressable>
  );
}

/** The full-width Help bar: always there, never behind a paywall (CLAUDE.md §1). */
export function HelpBar({
  label,
  hint,
  onPress,
}: {
  label: string;
  hint: string;
  onPress: () => void;
}) {
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        minHeight: 72,
        paddingHorizontal: 20,
        borderRadius: 22,
        backgroundColor: colors.helpTint,
        borderWidth: 1.5,
        borderColor: colors.helpTintBorder,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <Icon name="help" size={30} color={colors.helpText} />
      <T size={24} weight="bold" color={colors.helpText} style={{ flex: 1 }}>
        {label}
      </T>
      <T size={20} color={colors.helpText}>
        {hint}
      </T>
    </Pressable>
  );
}

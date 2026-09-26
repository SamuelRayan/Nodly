import { useNetInfo } from '@react-native-community/netinfo';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  type StyleProp,
  Text,
  TextInput,
  type TextInputProps,
  type TextStyle,
  View,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '@/api/errors';
import { Icon, type IconName } from '@/components/icons';
import en from '@/i18n/en.json';
import { useTheme } from '@/theme';
import { fonts } from '@/theme/tokens';

// Building blocks in the design's style (design/2026-09-26-nodly-handoff), sized by the
// current scale: elder or family (CLAUDE.md §15).

export function Screen({
  children,
  scroll = true,
  background,
}: {
  children: ReactNode;
  scroll?: boolean;
  background?: string;
}) {
  const { colors, scale } = useTheme();
  const body = (
    <View style={{ padding: scale.space + 4, gap: scale.space, flexGrow: 1 }}>{children}</View>
  );
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: background ?? colors.background }}>
      <OfflineBanner />
      {scroll ? (
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ flexGrow: 1 }}>
          {body}
        </ScrollView>
      ) : (
        body
      )}
    </SafeAreaView>
  );
}

/** Body text in Atkinson Hyperlegible at the current scale. */
export function T({
  children,
  size,
  weight = 'normal',
  color,
  style,
  center = false,
}: {
  children: ReactNode;
  size?: number;
  weight?: 'normal' | 'bold';
  color?: string;
  style?: StyleProp<TextStyle>;
  center?: boolean;
}) {
  const { colors, scale } = useTheme();
  return (
    <Text
      style={[
        {
          color: color ?? colors.text,
          fontFamily: fonts.body,
          fontSize: size ?? scale.body,
          fontWeight: weight === 'bold' ? '700' : '400',
          lineHeight: Math.round((size ?? scale.body) * 1.4),
          textAlign: center ? 'center' : undefined,
        },
        style,
      ]}
    >
      {children}
    </Text>
  );
}

export function Title({
  children,
  size,
  center = false,
  color,
}: {
  children: ReactNode;
  size?: number;
  center?: boolean;
  color?: string;
}) {
  const { colors, scale } = useTheme();
  const fontSize = size ?? scale.title;
  return (
    <Text
      accessibilityRole="header"
      style={{
        color: color ?? colors.text,
        fontFamily: fonts.heading,
        fontSize,
        fontWeight: '600',
        lineHeight: Math.round(fontSize * 1.08),
        letterSpacing: -0.015 * fontSize,
        textAlign: center ? 'center' : undefined,
      }}
    >
      {children}
    </Text>
  );
}

export function Heading({ children }: { children: ReactNode }) {
  const { colors, scale } = useTheme();
  return (
    <Text
      accessibilityRole="header"
      style={{
        color: colors.text,
        fontFamily: fonts.body,
        fontSize: scale.heading,
        fontWeight: '700',
      }}
    >
      {children}
    </Text>
  );
}

export function Body({ children, muted = false }: { children: ReactNode; muted?: boolean }) {
  const { colors } = useTheme();
  return <T color={muted ? colors.textMuted : colors.text}>{children}</T>;
}

type ButtonVariant = 'primary' | 'secondary' | 'ink' | 'help' | 'plain';

export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled = false,
  busy = false,
  icon,
  iconAfter = false,
  style,
  accessibilityHint,
}: {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  busy?: boolean;
  icon?: IconName;
  iconAfter?: boolean;
  style?: StyleProp<ViewStyle>;
  accessibilityHint?: string;
}) {
  const { colors, scale } = useTheme();
  const inactive = disabled || busy;
  const look = {
    primary: { background: colors.ok, text: colors.onOk, border: undefined },
    ink: { background: colors.ink, text: colors.onInk, border: undefined },
    help: { background: colors.help, text: colors.onHelp, border: undefined },
    secondary: { background: colors.surface, text: colors.text, border: colors.borderStrong },
    plain: { background: 'transparent', text: colors.text, border: undefined },
  }[variant];
  const iconNode = icon ? <Icon name={icon} size={scale.buttonText + 2} color={look.text} /> : null;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: inactive, busy }}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => [
        {
          minHeight: scale.buttonHeight,
          borderRadius: scale.radius,
          paddingHorizontal: scale.space,
          flexDirection: 'row',
          gap: 10,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: look.background,
          borderWidth: look.border ? 2 : 0,
          borderColor: look.border,
          opacity: inactive ? 0.55 : pressed ? 0.85 : 1,
        },
        style,
      ]}
    >
      {busy ? (
        <ActivityIndicator color={look.text} />
      ) : (
        <>
          {iconAfter ? null : iconNode}
          <Text
            style={{
              color: look.text,
              fontFamily: fonts.body,
              fontSize: scale.buttonText,
              fontWeight: '700',
              textAlign: 'center',
              textDecorationLine: variant === 'plain' ? 'underline' : 'none',
            }}
          >
            {label}
          </Text>
          {iconAfter ? iconNode : null}
        </>
      )}
    </Pressable>
  );
}

/** The elder's labelled back/close pill ("Home", "Close"): never an unlabelled arrow. */
export function PillButton({
  label,
  onPress,
  icon = 'arrowLeft',
}: {
  label: string;
  onPress: () => void;
  icon?: IconName;
}) {
  const { colors, scale } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => ({
        alignSelf: 'flex-start',
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        minHeight: 56,
        paddingHorizontal: 20,
        borderRadius: 999,
        borderWidth: 2,
        borderColor: colors.borderStrong,
        backgroundColor: colors.surface,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <Icon name={icon} size={24} />
      <T weight="bold" size={scale.small}>
        {label}
      </T>
    </Pressable>
  );
}

/** A small rounded label: "Okay today", "2 new", "Locked". */
export function Pill({
  label,
  background,
  color,
  icon,
}: {
  label: string;
  background: string;
  color: string;
  icon?: IconName;
}) {
  const { scale } = useTheme();
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: 5,
        paddingVertical: 6,
        paddingHorizontal: 11,
        borderRadius: 999,
        backgroundColor: background,
        alignSelf: 'flex-start',
      }}
    >
      {icon ? <Icon name={icon} size={16} color={color} strokeWidth={2.6} /> : null}
      <Text style={{ color, fontFamily: fonts.body, fontSize: scale.small - 2, fontWeight: '700' }}>
        {label}
      </Text>
    </View>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const { colors, scale } = useTheme();
  return (
    <View
      style={[
        {
          backgroundColor: colors.surface,
          borderWidth: 1,
          borderColor: colors.border,
          borderRadius: scale.cardRadius,
          padding: 18,
          gap: 16,
        },
        style,
      ]}
    >
      {children}
    </View>
  );
}

/** A round initial, e.g. "P" for Priya. */
export function Avatar({
  name,
  size = 46,
  background,
  color,
}: {
  name: string;
  size?: number;
  background?: string;
  color?: string;
}) {
  const { colors } = useTheme();
  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: background ?? colors.sand,
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Text
        style={{
          color: color ?? colors.onSand,
          fontFamily: fonts.heading,
          fontSize: size * 0.46,
          fontWeight: '600',
        }}
      >
        {name.trim().charAt(0).toUpperCase()}
      </Text>
    </View>
  );
}

export function Field({ label, ...input }: { label: string } & TextInputProps) {
  const { colors, scale } = useTheme();
  return (
    <View style={{ gap: 6 }}>
      <T size={scale.small} weight="bold">
        {label}
      </T>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={colors.textMuted}
        style={{
          minHeight: scale.buttonHeight,
          borderWidth: 2,
          borderColor: colors.borderStrong,
          borderRadius: scale.radius,
          paddingHorizontal: 14,
          color: colors.text,
          backgroundColor: colors.surface,
          fontFamily: fonts.body,
          fontSize: scale.body,
        }}
        {...input}
      />
    </View>
  );
}

export function Row({
  title,
  subtitle,
  onPress,
  right,
}: {
  title: string;
  subtitle?: string;
  onPress?: () => void;
  right?: ReactNode;
}) {
  const { colors, scale } = useTheme();
  return (
    <Pressable
      accessibilityRole={onPress ? 'button' : undefined}
      disabled={!onPress}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: scale.buttonHeight,
        paddingVertical: 12,
        paddingHorizontal: 16,
        borderRadius: scale.radius + 4,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <View style={{ flex: 1, gap: 2 }}>
        <T weight="bold">{title}</T>
        {subtitle ? (
          <T size={scale.small} color={colors.textMuted}>
            {subtitle}
          </T>
        ) : null}
      </View>
      {right ?? (onPress ? <Icon name="chevronRight" size={22} color={colors.textMuted} /> : null)}
    </Pressable>
  );
}

type ErrorKey = keyof typeof en.errors;

function isErrorKey(code: string): code is ErrorKey {
  return code in en.errors;
}

/** The message to show for any error; API problems by their `code`. */
export function useErrorMessage(): (error: unknown) => string {
  const { t } = useTranslation();
  return (error) => {
    if (error instanceof ApiError) {
      const code = error.fieldErrorType ?? error.code;
      if (isErrorKey(code)) {
        return t(`errors.${code}`);
      }
      if (isErrorKey(error.code)) {
        return t(`errors.${error.code}`);
      }
    }
    return t('errors.generic');
  };
}

export function ErrorNote({ error }: { error: unknown }) {
  const { colors } = useTheme();
  const message = useErrorMessage();
  if (!error) {
    return null;
  }
  return (
    <View accessibilityRole="alert">
      <T color={colors.helpText} weight="bold">
        {typeof error === 'string' ? error : message(error)}
      </T>
    </View>
  );
}

export function Loading() {
  const { colors } = useTheme();
  return (
    <View
      style={{
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.background,
      }}
    >
      <ActivityIndicator color={colors.text} size="large" />
    </View>
  );
}

/** Shown on every screen while the phone has no connection. */
export function OfflineBanner() {
  const { t } = useTranslation();
  const { colors, scale } = useTheme();
  const { isConnected } = useNetInfo();
  if (isConnected !== false) {
    return null;
  }
  return (
    <View
      accessibilityRole="alert"
      style={{ backgroundColor: colors.sand, paddingVertical: 10, paddingHorizontal: 16 }}
    >
      <T size={scale.small} weight="bold" color={colors.onSand}>
        {t('offline.banner')}
      </T>
    </View>
  );
}

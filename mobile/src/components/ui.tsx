import { useNetInfo } from '@react-native-community/netinfo';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  type TextInputProps,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '@/api/errors';
import en from '@/i18n/en.json';
import { useTheme } from '@/theme';

// Placeholder UI built on the design tokens (CLAUDE.md §15). Real designs arrive in Phase 8.

export function Screen({ children, scroll = true }: { children: ReactNode; scroll?: boolean }) {
  const { colors, scale } = useTheme();
  const body = (
    <View style={{ padding: scale.space, gap: scale.space, flexGrow: 1 }}>{children}</View>
  );
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }}>
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

export function Title({ children }: { children: ReactNode }) {
  const { colors, scale } = useTheme();
  return (
    <Text
      accessibilityRole="header"
      style={{ color: colors.text, fontSize: scale.title, fontWeight: '700' }}
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
      style={{ color: colors.text, fontSize: scale.heading, fontWeight: '600' }}
    >
      {children}
    </Text>
  );
}

export function Body({ children, muted = false }: { children: ReactNode; muted?: boolean }) {
  const { colors, scale } = useTheme();
  return (
    <Text style={{ color: muted ? colors.textMuted : colors.text, fontSize: scale.body }}>
      {children}
    </Text>
  );
}

type ButtonVariant = 'primary' | 'secondary';

export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled = false,
  busy = false,
  large = false,
}: {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  busy?: boolean;
  /** Extra-tall (the elder's "I'm okay"). */
  large?: boolean;
}) {
  const { colors, scale } = useTheme();
  const primary = variant === 'primary';
  const inactive = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: inactive, busy }}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: large ? scale.buttonHeight * 2 : scale.buttonHeight,
        borderRadius: scale.radius,
        paddingHorizontal: scale.space,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: primary ? colors.ok : colors.surface,
        borderWidth: primary ? 0 : 2,
        borderColor: colors.border,
        opacity: inactive ? 0.55 : pressed ? 0.85 : 1,
      })}
    >
      {busy ? (
        <ActivityIndicator color={primary ? colors.onOk : colors.text} />
      ) : (
        <Text
          style={{
            color: primary ? colors.onOk : colors.text,
            fontSize: large ? scale.title : scale.buttonText,
            fontWeight: '700',
            textAlign: 'center',
          }}
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}

export function Field({ label, ...input }: { label: string } & TextInputProps) {
  const { colors, scale } = useTheme();
  return (
    <View style={{ gap: 6 }}>
      <Text style={{ color: colors.text, fontSize: scale.small, fontWeight: '600' }}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={colors.textMuted}
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
        {...input}
      />
    </View>
  );
}

export function Row({
  title,
  subtitle,
  onPress,
}: {
  title: string;
  subtitle?: string;
  onPress?: () => void;
}) {
  const { colors, scale } = useTheme();
  return (
    <Pressable
      accessibilityRole={onPress ? 'button' : undefined}
      disabled={!onPress}
      onPress={onPress}
      style={{
        minHeight: scale.buttonHeight,
        padding: 12,
        borderRadius: scale.radius,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
        justifyContent: 'center',
        gap: 2,
      }}
    >
      <Text style={{ color: colors.text, fontSize: scale.body, fontWeight: '600' }}>{title}</Text>
      {subtitle ? (
        <Text style={{ color: colors.textMuted, fontSize: scale.small }}>{subtitle}</Text>
      ) : null}
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
  const { colors, scale } = useTheme();
  const message = useErrorMessage();
  if (!error) {
    return null;
  }
  return (
    <Text accessibilityRole="alert" style={{ color: colors.help, fontSize: scale.body }}>
      {typeof error === 'string' ? error : message(error)}
    </Text>
  );
}

export function Loading() {
  const { colors } = useTheme();
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
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
      style={{ backgroundColor: colors.accent, paddingVertical: 8, paddingHorizontal: 16 }}
    >
      <Text style={{ color: colors.surface, fontSize: scale.small, fontWeight: '600' }}>
        {t('offline.banner')}
      </Text>
    </View>
  );
}

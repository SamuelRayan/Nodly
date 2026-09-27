import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Modal, Pressable, ScrollView, View } from 'react-native';
import type { PurchasesPackage } from 'react-native-purchases';

import { api, unwrap } from '@/api/client';
import { keys, useAccess } from '@/api/hooks';
import { useMe } from '@/auth/session';
import {
  billingAvailable,
  buy,
  plusPackages,
  prepareBilling,
  restore,
} from '@/billing/revenuecat';
import { Icon, type IconName } from '@/components/icons';
import { Button, ErrorNote, Loading, T, Title } from '@/components/ui';
import { useAppStore } from '@/state/app';
import { useTheme } from '@/theme';

const CONFIRM_TRIES = 15;
const CONFIRM_EVERY_MS = 2_000;

type Phase = 'choose' | 'confirming' | 'waiting';

/**
 * The locked-feature sheet (design F8, CLAUDE.md §10): "Share a moment — free" first, then a
 * Day Pass and Nodly Plus, plus Restore purchases. After a purchase it shows "Confirming…"
 * and asks the server until the server says Plus is on: the app never unlocks anything.
 * Family mode only: on an elder's phone it renders nothing (§1).
 */
export function PlusSheet({
  familyId,
  title,
  visible,
  onClose,
  onUnlocked,
}: {
  familyId: string;
  title: string;
  visible: boolean;
  onClose: () => void;
  onUnlocked: () => void;
}) {
  const mode = useAppStore((state) => state.mode);
  if (mode !== 'family') {
    return null;
  }
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Sheet familyId={familyId} title={title} onClose={onClose} onUnlocked={onUnlocked} />
    </Modal>
  );
}

function Sheet({
  familyId,
  title,
  onClose,
  onUnlocked,
}: {
  familyId: string;
  title: string;
  onClose: () => void;
  onUnlocked: () => void;
}) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const queryClient = useQueryClient();
  const me = useMe();
  const access = useAccess(familyId);
  const [phase, setPhase] = useState<Phase>('choose');
  const [error, setError] = useState<unknown>(null);

  const userId = me.data?.id;
  const packages = useQuery({
    queryKey: ['plus-packages', userId, familyId],
    queryFn: async () => {
      await prepareBilling(userId ?? '', familyId);
      return plusPackages();
    },
    enabled: Boolean(userId) && billingAvailable(),
    retry: false,
  });

  /** Ask the server (which asks RevenueCat) until it says Plus is on. */
  const confirm = async () => {
    setPhase('confirming');
    for (let attempt = 0; attempt < CONFIRM_TRIES; attempt += 1) {
      try {
        const state = await unwrap(
          api.POST('/v1/families/{family_id}/access/refresh', {
            params: { path: { family_id: familyId } },
          }),
        );
        queryClient.setQueryData(keys.access(familyId), state);
        if (state.has_plus) {
          await queryClient.invalidateQueries({ queryKey: ['elders'] });
          setPhase('choose');
          onUnlocked();
          return;
        }
      } catch (caught) {
        setError(caught);
      }
      await new Promise((resolve) => setTimeout(resolve, CONFIRM_EVERY_MS));
    }
    setPhase('waiting');
  };

  const purchase = async (pkg: PurchasesPackage) => {
    setError(null);
    try {
      await prepareBilling(userId ?? '', familyId);
      if ((await buy(pkg)) === 'done') {
        await confirm();
      }
    } catch (caught) {
      setError(caught);
      setPhase('choose');
    }
  };

  const restorePurchases = async () => {
    setError(null);
    try {
      await prepareBilling(userId ?? '', familyId);
      await restore();
      await confirm();
    } catch (caught) {
      setError(caught);
      setPhase('choose');
    }
  };

  const offer = access.data?.day_pass;
  const dayPass = packages.data?.dayPass;
  const monthly = packages.data?.monthly ?? packages.data?.annual;
  const busy = phase === 'confirming';

  return (
    <View style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(30, 26, 21, 0.5)' }}>
      <Pressable accessibilityLabel={t('plus.not_now')} style={{ flex: 1 }} onPress={onClose} />
      <View
        accessibilityViewIsModal
        style={{
          maxHeight: '92%',
          borderTopLeftRadius: 30,
          borderTopRightRadius: 30,
          backgroundColor: colors.background,
          paddingTop: 10,
        }}
      >
        <ScrollView contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 28, gap: 16 }}>
          <View
            style={{ alignSelf: 'center', width: 40, height: 5, borderRadius: 3, backgroundColor: colors.borderStrong }}
          />
          {phase === 'choose' ? (
            <>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
                <View
                  style={{ width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.sand }}
                >
                  <Icon name="lock" size={24} color={colors.onSand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Title size={26}>{title}</Title>
                </View>
              </View>
              <T size={16} color={colors.textMuted}>
                {t('plus.line')}
              </T>
              <Option
                icon="photo"
                title={t('plus.share')}
                detail={t('plus.share_detail')}
                right={t('plus.free')}
                primary
                onPress={() => {
                  onClose();
                  router.push({ pathname: '/share', params: { familyId } });
                }}
              />
              {!billingAvailable() ? (
                <T size={15} color={colors.textMuted}>
                  {t('plus.unavailable')}
                </T>
              ) : packages.isPending ? (
                <Loading />
              ) : (
                <>
                  <Option
                    icon="ticket"
                    title={t('plus.day_pass')}
                    detail={
                      offer?.reason === 'moment_pending'
                        ? t('plus.day_pass_pending')
                        : dayPass
                          ? t('plus.day_pass_detail')
                          : t('plus.not_offered')
                    }
                    right={dayPass?.product.priceString}
                    disabled={!dayPass || !offer?.offered}
                    onPress={() => dayPass && void purchase(dayPass)}
                  />
                  <Option
                    icon="star"
                    title={t('plus.plus')}
                    detail={monthly ? t('plus.plus_detail') : t('plus.not_offered')}
                    right={
                      monthly
                        ? t(monthly === packages.data?.monthly ? 'plus.per_month' : 'plus.per_year', {
                            price: monthly.product.priceString,
                          })
                        : undefined
                    }
                    disabled={!monthly}
                    onPress={() => monthly && void purchase(monthly)}
                  />
                </>
              )}
              <ErrorNote error={error ?? packages.error} />
              <View
                style={{ flexDirection: 'row', alignItems: 'center', gap: 10, padding: 12, borderRadius: 14, backgroundColor: colors.okTintSoft }}
              >
                <Icon name="shield" size={20} color={colors.okText} />
                <T size={15} weight="bold" color={colors.okText} style={{ flex: 1 }}>
                  {t('plus.never_locked')}
                </T>
              </View>
              <View style={{ flexDirection: 'row', justifyContent: 'center', gap: 24 }}>
                {billingAvailable() ? (
                  <Button
                    variant="plain"
                    label={t('plus.restore')}
                    onPress={() => void restorePurchases()}
                    style={{ minHeight: 44 }}
                  />
                ) : null}
                <Button variant="plain" label={t('plus.not_now')} onPress={onClose} style={{ minHeight: 44 }} />
              </View>
            </>
          ) : (
            <View style={{ alignItems: 'center', gap: 14, paddingVertical: 24 }}>
              <Title center size={26}>
                {phase === 'confirming' ? t('plus.confirming_title') : t('plus.waiting_title')}
              </Title>
              <T center size={16} color={colors.textMuted} style={{ maxWidth: 320 }}>
                {phase === 'confirming' ? t('plus.confirming_line') : t('plus.waiting_line')}
              </T>
              {busy ? <Loading /> : null}
              <ErrorNote error={phase === 'waiting' ? error : null} />
              {phase === 'waiting' ? (
                <>
                  <Button label={t('plus.check_again')} onPress={() => void confirm()} />
                  <Button variant="plain" label={t('plus.not_now')} onPress={onClose} />
                </>
              ) : null}
            </View>
          )}
        </ScrollView>
      </View>
    </View>
  );
}

function Option({
  icon,
  title,
  detail,
  right,
  primary = false,
  disabled = false,
  onPress,
}: {
  icon: IconName;
  title: string;
  detail: string;
  right?: string;
  primary?: boolean;
  disabled?: boolean;
  onPress: () => void;
}) {
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      accessibilityLabel={[title, detail, right].filter(Boolean).join(', ')}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        paddingVertical: 14,
        paddingHorizontal: 16,
        borderRadius: 18,
        backgroundColor: colors.surface,
        borderWidth: primary ? 2 : 1.5,
        borderColor: primary ? colors.ok : colors.border,
        opacity: disabled ? 0.55 : pressed ? 0.85 : 1,
      })}
    >
      <View
        style={{
          width: 44,
          height: 44,
          borderRadius: 22,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: primary ? colors.okTint : colors.neutralTint,
        }}
      >
        <Icon name={icon} size={22} color={primary ? colors.okText : colors.text} />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <T size={17} weight="bold">
          {title}
        </T>
        <T size={14} color={colors.textMuted}>
          {detail}
        </T>
      </View>
      {right ? (
        primary ? (
          <View style={{ paddingHorizontal: 12, paddingVertical: 5, borderRadius: 999, backgroundColor: colors.ok }}>
            <T size={15} weight="bold" color={colors.onOk}>
              {right}
            </T>
          </View>
        ) : (
          <T size={17} weight="bold">
            {right}
          </T>
        )
      ) : null}
    </Pressable>
  );
}

import { Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Modal, Pressable, View } from 'react-native';

import { serverNow } from '@/api/client';
import type { components } from '@/api/schema';
import { useBillingTimeline, useReportProblem } from '@/api/hooks';
import { Icon } from '@/components/icons';
import { Button, Card, ErrorNote, Field, Loading, Pill, Screen, T, Title } from '@/components/ui';
import { dateTime } from '@/lib/format';
import { useTheme } from '@/theme';

type Entry = components['schemas']['TimelineEntryOut'];
type Reason = 'wrong_charge' | 'plus_not_working' | 'missing_purchase' | 'other';
const REASONS: Reason[] = ['wrong_charge', 'plus_not_working', 'missing_purchase', 'other'];

/**
 * "Plus & billing" (CLAUDE.md §10): a plain-language timeline of why the family has or doesn't
 * have Plus, what was charged and when, plus "Report a problem". Family members only.
 */
export default function Billing() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const { familyId } = useLocalSearchParams<{ familyId: string }>();
  const timeline = useBillingTimeline(familyId);
  const [reporting, setReporting] = useState(false);

  if (timeline.isPending) {
    return <Loading />;
  }
  if (timeline.isError) {
    return (
      <Screen>
        <ErrorNote error={timeline.error} />
      </Screen>
    );
  }
  const { access, entries } = timeline.data;
  const tz = access.today.timezone ?? undefined;

  return (
    <Screen>
      <Stack.Screen options={{ title: t('plus.timeline_title') }} />
      <View
        style={{
          gap: 8,
          padding: 18,
          borderRadius: 20,
          backgroundColor: access.has_plus ? colors.okTint : colors.neutralTint,
        }}
      >
        <Pill
          icon={access.has_plus ? 'star' : undefined}
          label={access.has_plus ? t('plus.timeline_now_on') : t('plus.timeline_now_off')}
          background={access.has_plus ? colors.ok : colors.surface}
          color={access.has_plus ? colors.onOk : colors.textMuted}
        />
        {access.has_plus && access.plus_until && tz ? (
          <T size={15} color={colors.okText}>
            {t('plus.timeline_now_on_detail', { time: dateTime(access.plus_until, tz) })}
          </T>
        ) : null}
      </View>

      {entries.length === 0 ? (
        <Card>
          <T color={colors.textMuted}>{t('plus.timeline_empty')}</T>
        </Card>
      ) : (
        <View style={{ gap: 10 }}>
          {entries.map((entry) => (
            <TimelineRow key={entry.id} entry={entry} timezone={tz} />
          ))}
        </View>
      )}

      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: 10,
          padding: 12,
          borderRadius: 14,
          backgroundColor: colors.neutralTint,
        }}
      >
        <Icon name="shield" size={18} color={colors.textMuted} />
        <T size={13} color={colors.textMuted} style={{ flex: 1 }}>
          {t('plus.never_charged_note')}
        </T>
      </View>

      <Button
        variant="secondary"
        label={t('plus.report_problem')}
        onPress={() => setReporting(true)}
      />

      <ReportSheet
        familyId={familyId}
        visible={reporting}
        onClose={() => setReporting(false)}
      />
    </Screen>
  );
}

function TimelineRow({ entry, timezone }: { entry: Entry; timezone?: string }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const tz = timezone ?? 'UTC';

  const label =
    entry.source === 'moment'
      ? t('plus.timeline_source_moment', {
          name: entry.moment_author_name ?? '',
          kind: t(`plus.timeline_kind_${(entry.moment_kind ?? 'photo') as 'photo' | 'voice' | 'video'}`),
        })
      : entry.source === 'day_pass'
        ? t('plus.timeline_source_day_pass')
        : entry.source === 'subscription'
          ? t('plus.timeline_source_subscription')
          : t('plus.timeline_source_goodwill');

  const icon =
    entry.source === 'moment'
      ? entry.moment_kind === 'voice'
        ? 'mic'
        : entry.moment_kind === 'video'
          ? 'video'
          : 'photo'
      : entry.source === 'goodwill'
        ? 'heart'
        : 'ticket';
  const active = !entry.revoked_at && new Date(entry.ends_at).getTime() > serverNow();

  return (
    <Card>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <View
          style={{
            width: 40,
            height: 40,
            borderRadius: 20,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: active ? colors.okTint : colors.neutralTint,
          }}
        >
          <Icon name={icon} size={18} color={active ? colors.okText : colors.textMuted} />
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <T size={16} weight="bold">
            {label}
          </T>
          <T size={13} color={colors.textMuted}>
            {t('plus.timeline_window', { from: dateTime(entry.starts_at, tz), to: dateTime(entry.ends_at, tz) })}
          </T>
        </View>
        {active ? (
          <Pill label={t('plus.timeline_now_on')} background={colors.okTint} color={colors.okText} />
        ) : null}
      </View>
      {entry.environment === 'SANDBOX' ? (
        <Pill label={t('plus.timeline_test_purchase')} background={colors.sand} color={colors.onSand} />
      ) : null}
      {entry.refunded_at ? (
        <T size={13} color={colors.helpText}>
          {t('plus.timeline_refunded', { time: dateTime(entry.refunded_at, tz) })}
        </T>
      ) : entry.revoked_at && entry.revoke_reason ? (
        <T size={13} color={colors.helpText}>
          {t('plus.timeline_revoked', { reason: entry.revoke_reason })}
        </T>
      ) : null}
      {entry.note ? (
        <T size={13} color={colors.textMuted}>
          {entry.note}
        </T>
      ) : null}
    </Card>
  );
}

function ReportSheet({
  familyId,
  visible,
  onClose,
}: {
  familyId: string;
  visible: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const report = useReportProblem(familyId);
  const [reason, setReason] = useState<Reason>('wrong_charge');
  const [message, setMessage] = useState('');
  const [sent, setSent] = useState(false);

  const close = () => {
    onClose();
    // Reset after the sheet has closed, so it doesn't flash back to the form.
    setTimeout(() => {
      setSent(false);
      setMessage('');
      setReason('wrong_charge');
      report.reset();
    }, 300);
  };

  const send = () => {
    report.mutate(
      { reason, message: message.trim() || undefined },
      { onSuccess: () => setSent(true) },
    );
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={close}>
      <View style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(30, 26, 21, 0.5)' }}>
        <Pressable accessibilityLabel={t('common.cancel')} style={{ flex: 1 }} onPress={close} />
        <View
          accessibilityViewIsModal
          style={{
            gap: 16,
            paddingHorizontal: 20,
            paddingTop: 10,
            paddingBottom: 28,
            borderTopLeftRadius: 30,
            borderTopRightRadius: 30,
            backgroundColor: colors.background,
          }}
        >
          <View
            style={{ alignSelf: 'center', width: 40, height: 5, borderRadius: 3, backgroundColor: colors.borderStrong }}
          />
          {sent ? (
            <View style={{ alignItems: 'center', gap: 12, paddingVertical: 20 }}>
              <Icon name="checkCircle" size={40} color={colors.okText} />
              <Title center size={24}>
                {t('plus.report_sent_title')}
              </Title>
              <T center color={colors.textMuted}>
                {t('plus.report_sent_line')}
              </T>
              <Button label={t('moments.done')} onPress={close} />
            </View>
          ) : (
            <>
              <Title size={24}>{t('plus.report_title')}</Title>
              <View style={{ gap: 8 }}>
                {REASONS.map((option) => (
                  <Pressable
                    key={option}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: reason === option }}
                    onPress={() => setReason(option)}
                    style={{
                      flexDirection: 'row',
                      alignItems: 'center',
                      gap: 12,
                      padding: 14,
                      borderRadius: 16,
                      borderWidth: reason === option ? 2 : 1.5,
                      borderColor: reason === option ? colors.ok : colors.border,
                      backgroundColor: colors.surface,
                    }}
                  >
                    <View
                      style={{
                        width: 20,
                        height: 20,
                        borderRadius: 10,
                        borderWidth: 2,
                        borderColor: reason === option ? colors.ok : colors.borderStrong,
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      {reason === option ? (
                        <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: colors.ok }} />
                      ) : null}
                    </View>
                    <T size={15} style={{ flex: 1 }}>
                      {t(`plus.report_reason_${option}`)}
                    </T>
                  </Pressable>
                ))}
              </View>
              <Field
                label={t('plus.report_message_label')}
                value={message}
                onChangeText={setMessage}
                multiline
                numberOfLines={3}
              />
              <ErrorNote error={report.error} />
              <Button label={t('plus.report_send')} busy={report.isPending} onPress={send} />
              <Button variant="plain" label={t('common.cancel')} onPress={close} />
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}

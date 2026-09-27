import * as Notifications from 'expo-notifications';
import * as TaskManager from 'expo-task-manager';

import { api, unwrap } from '@/api/client';
import i18n from '@/i18n';
import { useAppStore } from '@/state/app';

/**
 * Notification buttons that work without opening the app (CLAUDE.md §7, §8).
 *
 * On Android, a task registered with registerTaskAsync also runs when an action button is
 * tapped while the app is in the background or closed:
 * https://docs.expo.dev/versions/v57.0.0/sdk/notifications/#registertaskasynctaskname
 * The elder's "I'm okay" checks in and the family's "I'm on it" acknowledges Help, then the
 * notification is replaced by a quiet confirmation. In the foreground, the normal response
 * listener (useNotificationRouting) handles the same buttons.
 *
 * Defined at module scope and imported first by the root layout, as the docs require.
 */
export const NOTIFICATION_TASK = 'nodly-notification-actions';

type Payload = Notifications.NotificationTaskPayload;

async function confirm(title: string, body: string): Promise<void> {
  await Notifications.scheduleNotificationAsync({
    content: { title, body },
    trigger: { channelId: 'general' },
  });
}

async function handle(response: Notifications.NotificationResponse): Promise<void> {
  const action = response.actionIdentifier;
  const data = response.notification.request.content.data as Record<string, unknown>;
  // The app may not be running: load the mode and device token from SecureStore first.
  const store = useAppStore.getState();
  if (!store.hydrated) {
    await store.hydrate();
  }
  if (action === 'im_okay') {
    await unwrap(api.POST('/v1/device/checkin', { body: { source: 'notification' } }));
    await confirm(i18n.t('elder.thanks_short_title'), i18n.t('elder.thanks_short_body'));
  } else if (action === 'on_it' && typeof data.request_id === 'string') {
    await unwrap(
      api.POST('/v1/help/{request_id}/ack', {
        params: { path: { request_id: data.request_id } },
      }),
    );
    await confirm(i18n.t('help.on_it_done_title'), i18n.t('help.on_it_done_body'));
  } else {
    return;
  }
  await Notifications.dismissNotificationAsync(response.notification.request.identifier);
  // Handled here: don't act on it again when the app next opens.
  Notifications.clearLastNotificationResponse();
}

TaskManager.defineTask<Payload>(NOTIFICATION_TASK, async ({ data }) => {
  if (!data || !('actionIdentifier' in data)) {
    return; // a plain received notification: nothing to do in the background
  }
  try {
    await handle(data);
  } catch (error) {
    console.warn('notification action failed', error);
    await confirm(i18n.t('push.action_failed_title'), i18n.t('push.action_failed_body'));
  }
});

void Notifications.registerTaskAsync(NOTIFICATION_TASK).catch((error: unknown) =>
  console.warn('could not register the notification task', error),
);

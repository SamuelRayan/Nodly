import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { api, unwrap } from '@/api/client';
import { config } from '@/config';
import i18n from '@/i18n';

// Show notifications while the app is open, too.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

/**
 * Android notification channels (CLAUDE.md §8, §14). The importance of a channel can't be
 * changed by the app after it's created (only by the user), so choose carefully here.
 * They must exist before asking for permission on Android 13+.
 */
export async function ensureChannels(): Promise<void> {
  if (Platform.OS !== 'android') {
    return;
  }
  const { AndroidImportance, AndroidNotificationVisibility } = Notifications;
  await Promise.all([
    Notifications.setNotificationChannelAsync('checkin', {
      name: i18n.t('channels.checkin'),
      description: i18n.t('channels.checkin_description'),
      importance: AndroidImportance.HIGH,
    }),
    Notifications.setNotificationChannelAsync('moments', {
      name: i18n.t('channels.moments'),
      importance: AndroidImportance.DEFAULT,
    }),
    // Real emergencies only: loudest, visible on the lock screen, allowed through Do Not
    // Disturb when the user grants that. A custom alarm sound needs a new build (Phase 15).
    Notifications.setNotificationChannelAsync('help_alerts', {
      name: i18n.t('channels.help_alerts'),
      description: i18n.t('channels.help_alerts_description'),
      importance: AndroidImportance.MAX,
      bypassDnd: true,
      lockscreenVisibility: AndroidNotificationVisibility.PUBLIC,
      enableVibrate: true,
      vibrationPattern: [0, 800, 400, 800, 400, 800],
    }),
    Notifications.setNotificationChannelAsync('general', {
      name: i18n.t('channels.general'),
      importance: AndroidImportance.DEFAULT,
    }),
  ]);
}

/**
 * Action buttons, matched by the backend's categoryId. They act without opening the app: on
 * Android a background task handles the tap (push/background.ts). Identifiers must not contain
 * ":" or "-" (Expo docs).
 */
export async function ensureCategories(): Promise<void> {
  await Promise.all([
    Notifications.setNotificationCategoryAsync('checkin_reminder', [
      {
        identifier: 'im_okay',
        buttonTitle: i18n.t('elder.okay'),
        options: { opensAppToForeground: false },
      },
    ]),
    Notifications.setNotificationCategoryAsync('help_alert', [
      {
        identifier: 'on_it',
        buttonTitle: i18n.t('help.on_it'),
        options: { opensAppToForeground: false },
      },
    ]),
  ]);
}

let registeredToken: string | null = null;

/**
 * Ask for permission and register this phone's Expo push token with the API, for the signed-in
 * family member or for the paired elder device. Never throws: without push (no permission, no
 * Firebase config, no EAS project yet) the rest of the app still works.
 */
export async function registerForPush(target: 'user' | 'device'): Promise<void> {
  try {
    await ensureChannels();
    await ensureCategories();
    if (!config.easProjectId) {
      console.info('push: no EAS project id yet (see docs/SETUP.md); skipping registration');
      return;
    }
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== 'granted') {
      ({ status } = await Notifications.requestPermissionsAsync());
    }
    if (status !== 'granted') {
      return;
    }
    const token = (await Notifications.getExpoPushTokenAsync({ projectId: config.easProjectId }))
      .data;
    const body = {
      provider: 'expo' as const,
      token,
      platform: Platform.OS === 'ios' ? ('ios' as const) : ('android' as const),
    };
    if (target === 'user') {
      await unwrap(api.POST('/v1/me/push-tokens', { body }));
    } else {
      await unwrap(api.POST('/v1/device/push-token', { body }));
    }
    registeredToken = token;
  } catch (error) {
    console.warn('push: registration failed', error);
  }
}

/** On sign-out: stop this phone getting the user's notifications. */
export async function unregisterUserPush(): Promise<void> {
  if (!registeredToken) {
    return;
  }
  try {
    await unwrap(
      api.DELETE('/v1/me/push-tokens', { params: { query: { token: registeredToken } } }),
    );
  } catch (error) {
    console.warn('push: could not unregister', error);
  }
  registeredToken = null;
}

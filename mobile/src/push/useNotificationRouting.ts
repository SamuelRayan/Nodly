import { useQueryClient } from '@tanstack/react-query';
import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';
import { useEffect } from 'react';

import { api, unwrap } from '@/api/client';
import { keys } from '@/api/hooks';

type Where = 'elder' | 'family' | 'other';

/**
 * What tapping a notification (or one of its buttons) does. Buttons open the app
 * (opensAppToForeground), so the work happens here: "I'm okay" checks the elder in, "I'm on
 * it" acknowledges the Help alert. Each response is handled once, then cleared.
 */
export function useNotificationRouting(where: Where): void {
  const queryClient = useQueryClient();
  const response = Notifications.useLastNotificationResponse();

  useEffect(() => {
    if (!response || where === 'other') {
      return;
    }
    Notifications.clearLastNotificationResponse();
    const data = response.notification.request.content.data as Record<string, unknown>;
    const action = response.actionIdentifier;
    const type = typeof data.type === 'string' ? data.type : '';

    if (where === 'elder' && type === 'checkin_reminder') {
      if (action === 'im_okay') {
        void unwrap(api.POST('/v1/device/checkin', { body: { source: 'notification' } })).then(
          (today) => {
            queryClient.setQueryData(keys.deviceToday, today);
            router.push('/home/thanks');
          },
        );
      }
      return;
    }
    if (where !== 'family') {
      return;
    }
    const requestId = typeof data.request_id === 'string' ? data.request_id : null;
    if ((type === 'help' || type === 'help_call_me' || type === 'help_update') && requestId) {
      const open = () =>
        router.push({ pathname: '/help/[requestId]', params: { requestId } });
      if (action === 'on_it') {
        void unwrap(
          api.POST('/v1/help/{request_id}/ack', { params: { path: { request_id: requestId } } }),
        ).finally(open);
      } else {
        open();
      }
      return;
    }
    if (type.startsWith('checkin_')) {
      void queryClient.invalidateQueries({ queryKey: ['elders'] });
      router.navigate('/');
    }
  }, [response, where, queryClient]);
}

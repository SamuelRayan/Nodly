import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as Device from 'expo-device';
import Constants from 'expo-constants';
import { Platform } from 'react-native';

import { api, unwrap } from '@/api/client';
import { keys } from '@/api/hooks';
import { useAppStore } from '@/state/app';

/** A scanned or typed pairing code: "nodly://pair/7KQ4M2XD", "7KQ4-M2XD" or "7kq4 m2xd". */
export function codeFromScan(value: string): string | null {
  const match = /^nodly:\/\/pair\/([0-9A-Za-z-]+)$/.exec(value.trim());
  if (match) {
    return match[1];
  }
  return /^[0-9A-Za-z -]{8,12}$/.test(value.trim()) ? value.trim() : null;
}

/** Claim a pairing code: this phone becomes the elder's and keeps the device token. */
export function usePairing() {
  const queryClient = useQueryClient();
  const setDeviceToken = useAppStore((state) => state.setDeviceToken);
  return useMutation({
    mutationFn: (code: string) =>
      unwrap(
        api.POST('/v1/pairing/claim', {
          body: {
            code,
            platform: Platform.OS === 'ios' ? 'ios' : 'android',
            device_model: Device.modelName ?? undefined,
            app_version: Constants.expoConfig?.version,
          },
        }),
      ),
    onSuccess: async (claimed) => {
      queryClient.setQueryData(keys.deviceMe, {
        device: claimed.device,
        elder: claimed.elder,
        family: claimed.family,
        family_has_pin: false,
      });
      await queryClient.invalidateQueries({ queryKey: keys.deviceMe });
      // Stored in SecureStore; the root layout switches to the elder home.
      await setDeviceToken(claimed.device_token);
    },
  });
}

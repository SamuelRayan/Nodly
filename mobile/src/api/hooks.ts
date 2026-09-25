import { useQuery } from '@tanstack/react-query';

import { api, unwrap } from './client';

/** Query keys in one place so mutations can invalidate precisely. */
export const keys = {
  families: ['families'] as const,
  family: (id: string) => ['families', id] as const,
  invites: (familyId: string) => ['families', familyId, 'invites'] as const,
  elder: (id: string) => ['elders', id] as const,
  devices: (elderId: string) => ['elders', elderId, 'devices'] as const,
  deviceMe: ['device', 'me'] as const,
};

export function useFamilies() {
  return useQuery({
    queryKey: keys.families,
    queryFn: () => unwrap(api.GET('/v1/families')),
  });
}

export function useFamily(familyId: string) {
  return useQuery({
    queryKey: keys.family(familyId),
    queryFn: () =>
      unwrap(api.GET('/v1/families/{family_id}', { params: { path: { family_id: familyId } } })),
  });
}

export function useInvites(familyId: string) {
  return useQuery({
    queryKey: keys.invites(familyId),
    queryFn: () =>
      unwrap(
        api.GET('/v1/families/{family_id}/invites', {
          params: { path: { family_id: familyId } },
        }),
      ),
  });
}

export function useElder(elderId: string) {
  return useQuery({
    queryKey: keys.elder(elderId),
    queryFn: () =>
      unwrap(api.GET('/v1/elders/{elder_id}', { params: { path: { elder_id: elderId } } })),
  });
}

export function useDevices(elderId: string, refetchInterval?: number) {
  return useQuery({
    queryKey: keys.devices(elderId),
    queryFn: () =>
      unwrap(api.GET('/v1/elders/{elder_id}/devices', { params: { path: { elder_id: elderId } } })),
    refetchInterval,
  });
}

export function useDeviceMe() {
  return useQuery({
    queryKey: keys.deviceMe,
    queryFn: () => unwrap(api.GET('/v1/device/me')),
  });
}

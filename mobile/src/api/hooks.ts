import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, unwrap } from './client';

/** Query keys in one place so mutations can invalidate precisely. */
export const keys = {
  families: ['families'] as const,
  family: (id: string) => ['families', id] as const,
  invites: (familyId: string) => ['families', familyId, 'invites'] as const,
  elder: (id: string) => ['elders', id] as const,
  devices: (elderId: string) => ['elders', elderId, 'devices'] as const,
  deviceMe: ['device', 'me'] as const,
  deviceToday: ['device', 'today'] as const,
  checkins: (elderId: string) => ['elders', elderId, 'checkins'] as const,
  deviceHelp: ['device', 'help'] as const,
  familyHelp: (familyId: string) => ['families', familyId, 'help'] as const,
  help: (requestId: string) => ['help', requestId] as const,
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

/** The elder's day on their own phone: checked in or not, when the family would hear. */
export function useDeviceToday() {
  return useQuery({
    queryKey: keys.deviceToday,
    queryFn: () => unwrap(api.GET('/v1/device/today')),
    // Coming back to the home screen after a while (a new day, a family "mark okay").
    refetchInterval: 60_000,
  });
}

/** "I'm okay", from the home screen or a reminder's button. */
export function useCheckIn() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (source: 'app' | 'notification') =>
      unwrap(api.POST('/v1/device/checkin', { body: { source } })),
    onSuccess: (today) => queryClient.setQueryData(keys.deviceToday, today),
  });
}

/** An elder's check-in day, for the family. */
export function useCheckinStatus(elderId: string) {
  return useQuery({
    queryKey: keys.checkins(elderId),
    queryFn: () =>
      unwrap(
        api.GET('/v1/elders/{elder_id}/checkins/today', {
          params: { path: { elder_id: elderId } },
        }),
      ),
    refetchInterval: 60_000,
  });
}

/** "Mark okay" and "I'm on it" (missed check-in alert). */
export function useCheckinAction(elderId: string, action: 'mark-okay' | 'alert/ack') {
  const queryClient = useQueryClient();
  const path = { params: { path: { elder_id: elderId } } };
  return useMutation({
    mutationFn: () =>
      unwrap(
        action === 'mark-okay'
          ? api.POST('/v1/elders/{elder_id}/checkins/mark-okay', path)
          : api.POST('/v1/elders/{elder_id}/checkins/alert/ack', path),
      ),
    onSuccess: (status) => queryClient.setQueryData(keys.checkins(elderId), status),
  });
}

/** The elder's open Help request (null when there's none), polled while it's on screen. */
export function useDeviceHelp(pollMs?: number) {
  return useQuery({
    queryKey: keys.deviceHelp,
    queryFn: () => unwrap(api.GET('/v1/device/help')),
    refetchInterval: pollMs,
  });
}

export function useAskHelp() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { kind: 'help' | 'call_me'; network?: string }) =>
      unwrap(api.POST('/v1/device/help', { body })),
    onSuccess: (request) => queryClient.setQueryData(keys.deviceHelp, request),
  });
}

/** "I'm okay now". */
export function useCancelHelp() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST('/v1/device/help/cancel')),
    onSuccess: () => queryClient.setQueryData(keys.deviceHelp, null),
  });
}

/** Live Help requests in a family (the dashboard's red banner). */
export function useFamilyHelp(familyId: string) {
  return useQuery({
    queryKey: keys.familyHelp(familyId),
    queryFn: () =>
      unwrap(api.GET('/v1/families/{family_id}/help', { params: { path: { family_id: familyId } } })),
    refetchInterval: 10_000,
  });
}

export function useHelpRequest(requestId: string) {
  return useQuery({
    queryKey: keys.help(requestId),
    queryFn: () =>
      unwrap(api.GET('/v1/help/{request_id}', { params: { path: { request_id: requestId } } })),
    refetchInterval: 3_000,
  });
}

/** "I'm on it" and "resolved". */
export function useHelpAction(requestId: string, action: 'ack' | 'resolve') {
  const queryClient = useQueryClient();
  const path = { params: { path: { request_id: requestId } } };
  return useMutation({
    mutationFn: () =>
      unwrap(
        action === 'ack'
          ? api.POST('/v1/help/{request_id}/ack', path)
          : api.POST('/v1/help/{request_id}/resolve', { ...path, body: {} }),
      ),
    onSuccess: (request) => {
      queryClient.setQueryData(keys.help(requestId), request);
      void queryClient.invalidateQueries({ queryKey: ['families'] });
    },
  });
}

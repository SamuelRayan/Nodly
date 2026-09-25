import type { Session } from '@supabase/supabase-js';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, type ReactNode, useContext, useEffect, useState } from 'react';

import { api, unwrap } from '@/api/client';
import { unregisterUserPush } from '@/push/notifications';

import { supabase } from './supabase';

interface SessionState {
  /** False until the stored session (if any) has been read. */
  ready: boolean;
  session: Session | null;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [ready, setReady] = useState(false);
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    void supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, []);

  const signOut = async () => {
    await unregisterUserPush();
    await supabase.auth.signOut();
    queryClient.clear();
  };

  return (
    <SessionContext.Provider value={{ ready, session, signOut }}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const state = useContext(SessionContext);
  if (!state) {
    throw new Error('useSession() needs a <SessionProvider> above it');
  }
  return state;
}

/** The signed-in family member (created by the API on first call). */
export function useMe(enabled = true) {
  const { session } = useSession();
  return useQuery({
    queryKey: ['me', session?.user.id],
    queryFn: () => unwrap(api.GET('/v1/me')),
    enabled: enabled && session !== null,
  });
}

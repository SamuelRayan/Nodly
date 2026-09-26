import { create } from 'zustand';

import { secure } from '@/storage/secure';

/**
 * Which mode this phone is in, persisted in SecureStore:
 * - family: someone setting Nodly up for an elder (signs in with Supabase)
 * - elder: the elder's own phone, identified by its device token (no login)
 * Once an elder phone is paired it stays in elder mode; it only leaves when the family
 * disconnects it (the API answers device_revoked) or with the family PIN.
 */
export type Mode = 'family' | 'elder';
export type Notice = 'device_revoked' | 'left_elder_mode';

const MODE_KEY = 'nodly.mode';
const DEVICE_TOKEN_KEY = 'nodly.device_token';

interface AppState {
  hydrated: boolean;
  mode: Mode | null;
  deviceToken: string | null;
  notice: Notice | null;
  /** Paired a moment ago: the elder home first says who they're connected with (E2). */
  justPaired: boolean;
  hydrate: () => Promise<void>;
  chooseMode: (mode: Mode | null) => Promise<void>;
  setDeviceToken: (token: string) => Promise<void>;
  /** Forget the elder pairing (or the mode choice) and go back to the welcome screen. */
  resetToWelcome: (notice?: Notice) => Promise<void>;
  clearNotice: () => void;
  clearJustPaired: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  hydrated: false,
  mode: null,
  deviceToken: null,
  notice: null,
  justPaired: false,

  hydrate: async () => {
    const [mode, deviceToken] = await Promise.all([
      secure.get(MODE_KEY),
      secure.get(DEVICE_TOKEN_KEY),
    ]);
    set({
      hydrated: true,
      mode: mode === 'family' || mode === 'elder' ? mode : null,
      deviceToken,
    });
  },

  chooseMode: async (mode) => {
    if (mode) {
      await secure.set(MODE_KEY, mode);
    } else {
      await secure.remove(MODE_KEY);
    }
    set({ mode, notice: null });
  },

  setDeviceToken: async (token) => {
    await secure.set(DEVICE_TOKEN_KEY, token);
    await secure.set(MODE_KEY, 'elder');
    set({ deviceToken: token, mode: 'elder', justPaired: true });
  },

  resetToWelcome: async (notice) => {
    await Promise.all([secure.remove(DEVICE_TOKEN_KEY), secure.remove(MODE_KEY)]);
    set({ mode: null, deviceToken: null, notice: notice ?? null, justPaired: false });
  },

  clearNotice: () => set({ notice: null }),
  clearJustPaired: () => set({ justPaired: false }),
}));

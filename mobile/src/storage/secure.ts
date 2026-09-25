import * as SecureStore from 'expo-secure-store';

/**
 * SecureStore wrappers. Values can be rejected above ~2 KB on some platforms (Expo docs), and a
 * Supabase session can be larger, so `chunkedSecureStorage` splits values across keys.
 * Keys may only contain letters, digits, ".", "-" and "_".
 */

// Readable after the first unlock since boot, so future background work (e.g. an "I'm okay"
// tap on a notification) can use the elder's device token.
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK,
};
const CHUNK_SIZE = 1800;

export const secure = {
  get: (key: string) => SecureStore.getItemAsync(key, OPTIONS),
  set: (key: string, value: string) => SecureStore.setItemAsync(key, value, OPTIONS),
  remove: (key: string) => SecureStore.deleteItemAsync(key, OPTIONS),
};

/** A storage adapter (getItem/setItem/removeItem) that chunks large values. */
export const chunkedSecureStorage = {
  async getItem(key: string): Promise<string | null> {
    const count = await secure.get(`${key}.n`);
    if (count === null) {
      return null;
    }
    const parts: string[] = [];
    for (let i = 0; i < Number(count); i += 1) {
      const part = await secure.get(`${key}.${i}`);
      if (part === null) {
        return null; // incomplete write; treat as missing
      }
      parts.push(part);
    }
    return parts.join('');
  },

  async setItem(key: string, value: string): Promise<void> {
    const previous = Number((await secure.get(`${key}.n`)) ?? 0);
    const count = Math.max(1, Math.ceil(value.length / CHUNK_SIZE));
    for (let i = 0; i < count; i += 1) {
      await secure.set(`${key}.${i}`, value.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE));
    }
    await secure.set(`${key}.n`, String(count));
    for (let i = count; i < previous; i += 1) {
      await secure.remove(`${key}.${i}`);
    }
  },

  async removeItem(key: string): Promise<void> {
    const count = Number((await secure.get(`${key}.n`)) ?? 0);
    await secure.remove(`${key}.n`);
    for (let i = 0; i < count; i += 1) {
      await secure.remove(`${key}.${i}`);
    }
  },
};

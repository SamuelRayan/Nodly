import createClient from 'openapi-fetch';

import { supabase } from '@/auth/supabase';
import { config } from '@/config';
import { useAppStore } from '@/state/app';

import { ApiError } from './errors';
import type { paths } from './schema';

/**
 * The typed API client. Types come from backend/openapi.json (npm run gen:api); never write
 * them by hand. The Authorization header depends on the mode: an elder phone sends its device
 * token, a family member their Supabase access token (supabase-js refreshes it as needed).
 */
export const api = createClient<paths>({ baseUrl: config.apiUrl });

// A phone's clock can be off by seconds or minutes, so anything compared with a server timestamp
// (like a code's expiry) uses the server's clock, estimated from the latest response's Date
// header. The header has whole seconds, hence the +500 ms.
let clockOffsetMs = 0;

/** "Now" on the server's clock, in milliseconds. */
export function serverNow(): number {
  return Date.now() + clockOffsetMs;
}

api.use({
  onResponse({ response }) {
    const server = Date.parse(response.headers.get('date') ?? '');
    if (!Number.isNaN(server)) {
      clockOffsetMs = server + 500 - Date.now();
    }
  },
  async onRequest({ request }) {
    const { mode, deviceToken } = useAppStore.getState();
    if (mode === 'elder' && deviceToken) {
      request.headers.set('Authorization', `Bearer ${deviceToken}`);
    } else if (mode === 'family') {
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token;
      if (token) {
        request.headers.set('Authorization', `Bearer ${token}`);
      }
    }
    return request;
  },
});

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Await an openapi-fetch call and return its data, or throw an ApiError. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await call;
  } catch (cause) {
    throw ApiError.network(cause);
  }
  if (result.error !== undefined || !result.response.ok) {
    throw ApiError.fromResponse(result.response, result.error);
  }
  return result.data as T;
}

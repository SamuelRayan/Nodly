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

api.use({
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

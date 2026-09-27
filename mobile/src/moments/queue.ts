import NetInfo from '@react-native-community/netinfo';
import { Directory, File, Paths, UploadType } from 'expo-file-system';
import { AppState } from 'react-native';
import { create } from 'zustand';

import { api, authorizationHeader, unwrap } from '@/api/client';
import { ApiError } from '@/api/errors';
import { queryClient } from '@/api/query';
import { config } from '@/config';

/**
 * The moment upload queue (CLAUDE.md §9): a shared photo is copied into the app's own storage
 * and listed in a small JSON file, so it survives the app being closed and the phone going
 * offline. Each item walks: queued → uploading → checking → posted | rejected, retrying with
 * backoff whenever something fails. The server decides everything about it (including whether
 * it counts for today, §10); this only moves bytes and reports states.
 */

export type QueueState = 'queued' | 'uploading' | 'checking' | 'posted' | 'rejected';

export interface QueueItem {
  localId: string;
  /** null when an elder's phone shares it */
  familyId: string | null;
  fileUri: string;
  contentType: 'image/jpeg';
  kind: 'photo';
  momentId?: string;
  uploadPath?: string;
  uploaded?: boolean;
  state: QueueState;
  attempts: number;
  nextTryAt: number;
  /** Waiting because the last try failed (offline, server away). */
  waiting: boolean;
  qualifies?: boolean;
  notQualifyingReason?: string | null;
  rejectReason?: string | null;
  createdAt: number;
}

const DIRECTORY = new Directory(Paths.document, 'moment-queue');
const LIST = new File(Paths.document, 'moment-queue.json');
const CHECK_EVERY_MS = 2_000;
const KEEP_FINISHED_MS = 24 * 60 * 60 * 1000;

interface QueueStore {
  items: QueueItem[];
  loaded: boolean;
}

export const useMomentQueue = create<QueueStore>(() => ({ items: [], loaded: false }));

function save(items: QueueItem[]): void {
  useMomentQueue.setState({ items });
  try {
    LIST.write(JSON.stringify(items));
  } catch (error) {
    console.warn('moment queue: could not save', error);
  }
}

function update(localId: string, patch: Partial<QueueItem>): QueueItem | undefined {
  const items = useMomentQueue
    .getState()
    .items.map((item) => (item.localId === localId ? { ...item, ...patch } : item));
  save(items);
  return items.find((item) => item.localId === localId);
}

function load(): void {
  if (useMomentQueue.getState().loaded) {
    return;
  }
  let items: QueueItem[] = [];
  try {
    if (LIST.exists) {
      items = JSON.parse(LIST.textSync()) as QueueItem[];
    }
  } catch (error) {
    console.warn('moment queue: unreadable list, starting fresh', error);
  }
  const now = Date.now();
  // Forget finished items after a day (their files are already gone).
  items = items.filter(
    (item) =>
      !(['posted', 'rejected'] as QueueState[]).includes(item.state) ||
      now - item.createdAt < KEEP_FINISHED_MS,
  );
  useMomentQueue.setState({ loaded: true });
  save(items);
}

/** Add a prepared photo (a local file) to the queue and start sending it. */
export function enqueuePhoto(sourceUri: string, familyId: string | null): QueueItem {
  load();
  if (!DIRECTORY.exists) {
    DIRECTORY.create({ intermediates: true });
  }
  const localId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const copy = new File(DIRECTORY, `${localId}.jpg`);
  new File(sourceUri).copy(copy);
  const item: QueueItem = {
    localId,
    familyId,
    fileUri: copy.uri,
    contentType: 'image/jpeg',
    kind: 'photo',
    state: 'queued',
    attempts: 0,
    nextTryAt: 0,
    waiting: false,
    createdAt: Date.now(),
  };
  save([item, ...useMomentQueue.getState().items]);
  kick();
  return item;
}

function backoffMs(attempts: number): number {
  return Math.min(60_000, 2_000 * 2 ** Math.min(attempts, 5));
}

async function startIntent(item: QueueItem): Promise<QueueItem | undefined> {
  const body = { kind: item.kind, content_type: item.contentType };
  const moment = item.familyId
    ? await unwrap(
        api.POST('/v1/families/{family_id}/moments', {
          params: { path: { family_id: item.familyId } },
          body,
        }),
      )
    : await unwrap(api.POST('/v1/device/moments', { body }));
  return update(item.localId, {
    momentId: moment.id,
    uploadPath: moment.upload_path ?? undefined,
    state: 'uploading',
  });
}

async function sendFile(item: QueueItem): Promise<QueueItem | undefined> {
  if (!item.uploaded && item.uploadPath) {
    const authorization = await authorizationHeader();
    const result = await new File(item.fileUri).upload(`${config.apiUrl}${item.uploadPath}`, {
      httpMethod: 'PUT',
      uploadType: UploadType.BINARY_CONTENT,
      headers: {
        'Content-Type': item.contentType,
        ...(authorization ? { Authorization: authorization } : {}),
      },
    });
    // 409: the file already arrived (the reply to an earlier try was lost). Carry on.
    if (result.status !== 200 && result.status !== 409) {
      throw new Error(`upload failed with ${result.status}`);
    }
    item = update(item.localId, { uploaded: true }) ?? item;
  }
  const path = { params: { path: { moment_id: item.momentId ?? '' } } };
  await unwrap(
    item.familyId
      ? api.POST('/v1/moments/{moment_id}/complete', path)
      : api.POST('/v1/device/moments/{moment_id}/complete', path),
  );
  return update(item.localId, { state: 'checking' });
}

async function checkResult(item: QueueItem): Promise<QueueItem | undefined> {
  const path = { params: { path: { moment_id: item.momentId ?? '' } } };
  if (!item.familyId) {
    // Elders' phones only see their own moment in the feed until it's checked.
    const page = await unwrap(api.GET('/v1/device/moments', { params: { query: { limit: 30 } } }));
    const mine = page.items.find((moment) => moment.id === item.momentId);
    return settle(item, mine);
  }
  return settle(item, await unwrap(api.GET('/v1/moments/{moment_id}', path)));
}

function settle(
  item: QueueItem,
  moment: { status: string; qualifies: boolean; not_qualifying_reason: string | null; reject_reason: string | null } | undefined,
): QueueItem | undefined {
  if (!moment || moment.status === 'checking' || moment.status === 'awaiting_upload') {
    return update(item.localId, { nextTryAt: Date.now() + CHECK_EVERY_MS });
  }
  const finished = update(item.localId, {
    state: moment.status === 'published' ? 'posted' : 'rejected',
    qualifies: moment.qualifies,
    notQualifyingReason: moment.not_qualifying_reason,
    rejectReason: moment.reject_reason,
  });
  try {
    new File(item.fileUri).delete();
  } catch {
    // already gone
  }
  void queryClient.invalidateQueries({ queryKey: ['families'] });
  void queryClient.invalidateQueries({ queryKey: ['device'] });
  return finished;
}

async function step(item: QueueItem): Promise<void> {
  try {
    let current: QueueItem | undefined = item;
    if (!current.momentId) {
      current = await startIntent(current);
    }
    if (current && current.state === 'uploading') {
      current = await sendFile(current);
    }
    if (current && current.state === 'checking') {
      await checkResult(current);
    }
    if (current?.waiting) {
      update(item.localId, { waiting: false, attempts: 0 });
    }
  } catch (error) {
    // The moment itself is gone (deleted, or this phone left the family): give up on it.
    if (error instanceof ApiError && error.status === 404 && item.momentId) {
      update(item.localId, { state: 'rejected', rejectReason: 'upload_missing' });
      return;
    }
    const attempts = item.attempts + 1;
    update(item.localId, { waiting: true, attempts, nextTryAt: Date.now() + backoffMs(attempts) });
  }
}

let running = false;
let timer: ReturnType<typeof setTimeout> | null = null;

/** Work through whatever is due now, then schedule the next look. Safe to call any time. */
export function kick(): void {
  load();
  if (running) {
    return;
  }
  running = true;
  void (async () => {
    try {
      const due = useMomentQueue
        .getState()
        .items.filter(
          (item) =>
            !(['posted', 'rejected'] as QueueState[]).includes(item.state) &&
            item.nextTryAt <= Date.now(),
        )
        .reverse(); // oldest first
      for (const item of due) {
        await step(item);
      }
    } finally {
      running = false;
      schedule();
    }
  })();
}

function schedule(): void {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  const pending = useMomentQueue
    .getState()
    .items.filter((item) => !(['posted', 'rejected'] as QueueState[]).includes(item.state));
  if (pending.length === 0) {
    return;
  }
  const next = Math.min(...pending.map((item) => item.nextTryAt));
  timer = setTimeout(kick, Math.max(500, next - Date.now()));
}

/** Resume on launch, when the network comes back, and when the app returns to the front. */
export function startMomentQueue(): () => void {
  load();
  kick();
  const offNet = NetInfo.addEventListener((state) => {
    if (state.isConnected) {
      // Try waiting items straight away rather than after their backoff.
      save(
        useMomentQueue
          .getState()
          .items.map((item) => (item.waiting ? { ...item, nextTryAt: 0 } : item)),
      );
      kick();
    }
  });
  const offApp = AppState.addEventListener('change', (state) => {
    if (state === 'active') {
      kick();
    }
  });
  return () => {
    offNet();
    offApp.remove();
  };
}

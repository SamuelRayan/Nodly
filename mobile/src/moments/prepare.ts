import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';

import { config } from '@/config';

// Big enough for a phone screen, small enough to send on a weak connection (CLAUDE.md §9:
// client-side compression before upload).
const LONGEST_SIDE = 1600;
const QUALITY = 0.8;

/** A picked or taken photo, resized and saved as JPEG. Returns the new file's uri. */
export async function preparePhoto(uri: string, width: number, height: number): Promise<string> {
  const context = ImageManipulator.manipulate(uri);
  if (Math.max(width, height) > LONGEST_SIDE) {
    context.resize(width >= height ? { width: LONGEST_SIDE, height: null } : { width: null, height: LONGEST_SIDE });
  }
  const image = await context.renderAsync();
  const result = await image.saveAsync({ compress: QUALITY, format: SaveFormat.JPEG });
  return result.uri;
}

/** The API returns signed links as paths; the app knows which server it talks to. */
export function mediaUrl(path: string | null | undefined): string | undefined {
  return path ? `${config.apiUrl}${path}` : undefined;
}

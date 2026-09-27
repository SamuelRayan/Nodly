import * as ImagePicker from 'expo-image-picker';

export interface PickedPhoto {
  uri: string;
  width: number;
  height: number;
}

/** Take a photo or choose one. null if cancelled, 'denied' if the camera isn't allowed. */
export async function pickPhoto(source: 'camera' | 'library'): Promise<PickedPhoto | null | 'denied'> {
  if (source === 'camera') {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      return 'denied';
    }
  }
  const options: ImagePicker.ImagePickerOptions = { mediaTypes: ['images'], quality: 1 };
  const result =
    source === 'camera'
      ? await ImagePicker.launchCameraAsync(options)
      : await ImagePicker.launchImageLibraryAsync(options);
  if (result.canceled || result.assets.length === 0) {
    return null;
  }
  const [asset] = result.assets;
  return { uri: asset.uri, width: asset.width, height: asset.height };
}

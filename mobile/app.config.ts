import type { ConfigContext, ExpoConfig } from 'expo/config';

// Chosen per build profile in eas.json (CLAUDE.md §19): galaxy | play | ios.
const store = process.env.EXPO_PUBLIC_STORE ?? 'galaxy';
// Permanent once uploaded to a store. com.nodlyapp.nodly: unused on Google Play and not tied to
// a domain someone else owns (docs/DECISIONS.md D49).
const APP_ID = 'com.nodlyapp.nodly';
// EAS project @samuelrayan/nodly (npx eas-cli@latest init). Not a secret; builds and Expo push
// tokens need it.
const EAS_PROJECT_ID = 'a00f75c5-4eed-45ad-b6af-f3e5191372ff';
// Firebase config for Android push (FCM), never committed: a path in mobile/.env locally, an
// EAS "file" environment variable in cloud builds (docs/SETUP.md). Without it, push is off.
const googleServicesFile = process.env.GOOGLE_SERVICES_JSON;

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  owner: 'samuelrayan',
  name: 'Nodly',
  slug: 'nodly',
  scheme: 'nodly',
  version: '0.1.0',
  // Not locked: foldables, split screen and pop-up view (Galaxy optimisation, §15).
  orientation: 'default',
  icon: './assets/images/icon.png',
  userInterfaceStyle: 'automatic',
  ios: {
    bundleIdentifier: APP_ID,
    icon: './assets/expo.icon',
  },
  android: {
    package: APP_ID,
    adaptiveIcon: {
      backgroundColor: '#2D6A4F',
      foregroundImage: './assets/images/android-icon-foreground.png',
      backgroundImage: './assets/images/android-icon-background.png',
      monochromeImage: './assets/images/android-icon-monochrome.png',
    },
    predictiveBackGestureEnabled: false,
    ...(googleServicesFile ? { googleServicesFile } : {}),
  },
  plugins: [
    'expo-router',
    [
      'expo-splash-screen',
      {
        backgroundColor: '#FAF6EE',
        image: './assets/images/splash-icon.png',
        imageWidth: 96,
        dark: { backgroundColor: '#16130F', image: './assets/images/splash-icon.png' },
      },
    ],
    'expo-secure-store',
    'expo-localization',
    [
      'expo-camera',
      {
        cameraPermission:
          'Nodly uses the camera to scan your family’s code and to take photos to share with them.',
      },
    ],
    ['expo-notifications', { color: '#2D6A4F' }],
    [
      'expo-image-picker',
      {
        photosPermission: 'Nodly opens your photos so you can share one with your family.',
        cameraPermission: 'Nodly uses the camera to take photos and videos to share with your family.',
        microphonePermission: 'Nodly uses the microphone to record sound with your videos.',
      },
    ],
    [
      'expo-audio',
      {
        microphonePermission: 'Nodly uses the microphone to record voice notes for your family.',
        recordAudioAndroid: true,
        // Voice notes play while the app is open; no background service needed.
        enableBackgroundPlayback: false,
      },
    ],
    ['expo-video', { supportsBackgroundPlayback: false, supportsPictureInPicture: false }],
    [
      // The design's fonts (SIL Open Font License, see assets/fonts/OFL-*.txt), embedded at
      // build time. Use fontFamily + fontWeight: https://docs.expo.dev/develop/user-interface/fonts/
      'expo-font',
      {
        android: {
          fonts: [
            {
              fontFamily: 'Atkinson Hyperlegible',
              fontDefinitions: [
                { path: './assets/fonts/atkinson_hyperlegible_regular.ttf', weight: 400 },
                { path: './assets/fonts/atkinson_hyperlegible_bold.ttf', weight: 700 },
              ],
            },
            {
              // Static instances (expo-font 57.0.4's plugin takes one file per weight; it
              // doesn't read variable-font axes yet).
              fontFamily: 'Newsreader',
              fontDefinitions: [
                { path: './assets/fonts/newsreader_medium.ttf', weight: 500 },
                { path: './assets/fonts/newsreader_semibold.ttf', weight: 600 },
                { path: './assets/fonts/newsreader_bold.ttf', weight: 700 },
              ],
            },
          ],
        },
        ios: {
          fonts: [
            './assets/fonts/atkinson_hyperlegible_regular.ttf',
            './assets/fonts/atkinson_hyperlegible_bold.ttf',
            './assets/fonts/newsreader_medium.ttf',
            './assets/fonts/newsreader_semibold.ttf',
            './assets/fonts/newsreader_bold.ttf',
          ],
        },
      },
    ],
  ],
  experiments: {
    typedRoutes: true,
    reactCompiler: true,
  },
  extra: {
    store,
    eas: { projectId: EAS_PROJECT_ID },
  },
});

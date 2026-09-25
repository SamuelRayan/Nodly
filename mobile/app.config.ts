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
      backgroundColor: '#F6F1E7',
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
        backgroundColor: '#F6F1E7',
        image: './assets/images/splash-icon.png',
        imageWidth: 76,
        dark: { backgroundColor: '#1C1A17', image: './assets/images/splash-icon.png' },
      },
    ],
    'expo-secure-store',
    'expo-localization',
    [
      'expo-camera',
      { cameraPermission: 'Nodly uses the camera to scan the code your family shows you.' },
    ],
    ['expo-notifications', { color: '#245A41' }],
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

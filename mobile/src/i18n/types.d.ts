import 'i18next';

import type en from './en.json';

// Typed t() keys: a key missing from en.json is a type error.
declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'translation';
    resources: { translation: typeof en };
  }
}

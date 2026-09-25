import { getLocales } from 'expo-localization';
import { createInstance } from 'i18next';
import { initReactI18next } from 'react-i18next';

import en from './en.json';

/** Languages with a strings file. Add one: create xx.json and list it here. */
export const SUPPORTED_LANGUAGES = ['en'] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

const resources = { en: { translation: en } } as const;

function supported(tag: string | null | undefined): SupportedLanguage | undefined {
  if (!tag) {
    return undefined;
  }
  const code = tag.toLowerCase().split('-')[0];
  return SUPPORTED_LANGUAGES.find((language) => language === code);
}

/** The phone's first preferred language we have strings for, else English. */
export function deviceLanguage(): SupportedLanguage {
  for (const locale of getLocales()) {
    const match = supported(locale.languageTag);
    if (match) {
      return match;
    }
  }
  return 'en';
}

const i18n = createInstance();

void i18n.use(initReactI18next).init({
  resources,
  lng: deviceLanguage(),
  fallbackLng: 'en',
  interpolation: { escapeValue: false }, // React already escapes
  returnNull: false,
});

/** An elder's language setting (from their profile) wins over the phone's. */
export function applyLanguage(preferred?: string | null): void {
  const language = supported(preferred) ?? deviceLanguage();
  if (i18n.language !== language) {
    void i18n.changeLanguage(language);
  }
}

export default i18n;

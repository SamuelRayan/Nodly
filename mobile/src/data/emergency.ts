/**
 * The number to call for a medical emergency, by ISO 3166 country (CLAUDE.md §8: Help screens
 * always show the local emergency number; Nodly is not an emergency service).
 *
 * Source: https://en.wikipedia.org/wiki/List_of_emergency_telephone_numbers (retrieved
 * 2026-09-26), ambulance numbers where the country has one. EU/EEA countries use 112 (EU law
 * requires it to work everywhere in the Union). India uses 112, its single emergency number.
 * TODO(Phase 16): check every entry against each country's official source before launch.
 * Countries not listed get no number: the screen says "your local emergency number" instead.
 */
const EU_EEA_112 = [
  'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'DE', 'GR', 'HU', 'IE', 'LV', 'LT',
  'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK', 'SI', 'SE', 'IS', 'LI', 'NO',
] as const;

const NUMBERS: Record<string, string> = {
  ...Object.fromEntries(EU_EEA_112.map((code) => [code, '112'])),
  // EU countries whose ambulance line differs; 112 also works there.
  FR: '15',
  IT: '118',
  ES: '112',
  IN: '112',
  US: '911',
  CA: '911',
  MX: '911',
  GB: '999',
  AU: '000',
  NZ: '111',
  SG: '995',
  MY: '999',
  PH: '911',
  JP: '119',
  KR: '119',
  CN: '120',
  HK: '999',
  TW: '119',
  AE: '998',
  SA: '997',
  QA: '999',
  BD: '999',
  NP: '102',
  ZA: '10177',
  NG: '112',
  KE: '911',
  BR: '192',
  AR: '107',
  CH: '144',
  IL: '101',
  TR: '112',
  RU: '103',
  EG: '123',
  TH: '1669',
  VN: '115',
  ID: '118',
};

/** The medical emergency number for a country, or null if we don't have a checked one. */
export function emergencyNumber(countryCode: string | null | undefined): string | null {
  return countryCode ? (NUMBERS[countryCode.toUpperCase()] ?? null) : null;
}

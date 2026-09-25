/**
 * Design tokens from CLAUDE.md §15 (Claude Design may refine them; keep the contrast rules:
 * body text ≥ 7:1, large bold labels ≥ 4.5:1, no pure white and no pure black).
 */

export type ColorScheme = 'light' | 'dark';

export const colors = {
  light: {
    background: '#F6F1E7',
    surface: '#FFFBF4',
    text: '#2A2520',
    textMuted: '#52483F',
    ok: '#245A41',
    onOk: '#FFFBF4',
    help: '#B3261E', // reserved for real Help
    onHelp: '#FFFBF4',
    accent: '#A0501C', // icons / large text only
    border: '#D9CFC0',
  },
  dark: {
    background: '#1C1A17',
    surface: '#262320',
    text: '#F1EADF',
    textMuted: '#CFC5B7',
    ok: '#8FD1AE',
    onOk: '#1C1A17',
    help: '#F2B8B5',
    onHelp: '#1C1A17',
    accent: '#E7A47A',
    border: '#3A352F',
  },
} as const;

export type Colors = { [K in keyof (typeof colors)['light']]: string };

/** Type and touch sizes. Elder mode: body ≥ 20, titles 28–34, primary buttons ≥ 64 tall. */
export const scales = {
  family: {
    body: 16,
    small: 14,
    heading: 20,
    title: 26,
    buttonText: 17,
    buttonHeight: 48,
    space: 16,
    radius: 12,
  },
  elder: {
    body: 22,
    small: 20,
    heading: 26,
    title: 32,
    buttonText: 26,
    buttonHeight: 72,
    space: 20,
    radius: 16,
  },
} as const;

export type Scale = { [K in keyof (typeof scales)['family']]: number };
export type ScaleName = keyof typeof scales;

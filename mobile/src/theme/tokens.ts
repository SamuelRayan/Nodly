/**
 * Design tokens from the Claude Design handoff (design/2026-09-26-nodly-handoff, D70), light
 * and dark. Contrast (checked): body text ≥ 7.5:1 on every background, labels on green, red and
 * alert buttons ≥ 5.4:1. No pure white and no pure black (CLAUDE.md §15): where the design
 * draws white on green or red, we use cream.
 */

export type ColorScheme = 'light' | 'dark';

export const colors = {
  light: {
    background: '#FAF6EE',
    surface: '#FFFDF9',
    border: '#E7DFD2',
    borderStrong: '#CFC4B3', // buttons and inputs
    text: '#1E1A15',
    textMuted: '#574E44',
    ok: '#2D6A4F', // primary action, "okay"
    onOk: '#FAF6EE',
    onOkMuted: '#E3F0E6',
    okText: '#1F4D39', // green text on a green tint
    okTint: '#DCEBDF',
    okTintSoft: '#EEF4EF',
    okPanel: '#F1F6F1',
    ink: '#1E1A15', // dark buttons ("Share a moment")
    onInk: '#FAF6EE',
    accent: '#E8A33D', // amber: "new" badges, late
    onAccent: '#1E1A15',
    sand: '#F8E6C4', // moments, voice
    onSand: '#5C4A2A',
    neutralTint: '#F3EDE2',
    dashed: '#B8AC9A', // a missed day in the week strip
    help: '#B23A2B', // reserved for real Help and destructive actions
    onHelp: '#FAF6EE',
    helpText: '#8A2A1F',
    helpTint: '#F6DCD6',
    helpTintBorder: '#EBC3BA',
    helpPage: '#FBEDEA',
    alert: '#A5301F', // full-screen family alerts
    alertPanel: '#8A2718',
    alertButton: '#5E1A10',
    onAlert: '#FFFDF9',
    onAlertMuted: '#FBE3DE',
    star: '#B7791F',
    blueTint: '#DDE6F0',
    onBlue: '#2B3F55',
  },
  dark: {
    background: '#16130F',
    surface: '#211D18',
    border: '#3A342C',
    borderStrong: '#4A433A',
    text: '#F2ECE2',
    textMuted: '#B8AC9C',
    ok: '#2D6A4F',
    onOk: '#F2ECE2',
    onOkMuted: '#CFE3D5',
    okText: '#9FD3B4',
    okTint: '#1E3328',
    okTintSoft: '#1A2A21',
    okPanel: '#1B2820',
    ink: '#3A332A',
    onInk: '#F2ECE2',
    accent: '#E8A33D',
    onAccent: '#1E1A15',
    sand: '#3A2F1E',
    onSand: '#E3C99A',
    neutralTint: '#2A251F',
    dashed: '#6E6558',
    help: '#B23A2B',
    onHelp: '#F2ECE2',
    helpText: '#F2A596',
    helpTint: '#3A1F1B',
    helpTintBorder: '#5A2C25',
    helpPage: '#24160F',
    alert: '#A5301F',
    alertPanel: '#8A2718',
    alertButton: '#5E1A10',
    onAlert: '#F2ECE2',
    onAlertMuted: '#FBE3DE',
    star: '#E0A84A',
    blueTint: '#23303D',
    onBlue: '#C9D8E8',
  },
} as const;

export type Colors = { [K in keyof (typeof colors)['light']]: string };

/** Newsreader for headings, Atkinson Hyperlegible for everything else (embedded, D70). */
export const fonts = {
  heading: 'Newsreader',
  body: 'Atkinson Hyperlegible',
} as const;

/**
 * Type and touch sizes. Elder mode (CLAUDE.md §15): body ≥ 20, big titles, primary buttons
 * ≥ 64 tall and full width. Family mode is denser.
 */
export const scales = {
  family: {
    body: 16,
    small: 14,
    heading: 21,
    title: 30,
    buttonText: 16,
    buttonHeight: 52,
    space: 16,
    radius: 16,
    cardRadius: 26,
  },
  elder: {
    body: 22,
    small: 20,
    heading: 28,
    title: 44,
    buttonText: 24,
    buttonHeight: 72,
    space: 20,
    radius: 22,
    cardRadius: 28,
  },
} as const;

export type Scale = { [K in keyof (typeof scales)['family']]: number };
export type ScaleName = keyof typeof scales;

import { createContext, type ReactNode, useContext } from 'react';
import { useColorScheme } from 'react-native';

import { type Colors, colors, type Scale, type ScaleName, scales } from './tokens';

export interface Theme {
  colors: Colors;
  scale: Scale;
  scaleName: ScaleName;
  dark: boolean;
}

const ThemeContext = createContext<Theme | null>(null);

/** Elder screens use the elder scale; everything else the family scale. */
export function ThemeProvider({ scale, children }: { scale: ScaleName; children: ReactNode }) {
  const dark = useColorScheme() === 'dark';
  const theme: Theme = {
    colors: dark ? colors.dark : colors.light,
    scale: scales[scale],
    scaleName: scale,
    dark,
  };
  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  const theme = useContext(ThemeContext);
  if (!theme) {
    throw new Error('useTheme() needs a <ThemeProvider> above it');
  }
  return theme;
}

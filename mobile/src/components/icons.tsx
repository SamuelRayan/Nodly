import Svg, { Circle, Path, Rect } from 'react-native-svg';

import { useTheme } from '@/theme';

// The design's line icons (24-unit grid, 2px stroke, round caps), from the handoff's SVGs.
const ICONS = {
  photo: (
    <>
      <Rect x={3} y={5} width={18} height={14} rx={2} />
      <Circle cx={9} cy={10} r={1.6} />
      <Path d="M21 16l-5-5-8 8" />
    </>
  ),
  help: (
    <>
      <Circle cx={12} cy={12} r={9} />
      <Path d="M12 7.5v5.5" />
      <Path d="M12 16.5v.01" />
    </>
  ),
  check: <Path d="M5 12.5l4.5 4.5L19 7.5" />,
  checkCircle: (
    <>
      <Circle cx={12} cy={12} r={9} />
      <Path d="M8.5 12.5l2.5 2.5 4.5-5" />
    </>
  ),
  clock: (
    <>
      <Circle cx={12} cy={12} r={9} />
      <Path d="M12 7v5l3 2" />
    </>
  ),
  mic: (
    <>
      <Rect x={9} y={3} width={6} height={11} rx={3} />
      <Path d="M5 11a7 7 0 0 0 14 0" />
      <Path d="M12 18v3" />
    </>
  ),
  arrowRight: (
    <>
      <Path d="M5 12h14" />
      <Path d="M13 6l6 6-6 6" />
    </>
  ),
  arrowLeft: (
    <>
      <Path d="M19 12H5" />
      <Path d="M11 6l-6 6 6 6" />
    </>
  ),
  chevronRight: <Path d="M9 6l6 6-6 6" />,
  phone: (
    <Path d="M5 4h3l2 5-2.5 1.5a11 11 0 0 0 6 6L15 14l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z" />
  ),
  lock: (
    <>
      <Rect x={5} y={11} width={14} height={9} rx={2} />
      <Path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </>
  ),
  home: <Path d="M4 11l8-6 8 6v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z" />,
  qr: (
    <>
      <Rect x={3} y={3} width={7} height={7} rx={1} />
      <Rect x={14} y={3} width={7} height={7} rx={1} />
      <Rect x={3} y={14} width={7} height={7} rx={1} />
      <Path d="M14 14h3v3h-3z" />
      <Path d="M20 14v.01" />
      <Path d="M14 20h.01" />
      <Path d="M17 20h4v-3" />
    </>
  ),
  close: (
    <>
      <Path d="M6 6l12 12" />
      <Path d="M18 6L6 18" />
    </>
  ),
  bell: (
    <>
      <Path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z" />
      <Path d="M10 20.5a2 2 0 0 0 4 0" />
    </>
  ),
  heart: (
    <Path d="M12 20s-7.5-4.6-7.5-10.2A4.2 4.2 0 0 1 12 7.3a4.2 4.2 0 0 1 7.5 2.5C19.5 15.4 12 20 12 20z" />
  ),
  video: (
    <>
      <Rect x={3} y={6} width={13} height={12} rx={2} />
      <Path d="M16 10l5-3v10l-5-3" />
    </>
  ),
  refresh: (
    <>
      <Path d="M20 11a8 8 0 1 0-2.3 5.7" />
      <Path d="M20 5v6h-6" />
    </>
  ),
  ticket: (
    <>
      <Path d="M4 6h16v4a2 2 0 0 0 0 4v4H4v-4a2 2 0 0 0 0-4z" />
      <Path d="M14 7v2" />
      <Path d="M14 11v2" />
      <Path d="M14 15v2" />
    </>
  ),
  star: <Path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" />,
  shield: (
    <>
      <Path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" />
      <Path d="M9 12l2 2 4-4" />
    </>
  ),
} as const;

export type IconName = keyof typeof ICONS;

/** Decorative by default: icons always sit next to a text label (CLAUDE.md §15). */
export function Icon({
  name,
  size = 24,
  color,
  strokeWidth = 2.2,
}: {
  name: IconName;
  size?: number;
  color?: string;
  strokeWidth?: number;
}) {
  const { colors } = useTheme();
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color ?? colors.text}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      {ICONS[name]}
    </Svg>
  );
}

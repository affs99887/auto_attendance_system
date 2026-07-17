// 设计稿 icons.jsx 平移：16px 线条图标，颜色继承 currentColor。
import type { ReactNode, SVGProps } from 'react';

// `stroke` 与 SVG 原生 stroke (string) 冲突，所以这里用 `strokeWidth` 自定义键。
export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'children' | 'strokeWidth'> {
  size?: number;
  strokeWidth?: number;
}

const makeIcon = (children: ReactNode, viewBox: string = '0 0 16 16') => {
  const Cmp = ({ size = 16, strokeWidth = 1.5, ...props }: IconProps) => (
    <svg
      width={size}
      height={size}
      viewBox={viewBox}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {children}
    </svg>
  );
  return Cmp;
};

export const Icon = {
  Dashboard: makeIcon(
    <>
      <rect x="1.5" y="1.5" width="5.5" height="6.5" rx="1" />
      <rect x="9" y="1.5" width="5.5" height="4" rx="1" />
      <rect x="1.5" y="9.5" width="5.5" height="5" rx="1" />
      <rect x="9" y="7" width="5.5" height="7.5" rx="1" />
    </>,
  ),
  Records: makeIcon(
    <>
      <rect x="2" y="3" width="12" height="11" rx="1.5" />
      <path d="M5 1.5v3M11 1.5v3M2 6.5h12" />
      <path d="M5 9h2M9 9h2M5 11.5h2" />
    </>,
  ),
  Logs: makeIcon(
    <>
      <path d="M3 1.5h7l3 3v10H3z" />
      <path d="M10 1.5v3h3" />
      <path d="M5.5 8h5M5.5 10.5h5M5.5 5.5h2" />
    </>,
  ),
  Settings: makeIcon(
    <>
      <circle cx="8" cy="8" r="2" />
      <path d="M8 1.5v1.5M8 13v1.5M2.5 8H1M15 8h-1.5M3.8 3.8l1 1M11.2 11.2l1 1M3.8 12.2l1-1M11.2 4.8l1-1" />
    </>,
  ),
  Info: makeIcon(
    <>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M8 7v4M8 5h.01" />
    </>,
  ),
  Play: makeIcon(<path d="M4 3l8 5-8 5V3z" fill="currentColor" stroke="none" />),
  Clock: makeIcon(
    <>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M8 4.5V8l2.2 2.2" />
    </>,
  ),
  Calendar: makeIcon(
    <>
      <rect x="2" y="3" width="12" height="11" rx="1.5" />
      <path d="M5 1.5v3M11 1.5v3M2 6.5h12" />
    </>,
  ),
  Check: makeIcon(<path d="M3.5 8.5l3 3 6-7" />),
  X: makeIcon(<path d="M4 4l8 8M12 4l-8 8" />),
  ChevronDown: makeIcon(<path d="M3 6l5 4 5-4" />),
  ChevronRight: makeIcon(<path d="M6 3l4 5-4 5" />),
  ChevronLeft: makeIcon(<path d="M10 3L6 8l4 5" />),
  Power: makeIcon(
    <>
      <path d="M5 4.5a5 5 0 1 0 6 0" />
      <path d="M8 1.5v6.5" />
    </>,
  ),
  Refresh: makeIcon(
    <>
      <path d="M13.5 7a5.5 5.5 0 0 0-10-2.5" />
      <path d="M2.5 9a5.5 5.5 0 0 0 10 2.5" />
      <path d="M2.5 2v3h3M13.5 14v-3h-3" />
    </>,
  ),
  Search: makeIcon(
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5l3 3" />
    </>,
  ),
  Plus: makeIcon(<path d="M8 3v10M3 8h10" />),
  Pencil: makeIcon(<path d="M11.2 2.3l2.5 2.5L5.4 13l-3.2.8.8-3.2 8.2-8.3zM9.5 4l2.5 2.5" />),
  Trash: makeIcon(
    <>
      <path d="M2.5 4h11" />
      <path d="M4.5 4V2.5h7V4" />
      <path d="M3.5 4l1 10h7l1-10" />
    </>,
  ),
  Filter: makeIcon(<path d="M1.5 3h13l-5 6v4l-3 1.5V9z" />),
  Download: makeIcon(
    <>
      <path d="M8 1.5v9M4 7.5l4 4 4-4" />
      <path d="M2 14h12" />
    </>,
  ),
  Eye: makeIcon(
    <>
      <path d="M1.5 8C3 5 5.5 3.5 8 3.5s5 1.5 6.5 4.5C13 11 10.5 12.5 8 12.5s-5-1.5-6.5-4.5z" />
      <circle cx="8" cy="8" r="2.2" />
    </>,
  ),
  Globe: makeIcon(
    <>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M1.5 8h13M8 1.5c2 2 3 4 3 6.5s-1 4.5-3 6.5M8 1.5c-2 2-3 4-3 6.5s1 4.5 3 6.5" />
    </>,
  ),
  Lock: makeIcon(
    <>
      <rect x="3" y="7" width="10" height="7" rx="1.5" />
      <path d="M5 7V4.5a3 3 0 1 1 6 0V7" />
    </>,
  ),
  Zap: makeIcon(<path d="M9 1.5L3.5 9h4L7 14.5 12.5 7h-4L9 1.5z" />),
  Activity: makeIcon(<path d="M1.5 8h3l2-5 3 10 2-5h3" />),
  Cloud: makeIcon(
    <path d="M4.5 12.5a3 3 0 0 1-.5-6 4 4 0 0 1 7.7.5 2.8 2.8 0 0 1 .3 5.5z" />,
  ),
  AlertTriangle: makeIcon(
    <>
      <path d="M8 1.5l6.5 11.5H1.5z" />
      <path d="M8 6.5v3M8 11.2h.01" />
    </>,
  ),
  Bell: makeIcon(
    <>
      <path d="M8 2a4.2 4.2 0 0 1 4.2 4.2v2.6l1.3 2.4H2.5l1.3-2.4V6.2A4.2 4.2 0 0 1 8 2z" />
      <path d="M6.6 13.2a1.5 1.5 0 0 0 2.8 0" />
    </>,
  ),
  Minus: makeIcon(<path d="M3 8h10" />),
  Maximize: makeIcon(<rect x="2.5" y="2.5" width="11" height="11" rx="1" />),
  Close: makeIcon(<path d="M3 3l10 10M13 3L3 13" />),
};

export type IconName = keyof typeof Icon;

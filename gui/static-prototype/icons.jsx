/* global React */
// Lightweight inline icons — line style, 16px

const I = (path, viewBox = "0 0 16 16") => ({ size = 16, stroke = 1.5, ...props } = {}) =>
  React.createElement(
    "svg",
    {
      width: size,
      height: size,
      viewBox,
      fill: "none",
      stroke: "currentColor",
      strokeWidth: stroke,
      strokeLinecap: "round",
      strokeLinejoin: "round",
      ...props,
    },
    path
  );

const Icon = {
  Dashboard: I(<>
    <rect x="1.5" y="1.5" width="5.5" height="6.5" rx="1" />
    <rect x="9" y="1.5" width="5.5" height="4" rx="1" />
    <rect x="1.5" y="9.5" width="5.5" height="5" rx="1" />
    <rect x="9" y="7" width="5.5" height="7.5" rx="1" />
  </>),
  Punch: I(<>
    <circle cx="8" cy="8" r="6" />
    <path d="M8 4.5V8l2.2 2.2" />
  </>),
  Records: I(<>
    <rect x="2" y="3" width="12" height="11" rx="1.5" />
    <path d="M5 1.5v3M11 1.5v3M2 6.5h12" />
    <path d="M5 9h2M9 9h2M5 11.5h2" />
  </>),
  Camera: I(<>
    <rect x="1.5" y="4" width="13" height="9" rx="1.5" />
    <path d="M5.5 4l1-1.5h3l1 1.5" />
    <circle cx="8" cy="8.5" r="2.5" />
  </>),
  Tasks: I(<>
    <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" />
    <path d="M4 6h8M4 9h8M4 12h5" />
  </>),
  Logs: I(<>
    <path d="M3 1.5h7l3 3v10H3z" />
    <path d="M10 1.5v3h3" />
    <path d="M5.5 8h5M5.5 10.5h5M5.5 5.5h2" />
  </>),
  Settings: I(<>
    <circle cx="8" cy="8" r="2" />
    <path d="M8 1.5v1.5M8 13v1.5M2.5 8H1M15 8h-1.5M3.8 3.8l1 1M11.2 11.2l1 1M3.8 12.2l1-1M11.2 4.8l1-1" />
  </>),
  Info: I(<>
    <circle cx="8" cy="8" r="6.5" />
    <path d="M8 7v4M8 5h.01" />
  </>),
  Play: I(<>
    <path d="M4 3l8 5-8 5V3z" fill="currentColor" stroke="none" />
  </>),
  Stop: I(<>
    <rect x="3.5" y="3.5" width="9" height="9" rx="1" fill="currentColor" stroke="none" />
  </>),
  Bot: I(<>
    <rect x="2.5" y="4" width="11" height="9" rx="2" />
    <circle cx="6" cy="8" r="0.8" fill="currentColor" />
    <circle cx="10" cy="8" r="0.8" fill="currentColor" />
    <path d="M6.5 11h3M8 1.5v2.5" />
  </>),
  Mail: I(<>
    <rect x="1.5" y="3" width="13" height="10" rx="1.5" />
    <path d="M2 4.5l6 5 6-5" />
  </>),
  User: I(<>
    <circle cx="8" cy="5.5" r="2.5" />
    <path d="M3 14c0-2.5 2.2-4.5 5-4.5s5 2 5 4.5" />
  </>),
  Users: I(<>
    <circle cx="6" cy="5.5" r="2.2" />
    <circle cx="11.5" cy="6" r="1.8" />
    <path d="M2 13.5c0-2 1.8-3.7 4-3.7s4 1.7 4 3.7M10 13.5c0-1.6 1.3-2.9 2.5-2.9" />
  </>),
  Clock: I(<>
    <circle cx="8" cy="8" r="6.5" />
    <path d="M8 4.5V8l2.2 2.2" />
  </>),
  Calendar: I(<>
    <rect x="2" y="3" width="12" height="11" rx="1.5" />
    <path d="M5 1.5v3M11 1.5v3M2 6.5h12" />
  </>),
  Check: I(<path d="M3.5 8.5l3 3 6-7" />),
  X: I(<path d="M4 4l8 8M12 4l-8 8" />),
  ChevronDown: I(<path d="M3 6l5 4 5-4" />),
  ChevronRight: I(<path d="M6 3l4 5-4 5" />),
  ChevronLeft: I(<path d="M10 3L6 8l4 5" />),
  Power: I(<>
    <path d="M5 4.5a5 5 0 1 0 6 0" />
    <path d="M8 1.5v6.5" />
  </>),
  Refresh: I(<>
    <path d="M13.5 7a5.5 5.5 0 0 0-10-2.5" />
    <path d="M2.5 9a5.5 5.5 0 0 0 10 2.5" />
    <path d="M2.5 2v3h3M13.5 14v-3h-3" />
  </>),
  Search: I(<>
    <circle cx="7" cy="7" r="4.5" />
    <path d="M10.5 10.5l3 3" />
  </>),
  Plus: I(<path d="M8 3v10M3 8h10" />),
  Trash: I(<>
    <path d="M2.5 4h11" />
    <path d="M4.5 4V2.5h7V4" />
    <path d="M3.5 4l1 10h7l1-10" />
  </>),
  Filter: I(<path d="M1.5 3h13l-5 6v4l-3 1.5V9z" />),
  Download: I(<>
    <path d="M8 1.5v9M4 7.5l4 4 4-4" />
    <path d="M2 14h12" />
  </>),
  Eye: I(<>
    <path d="M1.5 8C3 5 5.5 3.5 8 3.5s5 1.5 6.5 4.5C13 11 10.5 12.5 8 12.5s-5-1.5-6.5-4.5z" />
    <circle cx="8" cy="8" r="2.2" />
  </>),
  Globe: I(<>
    <circle cx="8" cy="8" r="6.5" />
    <path d="M1.5 8h13M8 1.5c2 2 3 4 3 6.5s-1 4.5-3 6.5M8 1.5c-2 2-3 4-3 6.5s1 4.5 3 6.5" />
  </>),
  Lock: I(<>
    <rect x="3" y="7" width="10" height="7" rx="1.5" />
    <path d="M5 7V4.5a3 3 0 1 1 6 0V7" />
  </>),
  Zap: I(<path d="M9 1.5L3.5 9h4L7 14.5 12.5 7h-4L9 1.5z" />),
  Activity: I(<path d="M1.5 8h3l2-5 3 10 2-5h3" />),
  Cloud: I(<path d="M4.5 12.5a3 3 0 0 1-.5-6 4 4 0 0 1 7.7.5 2.8 2.8 0 0 1 .3 5.5z" />),
  Minus: I(<path d="M3 8h10" />, "0 0 16 16"),
  Maximize: I(<rect x="2.5" y="2.5" width="11" height="11" rx="1" />),
  Close: I(<path d="M3 3l10 10M13 3L3 13" />),
};

window.AAS_ICON = Icon;

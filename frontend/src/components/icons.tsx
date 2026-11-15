import type { ReactNode } from "react";

const P = (d: ReactNode) => ({ size = 24 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);
export const Icons = {
  home: P(<><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></>),
  user: P(<><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 4-6 8-6s8 2 8 6" /></>),
  users: P(<><circle cx="9" cy="8" r="3.5" /><circle cx="17" cy="9" r="2.5" /><path d="M2 20c0-3.5 3-5.5 7-5.5s7 2 7 5.5" /><path d="M16 14.5c3 0 6 1.5 6 4.5" /></>),
  key: P(<><circle cx="8" cy="15" r="4" /><path d="M11 12l9-9M16 7l3 3" /></>),
  building: P(<><path d="M4 21V5l8-3v19" /><path d="M12 9l8 3v9" /><path d="M8 8h1M8 12h1M8 16h1" /></>),
  door: P(<><path d="M6 21V4h12v17" /><path d="M3 21h18" /><circle cx="15" cy="13" r=".8" /></>),
  file: P(<><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></>),
  contract: P(<><path d="M6 3h9l3 3v15H6z" /><path d="M9 9h6M9 13h6M9 17h3" /></>),
  euro: P(<><path d="M18 6a7 7 0 100 12" /><path d="M4 10h9M4 14h9" /></>),
  calc: P(<><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8 7h8M8 12h2M12 12h2M8 16h2M12 16h2" /></>),
  receipt: P(<><path d="M6 3h12v18l-3-2-3 2-3-2-3 2z" /><path d="M9 8h6M9 12h6" /></>),
  check: P(<><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 12l3 3 5-6" /></>),
  wrench: P(<><path d="M14 6a4 4 0 005 5l-9 9a2.5 2.5 0 01-4-4l9-9a4 4 0 01-1-1z" /></>),
  chat: P(<><path d="M4 5h16v11H9l-5 4z" /></>),
  folder: P(<><path d="M3 6h6l2 2h10v11H3z" /></>),
  chart: P(<><path d="M4 20V4M4 20h16" /><path d="M8 16v-5M13 16V8M18 16v-8" /></>),
  gear: P(<><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" /></>),
  search: P(<><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></>),
  bell: P(<><path d="M6 17V11a6 6 0 0112 0v6l2 2H4z" /><path d="M10 21h4" /></>),
  chevronDown: P(<path d="M6 9l6 6 6-6" />),
  chevronRight: P(<path d="M9 6l6 6-6 6" />),
};

const paths = {
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 4v5l3 2',
  plan: 'M3 4h18v16H3zM3 11h7V4m0 16v-4h11m-5-5h5',
  calendar: 'M4 6h16v14H4zM8 3v6m8-6v6M4 11h16m-11 4h2m3 0h2',
  ticket: 'M3 7h18v3a2 2 0 0 0 0 4v3H3v-3a2 2 0 0 0 0-4Zm12 0v3m0 4v3',
  chart: 'M4 4v16h16M8 16v-3m4 3V9m4 7V6',
  control: 'M4 6h16M4 12h16M4 18h16M9 4v4m6 2v4m-7 2v4',
  projector: 'M3 9h18v8H3zM8 17v2m8-2v2m0-6h2m-9 0h1',
  pc: 'M3 4h18v12H3zM12 16v4m-4 0h8',
  board: 'M3 4h18v13H3zM6 17v3m12-3v3M7 12l3-3 3 4 3-2',
  laboratory: 'M9 3h6m-5 0v6l-6 9a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-6-9V3M7 15h10',
  access: 'M10 3h.1M10 6l1 7h6l2 5h2m-7-8h4m-9 3a5 5 0 1 0 6 5',
  lift: 'M4 3h16v18H4zM12 8v13M8 8h8m-6-2 2-2 2 2',
  walking: 'M13 3h.1M11 7l3 3 4 1m-6-3-2 6-4 5m4-5 4 2 1 4m-4-13L7 9',
  group: 'M7 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm10 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM2 20v-2a5 5 0 0 1 10 0v2m2 0v-2a4 4 0 0 1 8 0v2',
  bell: 'M6 16h12l-2-3V9a4 4 0 0 0-8 0v4Zm4 3a2 2 0 0 0 4 0',
  lock: 'M5 10h14v10H5zM8 10V7a4 4 0 0 1 8 0v3m-4 4v3',
  upload: 'M4 15v5h16v-5M12 4v11M7 9l5-5 5 5',
  room: 'M3 20h18M6 20V4h12v16m-5-8h2',
  search: 'M10 4a6 6 0 1 0 0 12 6 6 0 0 0 0-12Zm4 10 6 6',
  close: 'm5 5 14 14M19 5 5 19',
} as const

export type IconName = keyof typeof paths
export function Icon({ name }: { name: IconName }) {
  return <svg className="line-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d={paths[name]} stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
}

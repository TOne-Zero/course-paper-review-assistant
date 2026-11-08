import type { CSSProperties } from 'react';

const paths = {
  reset: 'M3 10a9 9 0 1 1 1.6 7M3 4v6h6',
  arrow: 'M4 12h15m-6-6 6 6-6 6',
  back: 'M20 12H5m6-6-6 6 6 6',
  close: 'm6 6 12 12M6 18 18 6',
  plus: 'M12 5v14M5 12h14',
  upload: 'M12 16V4m-5 5 5-5 5 5M4 15v5h16v-5',
  download: 'M12 4v12m-5-5 5 5 5-5M4 17v3h16v-3',
  check: 'm5 12 4 4L19 6',
  eye: 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
  eyeOff: 'm3 3 18 18M10.6 5.1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3 3.7M6.2 6.2A19 19 0 0 0 2 12s3.5 7 10 7c1.8 0 3.3-.5 4.6-1.2M9.9 9.9a3 3 0 0 0 4.2 4.2',
  file: 'M5 3h9l5 5v13H5V3Zm9 0v6h5M8 13h8m-8 4h6',
  settings: 'M9.4 3 9 5.1 6.7 6.4 4.6 5.7 2.9 8.6l1.6 1.4v2.7l-1.6 1.4L4.6 17l2.1-.7L9 17.6l.4 2.4h3.2l.4-2.4 2.3-1.3 2.1.7 1.7-2.9-1.6-1.4V10l1.6-1.4-1.7-2.9-2.1.7L13 5.1 12.6 3H9.4ZM14 11.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
  trash: 'M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7',
  pause: 'M8 5v14M16 5v14',
  play: 'm7 4 13 8-13 8V4Z',
  chevron: 'm6 9 6 6 6-6',
};
export function Icon({ name, size = 20, className = '', style }: { name: keyof typeof paths; size?: number; className?: string; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className} style={style}><path d={paths[name]} /></svg>;
}

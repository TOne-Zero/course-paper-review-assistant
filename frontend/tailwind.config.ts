import type { Config } from 'tailwindcss';

/** 杂志编辑室：以字阶、留白和一像素细线组织界面。 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: '#FAFAFA', ink: '#111111', muted: '#666666',
        accent: '#A31F34', hairline: '#E5E7EB', 'accent-wash': '#F8EEF0',
      },
      fontFamily: {
        serif: ['"Noto Serif SC Variable"', '"Source Han Serif SC"', 'SimSun', 'serif'],
        sans: ['"Inter Variable"', '"PingFang SC"', '"Microsoft YaHei"', 'sans-serif'],
      },
      fontSize: {
        display: ['clamp(2.25rem, 6.6vw, 6rem)', { lineHeight: '1.38', letterSpacing: '-0.025em', fontWeight: '400' }],
        'page-title': ['2.625rem', { lineHeight: '1.4', letterSpacing: '-0.025em', fontWeight: '500' }],
        'section-title': ['1.375rem', { lineHeight: '1.6', fontWeight: '500' }],
        body: ['0.875rem', { lineHeight: '1.75' }],
        caption: ['0.75rem', { lineHeight: '1.7' }],
      },
      spacing: { page: 'clamp(1.25rem, 5.5vw, 5.5rem)', section: '3.5rem' },
      maxWidth: { editorial: '1480px', reading: '70ch' },
      transitionTimingFunction: { editorial: 'cubic-bezier(0.16, 1, 0.3, 1)' },
      animation: { 'page-in': 'page-in 320ms ease-out both', breathe: 'breathe 1.8s ease-in-out infinite' },
      keyframes: {
        'page-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        breathe: { '0%,100%': { opacity: '0.35' }, '50%': { opacity: '1' } },
      },
    },
  },
  plugins: [],
} satisfies Config;

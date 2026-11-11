import type { CSSProperties, JSX, ReactNode } from 'react';

export type BadgeTone = 'neutral' | 'ok' | 'warn' | 'bad' | 'accent';

const TONE_COLOR: Record<BadgeTone, string> = {
  neutral: 'var(--color-fg-muted)',
  ok: 'var(--color-ok)',
  warn: 'var(--color-warn)',
  bad: 'var(--color-bad)',
  accent: 'var(--c1)',
};

export function Badge({ tone = 'neutral', dot, testId, children }: { tone?: BadgeTone; dot?: boolean; testId?: string; children: ReactNode }): JSX.Element {
  const color = TONE_COLOR[tone];
  const style: CSSProperties = {
    color,
    background: tone === 'neutral' ? 'var(--cds-chart-grid)' : `color-mix(in srgb, ${color} 12%, transparent)`,
  };
  return (
    <span className="hs-badge" style={style} data-testid={testId}>
      {dot && <span className="hs-dot" />}
      {children}
    </span>
  );
}

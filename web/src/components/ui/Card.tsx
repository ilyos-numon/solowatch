import type { JSX, ReactNode } from 'react';

export interface CardProps {
  title?: string;
  eyebrow?: string;
  right?: ReactNode;
  dense?: boolean;
  testId?: string;
  className?: string;
  children: ReactNode;
}

export function Card({ title, eyebrow, right, dense, testId, className, children }: CardProps): JSX.Element {
  const cls = ['hs-card', className].filter(Boolean).join(' ');
  return (
    <section className={cls} data-testid={testId} style={dense ? { padding: 'var(--cds-pad-md)' } : undefined}>
      {eyebrow && <p className="hs-eyebrow">{eyebrow}</p>}
      {(title || right) && (
        <div className="sec-head">
          {title && <h2>{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

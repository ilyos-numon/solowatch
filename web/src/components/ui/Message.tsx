import type { JSX, ReactNode } from 'react';

export function Note({ children, className, testId }: { children: ReactNode; className?: string; testId?: string }): JSX.Element {
  return (
    <p className={className ? `hs-note ${className}` : 'hs-note'} data-testid={testId}>
      {children}
    </p>
  );
}

export function Msg({ tone, testId, children }: { tone: 'warn' | 'bad'; testId?: string; children: ReactNode }): JSX.Element {
  return (
    <p className={`msg msg--${tone}`} data-testid={testId}>
      {children}
    </p>
  );
}

export function Spinner(): JSX.Element {
  return <div className="spinner" role="status" aria-label="불러오는 중" />;
}

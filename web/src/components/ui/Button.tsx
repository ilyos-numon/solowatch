import type { ButtonHTMLAttributes, JSX } from 'react';

export type ButtonVariant = 'default' | 'primary' | 'ghost';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  busy?: boolean;
  testId?: string;
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  default: 'hs-btn',
  primary: 'hs-btn hs-btn--primary',
  ghost: 'hs-btn hs-btn--ghost',
};

export function Button({ variant = 'default', busy, testId, type = 'button', className, disabled, children, ...rest }: ButtonProps): JSX.Element {
  const cls = className ? `${VARIANT_CLASS[variant]} ${className}` : VARIANT_CLASS[variant];
  return (
    <button
      {...rest}
      type={type}
      className={cls}
      disabled={busy || disabled}
      aria-busy={busy ? 'true' : undefined}
      data-testid={testId}
    >
      {children}
    </button>
  );
}

import type { JSX } from 'react';
import { useTheme } from '../../lib/theme';

export function ThemeToggle(): JSX.Element {
  const [theme, toggle] = useTheme();
  return (
    <button className="theme-toggle" type="button" data-testid="theme-toggle" onClick={toggle}>
      {theme === 'dark' ? '라이트 모드' : '다크 모드'}
    </button>
  );
}

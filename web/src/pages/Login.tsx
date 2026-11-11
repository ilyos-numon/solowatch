import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { supabase } from '../lib/supabase';
import { DEMO_EMAIL, signInDemo } from '../lib/demoSession';
import { Button } from '../components/ui/Button';
import { Msg } from '../components/ui/Message';
import SleepBanner from '../components/SleepBanner';

// `/?demo=1` 은 세션 가드가 쿼리 없이 `/login` 으로 보내므로, 앱이 처음 열린 주소를 여기서 한 번 기억한다
let pendingDemo = new URLSearchParams(window.location.search).get('demo') === '1';

// app.css 의 .away-form label/input 과 같은 모양 (로그인 전용 클래스가 없어 인라인으로 맞춘다)
const labelStyle: CSSProperties = {
  display: 'grid',
  gap: 4,
  fontSize: 'var(--cds-font-size-caption)',
  color: 'var(--color-fg-muted)',
};
const inputStyle: CSSProperties = {
  font: 'inherit',
  fontSize: 'var(--cds-font-size-body)',
  color: 'var(--color-fg)',
  background: 'var(--color-bg)',
  border: '1px solid var(--color-border-line)',
  borderRadius: 'var(--cds-radius)',
  padding: '6px 8px',
  minWidth: 0,
};

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const location = useLocation();
  const autoTried = useRef(false);

  async function demoLogin() {
    setLoading(true);
    setError(null);
    const ok = await signInDemo();
    setLoading(false);
    if (!ok) {
      setError('데모 계정으로 들어가지 못했습니다');
      return;
    }
    navigate('/', { replace: true });
  }

  useEffect(() => {
    const wantsDemo = pendingDemo || new URLSearchParams(location.search).get('demo') === '1';
    pendingDemo = false;
    if (!wantsDemo || !DEMO_EMAIL || autoTried.current) return;
    autoTried.current = true;
    void demoLogin();
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const { error: err } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (err) {
      setError('이메일 또는 비밀번호가 맞지 않습니다');
      return;
    }
    navigate('/', { replace: true });
  }

  return (
    <div className="hs">
      <div className="login">
        <h1 className="hs-title">홀로안심</h1>
        <p className="hs-lede">가족의 하루 리듬을 조용히 함께 봅니다.</p>
        <SleepBanner />
        <form onSubmit={onSubmit} className="hs-card" style={{ display: 'grid', gap: 'var(--cds-gap-sm)' }}>
          <label style={labelStyle}>
            이메일
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.currentTarget.value)}
              data-testid="login-email"
              style={inputStyle}
            />
          </label>
          <label style={labelStyle}>
            비밀번호
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
              data-testid="login-password"
              style={inputStyle}
            />
          </label>
          {error && (
            <Msg tone="bad" testId="login-error">
              {error}
            </Msg>
          )}
          <Button type="submit" variant="primary" busy={loading} testId="login-submit">
            로그인
          </Button>
          {DEMO_EMAIL && (
            <Button busy={loading} onClick={demoLogin} testId="btn-demo-login">
              데모로 둘러보기
            </Button>
          )}
        </form>
      </div>
    </div>
  );
}

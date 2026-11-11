import { useCallback, useEffect, useRef, useState } from 'react';
import type { Session } from '@supabase/supabase-js';
import { supabase } from '../../lib/supabase';
import { DEMO_EMAIL, signInDemo } from '../../lib/demoSession';
import { Button } from '../ui/Button';
import { Msg, Note, Spinner } from '../ui/Message';
import FamilyHome from '../FamilyHome';
import GuideCards from '../GuideCards';

/** /demo 의 가족 앱 탭 — 데모 계정으로 로그인한 가족 홈을 그대로 보여준다. */
export default function DemoFamilyPane() {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [loggedOut, setLoggedOut] = useState(false);
  const [failed, setFailed] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  const tried = useRef(false);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((event, s) => {
      setSession(s);
      if (event === 'SIGNED_OUT') setLoggedOut(true);
      if (event === 'SIGNED_IN') setLoggedOut(false);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  const login = useCallback(async () => {
    setSigningIn(true);
    setFailed(false);
    const ok = await signInDemo();
    setSigningIn(false);
    if (ok) setLoggedOut(false);
    else setFailed(true);
  }, []);

  // 세션이 없고 직접 로그아웃한 것도 아니면 한 번만 자동으로 들어간다
  useEffect(() => {
    if (session === null && !loggedOut && DEMO_EMAIL && !tried.current) {
      tried.current = true;
      void login();
    }
  }, [session, loggedOut, login]);

  if (session === undefined) return <Spinner />;
  if (session) {
    return (
      <div className="fam">
        <FamilyHome />
        <GuideCards />
      </div>
    );
  }
  if (failed) {
    return (
      <div className="login">
        <Msg tone="bad">데모 계정으로 들어가지 못했습니다</Msg>
        <Button variant="primary" busy={signingIn} testId="btn-demo-login" onClick={() => void login()}>
          다시 시도
        </Button>
      </div>
    );
  }
  if (loggedOut || !DEMO_EMAIL) {
    return (
      <div className="login">
        <Note>로그아웃했습니다.</Note>
        <Button variant="primary" busy={signingIn} testId="btn-demo-login" onClick={() => void login()}>
          데모 계정으로 들어가기
        </Button>
      </div>
    );
  }
  return <Spinner />;
}

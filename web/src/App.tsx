import { useEffect, useState } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import type { Session } from '@supabase/supabase-js';
import { supabase } from './lib/supabase';
import { Spinner } from './components/ui/Message';
import { ThemeToggle } from './components/ui/ThemeToggle';
import Login from './pages/Login';
import Home from './pages/Home';
import Demo from './pages/Demo';

export default function App() {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const location = useLocation();

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  let content;
  if (location.pathname === '/demo') {
    // 데모 페이지는 세션 가드 밖 (로그인 불필요)
    content = <Demo />;
  } else if (session === undefined) {
    content = <Spinner />;
  } else {
    content = (
      <Routes>
        <Route path="/login" element={session ? <Navigate to="/" replace /> : <Login />} />
        <Route
          path="/"
          element={session ? <Home /> : <Navigate to={{ pathname: '/login', search: location.search }} replace />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    );
  }

  return (
    <>
      <ThemeToggle />
      {content}
    </>
  );
}

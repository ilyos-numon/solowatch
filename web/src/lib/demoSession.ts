import { supabase } from './supabase';

export const DEMO_EMAIL: string = (import.meta.env.VITE_DEMO_EMAIL as string | undefined) ?? '';
const DEMO_PASSWORD: string = (import.meta.env.VITE_DEMO_PASSWORD as string | undefined) ?? '';

/** 데모 계정으로 로그인한다. 데모 계정이 없거나 실패하면 false. */
export async function signInDemo(): Promise<boolean> {
  if (!DEMO_EMAIL) return false;
  const { error } = await supabase.auth.signInWithPassword({ email: DEMO_EMAIL, password: DEMO_PASSWORD });
  return !error;
}

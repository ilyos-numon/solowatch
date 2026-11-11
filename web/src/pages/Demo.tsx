import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import EventButtons from '../components/demo/EventButtons';
import InsidePanel, { type Shade, type WindowKey } from '../components/demo/InsidePanel';
import OutboxPanel from '../components/demo/OutboxPanel';
import ScorePanel, { FOCUS } from '../components/demo/ScorePanel';
import DemoFamilyPane from '../components/demo/DemoFamilyPane';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Msg, Note } from '../components/ui/Message';
import { virtualNowLabel } from '../lib/format';
import {
  DemoApiError,
  getState,
  inject,
  reset,
  type DemoEventKind,
  type DemoState,
  type InjectResult,
} from '../lib/demoApi';

const POLL_MS = 2000;
const MAX_DAYS = 14;

type Tab = 'family' | 'demo';

function tabFromHash(): Tab {
  return window.location.hash === '#family' ? 'family' : 'demo';
}

function errorMessage(e: unknown): string {
  if (e instanceof DemoApiError) {
    if (e.status === 400) return `알 수 없는 이벤트입니다 (${e.message})`;
    return `요청을 처리하지 못했습니다 (${e.status} ${e.message})`;
  }
  return '데모 서버에 닿지 못했습니다. 잠시 후 다시 눌러 주세요';
}

export default function Demo() {
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [state, setState] = useState<DemoState | null>(null);
  const [notReady, setNotReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InjectResult | null>(null);
  const [busy, setBusy] = useState<DemoEventKind | 'reset' | null>(null);
  const [playKey, setPlayKey] = useState(0);
  const loaded = useRef(false);

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  function selectTab(t: Tab) {
    setTab(t);
    window.history.replaceState(window.history.state, '', `#${t}`);
  }

  const refresh = useCallback(async () => {
    try {
      const s = await getState();
      loaded.current = true;
      setState(s);
      setNotReady(!s.ready);
    } catch (e) {
      // 503 은 초기화 중. 한 번도 못 받았는데 닿지 않으면 역시 준비 중으로 본다
      if ((e instanceof DemoApiError && e.status === 503) || !loaded.current) setNotReady(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  async function onInject(kind: DemoEventKind) {
    setBusy(kind);
    setError(null);
    try {
      const r = await inject(kind);
      setResult(r);
      await refresh();
      setPlayKey((k) => k + 1);
    } catch (e) {
      if (e instanceof DemoApiError && e.status === 503) setNotReady(true);
      else setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function onReset() {
    setBusy('reset');
    setError(null);
    try {
      const s = await reset();
      setState(s);
      setNotReady(!s.ready);
      setResult(null);
    } catch (e) {
      if (e instanceof DemoApiError && e.status === 503) setNotReady(true);
      else setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const shown = result ?? state?.last_inject ?? null;
  const ready = state !== null && !notReady;

  const shade = useMemo<Shade[]>(() => {
    if (!shown) return [];
    return (FOCUS[shown.kind] ?? []).flatMap(([sid, window]) => {
      const s = shown.scores.find((x) => x.sensor_id === sid && x.window === window);
      return s ? [{ sensor_id: sid, window: window as WindowKey, flagged: s.flagged }] : [];
    });
  }, [shown]);

  return (
    <div className="hs">
      <header className="hs-head">
        <h1 className="hs-title">홀로안심</h1>
        <p className="hs-lede">
          카메라와 마이크 없이 수도와 전력 사용만으로 하루 리듬을 봅니다. 가족 앱은 알림 문장과 하루 요약만 받고, 5분 단위 값은 집 안에 남습니다.
        </p>
        <nav className="hs-tabs" role="tablist" aria-label="화면">
          <button
            className="hs-tab"
            type="button"
            role="tab"
            id="tab-family"
            data-testid="tab-family"
            aria-selected={tab === 'family'}
            aria-controls="pane-family"
            onClick={() => selectTab('family')}
          >
            가족 앱
          </button>
          <button
            className="hs-tab"
            type="button"
            role="tab"
            id="tab-demo"
            data-testid="tab-demo"
            aria-selected={tab === 'demo'}
            aria-controls="pane-demo"
            onClick={() => selectTab('demo')}
          >
            라이브 데모
          </button>
        </nav>
      </header>

      <section id="pane-family" data-testid="pane-family" role="tabpanel" aria-labelledby="tab-family" hidden={tab !== 'family'}>
        <DemoFamilyPane />
      </section>

      <section id="pane-demo" data-testid="pane-demo" role="tabpanel" aria-labelledby="tab-demo" hidden={tab !== 'demo'}>
        <div style={{ display: 'grid', gap: 'var(--cds-gap-md)' }} data-testid="demo-page">
          {/* 오른쪽 위 고정 테마 토글과 처음부터 버튼이 겹치지 않게 오른쪽 여백을 둔다 */}
          <div className="demo-bar" style={{ paddingRight: '7.5rem' }}>
            <div className="kvs">
              <div className="kv">
                <span className="hs-eyebrow">가상 시각</span>
                <span className="big" data-testid="demo-virtual-now">
                  {state ? virtualNowLabel(state.virtual_now) : '—'}
                </span>
              </div>
              <div className="kv">
                <span className="hs-eyebrow">진행</span>
                <span className="big" data-testid="demo-day-index">
                  {state ? `${state.day_index}일째 / ${MAX_DAYS}일` : '—'}
                </span>
              </div>
            </div>
            <Button
              busy={busy === 'reset'}
              disabled={!ready || (busy !== null && busy !== 'reset')}
              onClick={() => void onReset()}
              testId="btn-reset"
            >
              처음부터
            </Button>
          </div>

          {notReady && (
            <Msg tone="warn" testId="demo-not-ready">
              가상 집을 준비하는 중입니다
            </Msg>
          )}
          {error && (
            <Msg tone="bad" testId="demo-error">
              {error}
            </Msg>
          )}
          {shown?.auto_reset && (
            <Msg tone="warn" testId="demo-auto-reset">
              {MAX_DAYS}일이 지나 가상 집을 처음부터 다시 시작했습니다
            </Msg>
          )}

          <div className="demo-grid">
            <div className="col">
              <Card title="오늘 하루 넣기">
                <Note>
                  버튼 하나가 가상 집의 하루입니다. 가족 앱에서 괜찮았음이라고 답한 뒤 같은 하루를 다시 넣으면 평소 기준이 바뀝니다.
                </Note>
                <EventButtons
                  busy={busy === 'reset' ? null : busy}
                  disabled={!ready || busy !== null}
                  pressed={shown?.kind ?? null}
                  onInject={(k) => void onInject(k)}
                />
              </Card>
              <InsidePanel recent={state?.recent ?? {}} playKey={playKey} shade={shade} />
              <ScorePanel result={shown} />
            </div>
            <div className="col">
              <OutboxPanel outbox={state?.outbox ?? []} />
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

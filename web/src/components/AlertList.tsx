import { useState } from 'react';
import type { Alert, Verdict } from '../lib/queries';
import { splitSentence, windowStartLabel } from '../lib/format';
import { Badge, type BadgeTone } from './ui/Badge';
import { Button } from './ui/Button';
import { Msg, Note } from './ui/Message';

const STATUS_META: Record<string, { label: string; tone: BadgeTone }> = {
  open: { label: '확인 필요', tone: 'warn' },
  ok: { label: '괜찮았음', tone: 'ok' },
  checking: { label: '확인 중', tone: 'accent' },
  confirmed: { label: '실제 이상', tone: 'bad' },
};

const VERDICTS: [Verdict, string][] = [
  ['ok', '괜찮았음'],
  ['checking', '확인 중'],
  ['confirmed', '실제 이상'],
];

const SEP = ' · ';

interface Props {
  alerts: Alert[];
  onFeedback: (alert: Alert, verdict: Verdict) => Promise<void>;
}

// 구분자 텍스트 노드를 원문 위치 그대로 두어 카드의 textContent 가 원문 문장과 같게 한다
function Sentence({ text }: { text: string }) {
  const p = splitSentence(text);
  if (!p.prefix && !p.window && !p.suffix) {
    return (
      <p className="alert-text">
        <span className="what">{p.what}</span>
      </p>
    );
  }
  const midSep = [p.prefix, p.window, p.what, p.suffix].join(SEP) === text ? SEP : ' ';
  return (
    <p className="alert-text">
      <span className="muted">{p.prefix}</span>
      {SEP}
      {p.window}
      {midSep}
      <span className="what">{p.what}</span>
      {SEP}
      <span className="muted">{p.suffix}</span>
    </p>
  );
}

export default function AlertList({ alerts, onFeedback }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  // 답 바꾸기를 누른 알림 → 그때의 행. Realtime 으로 행이 바뀌면(다른 객체) 다시 답하는 상태가 풀린다.
  const [reopen, setReopen] = useState<Record<string, Alert>>({});
  const [failed, setFailed] = useState<Record<string, boolean>>({});

  if (alerts.length === 0) {
    return <Note>받은 알림이 없습니다.</Note>;
  }

  async function send(alert: Alert, verdict: Verdict) {
    setBusy(alert.id);
    setFailed((f) => ({ ...f, [alert.id]: false }));
    try {
      await onFeedback(alert, verdict);
    } catch {
      setFailed((f) => ({ ...f, [alert.id]: true }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="alerts">
      {alerts.map((a) => {
        const reopened = reopen[a.id] === a;
        const st = reopened ? 'open' : a.status;
        const cur = STATUS_META[a.status] ?? { label: a.status, tone: 'neutral' as BadgeTone };
        const meta = STATUS_META[st] ?? cur;
        const label = reopened ? `${cur.label} → 다시 답하는 중` : meta.label;
        return (
          <article key={a.id} className={st === 'open' ? 'alert alert--open' : 'alert'} data-testid="alert-item">
            <div className="alert-top">
              <span className="alert-time">{windowStartLabel(a.window_start)}</span>
              <Badge tone={meta.tone} dot testId="alert-status">
                {label}
              </Badge>
            </div>
            <Sentence text={a.sentence} />
            {st === 'open' ? (
              <div className="alert-actions">
                {VERDICTS.map(([v, text]) => (
                  <Button key={v} busy={busy === a.id} onClick={() => send(a, v)} testId={`btn-${v}`}>
                    {text}
                  </Button>
                ))}
              </div>
            ) : (
              <div className="alert-foot">
                <Button variant="ghost" testId="btn-reanswer" onClick={() => setReopen((r) => ({ ...r, [a.id]: a }))}>
                  답 바꾸기
                </Button>
              </div>
            )}
            {failed[a.id] && (
              <Msg tone="bad" testId="alert-msg">
                저장하지 못했습니다. 잠시 후 다시 눌러 주세요.
              </Msg>
            )}
          </article>
        );
      })}
    </div>
  );
}

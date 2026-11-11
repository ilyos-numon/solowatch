import { useEffect, useMemo, useRef } from 'react';
import { Badge } from '../ui/Badge';
import { Card } from '../ui/Card';
import { Note } from '../ui/Message';
import { clock } from '../../lib/format';
import type { OutboxEntry } from '../../lib/demoApi';

const TABLE_LABEL: Record<string, string> = {
  alerts: '알림',
  daily_reports: '일일 요약',
  alert_feedback: '가족 응답',
  away_periods: '외출',
};

const keyOf = (e: OutboxEntry) => `${e.at}|${e.summary}`;

/** 집 밖으로 나간 것 — 알림 문장·창 합계·일일 요약 행과 돌아온 피드백만. 원시 값은 여기 오지 않는다. */
export default function OutboxPanel({ outbox }: { outbox: OutboxEntry[] }) {
  const sig = outbox.map(keyOf).join('\n');
  // 직전 렌더에서 본 줄. null 이면 아직 한 번도 그리지 않았다 (첫 목록은 새 줄로 치지 않는다)
  const seen = useRef<Set<string> | null>(null);

  const fresh = useMemo(() => {
    const prev = seen.current;
    if (prev === null) return new Set<string>();
    return new Set(sig.split('\n').filter((k) => k && !prev.has(k)));
  }, [sig]);

  useEffect(() => {
    seen.current = new Set(sig ? sig.split('\n') : []);
  }, [sig]);

  return (
    <Card title="집 밖으로 나간 것" testId="demo-outbox">
      <Note>
        5분 값은 나가지 않습니다. 알림 문장과 하루 요약만 나가고, 가족의 응답과 외출 표시가 돌아옵니다. 가족 앱 탭에서 답하면 여기에 바로 보입니다.
      </Note>
      <div className="outbox">
        {outbox.length === 0 ? (
          <Note>아직 나간 데이터가 없습니다</Note>
        ) : (
          outbox.map((e, i) => (
            <div
              key={`${keyOf(e)}-${i}`}
              className={fresh.has(keyOf(e)) ? 'ob ob--new' : 'ob'}
              data-testid="outbox-item"
              data-direction={e.direction}
            >
              <div className="ob-top">
                <Badge tone={e.direction === 'out' ? 'accent' : 'ok'} dot>{e.direction === 'out' ? '집 → 밖' : '밖 → 집'}</Badge>
                <span>
                  {TABLE_LABEL[e.table] ?? e.table} · {clock(e.at)}
                </span>
              </div>
              <div className="ob-sum">{e.summary}</div>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}

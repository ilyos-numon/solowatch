import { Badge } from '../ui/Badge';
import { Card } from '../ui/Card';
import { Note } from '../ui/Message';
import { formatScorePercent } from '../../lib/format';
import {
  DEMO_EVENTS,
  SENSOR_LABEL_KO,
  WINDOW_LABEL_KO,
  type DemoEventKind,
  type InjectResult,
  type ScoreEntry,
} from '../../lib/demoApi';

// 이벤트가 영향을 주는 (sensor_id, window) — contracts_demo.DEMO_EVENT_FOCUS 와 같다
export const FOCUS: Record<DemoEventKind, [string, string][]> = {
  normal: [],
  no_morning_water: [['water_main', 'morning']],
  fridge_off: [
    ['plug_fridge', 'night'],
    ['plug_fridge', 'morning'],
    ['plug_fridge', 'afternoon'],
    ['plug_fridge', 'evening'],
  ],
  light_all_night: [['plug_light', 'night']],
  night_flow: [['water_main', 'night']],
};

const UNIT: Record<string, string> = { water_main: 'L', plug_fridge: 'W·슬롯', plug_tv: 'W·슬롯', plug_light: 'W·슬롯' };

function find(list: ScoreEntry[], sid: string, window: string): ScoreEntry | undefined {
  return list.find((s) => s.sensor_id === sid && s.window === window);
}

function verdict(now: ScoreEntry | undefined, prev: ScoreEntry | undefined): '알림' | '억제' | '-' {
  if (now?.flagged) return '알림';
  if (prev?.flagged) return '억제';
  return '-';
}

function baseline(now: ScoreEntry | undefined, prev: ScoreEntry | undefined, unit: string): string {
  if (!now) return '-';
  const after = now.expected.toFixed(1);
  return prev ? `${prev.expected.toFixed(1)} → ${after} ${unit}` : `${after} ${unit}`;
}

export default function ScorePanel({ result }: { result: InjectResult | null }) {
  const label = result ? (DEMO_EVENTS.find((e) => e.kind === result.kind)?.label ?? result.kind) : '';
  const focus = result ? (FOCUS[result.kind] ?? []) : [];
  const hasAlerts = !!result && result.alerts.length > 0;

  return (
    <Card eyebrow="넣은 하루의 결과">
      <h2 className="score-title" data-testid="demo-score-title">
        {result ? `${result.day} · ${label}` : '버튼을 누르면 가상 집이 그 하루를 삽니다'}
      </h2>
      {result && (
        <p className="score-alerts" style={{ color: hasAlerts ? 'var(--color-warn)' : 'var(--color-fg-muted)' }}>
          {hasAlerts ? result.alerts.map((a) => a.sentence).join(' / ') : '이 날은 알림이 없었습니다'}
        </p>
      )}
      {result && focus.length === 0 && <Note className="score-empty">평범한 하루는 따로 살펴볼 시간대가 없습니다</Note>}
      {result && focus.length > 0 && (
        <div className="tbl-wrap">
          <table className="sc">
            <thead>
              <tr>
                <th>시간대</th>
                <th className="num">평소 기준</th>
                <th className="num">이날</th>
                <th className="num">지난번 다른 정도</th>
                <th className="num">이번 다른 정도</th>
                <th>결과</th>
              </tr>
            </thead>
            <tbody>
              {focus.map(([sid, window]) => {
                const now = find(result.scores, sid, window);
                const prev = find(result.previous_scores, sid, window);
                const v = verdict(now, prev);
                return (
                  <tr key={`${sid}-${window}`} data-testid="demo-score-row">
                    <td>
                      {SENSOR_LABEL_KO[sid] ?? sid} · {WINDOW_LABEL_KO[window] ?? window}
                    </td>
                    <td className="num">{baseline(now, prev, UNIT[sid] ?? '')}</td>
                    <td className="num">{now ? `${now.actual.toFixed(1)} ${UNIT[sid] ?? ''}` : '-'}</td>
                    <td className="num" data-testid="demo-score-before">
                      {formatScorePercent(prev?.score)}
                    </td>
                    <td className="num" data-testid="demo-score-after">
                      {formatScorePercent(now?.score)}
                    </td>
                    <td data-testid="demo-score-verdict">
                      {v === '알림' ? <Badge tone="warn" dot>알림</Badge> : v === '억제' ? <Badge tone="ok" dot>억제</Badge> : '-'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <Note>
        괜찮았음을 받으면 그 시간대의 평소 기준을 다시 배웁니다. 한 번에 알림이 사라지지 않을 수 있지만 평소와 다른 정도는 줄어듭니다. 결과의 억제는 지난번에는 알림이었고 이번에는 아니라는 뜻입니다.
      </Note>
    </Card>
  );
}

import { useEffect, useState } from 'react';
import { listDailyReports, type DailyReport } from '../lib/queries';
import { shortDate } from '../lib/format';
import { Note } from './ui/Message';

const SENSORS: { id: string; label: string }[] = [
  { id: 'water_main', label: '물' },
  { id: 'plug_fridge', label: '냉장고' },
  { id: 'plug_tv', label: 'TV' },
  { id: 'plug_light', label: '거실등' },
];

const AXIS = ['0시', '6시', '12시', '18시'];

type Rhythm = Record<string, boolean[] | undefined>;
type Hour = { hour: number; today: 0 | 1; usual: 0 | 1 };

function rhythmOf(report: DailyReport): Rhythm {
  const r = report.rhythm;
  return r && typeof r === 'object' && !Array.isArray(r) ? (r as unknown as Rhythm) : {};
}

/** 24 hours: today = latest report, usual = active in at least half of the previous reports. */
export function chartData(reports: DailyReport[], sensorId: string): Hour[] {
  const [latest, ...previous] = reports;
  const today = latest ? rhythmOf(latest)[sensorId] ?? [] : [];
  const prev = previous.map((p) => rhythmOf(p)[sensorId] ?? []);
  return Array.from({ length: 24 }, (_, h) => {
    const activeCount = prev.filter((flags) => flags[h] === true).length;
    const usual = prev.length > 0 && activeCount * 2 >= prev.length;
    return { hour: h, today: today[h] ? 1 : 0, usual: usual ? 1 : 0 };
  });
}

const has = (v: 0 | 1) => (v ? '사용 있음' : '사용 없음');

export default function RhythmChart({ householdId }: { householdId: string }) {
  const [reports, setReports] = useState<DailyReport[] | null>(null);
  const [hot, setHot] = useState<{ sid: string; hour: number; row: 'usual' | 'today' } | null>(null);

  useEffect(() => {
    let cancelled = false;
    listDailyReports(householdId)
      .then((r) => {
        if (!cancelled) setReports(r);
      })
      .catch(() => {
        if (!cancelled) setReports([]);
      });
    return () => {
      cancelled = true;
    };
  }, [householdId]);

  if (reports === null) return null;

  const blocks = SENSORS.map((s) => ({ ...s, hours: chartData(reports, s.id) }));
  let readout = reports.length > 0 ? `${shortDate(reports[0].day)} 요약을 오늘로 봅니다. 칸에 마우스를 올리면 시간별로 보입니다.` : '';
  if (hot) {
    const b = blocks.find((x) => x.id === hot.sid);
    const h = b?.hours[hot.hour];
    if (b && h) readout = `${b.label} · ${h.hour}시 · 오늘 ${has(h.today)} · 평소 ${has(h.usual)}`;
  }

  return (
    <div className="hs-card" style={{ padding: 'var(--cds-pad-md)' }}>
      <div className="sec-head">
        <h3>하루 리듬</h3>
        <span className="legend">
          <span>
            <i style={{ background: 'var(--cds-chart-muted)' }} />
            평소
          </span>
          <span>
            <i style={{ background: 'var(--color-ok)' }} />
            오늘
          </span>
        </span>
      </div>
      <Note>시간마다 사용이 있었는지만 봅니다. 평소는 지난 요약 중 절반 이상에서 사용이 있던 시간입니다.</Note>
      {reports.length === 0 ? (
        <Note testId="rhythm-empty">아직 리듬 데이터가 없습니다</Note>
      ) : (
        <div className="rhythm" onPointerLeave={() => setHot(null)}>
          {blocks.map((b) => {
            const missed = b.hours.filter((h) => h.usual && !h.today).length;
            const row = (title: string, field: 'usual' | 'today', cls: string) => (
              <div className="rh-row">
                <span>{title}</span>
                {b.hours.map((h) => {
                  const isHot = hot?.sid === b.id && hot.hour === h.hour && hot.row === field;
                  const select = () => setHot({ sid: b.id, hour: h.hour, row: field });
                  return (
                    <span
                      key={h.hour}
                      className={`rh-cell${h[field] ? ` ${cls}` : ''}${isHot ? ' hot' : ''}`}
                      aria-label={`${b.label} ${h.hour}시 ${title} ${has(h[field])}`}
                      onPointerEnter={select}
                      onPointerDown={select}
                    />
                  );
                })}
              </div>
            );
            return (
              <div key={b.id} className="rh-sensor" data-testid={`rhythm-chart-${b.id}`}>
                <div className="rh-label">
                  <span>{b.label}</span>
                  <span>{missed ? `평소 쓰던 ${missed}시간에 사용 없음` : ''}</span>
                </div>
                {row('평소', 'usual', 'on-usual')}
                {row('오늘', 'today', 'on-today')}
              </div>
            );
          })}
          <div className="rh-axis">
            <span />
            {AXIS.map((t) => (
              <span key={t}>{t}</span>
            ))}
          </div>
          <p className="rh-readout" data-testid="rhythm-readout">
            {readout}
          </p>
        </div>
      )}
    </div>
  );
}

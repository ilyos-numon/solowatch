import { useCallback, useEffect, useState } from 'react';
import { endAway, insertAway, listAway, type AwayPeriod } from '../lib/queries';
import { localToday, shortDate, yesterdayOf } from '../lib/format';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Msg, Note } from './ui/Message';

type Message = { tone: 'warn' | 'bad'; text: string };

const MSG_EMPTY: Message = { tone: 'warn', text: '시작하는 날과 끝나는 날을 모두 골라 주세요.' };
const MSG_ORDER: Message = { tone: 'warn', text: '끝나는 날이 시작하는 날보다 앞설 수 없습니다.' };
const MSG_SAVE_FAIL: Message = { tone: 'bad', text: '저장하지 못했습니다. 잠시 후 다시 시도해 주세요.' };
const MSG_END_FAIL: Message = { tone: 'bad', text: '종료하지 못했습니다. 잠시 후 다시 시도해 주세요.' };
const MSG_NOT_OWNER: Message = { tone: 'bad', text: '이 외출은 표시한 사람만 바꿀 수 있습니다.' };

export default function AwayForm({ householdId }: { householdId: string }) {
  const [periods, setPeriods] = useState<AwayPeriod[]>([]);
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [ending, setEnding] = useState<string | null>(null);
  const [msg, setMsg] = useState<Message | null>(null);

  const reload = useCallback(async () => {
    setPeriods(await listAway(householdId));
  }, [householdId]);

  useEffect(() => {
    reload().catch(() => setPeriods([]));
  }, [reload]);

  function toggle(next: boolean) {
    setOpen(next);
    setMsg(null);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!start || !end) {
      setMsg(MSG_EMPTY);
      return;
    }
    if (end < start) {
      setMsg(MSG_ORDER);
      return;
    }
    setMsg(null);
    setSaving(true);
    try {
      await insertAway(householdId, start, end, note.trim());
      setStart('');
      setEnd('');
      setNote('');
      setOpen(false);
      await reload();
    } catch {
      setMsg(MSG_SAVE_FAIL);
    } finally {
      setSaving(false);
    }
  }

  async function onEnd(p: AwayPeriod, started: boolean) {
    const today = localToday();
    setMsg(null);
    setEnding(p.id);
    try {
      const n = await endAway(p.id, started ? today : yesterdayOf(today));
      if (n === 0) setMsg(MSG_NOT_OWNER);
      await reload();
    } catch {
      setMsg(MSG_END_FAIL);
    } finally {
      setEnding(null);
    }
  }

  const today = localToday();

  return (
    <div className="hs-card" style={{ padding: 'var(--cds-pad-md)' }}>
      <div className="sec-head">
        <h3>외출·여행</h3>
        <Button testId="away-open" aria-expanded={open} onClick={() => toggle(!open)}>
          외출·여행 표시
        </Button>
      </div>
      {open && (
        <form className="away-form" onSubmit={onSubmit} noValidate>
          <Note className="full">집을 비우는 동안에는 알림을 보내지 않고, 그 기간은 평소 기준을 배우는 데도 쓰지 않습니다.</Note>
          <label>
            시작하는 날
            <input type="date" data-testid="away-start" value={start} onChange={(e) => setStart(e.currentTarget.value)} />
          </label>
          <label>
            끝나는 날
            <input
              type="date"
              data-testid="away-end"
              value={end}
              min={start || undefined}
              onChange={(e) => setEnd(e.currentTarget.value)}
            />
          </label>
          <label className="full">
            메모 (선택)
            <input type="text" placeholder="여행" data-testid="away-note" value={note} onChange={(e) => setNote(e.currentTarget.value)} />
          </label>
          <div className="full" style={{ display: 'flex', gap: 'var(--cds-gap-xs)', justifyContent: 'flex-end' }}>
            <Button testId="away-cancel" onClick={() => toggle(false)}>
              취소
            </Button>
            <Button type="submit" variant="primary" busy={saving} testId="away-submit">
              저장
            </Button>
          </div>
        </form>
      )}
      {msg && (
        <Msg tone={msg.tone} testId="away-msg">
          {msg.text}
        </Msg>
      )}
      <div className="away-list">
        {periods.length === 0 ? (
          <Note>표시된 외출이 없습니다. 집을 비우는 날을 미리 표시하면 그동안 알림이 오지 않습니다.</Note>
        ) : (
          periods.map((p) => {
            const started = p.start_date <= today;
            return (
              <div key={p.id} className="away-item" data-testid="away-item">
                <Badge tone={started ? 'ok' : 'accent'} dot>
                  {started ? '표시 중' : '예정'}
                </Badge>
                <span className="grow">{`${shortDate(p.start_date)} ~ ${shortDate(p.end_date)}${p.note ? ` ${p.note}` : ''}`}</span>
                <Button testId="away-end-btn" busy={ending === p.id} onClick={() => onEnd(p, started)}>
                  {started ? '오늘 종료' : '취소'}
                </Button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

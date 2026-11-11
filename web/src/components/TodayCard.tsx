import type { Alert, DailyReport } from '../lib/queries';

interface Props {
  report: DailyReport | null;
  alerts: Alert[];
  today: string;
}

export function todaySentence(report: DailyReport | null, alerts: Alert[], today: string): string {
  if (report && report.day === today) return report.sentence;
  const open = alerts.find((a) => a.status === 'open');
  if (open) return open.sentence;
  if (!report && alerts.length === 0) return '평소 리듬을 배우는 중입니다';
  return '오늘 리듬을 지켜보는 중입니다';
}

export default function TodayCard({ report, alerts, today }: Props) {
  return (
    <div className="today" data-testid="today-card">
      <p className="hs-eyebrow">오늘</p>
      <p className="today-text">{todaySentence(report, alerts, today)}</p>
    </div>
  );
}

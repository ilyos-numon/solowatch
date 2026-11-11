// 화면 공용 날짜·숫자·문장 표시 함수. 기존 부품의 출력과 같게 유지한다.

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

const WEEKDAY_KO = ['일', '월', '화', '수', '목', '금', '토'];

/** 브라우저 현지 기준 오늘 YYYY-MM-DD */
export function localToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

/** 하루 전 YYYY-MM-DD */
export function yesterdayOf(isoDate: string): string {
  const [y, m, d] = isoDate.split('-').map(Number);
  const dt = new Date(y, m - 1, d - 1);
  return `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())}`;
}

/** '2026-11-10' → '11/10' */
export function shortDate(isoDate: string): string {
  const [, m, d] = isoDate.split('-');
  return `${Number(m)}/${Number(d)}`;
}

/** 현지 'M/D HH:MM' */
export function windowStartLabel(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

/** 현지 'HH:MM:SS' (파싱 불가면 원문) */
export function clock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

/** '+09:00' ISO 문자열의 시:분을 그대로 쓴다 (브라우저 시간대와 무관) */
export function hhmm(ts: string): string {
  const m = /T(\d{2}):(\d{2})/.exec(ts);
  return m ? `${m[1]}:${m[2]}` : ts;
}

/** 'YYYY-MM-DD (요일) HH:MM' */
export function virtualNowLabel(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!m) return iso;
  const wd = WEEKDAY_KO[new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getDay()];
  return `${m[1]}-${m[2]}-${m[3]} (${wd}) ${m[4]}:${m[5]}`;
}

// 점수(0~1)를 "평소와 다른 정도" 백분율로. 100 에서 뺀 값의 첫 유효숫자 다음 자리까지, 소수 최대 4 자리.
// 0.9999991 → 99.9999%, 0.99679 → 99.68%, 0.91 → 91.0%
export function formatScorePercent(score: number | undefined): string {
  if (score === undefined || !Number.isFinite(score)) return '-';
  const pct = score * 100;
  const gap = 100 - pct;
  if (gap <= 0) return '100%';
  const decimals = Math.min(4, Math.max(0, 1 - Math.floor(Math.log10(gap))));
  return `${pct.toFixed(decimals)}%`;
}

export interface SentenceParts {
  prefix: string;
  window: string;
  what: string;
  suffix: string;
}

const SEP = ' · ';

/**
 * 알림 문장을 강조용 부분으로 나눈다.
 * 4부분('A · W · X · S') → {A,W,X,S}; 3부분('A · W X · S') → W 는 첫 ') ' 까지(괄호 포함), X 는 그 뒤;
 * 분할 불가 → {prefix:'', window:'', what:s, suffix:''}
 */
export function splitSentence(s: string): SentenceParts {
  const parts = s.split(SEP);
  if (parts.length === 4) {
    return { prefix: parts[0], window: parts[1], what: parts[2], suffix: parts[3] };
  }
  if (parts.length === 3) {
    const mid = parts[1];
    const i = mid.indexOf(') ');
    if (i >= 0) {
      return { prefix: parts[0], window: mid.slice(0, i + 1), what: mid.slice(i + 2), suffix: parts[2] };
    }
  }
  return { prefix: '', window: '', what: s, suffix: '' };
}

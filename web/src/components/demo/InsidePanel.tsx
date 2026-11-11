import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { Badge } from '../ui/Badge';
import { Card } from '../ui/Card';
import { Note } from '../ui/Message';
import { hhmm } from '../../lib/format';
import { SENSOR_LABEL_KO } from '../../lib/demoApi';

export type WindowKey = 'night' | 'morning' | 'afternoon' | 'evening';
export interface Shade {
  sensor_id: string;
  window: WindowKey;
  flagged: boolean;
}

const SENSORS: { id: string; unit: string; digits: number }[] = [
  { id: 'water_main', unit: 'L', digits: 2 },
  { id: 'plug_fridge', unit: 'W', digits: 1 },
  { id: 'plug_tv', unit: 'W', digits: 1 },
  { id: 'plug_light', unit: 'W', digits: 1 },
];
const COLORS = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)'];
const WINDOW_HOURS: Record<WindowKey, [number, number]> = {
  night: [0, 6],
  morning: [6, 12],
  afternoon: [12, 18],
  evening: [18, 24],
};
const H = 84;
const M = { t: 6, r: 4, b: 18, l: 4 };
const PLAY_MS = 3000;

interface Pt {
  m: number;
  v: number;
}

function toPoints(raw: [string, number][] | undefined): Pt[] {
  return (raw ?? [])
    .map(([ts, v]) => {
      const [h, mm] = hhmm(ts).split(':').map(Number);
      return { m: h * 60 + mm, v: Number(v) };
    })
    .filter((p) => Number.isFinite(p.m) && Number.isFinite(p.v))
    .sort((a, b) => a.m - b.m);
}

function reducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

interface ChartProps {
  sid: string;
  unit: string;
  digits: number;
  color: string;
  pts: Pt[];
  W: number;
  shade: Shade[];
  playKey: number;
}

function SensorChart({ sid, unit, digits, color, pts, W, shade, playKey }: ChartProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const played = useRef(playKey);
  const dataKey = pts.map((p) => `${p.m}:${p.v}`).join(',');
  const shadeKey = shade.map((s) => `${s.window}:${s.flagged}`).join(',');

  useEffect(() => {
    const svgEl = svgRef.current;
    const box = boxRef.current;
    const tipEl = tipRef.current;
    if (!svgEl || !box || !tipEl) return;
    const animate = played.current !== playKey && !reducedMotion();
    played.current = playKey;

    const ymax = d3.max(pts, (d) => d.v) || 1;
    const x = d3.scaleLinear([0, 1440], [M.l, W - M.r]);
    const y = d3.scaleLinear([0, ymax * 1.08], [H - M.b, M.t]);
    const svg = d3.select(svgEl);
    svg.selectAll('*').interrupt().remove();

    for (const s of shade) {
      const r = WINDOW_HOURS[s.window];
      if (!r) continue;
      svg
        .append('rect')
        .attr('x', x(r[0] * 60))
        .attr('width', x(r[1] * 60) - x(r[0] * 60))
        .attr('y', M.t)
        .attr('height', H - M.b - M.t)
        .attr('fill', s.flagged ? 'var(--color-warn)' : 'var(--cds-chart-muted)')
        .attr('opacity', 0.12)
        .attr('rx', 2);
    }
    svg
      .append('line')
      .attr('x1', M.l)
      .attr('x2', W - M.r)
      .attr('y1', H - M.b)
      .attr('y2', H - M.b)
      .attr('stroke', 'var(--cds-chart-axis)');
    for (const h of [0, 6, 12, 18, 24]) {
      svg
        .append('text')
        .attr('x', x(h * 60))
        .attr('y', H - 4)
        .attr('text-anchor', h === 0 ? 'start' : h === 24 ? 'end' : 'middle')
        .attr('fill', 'var(--color-fg-muted)')
        .style('font-size', '10px')
        .text(`${h}시`);
    }
    const line = d3
      .line<Pt>()
      .x((d) => x(d.m))
      .y((d) => y(d.v));
    const path = svg
      .append('path')
      .datum(pts)
      .attr('fill', 'none')
      .attr('stroke', color)
      .attr('stroke-width', 1.75)
      .attr('stroke-linejoin', 'round')
      .attr('stroke-linecap', 'round')
      .attr('d', line);

    let raf = 0;
    const play = () => {
      const node = path.node();
      const len = node ? node.getTotalLength() : 0;
      if (!len) return false;
      path
        .attr('stroke-dasharray', `${len} ${len}`)
        .attr('stroke-dashoffset', len)
        .transition()
        .duration(PLAY_MS)
        .ease(d3.easeLinear)
        .attr('stroke-dashoffset', 0)
        .on('end', function () {
          d3.select(this).attr('stroke-dasharray', null);
        });
      return true;
    };
    if (animate && !play()) {
      // 아직 그려지기 전이면 길이가 0 — 한 틱 뒤에 한 번 더
      raf = window.requestAnimationFrame(() => void play());
    }

    const dot = svg.append('circle').attr('r', 3).attr('fill', color).style('display', 'none');
    const tip = d3.select(tipEl);
    const bis = d3.bisector((d: Pt) => d.m).center;
    svg
      .on('pointermove', (ev: PointerEvent) => {
        // d3.pointer 는 svg 의 viewBox 좌표를 돌려준다
        const [px] = d3.pointer(ev, svgEl);
        const d = pts[bis(pts, x.invert(px))];
        if (!d) return;
        dot.style('display', null).attr('cx', x(d.m)).attr('cy', y(d.v));
        const t = `${String(Math.floor(d.m / 60)).padStart(2, '0')}:${String(d.m % 60).padStart(2, '0')}`;
        tip.selectAll('*').remove();
        tip.append('div').attr('class', 't').text(t);
        tip.append('div').text(`${d.v.toFixed(digits)} ${unit}`);
        tipEl.hidden = false;
        const bw = box.clientWidth;
        const sx = x(d.m) * (bw / W);
        tipEl.style.left = `${Math.min(Math.max(0, sx - 40), bw - 90)}px`;
        tipEl.style.top = '0px';
      })
      .on('pointerleave', () => {
        dot.style('display', 'none');
        tipEl.hidden = true;
      });

    return () => {
      if (raf) window.cancelAnimationFrame(raf);
    };
    // pts·shade 는 내용 키로 비교한다 (폴링마다 새 배열이 와도 다시 그리지 않는다)
  }, [dataKey, shadeKey, W, playKey, color, digits, unit]);

  return (
    <div className="ichart" ref={boxRef} data-testid={`inside-chart-${sid}`}>
      <div className="lab">
        <span>
          {SENSOR_LABEL_KO[sid] ?? sid} ({unit}, 최근 24시간 · 5분 단위)
        </span>
      </div>
      {pts.length === 0 ? (
        <Note>아직 값이 없습니다</Note>
      ) : (
        <svg ref={svgRef} width="100%" height={H} viewBox={`0 0 ${W} ${H}`} />
      )}
      <div className="tip" ref={tipRef} hidden />
    </div>
  );
}

interface Props {
  recent: Record<string, [string, number][]>;
  /** 값이 바뀌면 최근 24 h 선을 3 초 동안 처음부터 다시 그린다 (하루 재생). */
  playKey: number;
  /** 넣은 하루에서 살펴본 (센서, 시간대). flagged 면 경고색 음영 */
  shade: Shade[];
}

/** 집 안 패널 — 원시 5 분 값은 이 패널에서만 쓴다. */
export default function InsidePanel({ recent, playKey, shade }: Props) {
  const gridRef = useRef<HTMLDivElement>(null);
  const [cw, setCw] = useState(600);

  useLayoutEffect(() => {
    const el = gridRef.current;
    if (!el) return;
    const measure = () => setCw(el.clientWidth || 600);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const W = Math.max(240, Math.floor(cw / (cw > 560 ? 2 : 1)) - 16);

  return (
    <Card title="집 안" right={<Badge>집 밖으로 나가지 않음</Badge>} testId="demo-inside">
      <Note>
        가상 집의 최근 24시간, 5분 단위 값입니다. 실제 제품에서는 이 값이 집 안에만 머뭅니다. 음영은 이날 평소와 달랐던 시간대입니다.
      </Note>
      <div className="inside" ref={gridRef}>
        {SENSORS.map((s, i) => (
          <SensorChart
            key={s.id}
            sid={s.id}
            unit={s.unit}
            digits={s.digits}
            color={COLORS[i % COLORS.length]}
            pts={toPoints(recent[s.id])}
            W={W}
            shade={shade.filter((x) => x.sensor_id === s.id)}
            playKey={playKey}
          />
        ))}
      </div>
    </Card>
  );
}

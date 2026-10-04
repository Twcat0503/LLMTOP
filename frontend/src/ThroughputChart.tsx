import { useCallback, useRef, useState } from 'react';
import type { History, Service } from './types';

const colors = ['#53d9bf', '#a99afb', '#f5bb4c', '#fa716d'];

export function ThroughputChart({ history, services, title = 'Output throughput (t/s)', unit = 't/s', emptyText = 'History appears after two observed samples.' }: { history: History | null; services: Service[]; title?: string; unit?: string; emptyText?: string }) {
  const observer = useRef<ResizeObserver | null>(null);
  const [box, setBox] = useState({width: 1160, height: 204});
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [tooltip, setTooltip] = useState<string | null>(null);
  const observe = useCallback((element: SVGSVGElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!element) return;
    observer.current = new ResizeObserver(entries => {
      const {width, height} = entries[0].contentRect;
      if (width && height) setBox({width, height});
    });
    observer.current.observe(element);
  }, []);
  const series = (history?.series ?? []).filter(s => services.some(service => service.id === s.id));
  const validSeries = series.filter(s => s.points.some(p => p.value !== null));
  const all = series.flatMap(s => s.points);
  const times = all.map(p => Date.parse(p.timestamp));
  const start = Math.min(...times), end = Math.max(...times);
  const valid = all.filter(p => p.value !== null);
  const peak = Math.max(0, ...valid.map(p => p.value ?? 0));
  const step = peak <= 5 ? 1 : peak <= 20 ? 5 : 50;
  const max = Math.max(step, Math.ceil(peak / step) * step);
  const left = 42, right = box.width - 14, bottom = box.height - 36;
  const x = (time: string) => left + (Date.parse(time) - start) / Math.max(1, end - start) * (right - left);
  const y = (n: number) => bottom - n / max * (bottom - 28);
  const duration = Number.isFinite(end - start) ? (end - start) / 1000 : 0;
  const paths = (points: typeof all): string[] => {
    const result: string[] = []; let path = '';
    for (const p of points) {
      if (p.value === null) { if (path) result.push(path); path = ''; }
      else path += `${path ? ' L' : 'M'}${x(p.timestamp).toFixed(2)},${y(p.value).toFixed(2)}`;
    }
    if (path) result.push(path);
    return result;
  };
  return <section className="panel chart-panel"><div className="chart-header"><h2>{title}</h2><div className="legend">
    {validSeries.map((s, index) => <button key={s.id} className={hidden.has(s.id) ? 'muted' : ''} aria-pressed={!hidden.has(s.id)} onClick={() => setHidden(old => { const next = new Set(old); if (next.has(s.id)) next.delete(s.id); else next.add(s.id); return next; })}><i style={{ background: colors[index % colors.length] }} />{services.find(service => service.id === s.id)?.label ?? s.id}</button>)}
  </div></div>
    {duration > 0 && valid.length > 1 ? <svg ref={observe} className="chart" viewBox={`0 0 ${box.width} ${box.height}`} role="img" aria-label={`Observed ${title} over time`}>
      {[0, max / 2, max].map(n => <g key={n}><line x1={left} x2={right} y1={y(n)} y2={y(n)} className="gridline" /><text x={left - 12} y={y(n) + 4} textAnchor="end">{n}</text></g>)}
      {[left, (left + right) / 2, right].map(px => <line key={px} x1={px} x2={px} y1="28" y2={bottom} className="gridline" />)}
      <line x1={left} x2={right} y1={bottom} y2={bottom} className="axis" />
      <text x={left} y={box.height - 10} textAnchor="middle">-{duration < 120 ? `${Math.round(duration)} s` : `${Math.round(duration / 60)} min`}</text><text x={(left + right) / 2} y={box.height - 10} textAnchor="middle">-{duration < 120 ? `${Math.round(duration / 2)} s` : `${Math.round(duration / 120)} min`}</text><text x={right} y={box.height - 10} textAnchor="end">now</text>
      {validSeries.map((s, index) => hidden.has(s.id) ? null : <g key={s.id} stroke={colors[index % colors.length]} fill="none">{paths(s.points).map((path, i) => <path key={i} d={path} strokeWidth="2.4" vectorEffect="non-scaling-stroke" />)}
        {s.points.filter((p, i) => p.value !== null && (i === s.points.length - 1 || i % Math.max(1, Math.ceil(s.points.length / 25)) === 0)).map(p => <circle key={p.snapshot_seq} cx={x(p.timestamp)} cy={y(p.value!)} r="5" fill="transparent" stroke="transparent" tabIndex={0} role="button" aria-label={`${s.id}: ${p.value!.toFixed(1)} ${unit} at ${new Date(p.timestamp).toLocaleTimeString()}`} onFocus={() => setTooltip(`${s.id}: ${p.value!.toFixed(1)} ${unit} · ${new Date(p.timestamp).toLocaleTimeString()}`)} onMouseEnter={() => setTooltip(`${s.id}: ${p.value!.toFixed(1)} ${unit} · ${new Date(p.timestamp).toLocaleTimeString()}`)} onBlur={() => setTooltip(null)} onMouseLeave={() => setTooltip(null)} />)}
      </g>)}
    </svg> : <div className="chart-empty">{emptyText}</div>}
    {tooltip && <output className="chart-tooltip" aria-live="polite">{tooltip}</output>}
  </section>;
}

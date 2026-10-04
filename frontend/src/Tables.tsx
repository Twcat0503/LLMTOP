import { useEffect, useRef } from 'react';
import { Icon } from './Icon';
import { DetailTrend } from './DetailTrend';
import { engineName, gib, number, percent, value, type Host, type Observation, type Service } from './types';

export function Meter({ n }: { n: number | null }) { return <span className="meter" aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(1, n ?? 0)) * 100}%` }} /></span>; }

const healthLabel = (health: string) => ({ reachable: 'Reachable', unreachable: 'Unavailable', auth_error: 'Auth error', degraded: 'Degraded', loading: 'Loading', unknown: 'Unknown' }[health] ?? health);

export function ServicesTable({ services, onSelect, sort, onSort }: { services: Service[]; onSelect: (service: Service) => void; sort: boolean; onSort: () => void }) {
  return <div className="table-wrap"><table className="services-table"><thead><tr>
    <th>Service</th><th>Engine and model</th><th>Status</th><th>Input t/s</th>
    <th aria-sort={sort ? 'descending' : 'none'}><button className="sort" onClick={onSort}>Output t/s<span aria-hidden="true">{sort ? ' ↓' : ''}</span></button></th>
    <th>Running</th><th>Waiting</th><th>KV cache</th>
  </tr></thead><tbody>{services.length ? services.map(s => <tr key={s.id}>
    <td><button className="service-link" onClick={() => onSelect(s)}>{s.label}</button></td>
    <td>{engineName(s.engine)}<span className="subtext">{s.model_name ?? 'N/A'}</span></td>
    <td><span className={`health ${s.health}`}><i />{healthLabel(s.health)}</span>{s.reason && <span className="subtext reason">{s.reason}</span>}</td>
    <td className="numeric" title={s.metrics.input_tps?.reason ?? undefined}>{number(s.metrics.input_tps)}</td>
    <td className="numeric" title={s.metrics.output_tps?.reason ?? undefined}>{number(s.metrics.output_tps)}</td>
    <td className="numeric">{number(s.metrics.engine_running_requests)}</td><td className="numeric">{number(s.metrics.engine_waiting_requests)}</td>
    <td><span className="meter-cell"><span className="numeric" title={s.metrics.kv_cache_usage_ratio?.reason ?? undefined}>{percent(s.metrics.kv_cache_usage_ratio)}</span>{value(s.metrics.kv_cache_usage_ratio) !== null && <Meter n={value(s.metrics.kv_cache_usage_ratio)} />}</span></td>
  </tr>) : <tr><td colSpan={8} className="empty">No services match these filters.</td></tr>}</tbody></table></div>;
}

function memoryRatio(used?: Observation, total?: Observation): number | null { const a = value(used), b = value(total); return a !== null && b !== null && b > 0 ? a / b : null; }

export function HostsTable({ hosts }: { hosts: Host[] }) {
  return <section className="panel host-panel"><h2>Host resources</h2><div className="table-wrap"><table className="hosts-table"><thead><tr><th>Host / Device</th><th>Type</th><th>Utilization</th><th>Memory</th><th>Extra</th></tr></thead><tbody>
    {hosts.map(host => {
      const m = host.metrics;
      const total = value(m.host_ram_total_bytes), available = value(m.host_ram_available_bytes);
      const used = total !== null && available !== null ? ((total - available) / 1073741824).toFixed(1) : 'N/A';
      return <HostRows key={host.id} host={host} used={used} />;
    })}
    {!hosts.length && <tr><td colSpan={5} className="empty">No hosts match these filters.</td></tr>}
  </tbody></table></div></section>;
}

function HostRows({ host, used }: { host: Host; used: string }) {
  const m = host.metrics;
  return <><tr><td><strong>{host.label}</strong><span className="scope" title={host.reason ?? undefined}>{host.scope}</span></td><td>CPU</td>
    <td><span className="meter-cell"><span className="numeric">{percent(m.host_cpu_usage_ratio)}</span><Meter n={value(m.host_cpu_usage_ratio)} /></span></td>
    <td><span className="meter-cell"><span className="numeric">{used} / {gib(m.host_ram_total_bytes)} GiB</span><Meter n={value(m.host_ram_usage_ratio)} /></span></td>
    <td><span className="meter-cell"><span className="numeric">Swap: {gib(m.host_swap_used_bytes)} / {gib(m.host_swap_total_bytes)} GiB</span><Meter n={memoryRatio(m.host_swap_used_bytes, m.host_swap_total_bytes)} /></span></td></tr>
    {host.devices.map(device => { const g = device.metrics; return <tr key={device.id}><td><strong>{device.label}</strong></td><td>GPU</td>
      <td><span className="meter-cell"><span className="numeric">{percent(g.gpu_utilization_ratio)}</span><Meter n={value(g.gpu_utilization_ratio)} /></span></td>
      <td><span className="meter-cell"><span className="numeric">{gib(g.gpu_memory_used_bytes)} / {gib(g.gpu_memory_total_bytes)} GiB</span><Meter n={memoryRatio(g.gpu_memory_used_bytes, g.gpu_memory_total_bytes)} /></span></td>
      <td className="numeric">{number(g.gpu_temperature_celsius)} °C <span className="extra-power">{number(g.gpu_power_watts)} W</span></td></tr>; })}
  </>;
}

export function ServiceDetail({ service, onClose }: { service: Service; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => { dialog?.close(); }; }, []);
  return <dialog ref={ref} className="detail" onCancel={onClose} onClick={e => { if (e.target === ref.current) onClose(); }} aria-labelledby="detail-title">
    <div className="detail-header"><div><h2 id="detail-title">{service.label}</h2><p>{engineName(service.engine)} · {service.model_name ?? 'N/A'} · version {service.engine_version ?? 'unverified'}</p></div><button className="icon-button" onClick={onClose} aria-label="Close details"><Icon name="close" /></button></div>
    {service.reason && <p className="notice">{service.reason}</p>}
    <DetailTrend service={service} />
    <div className="table-wrap"><table className="detail-table"><thead><tr><th>Metric</th><th>Value / status</th><th>Source / scope</th></tr></thead><tbody>{Object.values(service.metrics).map(m => <tr key={m.metric}>
      <td>{m.metric}<span className="subtext">{m.semantics}</span></td><td className="numeric">{number(m)} {m.unit}<span className="subtext">{m.status}{m.window_seconds !== null ? ` · ${m.window_seconds.toFixed(2)}s window` : ''}{m.epoch !== null ? ` · epoch ${m.epoch}` : ''}</span></td>
      <td>{m.source_metric ?? 'N/A'}<span className="subtext">{m.scope} · {m.coverage} · {m.measurement_kind}</span>{m.reason && <span className="subtext">{m.reason}</span>}</td></tr>)}</tbody></table></div>
  </dialog>;
}

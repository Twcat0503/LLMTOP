import { useEffect, useMemo, useState } from 'react';
import { Icon } from './Icon';
import { HostsTable, ServiceDetail, ServicesTable } from './Tables';
import { ThroughputChart } from './ThroughputChart';
import { engineName, value, type History, type Service, type Snapshot } from './types';
import { useMonitor } from './useMonitor';

export default function App() {
  const monitor = useMonitor();
  const [page, setPage] = useState<'Overview' | 'Services' | 'Hosts'>('Overview');
  const [host, setHost] = useState('all');
  const [engine, setEngine] = useState('all');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState(false);
  const [paused, setPaused] = useState(false);
  const [display, setDisplay] = useState<Snapshot | null>(null);
  const [displayHistory, setDisplayHistory] = useState<History | null>(null);
  const [selected, setSelected] = useState<Service | null>(null);
  useEffect(() => { if (!paused) { setDisplay(monitor.latest); setDisplayHistory(monitor.history); } }, [monitor.latest, monitor.history, paused]);

  const services = useMemo(() => (display?.services ?? []).filter(s => (host === 'all' || host === s.host_id) && (engine === 'all' || engine === s.engine) && `${s.label} ${s.model_name ?? ''}`.toLowerCase().includes(search.toLowerCase())).sort((a, b) => sort ? (value(b.metrics.output_tps) ?? -1) - (value(a.metrics.output_tps) ?? -1) : 0), [display, host, engine, search, sort]);
  const hosts = (display?.hosts ?? []).filter(h => host === 'all' || host === h.id);
  const sum = (name: string) => { const values = services.map(s => value(s.metrics[name])).filter((n): n is number => n !== null); return values.length ? values.reduce((a, b) => a + b, 0) : null; };
  const output = sum('output_tps'), running = sum('engine_running_requests'), waiting = sum('engine_waiting_requests');
  const partial = services.some(s => value(s.metrics.output_tps) === null);
  const reachable = services.filter(s => s.health === 'reachable').length;
  const engines = [...new Set(display?.services.map(s => s.engine) ?? [])];
  const connection = monitor.stale ? 'Disconnected' : monitor.connection;
  const lastUpdate = paused && display ? `${new Date(display.collected_at).toLocaleTimeString()}` : monitor.age === null ? 'N/A' : `${Math.floor(monitor.age)} seconds ago`;

  return <div className="app-shell"><aside className="rail"><a className="brand" href="#" onClick={e => { e.preventDefault(); setPage('Overview'); }}><Icon name="logo" size={30} /><span>LLMTOP</span></a>
    <nav aria-label="Main navigation">{(['Overview', 'Services', 'Hosts'] as const).map(name => <button key={name} className={page === name ? 'active' : ''} aria-current={page === name ? 'page' : undefined} onClick={() => setPage(name)}><Icon name={name.toLowerCase() as 'overview' | 'services' | 'hosts'} />{name}</button>)}</nav>
    <div className="rail-status"><span className={`connection ${connection.toLowerCase()}`}><i />{connection}</span><span className="version">v0.1.0</span></div>
  </aside><main><header className="page-header"><div><h1>{page}</h1><p>Service throughput, queue and host resources.</p></div><div className="actions"><button className={`icon-button ${paused ? 'selected' : ''}`} aria-label={paused ? 'Resume' : 'Pause'} title={paused ? 'Resume' : 'Pause'} aria-pressed={paused} onClick={() => setPaused(old => !old)}><Icon name={paused ? 'play' : 'pause'} size={24} /></button><button className="icon-button" aria-label="Refresh" title="Refresh" onClick={() => { void monitor.refresh(); }}><Icon name="refresh" size={24} /></button></div></header>
    <div className="toolbar"><div className="filters"><select aria-label="Filter host" value={host} onChange={e => setHost(e.target.value)}><option value="all">All hosts</option>{display?.hosts.map(h => <option key={h.id} value={h.id}>{h.label}</option>)}</select><select aria-label="Filter engine" value={engine} onChange={e => setEngine(e.target.value)}><option value="all">All engines</option>{engines.map(name => <option key={name} value={name}>{engineName(name)}</option>)}</select><label className="search"><Icon name="search" /><input aria-label="Search services" placeholder="Search services…" value={search} onChange={e => setSearch(e.target.value)} /></label></div>
      {display?.demo && <div className="demo-note"><span>Demo data</span><p>Synthetic example values.</p></div>}</div>
    {paused && <p className="notice" role="status">Paused · collector continues</p>}
    {monitor.error && <p className="notice error" role="status">{monitor.error}</p>}
    {monitor.stale && !paused && <p className="notice error" role="status">Snapshot is stale. Waiting for the collector.</p>}
    {!display ? <div className="panel initializing" role="status">Connecting to the collector…</div> : <>
      <section className="stats" aria-label="Service summary"><div><span>Reachable services</span><strong><em>{reachable}</em> / {services.length}</strong></div><div title={partial ? 'Partial: sum of available service rates' : 'Sum of available service rates'}><span>Output throughput{partial ? ' · partial' : ''}</span><strong>{output === null ? 'N/A' : output.toFixed(1)} <small>t/s</small></strong></div><div><span>Running / waiting</span><strong><em>{running ?? 'N/A'}</em> / {waiting ?? 'N/A'}</strong></div><div><span>Last update</span><strong className="last-update">{lastUpdate}</strong></div></section>
      {page !== 'Hosts' && <><ServicesTable services={services} onSelect={setSelected} sort={sort} onSort={() => setSort(old => !old)} /><ThroughputChart history={displayHistory} services={services} /></>}
      {page !== 'Services' && <HostsTable hosts={hosts} />}
      <p className="scope-note">Missing metrics are shown as N/A. Remote hardware requires a collector on that host.</p>
    </>}
    {selected && <ServiceDetail service={display?.services.find(s => s.id === selected.id) ?? selected} onClose={() => setSelected(null)} />}
  </main></div>;
}

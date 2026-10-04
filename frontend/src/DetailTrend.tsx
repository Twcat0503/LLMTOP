import { useEffect, useState } from 'react';
import type { History, Service } from './types';
import { ThroughputChart } from './ThroughputChart';

const metrics = [
  {id: 'output_tps', title: 'Output throughput (t/s)', unit: 't/s'},
  {id: 'input_tps', title: 'Input throughput (t/s)', unit: 't/s'},
  {id: 'kv_cache_usage_ratio', title: 'KV cache (%)', unit: '%'},
  {id: 'engine_waiting_requests', title: 'Waiting requests', unit: 'requests'},
];

export function DetailTrend({service}: {service: Service}) {
  const [metric, setMetric] = useState(metrics[0].id);
  const [history, setHistory] = useState<History | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setHistory(null);
    const refresh = async () => {
      try {
        const response = await fetch(`/api/v1/history?id=${encodeURIComponent(service.id)}&metric=${metric}&window=600&limit=300`, {signal: controller.signal});
        if (response.ok) {
          const data: History = await response.json();
          // Percent is a display unit; the API preserves the native 0–1 ratio.
          if (metric === 'kv_cache_usage_ratio') data.series = data.series.map(s => ({...s, points: s.points.map(p => ({...p, value: p.value === null ? null : p.value * 100}))}));
          setHistory(data);
        }
      } catch { /* Missing history remains explicit. */ }
    };
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [service.id, metric]);
  const selected = metrics.find(m => m.id === metric)!;
  return <div className="detail-trend"><label>Trend metric <select aria-label="Trend metric" value={metric} onChange={e => setMetric(e.target.value)}>{metrics.map(m => <option value={m.id} key={m.id}>{m.title}</option>)}</select></label>
    <ThroughputChart history={history} services={[service]} title={selected.title} unit={selected.unit} emptyText={service.metrics[metric]?.reason ?? undefined} />
  </div>;
}

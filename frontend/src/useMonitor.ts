import { useCallback, useEffect, useRef, useState } from 'react';
import type { History, Snapshot } from './types';

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error(`Backend returned HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

export function useMonitor() {
  const [latest, setLatest] = useState<Snapshot | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [connection, setConnection] = useState('Reconnecting');
  const [error, setError] = useState<string | null>(null);
  const [clock, setClock] = useState(Date.now());
  const cursor = useRef<Snapshot | null>(null);
  const historyBusy = useRef(false);
  const lifetime = useRef<AbortController | null>(null);

  const accept = useCallback((next: Snapshot) => {
    if (next.schema_version !== 1) { setError('Unsupported snapshot schema'); return; }
    const old = cursor.current;
    if (old && old.runtime_id === next.runtime_id && old.snapshot_seq >= next.snapshot_seq) return;
    if (old && old.runtime_id !== next.runtime_id) setHistory(null);
    cursor.current = next;
    setLatest(next);
    setError(null);
  }, []);

  const refreshHistory = useCallback(async () => {
    if (historyBusy.current) return;
    historyBusy.current = true;
    try {
      const next = await get<History>('/api/v1/history?metric=output_tps&window=600&limit=300', lifetime.current?.signal);
      if (!cursor.current || cursor.current.runtime_id === next.runtime_id) setHistory(next);
    } catch { /* Keep existing history; snapshot connection describes freshness. */ }
    finally { historyBusy.current = false; }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [snapshot] = await Promise.all([get<Snapshot>('/api/v1/snapshot', lifetime.current?.signal), refreshHistory()]);
      accept(snapshot);
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) {
        setConnection('Reconnecting');
        setError(e instanceof Error ? e.message : 'Backend unavailable');
      }
    }
  }, [accept, refreshHistory]);

  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    let streaming = false;
    void refresh();
    const events = new EventSource('/api/v1/events');
    events.onopen = () => { streaming = true; setConnection('Connected'); };
    events.onerror = () => { streaming = false; setConnection('Reconnecting'); };
    events.addEventListener('snapshot', (event) => {
      try { accept(JSON.parse((event as MessageEvent<string>).data)); setConnection('Connected'); }
      catch { setError('Invalid snapshot response'); }
    });
    events.addEventListener('reset', () => { cursor.current = null; setHistory(null); void refresh(); });
    const polling = window.setInterval(() => { if (!streaming) void refresh(); }, 2000);
    const historyTimer = window.setInterval(() => { void refreshHistory(); }, 5000);
    const ageTimer = window.setInterval(() => { setClock(Date.now()); }, 1000);
    return () => { controller.abort(); events.close(); window.clearInterval(polling); window.clearInterval(historyTimer); window.clearInterval(ageTimer); lifetime.current = null; };
  }, [accept, refresh, refreshHistory]);

  const age = latest ? Math.max(0, (clock - Date.parse(latest.collected_at)) / 1000) : null;
  const stale = age !== null && age > (latest?.stale_after_seconds ?? 10);
  return { latest, history, connection, error, age, stale, refresh };
}

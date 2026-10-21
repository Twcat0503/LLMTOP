export interface Observation {
  metric: string; value: number | null; unit: string; status: string;
  reason: string | null; source_kind: string; source_metric: string | null;
  scope: string; measurement_kind: string; observed_at: string;
  last_success_at: string | null; window_seconds: number | null; epoch: string | null;
  semantics: string | null; coverage: string;
}
export interface Service {
  id: string; label: string; host_id: string; engine: string; model_name: string | null;
  engine_version: string | null; version_verified: boolean; health: string;
  reason: string | null; metrics: Record<string, Observation>;
}
export interface Device { id: string; label: string; provider: string; driver_version: string | null; metrics: Record<string, Observation>; }
export interface Host { id: string; label: string; scope: string; collector: string; reason: string | null; metrics: Record<string, Observation>; devices: Device[]; }
export interface Snapshot { schema_version: number; runtime_id: string; snapshot_seq: number; collected_at: string; demo: boolean; refresh_interval_seconds: number; stale_after_seconds: number; services: Service[]; hosts: Host[]; }
export interface Point { timestamp: string; snapshot_seq: number; value: number | null; status: string; }
export interface Series { id: string; metric: string; unit: string; points: Point[]; }
export interface History { runtime_id: string; series: Series[]; truncated: boolean; window_seconds: number; }
export const engineName = (engine: string) => ({ vllm: 'vLLM', llamacpp: 'llama.cpp', sglang: 'SGLang', ollama: 'Ollama', strata: 'Strata' }[engine] ?? engine);
export const value = (metric?: Observation): number | null => metric?.status === 'ok' ? metric.value : null;
export const number = (metric?: Observation) => { const n = value(metric); return n === null ? 'N/A' : n.toLocaleString('en-US', { maximumFractionDigits: metric?.unit === 'tokens/s' ? 1 : 0, minimumFractionDigits: metric?.unit === 'tokens/s' ? 1 : 0 }); };
export const percent = (metric?: Observation) => { const n = value(metric); return n === null ? 'N/A' : `${Math.round(n * 100)}%`; };
export const gib = (metric?: Observation) => { const n = value(metric); return n === null ? 'N/A' : (n / 1073741824).toFixed(1); };

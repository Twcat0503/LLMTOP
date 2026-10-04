import asyncio
from datetime import timedelta

import pytest

from llmtop.config import ConfigError, load_config
from llmtop.core.models import Snapshot, Status, utc_now
from llmtop.core.rates import RateTracker
from llmtop.core.runtime import Runtime
from llmtop.core.store import Store


def test_rate_uses_actual_interval_and_preserves_zero():
    tracker = RateTracker(10)
    assert tracker.observe("s", "tokens", 100, 10, "model").status == Status.WARMING_UP
    result = tracker.observe("s", "tokens", 125, 12.5, "model")
    assert result.value == 10
    assert result.window == 2.5
    assert tracker.observe("s", "tokens", 125, 14.5, "model").value == 0


@pytest.mark.parametrize("value,time,identity", [(5, 12, "a"), (200, 22, "a"), (200, 12, "b")])
def test_reset_gap_and_identity_start_new_epoch(value, time, identity):
    tracker = RateTracker(10)
    initial = tracker.observe("s", "tokens", 100, 10, "a")
    result = tracker.observe("s", "tokens", value, time, identity)
    assert result.value is None and result.status == Status.WARMING_UP
    assert result.epoch == initial.epoch + 1
    assert tracker.observe("s", "tokens", value + 20, time + 2, identity).value == 10


def test_nonpositive_interval_cannot_corrupt_baseline():
    tracker = RateTracker(10)
    tracker.observe("s", "tokens", 100, 10, "a")
    assert tracker.observe("s", "tokens", 110, 10, "a").value is None
    assert tracker.observe("s", "tokens", 120, 12, "a").value == 10
    tracker.invalidate("s", "tokens")
    assert tracker.observe("s", "tokens", 130, 14, "a").value is None


def test_bounded_store_skips_slow_clients_and_truncates():
    store = Store(10, 2)
    queue = store.subscribe()
    for seq in range(1, 100):
        store.publish(
            Snapshot(
                runtime_id="r", snapshot_seq=seq, refresh_interval_seconds=2, services=[], hosts=[]
            )
        )
    assert len(store.history) <= 7
    assert queue.qsize() == 1 and queue.get_nowait().snapshot_seq == 99
    assert store.series([], "output_tps", 10, 2)["truncated"]
    store.unsubscribe(queue)
    assert not store.subscribers


def test_store_time_retention_and_subscriber_limit():
    store = Store(1, 1)
    store.publish(
        Snapshot(
            runtime_id="r",
            snapshot_seq=1,
            collected_at=utc_now() - timedelta(seconds=5),
            refresh_interval_seconds=1,
            services=[],
            hosts=[],
        )
    )
    store.publish(
        Snapshot(runtime_id="r", snapshot_seq=2, refresh_interval_seconds=1, services=[], hosts=[])
    )
    assert len(store.history) == 1
    for _ in range(64):
        store.subscribe()
    with pytest.raises(ValueError):
        store.subscribe()


@pytest.mark.parametrize(
    "text",
    [
        '[[hosts]]\nid="x"\nlabel="x"\n[[services]]\nid="s"\nlabel="s"\nhost_id="missing"\nengine="vllm"\napi_url="http://x"',
        '[web]\nbind_host="0.0.0.0"',
        "[privacy]\ncapture_prompt=true",
        'secret="private-token"',
    ],
)
def test_invalid_config_is_sanitized(tmp_path, text):
    path = tmp_path / "invalid.toml"
    path.write_text(text)
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert "private-token" not in str(error.value)
    assert "Invalid configuration" in str(error.value)


async def test_demo_is_explicit_and_has_no_network(config):
    from llmtop.config import demo_config

    runtime = Runtime(demo_config(), demo=True)
    try:
        first = await runtime.poll()
        await asyncio.sleep(0.01)
        second = await runtime.poll()
        assert first.demo and second.demo
        assert second.services[0].metrics["output_tps"].value > 0
        assert second.services[2].metrics["output_tps"].value is None
        assert len(runtime.store.history) == 2
    finally:
        await runtime.close()

from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Dict, Generator, Iterable


def _now_iso() -> str:
	return datetime.utcnow().isoformat() + "Z"


def make_web_log(level: str, msg: str) -> Dict:
	return {
		"ts": _now_iso(),
		"source": "web",
		"level": level,
		"message": msg,
		"http": {
			"path": random.choice(["/", "/login", "/api/checkout", "/search"]),
			"status": random.choice([200, 200, 200, 500, 502, 504]),
			"latency_ms": random.randint(80, 900),
		},
	}


def make_db_log(level: str, msg: str) -> Dict:
	return {
		"ts": _now_iso(),
		"source": "db",
		"level": level,
		"message": msg,
		"db": {
			"query": random.choice(["SELECT * FROM users", "UPDATE orders SET status='paid' WHERE id=...", "VACUUM", "CREATE INDEX ..."]),
			"duration_ms": random.randint(2, 4000),
			"error": random.choice([None, None, "deadlock detected", "timeout"]),
		},
	}


def mixed_log_stream(steps: int = 200, seed: int | None = 7, sleep: float = 0.0) -> Generator[Dict, None, None]:
	"""Yield a stream of mixed web/db logs with occasional downtime-like patterns."""
	rng = random.Random(seed)
	for i in range(steps):
		# background noise
		if rng.random() < 0.6:
			yield make_web_log("INFO", "request completed")
		else:
			yield make_db_log("INFO", "query done")

		# occasional web outage spike
		if rng.random() < 0.08:
			for _ in range(rng.randint(3, 7)):
				yield make_web_log("ERROR", rng.choice(["upstream connect error", "gateway timeout", "5xx surge observed"]))

		# occasional db slowdown/deadlock
		if rng.random() < 0.06:
			for _ in range(rng.randint(2, 5)):
				yield make_db_log("ERROR", rng.choice(["deadlock detected", "connection pool exhausted", "slow query > 3s"]))

		# occasional module failures (sensor/ingestion) that can cascade
		if rng.random() < 0.05:
			yield {
				"ts": _now_iso(),
				"source": "sensor",
				"level": "ERROR",
				"message": rng.choice(["sensor offline", "sensor timeout", "sensor calibration lost"]),
				"module": {"name": "sensor", "status": "down"},
			}
		if rng.random() < 0.04:
			yield {
				"ts": _now_iso(),
				"source": "ingestion",
				"level": "ERROR",
				"message": rng.choice(["ingestion backlog", "kafka consumer lag", "ingestion stalled"]),
				"module": {"name": "ingestion", "status": "degraded"},
			}

		if sleep:
			time.sleep(sleep)


def heartbeat_stream(steps: int = 100, seed: int | None = 11, sleep: float = 0.0) -> Generator[Dict, None, None]:
	"""Generate heartbeat/online-status events for services and modules."""
	rng = random.Random(seed)
	modules = [
		("sensor", ["online", "offline"]),
		("ingestion", ["online", "degraded", "offline"]),
		("web", ["online", "degraded", "offline"]),
		("db", ["online", "degraded", "offline"]),
	]
	for _ in range(steps):
		name, states = rng.choice(modules)
		status = rng.choices(states, weights=[0.8, 0.15, 0.05], k=1)[0]
		evt = {
			"ts": _now_iso(),
			"source": name,
			"level": "INFO" if status == "online" else "WARN",
			"message": f"heartbeat: {name} {status}",
			"heartbeat": {"name": name, "status": status},
		}
		yield evt
		if sleep:
			time.sleep(sleep)


def as_strings(stream: Iterable[Dict]) -> Generator[str, None, None]:
	"""Optionally present logs as raw strings (format-agnostic input)."""
	for item in stream:
		if random.random() < 0.3:
			# degrade structure to a string (to test parser robustness)
			yield f"[{item.get('ts')}] {item.get('source')}: {item.get('level')} - {item.get('message')}"
		else:
			yield item


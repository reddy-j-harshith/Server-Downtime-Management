from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Dict, Any

from langchain_core.tools import tool


@dataclass
class Service:
	name: str
	status: str = "healthy"  # healthy | degraded | down
	error_rate: float = 0.01
	latency_ms: int = 120
	replicas: int = 3
	notes: str = ""


@dataclass
class World:
	services: Dict[str, Service] = field(default_factory=dict)
	incidents_open: int = 0
	# Non-service modules (e.g., sensors, ingestion pipelines) with simple statuses
	modules: Dict[str, str] = field(default_factory=dict)  # name -> status: healthy|degraded|down

	def snapshot(self) -> Dict[str, Any]:
		return {
			"services": {k: vars(v) for k, v in self.services.items()},
			"incidents_open": self.incidents_open,
		}


# Global simulation world state (simple in-memory singleton)
WORLD = World(
	services={
		"web": Service(name="web", status="healthy", error_rate=0.01, latency_ms=110, replicas=3),
		"db": Service(name="db", status="healthy", error_rate=0.005, latency_ms=9, replicas=1),
	},
	modules={
		"sensor": "healthy",
		"ingestion": "healthy",
	},
)


@tool
def get_service_metrics(service: str) -> Dict[str, Any]:
	"""Return current simulated metrics for the given service name (web, db)."""
	svc = WORLD.services.get(service)
	if not svc:
		return {"error": f"service '{service}' not found"}
	# Add small jitter to keep it lively
	jitter_latency = max(1, int(random.gauss(mu=svc.latency_ms, sigma=max(1, svc.latency_ms * 0.05))))
	jitter_error = max(0.0, min(1.0, random.gauss(mu=svc.error_rate, sigma=max(0.0005, svc.error_rate * 0.2))))
	return {
		"service": svc.name,
		"status": svc.status,
		"replicas": svc.replicas,
		"latency_ms": jitter_latency,
		"error_rate": round(jitter_error, 4),
	}


@tool
def restart_service(service: str) -> str:
	"""Simulate restarting a service; may improve status/metrics if service was degraded/down."""
	svc = WORLD.services.get(service)
	if not svc:
		return f"service '{service}' not found"
	time.sleep(0.1)
	if svc.status in ("degraded", "down"):
		svc.status = "healthy"
		svc.error_rate = max(0.002, svc.error_rate * 0.5)
		svc.latency_ms = max(80, int(svc.latency_ms * 0.8))
		svc.notes = "restarted"
		return f"{service} restarted; status=healthy"
	return f"{service} was healthy; restart skipped"


@tool
def scale_service(service: str, delta: int) -> str:
	"""Scale a service by delta replicas (can be negative). Returns new replica count."""
	svc = WORLD.services.get(service)
	if not svc:
		return f"service '{service}' not found"
	new_replicas = max(1, svc.replicas + int(delta))
	svc.replicas = new_replicas
	# naive impact model: more replicas -> lower latency and error
	svc.latency_ms = max(60, int(svc.latency_ms * (0.95 if delta > 0 else 1.05)))
	svc.error_rate = max(0.001, round(svc.error_rate * (0.9 if delta > 0 else 1.05), 4))
	return f"{service} scaled to {new_replicas} replicas"


@tool
def purge_cache(service: str) -> str:
	"""Simulate purging a cache for a service; helps transient 5xx spikes for web."""
	svc = WORLD.services.get(service)
	if not svc:
		return f"service '{service}' not found"
	if service == "web":
		svc.error_rate = max(0.001, round(svc.error_rate * 0.7, 4))
		svc.latency_ms = max(70, int(svc.latency_ms * 0.9))
		return "web cache purged; improved error/latency"
	return f"no cache configured for {service}"


@tool
def open_incident(summary: str, severity: str = "P2") -> str:
	"""Open a simulated incident ticket with a summary and severity (P1..P4). Returns incident id."""
	WORLD.incidents_open += 1
	inc_id = f"INC-{1000 + WORLD.incidents_open}"
	return f"opened {inc_id} ({severity}): {summary}"


@tool
def send_notification(channel: str, message: str) -> str:
	"""Send a simulated notification to a channel (slack://alerts, email://oncall)."""
	return f"notified {channel}: {message}"


@tool
def repair_module(module: str) -> str:
	"""Simulate repairing a non-service module (e.g., sensor, ingestion). Sets status to healthy."""
	if module not in WORLD.modules:
		return f"module '{module}' not found"
	WORLD.modules[module] = "healthy"
	return f"module {module} repaired; status=healthy"


# Export a convenient list of tools per domain
WEB_TOOLS = [get_service_metrics, restart_service, scale_service, purge_cache, open_incident, send_notification]
DB_TOOLS = [get_service_metrics, restart_service, scale_service, open_incident, send_notification]
ALL_TOOLS = list({t.name: t for t in WEB_TOOLS + DB_TOOLS + [repair_module]}.values())


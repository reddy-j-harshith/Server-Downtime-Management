from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Any

from src.ingest.parser import normalize_event
from src.tools.actions import WORLD, repair_module, restart_service, purge_cache, scale_service


@dataclass
class DependencyGraph:
    # adjacency: module -> list of dependencies (must be healthy before this)
    deps: Dict[str, List[str]] = field(default_factory=dict)
    status: Dict[str, str] = field(default_factory=dict)  # healthy|degraded|down

    def add_module(self, name: str, status: str = "healthy"):
        self.deps.setdefault(name, [])
        self.status.setdefault(name, status)

    def add_dependency(self, module: str, depends_on: str):
        self.add_module(module)
        self.add_module(depends_on)
        self.deps[module].append(depends_on)

    def mark(self, module: str, status: str):
        self.add_module(module)
        self.status[module] = status

    def failing_modules(self) -> List[str]:
        return [m for m, s in self.status.items() if s in ("down", "degraded")]

    def recovery_plan(self, target: str) -> List[str]:
        # Return bottom-up plan: dependencies first, then the target
        visited: Dict[str, bool] = {}
        order: List[str] = []

        def dfs(m: str):
            if visited.get(m):
                return
            visited[m] = True
            for d in self.deps.get(m, []):
                dfs(d)
            order.append(m)

        dfs(target)
        return order  # dependencies first due to post-order


def default_graph() -> DependencyGraph:
    g = DependencyGraph()
    # Example industrial-ish chain: web depends on db and ingestion; ingestion depends on sensor
    g.add_dependency("web", "db")
    g.add_dependency("web", "ingestion")
    g.add_dependency("ingestion", "sensor")
    # Initialize from WORLD
    g.mark("web", WORLD.services["web"].status)
    g.mark("db", WORLD.services["db"].status)
    g.mark("sensor", WORLD.modules.get("sensor", "healthy"))
    g.mark("ingestion", WORLD.modules.get("ingestion", "healthy"))
    return g


def infer_modules_from_event(event: Any) -> List[Tuple[str, str]]:
    # returns list of (module, status) updates based on event content
    norm = normalize_event(event)
    msg = (norm.get("message") or "").lower()
    src = (norm.get("source") or "").lower()
    updates: List[Tuple[str, str]] = []
    if "sensor" in msg or src == "sensor":
        if any(k in msg for k in ["offline", "timeout", "lost"]):
            updates.append(("sensor", "down"))
    if "ingestion" in msg or src == "ingestion":
        if any(k in msg for k in ["backlog", "lag", "stalled"]):
            updates.append(("ingestion", "degraded"))
    if src == "web":
        if any(k in msg for k in ["5xx", "timeout", "gateway", "upstream", "error"]):
            updates.append(("web", "degraded"))
    if src == "db":
        if any(k in msg for k in ["deadlock", "timeout", "exhausted", "slow"]):
            updates.append(("db", "degraded"))
    return updates


def execute_recovery(plan: List[str]) -> List[str]:
    # Perform actions bottom-up; return action log strings
    actions: List[str] = []
    for mod in plan:
        if mod == "sensor":
            res = repair_module.invoke({"module": "sensor"})
            actions.append(res)
            WORLD.modules["sensor"] = "healthy"
        elif mod == "ingestion":
            # treat as module repair
            res = repair_module.invoke({"module": "ingestion"})
            actions.append(res)
            WORLD.modules["ingestion"] = "healthy"
        elif mod == "db":
            res = restart_service.invoke({"service": "db"})
            actions.append(res)
        elif mod == "web":
            # conservative: purge cache and scale a bit to absorb backlog
            actions.append(purge_cache.invoke({"service": "web"}))
            actions.append(scale_service.invoke({"service": "web", "delta": 1}))
        else:
            actions.append(f"no action for module {mod}")
    return actions

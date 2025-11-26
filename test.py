import json
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional
import pandas as pd
# Import base classes and agents so we can safely patch runtime issues
from agents import base_agent as _base_agent_module
from agents.domain_recovery import DomainRecoveryAgent
from agents.heuristic_memory import HeuristicMemoryAgent
from agents.planner import ReActPlanner
from agents.orchestrator import MultiAgentOrchestrator
# --- Runtime compatibility patches (without modifying agent files) ---
# 1) Make BaseAgent.__init__ accept an optional name so agents that forget to
#    pass it (e.g. ParsingAgent) can still be instantiated.
_original_base_init = _base_agent_module.BaseAgent.__init__
def _patched_base_init(self, name: str = "agent"):
    _original_base_init(self, name)
_base_agent_module.BaseAgent.__init__ = _patched_base_init
# 2) Ensure concrete agents that don't override abstract start/stop are
#    instantiable by clearing their abstract methods at runtime.
for _cls in (DomainRecoveryAgent, HeuristicMemoryAgent, ReActPlanner):
    if getattr(_cls, "__abstractmethods__", None):
        _cls.__abstractmethods__ = frozenset()
def load_topology(topology_path: str = "topology.json") -> Dict[str, Any]:
    """
    Load the topology description from a JSON file.
    """
    path = Path(topology_path)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
def build_dependency_graph_from_topology(
    orchestrator: MultiAgentOrchestrator, topology: Dict[str, Any]
) -> None:
    """
    Populate the orchestrator's dependency graph using the topology definition.
    Uses the existing DependencyGraphAgent instance without modifying its code.
    """
    dep_graph_agent = orchestrator.dep_graph
    G = dep_graph_agent.G
    # Add nodes with metadata
    for node in topology.get("nodes", []):
        node_id = node.get("id")
        if not node_id:
            continue
        # everything except "id" becomes node attributes
        attrs = {k: v for k, v in node.items() if k != "id"}
        G.add_node(node_id, **attrs)
    # Add directed edges according to topology
    for edge in topology.get("edges", []):
        src = edge.get("from")
        dst = edge.get("to")
        if src is None or dst is None:
            continue
        G.add_edge(src, dst)
def simulate_events_from_topology(
    topology: Dict[str, Any],
    minutes: int = 5,
    base_cpu: float = 20.0,
    fault_cpu: float = 95.0,
) -> pd.DataFrame:
    """
    Create a synthetic time series of metric events based on the topology,
    including injected failures that will be detected by FaultDetectionAgent.
    """
    rows: List[Dict[str, Any]] = []
    nodes = topology.get("nodes", [])
    faulty_nodes_spec = topology.get("faulty_nodes", [])
    # Index faulty nodes for quick lookup
    faulty_by_id = {f["node_id"]: f for f in faulty_nodes_spec if "node_id" in f}
    # Generate per-minute events for each node
    for minute in range(minutes):
        for node in nodes:
            node_id = node.get("id")
            if not node_id:
                continue
            meta = {
                "node_type": node.get("node_type"),
                "layer": node.get("layer"),
            }
            # Decide CPU value: normal vs faulty
            cpu_value = base_cpu
            fault_spec = faulty_by_id.get(node_id)
            if fault_spec is not None:
                inject_minute = fault_spec.get("inject_at_minute", 0)
                if minute >= inject_minute:
                    cpu_value = fault_cpu
            rows.append(
                {
                    # The ParsingAgent will normalize timestamp if needed
                    "ts": minute,
                    "node_id": node_id,
                    "metric": "cpu",
                    "value": cpu_value,
                    "meta": meta,
                }
            )
    df = pd.DataFrame(rows)
    return df
def run_orchestrator_simulation(
    topology_path: str = "topology.json",
    topology: Optional[Dict[str, Any]] = None,
    stream_callback: Optional[Callable[[str], None]] = None,
    minutes: int = 5,
    base_cpu: float = 20.0,
    fault_cpu: float = 95.0,
) -> Dict[str, Any]:
    """
    High-level function that:
      1. Loads topology
      2. Initializes the MultiAgentOrchestrator and its agents
      3. Builds the dependency graph
      4. Simulates events and feeds them through the orchestrator
      5. Returns a structured result for visualization
    """
    def emit(msg: str) -> None:
        print(msg)
        if stream_callback is not None:
            stream_callback(msg)
    if topology is None:
        emit(f"Loading topology from '{topology_path}'...")
        topology = load_topology(topology_path)
>>>>>>> 7d1e4e0 (Add Streamlit UI, RCA analysis, and visualization utilities)
    else:
        emit("Using topology provided in-memory...")
    emit("Initializing MultiAgentOrchestrator and agents...")
    orchestrator = MultiAgentOrchestrator()
    emit("Building dependency graph from topology...")
    build_dependency_graph_from_topology(orchestrator, topology)
    emit("Simulating events based on topology and failure specifications...")
    events_df = simulate_events_from_topology(
        topology, minutes=minutes, base_cpu=base_cpu, fault_cpu=fault_cpu
    )
    emit("Processing events through the orchestrator pipeline...")
    orchestrator.process_events_from_dataframe(events_df)
    emit("Generating report from orchestrator...")
    report = orchestrator.generate_report()
    # Use existing agents to summarize failure propagation
    detected_fault_nodes = [f["node_id"] for f in orchestrator.detected_faults]
    root_cause_candidates = orchestrator.dep_graph.find_root_cause_candidates(
        detected_fault_nodes
    )
    emit(f"Detected faulty nodes: {detected_fault_nodes}")
    emit(f"Root cause candidates (via dependency graph): {root_cause_candidates}")
    result: Dict[str, Any] = {
        "topology": topology,
        "events": events_df,
        "summary": report.get("summary", {}),
        "details": report.get("details", {}),
        "detected_fault_nodes": detected_fault_nodes,
        "root_cause_candidates": root_cause_candidates,
    }
    return result
def main(stream_callback: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """
    Entry point intended to be called from Streamlit.
    Example Streamlit usage:
        import test
        result = test.main()
        st.json(result["summary"])
    """
    return run_orchestrator_simulation(stream_callback=stream_callback)
if __name__ == "__main__":
    # Run a local simulation when executed as a script.
    main()

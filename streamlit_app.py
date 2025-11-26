"""
Streamlit UI for the multi-agent server downtime management system.

How to run:
    streamlit run streamlit_app.py
or:
    python -m streamlit run streamlit_app.py
"""

from __future__ import annotations

import json
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Runtime compatibility patches for agent instantiation issues
# TODO: These patches handle abstract class issues without modifying agent files
from agents import base_agent as _base_agent_module
from agents.classification import ClassificationAgent
from agents.domain_recovery import DomainRecoveryAgent
from agents.heuristic_memory import HeuristicMemoryAgent
from agents.planner import ReActPlanner

_original_base_init = _base_agent_module.BaseAgent.__init__


def _patched_base_init(self, name: str = "agent"):
    _original_base_init(self, name)


_base_agent_module.BaseAgent.__init__ = _patched_base_init

for _cls in (DomainRecoveryAgent, HeuristicMemoryAgent, ReActPlanner, ClassificationAgent):
    if getattr(_cls, "__abstractmethods__", None):
        _cls.__abstractmethods__ = frozenset()

# Import project functions
from agents.orchestrator import MultiAgentOrchestrator
from rca_llm import generate_llm_rca
from test import (
    build_dependency_graph_from_topology,
    load_topology,
    run_orchestrator_simulation,
    simulate_events_from_topology,
)
from utils import nx_to_plotly_figure


def _init_session_state() -> None:
    """Initialize Streamlit session_state keys."""
    defaults = {
        "logs": [],
        "last_result": None,
        "step_orchestrator": None,
        "step_events": None,
        "current_step": -1,
        "selected_topology": None,
        "trace_ids": [],
        "auto_run_enabled": False,
        "simulation_status": "idle",
        "event_count": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _discover_topology_files() -> Dict[str, Path]:
    """Find all JSON topology files in `./` and `./topologies`."""
    base = Path(".")
    candidates = list(base.glob("*.json"))
    topologies_dir = base / "topologies"
    if topologies_dir.exists():
        candidates.extend(topologies_dir.glob("*.json"))

    files: Dict[str, Path] = {}
    for p in candidates:
        label = f"{p.parent.name}/{p.name}" if p.parent != base else p.name
        files[label] = p
    return files


def _apply_dark_theme() -> None:
    """Apply dark theme CSS styling."""
    st.markdown(
        """
        <style>
        .main {
            background-color: #0e1117;
        }
        .stApp {
            background-color: #0e1117;
        }
        h1, h2, h3 {
            color: #ffffff;
        }
        .stMetric {
            background-color: #262730;
            padding: 1rem;
            border-radius: 0.5rem;
        }
        .stMetric label {
            color: #ffffff;
        }
        .stMetric [data-testid="stMetricValue"] {
            color: #ffffff;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _append_log(msg: str, placeholder) -> None:
    """Append a message to the log and update UI."""
    st.session_state["logs"].append(msg)
    text = "\n".join(st.session_state["logs"][-100:])  # Keep last 100 lines
    placeholder.text(text)


def _generate_trace_id() -> str:
    """Generate a unique trace ID for events."""
    return str(uuid.uuid4())[:8]


def main() -> None:
    """Main entrypoint for the Streamlit UI."""
    st.set_page_config(
        page_title="Server Downtime Multi-Agent Simulation",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _init_session_state()
    _apply_dark_theme()

    # Large heading
    st.markdown("# 🚨 Server Downtime Multi-Agent Simulation")

    # Sidebar: Topology & Controls
    with st.sidebar:
        st.markdown("## 📋 Topology & Simulation Controls")

        # Topology selection
        topo_files = _discover_topology_files()
        topo_labels = list(topo_files.keys()) or ["topology.json"]

        selected_label = st.selectbox("Select topology file", topo_labels, key="topo_select")
        selected_path: Optional[Path] = topo_files.get(selected_label, Path("topology.json"))

        uploaded_file = st.file_uploader("Or upload topology JSON", type=["json"], key="topo_upload")

        # Show topology preview
        topology_dict: Optional[Dict[str, Any]] = None
        topology_path_str: str = str(selected_path)

        if uploaded_file is not None:
            try:
                topology_dict = json.load(uploaded_file)
                topology_path_str = uploaded_file.name or "uploaded_topology.json"
                st.success(f"✅ Loaded: {topology_path_str}")
            except Exception as e:
                st.error(f"Failed to parse uploaded JSON: {e}")
        else:
            try:
                topology_dict = load_topology(topology_path_str)
                st.info(f"📄 Selected: {selected_label}")
            except Exception:
                pass

        if topology_dict:
            nodes = topology_dict.get("nodes", [])
            edges = topology_dict.get("edges", [])
            st.caption(f"Nodes: {len(nodes)} | Edges: {len(edges)}")

        st.divider()

        # Simulation parameters
        st.markdown("### ⚙️ Simulation Parameters")
        minutes = st.number_input("Minutes", min_value=1, max_value=1440, value=5, step=1, key="sim_minutes")
        base_cpu = st.number_input("Base CPU", min_value=0.0, max_value=100.0, value=20.0, step=1.0, key="sim_base_cpu")
        fault_cpu = st.number_input("Fault CPU", min_value=0.0, max_value=100.0, value=95.0, step=1.0, key="sim_fault_cpu")
        step_seconds = st.number_input("Step seconds (UI animation)", min_value=0.1, max_value=10.0, value=1.0, step=0.1, key="sim_step_sec")

        st.markdown("### 📊 Propagation Parameters")
        base_prob = st.slider("Base probability", min_value=0.0, max_value=1.0, value=0.3, step=0.05, key="prop_base_prob")
        severity_mult = st.slider("Severity multiplier", min_value=0.0, max_value=5.0, value=1.0, step=0.1, key="prop_severity")
        hop_mult = st.slider("Hop multiplier", min_value=0.0, max_value=2.0, value=0.5, step=0.1, key="prop_hop")

        st.divider()

        # Control buttons
        st.markdown("### 🎮 Controls")
        col1, col2 = st.columns(2)
        with col1:
            schedule_inject = st.button("📅 Schedule injection", use_container_width=True)
        with col2:
            run_sim = st.button("▶️ Run simulation", type="primary", use_container_width=True)

        col3, col4 = st.columns(2)
        with col3:
            step_forward = st.button("⏩ Step forward", use_container_width=True)
        with col4:
            step_back = st.button("⏪ Step back", use_container_width=True)

        auto_run = st.checkbox("🔄 Auto run (safe)", value=st.session_state.get("auto_run_enabled", False), key="auto_run_check")
        st.session_state["auto_run_enabled"] = auto_run

        clear_logs = st.button("🗑️ Clear logs", use_container_width=True)

        # Status badge
        st.divider()
        status = st.session_state.get("simulation_status", "idle")
        status_colors = {"idle": "⚪", "running": "🟢", "paused": "🟡", "error": "🔴", "complete": "✅"}
        st.markdown(f"### Status: {status_colors.get(status, '⚪')} {status.upper()}")
        event_count = st.session_state.get("event_count", 0)
        st.caption(f"Simulated events: {event_count}")

    # Main content area
    # Top: Summary cards
    result = st.session_state.get("last_result")
    if result:
        topology = result["topology"]
        nodes = topology.get("nodes", [])
        edges = topology.get("edges", [])
        detected_fault_nodes = result.get("detected_fault_nodes", [])
        root_cause_candidates = result.get("root_cause_candidates", [])
    else:
        nodes = topology_dict.get("nodes", []) if topology_dict else []
        edges = topology_dict.get("edges", []) if topology_dict else []
        detected_fault_nodes = []
        root_cause_candidates = []

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Nodes", len(nodes))
    with col2:
        st.metric("Edges", len(edges))
    with col3:
        st.metric("Detected Faulty Nodes", len(detected_fault_nodes))
    with col4:
        st.metric("Root Cause Candidates", len(root_cause_candidates))

    # Log panel
    st.markdown("## 📝 Simulation Logs")
    log_placeholder = st.empty()
    if clear_logs:
        st.session_state["logs"] = []
        log_placeholder.text("")

    # Stream callback
    def stream_write(msg: str) -> None:
        _append_log(msg, log_placeholder)

    # Handle schedule injection
    if schedule_inject:
        st.info("💡 Injection scheduling feature: Modify topology.json 'faulty_nodes' section to schedule failures.")

    # Handle run simulation
    if run_sim:
        try:
            st.session_state["simulation_status"] = "running"
            st.session_state["logs"] = []
            _append_log("Starting simulation run...", log_placeholder)

            with st.spinner("Running simulation..."):
                result = run_orchestrator_simulation(
                    topology_path=topology_path_str,
                    topology=topology_dict,
                    stream_callback=stream_write,
                    minutes=int(minutes),
                    base_cpu=float(base_cpu),
                    fault_cpu=float(fault_cpu),
                )

                st.session_state["last_result"] = result
                st.session_state["simulation_status"] = "complete"
                events_df = result.get("events", pd.DataFrame())
                st.session_state["event_count"] = len(events_df) if isinstance(events_df, pd.DataFrame) else 0
                _append_log("Simulation completed successfully.", log_placeholder)
                st.rerun()
        except Exception:
            tb = traceback.format_exc()
            st.session_state["simulation_status"] = "error"
            st.error("An error occurred while running the simulation.")
            st.code(tb)
            _append_log(f"ERROR: {tb}", log_placeholder)

    # Step-by-step mode
    if step_forward or step_back:
        try:
            if st.session_state.get("step_orchestrator") is None:
                # Initialize
                if topology_dict is None:
                    topology_dict = load_topology(topology_path_str)

                events_df = simulate_events_from_topology(
                    topology_dict,
                    minutes=int(minutes),
                    base_cpu=float(base_cpu),
                    fault_cpu=float(fault_cpu),
                )

                orchestrator = MultiAgentOrchestrator()
                build_dependency_graph_from_topology(orchestrator, topology_dict)

                st.session_state["step_orchestrator"] = orchestrator
                st.session_state["step_events"] = events_df
                st.session_state["current_step"] = -1

            orch = st.session_state["step_orchestrator"]
            events_df = st.session_state["step_events"]
            current_step = st.session_state["current_step"]

            if step_forward:
                next_step = current_step + 1
                if next_step < int(minutes):
                    batch = events_df[events_df["ts"] == next_step]
                    if not batch.empty:
                        orch.process_events_from_dataframe(batch)
                        _append_log(f"Processed events for minute {next_step}.", log_placeholder)

                    report = orch.generate_report()
                    detected_fault_nodes = [f["node_id"] for f in orch.detected_faults]
                    root_cause_candidates = orch.dep_graph.find_root_cause_candidates(detected_fault_nodes)

                    st.session_state["last_result"] = {
                        "topology": topology_dict or load_topology(topology_path_str),
                        "events": events_df,
                        "summary": report.get("summary", {}),
                        "details": report.get("details", {}),
                        "detected_fault_nodes": detected_fault_nodes,
                        "root_cause_candidates": root_cause_candidates,
                    }

                    st.session_state["current_step"] = next_step
                    st.session_state["event_count"] = len(events_df[events_df["ts"] <= next_step])
                    st.rerun()
                else:
                    _append_log("Reached end of simulation window.", log_placeholder)

            elif step_back:
                prev_step = max(-1, current_step - 1)
                st.session_state["current_step"] = prev_step
                _append_log(f"Stepped back to minute {prev_step}.", log_placeholder)
                st.rerun()

        except Exception:
            tb = traceback.format_exc()
            st.error("An error occurred in step-by-step mode.")
            st.code(tb)

    # Main content: Two-column layout (left: tabs, right: graph)
    left_col, right_col = st.columns([2, 1])

    with right_col:
        st.markdown("## 🕸️ Topology Graph")
        if result:
            try:
                import networkx as nx

                G = nx.DiGraph()
                for n in nodes:
                    node_id = n.get("id")
                    if node_id:
                        attrs = {k: v for k, v in n.items() if k != "id"}
                        G.add_node(node_id, **attrs)
                for e in edges:
                    src = e.get("from")
                    dst = e.get("to")
                    if src and dst:
                        G.add_edge(src, dst)

                fig = nx_to_plotly_figure(
                    G, faulty_nodes=detected_fault_nodes, rca_nodes=root_cause_candidates
                )
                fig.update_layout(
                    height=600,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="white"),
                )
                st.plotly_chart(fig, use_container_width=True)
            except Exception:
                st.error("Failed to render topology graph.")
        else:
            st.info("Run a simulation to see the graph.")

    with left_col:
        tabs = st.tabs(["📈 Timeline", "📋 Events", "🔍 Trace Inspector", "🔬 RCA", "📊 Report & Exports"])

        with tabs[0]:
            st.markdown("### Time-Series Chart")
            if result:
                events_df = result.get("events")
                if isinstance(events_df, pd.DataFrame) and not events_df.empty:
                    node_ids = sorted(events_df["node_id"].unique())
                    selected_nodes = st.multiselect("Filter by node", node_ids, default=node_ids, key="timeline_filter")
                    filtered = events_df[events_df["node_id"].isin(selected_nodes)]

                    if not filtered.empty:
                        fig = go.Figure()
                        for node_id in selected_nodes:
                            node_data = filtered[filtered["node_id"] == node_id]
                            fig.add_trace(
                                go.Scatter(
                                    x=node_data["ts"],
                                    y=node_data["value"],
                                    mode="lines+markers",
                                    name=node_id,
                                    hovertemplate=f"<b>{node_id}</b><br>Time: %{{x}}<br>CPU: %{{y}}<extra></extra>",
                                )
                            )

                        fig.update_layout(
                            title="CPU Usage Over Time",
                            xaxis_title="Time (minutes)",
                            yaxis_title="CPU Usage (%)",
                            height=400,
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="white"),
                            legend=dict(bgcolor="rgba(0,0,0,0.5)"),
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No data for selected nodes.")
                else:
                    st.info("No events data available.")
            else:
                st.info("Run a simulation to see the timeline.")

        with tabs[1]:
            st.markdown("### Events Table")
            if result:
                events_df = result.get("events")
                if isinstance(events_df, pd.DataFrame) and not events_df.empty:
                    # Add trace IDs if not present
                    if "trace_id" not in events_df.columns:
                        events_df["trace_id"] = [_generate_trace_id() for _ in range(len(events_df))]
                        st.session_state["trace_ids"] = events_df["trace_id"].unique().tolist()

                    st.dataframe(events_df, use_container_width=True, height=400)
                else:
                    st.info("No events data available.")
            else:
                st.info("Run a simulation to see events.")

        with tabs[2]:
            st.markdown("### Trace Inspector")
            trace_input = st.text_input("Enter trace ID", key="trace_input")
            recent_traces = st.session_state.get("trace_ids", [])

            if recent_traces:
                st.markdown("**Recent trace IDs:**")
                for tid in recent_traces[-10:]:
                    if st.button(f"🔍 {tid}", key=f"trace_{tid}", use_container_width=True):
                        st.session_state["trace_input"] = tid
                        st.rerun()

            if trace_input:
                if result:
                    events_df = result.get("events")
                    if isinstance(events_df, pd.DataFrame) and "trace_id" in events_df.columns:
                        trace_events = events_df[events_df["trace_id"] == trace_input]
                        if not trace_events.empty:
                            st.markdown(f"**Trace: {trace_input}**")
                            st.dataframe(trace_events)
                            st.json(trace_events.to_dict("records"))
                        else:
                            st.warning(f"No events found for trace ID: {trace_input}")
                    else:
                        st.info("Trace IDs not available in events data.")
                else:
                    st.info("Run a simulation first.")

        with tabs[3]:
            st.markdown("### Root Cause Analysis")
            if result:
                try:
                    report_for_rca = {
                        "summary": result.get("summary", {}),
                        "details": result.get("details", {}),
                    }
                    events_for_rca = result.get("events", pd.DataFrame())
                    if not isinstance(events_for_rca, pd.DataFrame):
                        events_for_rca = pd.DataFrame(events_for_rca)

                    rca = generate_llm_rca(report_for_rca, events_for_rca, topology)

                    st.markdown("#### Dependency Graph Candidates")
                    st.write(root_cause_candidates)

                    st.markdown("#### LLM-style RCA Analysis")
                    st.markdown(rca["markdown"])

                    st.markdown("#### Confidence & Remediation")
                    st.metric("Confidence Score", f"{rca.get('confidence', 0):.2%}")
                    st.markdown("**Remediation Suggestions:**")
                    for rem in rca.get("remediation", []):
                        st.markdown(f"- {rem}")

                    # Download buttons
                    col1, col2 = st.columns(2)
                    with col1:
                        rca_json_bytes = json.dumps(rca, indent=2).encode("utf-8")
                        st.download_button(
                            "📥 Download RCA (JSON)",
                            data=rca_json_bytes,
                            file_name="rca_report.json",
                            mime="application/json",
                            use_container_width=True,
                        )
                    with col2:
                        rca_md_bytes = rca["markdown"].encode("utf-8")
                        st.download_button(
                            "📥 Download RCA (Markdown)",
                            data=rca_md_bytes,
                            file_name="rca_report.md",
                            mime="text/markdown",
                            use_container_width=True,
                        )
                except Exception:
                    tb = traceback.format_exc()
                    st.error("Failed to generate RCA.")
                    st.code(tb)
            else:
                st.info("Run a simulation to generate RCA.")

        with tabs[4]:
            st.markdown("### Raw Report")
            if result:
                with st.expander("Summary", expanded=False):
                    st.json(result.get("summary", {}))

                with st.expander("Details", expanded=False):
                    st.json(result.get("details", {}))

                st.markdown("### Exports")
                exp_col1, exp_col2, exp_col3 = st.columns(3)

                with exp_col1:
                    events_df = result.get("events", pd.DataFrame())
                    if isinstance(events_df, pd.DataFrame):
                        csv_bytes = events_df.to_csv(index=False).encode("utf-8")
                    else:
                        csv_bytes = pd.DataFrame(events_df).to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "📥 Download Events CSV",
                        data=csv_bytes,
                        file_name="events.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

                with exp_col2:
                    dep_graph_json_bytes = json.dumps(topology, indent=2).encode("utf-8")
                    st.download_button(
                        "📥 Download Dependency Graph JSON",
                        data=dep_graph_json_bytes,
                        file_name="dependency_graph.json",
                        mime="application/json",
                        use_container_width=True,
                    )

                with exp_col3:
                    topology_json_bytes = json.dumps(topology, indent=2).encode("utf-8")
                    st.download_button(
                        "📥 Download Topology JSON",
                        data=topology_json_bytes,
                        file_name="topology.json",
                        mime="application/json",
                        use_container_width=True,
                    )
            else:
                st.info("Run a simulation to see the report.")


if __name__ == "__main__":
    main()

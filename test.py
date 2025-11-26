<<<<<<< HEAD
import streamlit as st
import json, uuid, random, time, io, traceback
from datetime import datetime, timedelta
import networkx as nx
import pandas as pd
import plotly.graph_objects as go
# ------------- defaults / knobs -------------
BASE_TS = datetime.now()
DEFAULT_MINUTES = 6
SENSOR_PERIOD = 5
DEVICE_PERIOD = 7
BASE_PROP_PROB = 0.18 # baseline
SEVERITY_MULT = 0.7 # how strongly severity amplifies p
HOP_MULT = 1.2 # increase per hop
PRECURSOR_WINDOW = 12 # seconds before failure where precursors appear
# ------------- helpers -------------
def safe_iso(ts):
    if ts is None:
        return None
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if isinstance(ts, datetime):
        return ts.replace(microsecond=0).isoformat() + "Z"
    s = str(ts)
    return s if s.endswith("Z") else s + "Z"
def parse_topology_json(raw):
    topo = json.loads(raw)
    # validation
    if "nodes" not in topo or not isinstance(topo["nodes"], list):
        raise ValueError("topology JSON must include a 'nodes' array")
    if "edges" not in topo or not isinstance(topo["edges"], list):
        raise ValueError("topology JSON must include an 'edges' array")
    G = nx.DiGraph()
    for n in topo["nodes"]:
        if "id" not in n:
            raise ValueError("each node must have an 'id'")
        attrs = dict(n)
        attrs.setdefault("node_type", "device")
        attrs.setdefault("layer", "L2")
        G.add_node(n["id"], **attrs)
    for e in topo["edges"]:
        src = e.get("from") or e.get("src")
        dst = e.get("to") or e.get("dst")
        if src is None or dst is None:
            raise ValueError("each edge must have 'from' and 'to'")
        attrs = {k:v for k,v in e.items() if k not in ("from","to","src","dst")}
        # default weight 1.0
        if "weight" not in attrs:
            attrs["weight"] = 1.0
        G.add_edge(src, dst, **attrs)
    faulty = topo.get("faulty_nodes", [])
    if not isinstance(faulty, list):
        raise ValueError("'faulty_nodes' must be a list")
    return G, faulty
def load_topology(source):
    if source is None:
        raise ValueError("no topology provided")
    if hasattr(source, "read"):
        raw = source.read()
        raw = raw.decode("utf-8") if isinstance(raw, (bytes,bytearray)) else raw
        return parse_topology_json(raw)
    else:
        with open(source, "r", encoding="utf-8") as f:
            return parse_topology_json(f.read())
# ------------- simulation (rich) -------------
def gen_metric_val(node_type, extra=None):
    # extra: dict for bumped cpu/qlen etc
    if node_type == "sensor":
        base = 20 + random.gauss(0,0.6)
        return {"temperature": round(base + (extra.get("temp_delta",0) if extra else 0),3)}
    else:
        cpu = min(100, max(0, 10 + random.gauss(0,6) + (extra.get("cpu_delta",0) if extra else 0)))
        q = max(0, int(random.expovariate(1/3) + (extra.get("q_delta",0) if extra else 0)))
        return {"cpu": round(cpu,2), "queue_len": q}
def gen_error(ts, node_id, code, name, severity_level, trace_id, parent_trace=None, cascade_id=None, hop=None, parent_node_id=None, origin_id=None):
    # severity_level: numeric 0..2
    return {
        "ts": safe_iso(ts),
        "node_id": node_id,
        "event_type": "error",
        "error": {"code": code, "name": name, "severity_level": severity_level},
        "trace_id": trace_id,
        "parent_trace": parent_trace,
        "cascade_id": cascade_id,
        "hop": hop,
        "parent_node_id": parent_node_id,
        "origin_id": origin_id,
    }
def gen_status(ts, node_id, status, trace_id=None, parent_trace=None):
    return {"ts": safe_iso(ts), "node_id": node_id, "event_type":"status", "status": status,
            "trace_id": trace_id, "parent_trace": parent_trace}
def compute_prop_prob(base, severity_mult, hop_mult, severity_level, hop, edge_weight):
    # severity_level 0..2 -> use multiplier (1 + severity_mult * level)
    sev_factor = 1.0 + float(severity_mult) * severity_level
    hop_factor = (float(hop_mult) ** hop)
    p = float(base) * edge_weight * sev_factor * hop_factor
    return min(1.0, p)
def simulate_rich(G, faulty_cfg, minutes=DEFAULT_MINUTES, seed=0, base_prop=BASE_PROP_PROB, severity_mult=SEVERITY_MULT, hop_mult=HOP_MULT, stochastic_multiplier=10.0, force_demo=True):
    random.seed(seed)
    nodes = list(G.nodes)
    if not nodes:
        raise ValueError("topology empty")
    # choose periods per node_type
    next_emit = {}
    node_period = {}
    for n in nodes:
        nt = G.nodes[n].get("node_type","device")
        node_period[n] = SENSOR_PERIOD if nt=="sensor" else DEVICE_PERIOD
        next_emit[n] = BASE_TS
    end_ts = BASE_TS + timedelta(minutes=minutes)
    cursor = BASE_TS
    events = []
    active_traces = {} # trace_id -> {'origin', 'severity_level', 'hops':{node:hop}, 'last_ts'}
    # interpret faulty_cfg: support node_id, inject_at_minute, inject_rate_per_minute, severity_level
    explicit = []
    stochastic = []
    for f in faulty_cfg:
        if not isinstance(f, dict) or "node_id" not in f:
            continue
        if "inject_at_minute" in f:
            explicit.append((BASE_TS + timedelta(minutes=f["inject_at_minute"]), f["node_id"], f.get("severity_level",2)))
        elif "inject_rate_per_minute" in f:
            ff = dict(f)
            ff["inject_rate_per_minute"] = float(f.get("inject_rate_per_minute", 0)) * float(stochastic_multiplier)
            stochastic.append(ff)
        else:
            # immediate inject
            explicit.append((BASE_TS, f["node_id"], f.get("severity_level",2)))
    # ensure at least one demo injection if requested
    if force_demo and not explicit and not stochastic:
        candidate_nodes = [n for n in G.nodes] or []
        if candidate_nodes:
            explicit.append((BASE_TS + timedelta(seconds=3), random.choice(candidate_nodes), 2))
    # helper: schedule precursor bump on downstream nodes
    def schedule_precursors(origin_node, severity_level, ts_origin):
        # for each successive node along BFS up to depth 3, create metric bumps before ts_origin
        planned = []
        for depth in range(1,4):
            for node, dist in nx.single_source_shortest_path_length(G, origin_node, cutoff=depth).items():
                if dist != depth:
                    continue
                nt = G.nodes[node].get("node_type", "device")
                prec_window = PRECURSOR_WINDOW // (depth + 1)
                ts_spike = ts_origin - timedelta(seconds=random.randint(1, max(1, prec_window)))
                if nt == "sensor":
                    temp_delta = max(0, 5 - depth * 1) * (1 + severity_level * 0.5)
                    extra = {"temp_delta": temp_delta}
                else:
                    cpu_delta = max(0, 15 - depth * 3) * (1 + severity_level * 0.5)
                    q_delta = max(0, 10 - depth * 2) * (1 + severity_level * 0.4)
                    extra = {"cpu_delta": cpu_delta, "q_delta": q_delta}
                planned.append((node, ts_spike, extra))
        return planned
    # main loop
    while cursor < end_ts:
        # explicit injections at cursor
        for inj in list(explicit):
            ts_inj, nid, sev = inj
            if cursor >= ts_inj:
                trace_id = str(uuid.uuid4())
                events.append(gen_error(cursor, nid, 100 + random.randint(0,50), "SEED_FAILURE", sev, trace_id, cascade_id=trace_id, hop=0, origin_id=nid))
                events.append(gen_status(cursor, nid, "FAILED", trace_id))
                active_traces[trace_id] = {"origin": nid, "severity_level": sev, "hops": {nid:0}, "last_ts": cursor, "cascade_id": trace_id}
                # schedule precursors for downstream nodes (so they show metric bumps prior to their failure)
                precs = schedule_precursors(nid, sev, cursor)
                for nnode, ts_spike, bumps in precs:
                    # insert a metric event at ts_spike (we'll append and sort later)
                    events.append({"ts": safe_iso(ts_spike), "node_id": nnode, "event_type":"metric", "metric": gen_metric_val(G.nodes[nnode].get("node_type","device"), extra=bumps)})
                explicit.remove(inj)
        # stochastic injections
        for s in stochastic:
            rate = s.get("inject_rate_per_minute", 0)
            chance_per_sec = rate / 60.0
            if random.random() < chance_per_sec:
                node = s["node_id"]
                sev = s.get("severity_level",1)
                trace_id = str(uuid.uuid4())
                events.append(gen_error(cursor, node, 120 + random.randint(0,30), "STOCH_FAIL", sev, trace_id, cascade_id=trace_id, hop=0, origin_id=node))
                events.append(gen_status(cursor, node, "DEGRADED", trace_id))
                active_traces[trace_id] = {"origin": node, "severity_level": sev, "hops": {node:0}, "last_ts": cursor, "cascade_id": trace_id}
                # schedule precursors
                for nnode, ts_spike, bumps in schedule_precursors(node, sev, cursor):
                    events.append({"ts": safe_iso(ts_spike), "node_id": nnode, "event_type":"metric", "metric": gen_metric_val(G.nodes[nnode].get("node_type","device"), extra=bumps)})
        # emit metrics normally (and include metric spikes we appended earlier)
        for n in nodes:
            if cursor >= next_emit[n]:
                # check if there is a pre-inserted metric event at this exact timestamp in events list
                # simpler: just emit usual metric with no extra unless there is a recent planned spike in events (rare)
                # We'll emit normal metric
                extra = {}
                metric = gen_metric_val(G.nodes[n].get("node_type","device"), extra=extra)
                events.append({"ts": safe_iso(cursor), "node_id": n, "event_type":"metric", "metric": metric})
                next_emit[n] = cursor + timedelta(seconds=node_period[n] + random.randint(0,2))
        # process active traces: attempt propagate along edges
        for tid, info in list(active_traces.items()):
            frontier_nodes = list(info["hops"].keys())
            for fnode in frontier_nodes:
                hop = info["hops"][fnode]
                for succ in G.successors(fnode):
                    if succ in info["hops"]:
                        continue
                    edge_weight = float(G[fnode][succ].get("weight",1.0))
                    p = compute_prop_prob(base_prop, severity_mult, hop_mult, info["severity_level"], hop, edge_weight)
                    if random.random() < p:
                        # create propagated error after delay
                        delay = max(0.2, random.gauss(2.0 + hop*1.0, 0.7))
                        ev_ts = cursor + timedelta(seconds=delay)
                        new_trace = str(uuid.uuid4())
                        # severity may attenuate or amplify: small random variation
                        child_sev = max(0, min(2, info["severity_level"] + (1 if random.random() < 0.2 else 0)))
                        events.append(gen_error(ev_ts, succ, 200 + random.randint(0,50), "PROPAGATED", child_sev, new_trace, parent_trace=tid, cascade_id=active_traces.get(tid,{}).get("cascade_id", tid), hop=hop+1, parent_node_id=fnode, origin_id=active_traces.get(tid,{}).get("origin")))
                        events.append(gen_status(ev_ts, succ, "DEGRADED" if child_sev<2 else "FAILED", new_trace, parent_trace=tid))
                        active_traces[new_trace] = {"origin": succ, "severity_level": child_sev, "hops": {succ: hop+1}, "last_ts": ev_ts, "cascade_id": active_traces.get(tid,{}).get("cascade_id", tid)}
                        # schedule precursors from this propagated node too
                        for nnode, ts_spike, bumps in schedule_precursors(succ, child_sev, ev_ts):
                            events.append({"ts": safe_iso(ts_spike), "node_id": nnode, "event_type":"metric", "metric": gen_metric_val(G.nodes[nnode].get("node_type","device"), extra=bumps)})
                        info["hops"][succ] = hop+1
            # autoproc attempt: may succeed and close traces
            if random.random() < 0.65 and info["hops"]:
                # pick random affected node in hops
                cand = random.choice(list(info["hops"].keys()))
                if random.random() < 0.8:
                    act_ts = cursor + timedelta(seconds=1.5)
                    events.append({"ts": safe_iso(act_ts), "node_id": cand, "event_type":"action", "action":{"actor":"autoproc","action_type":"restart"}})
                    events.append(gen_status(act_ts + timedelta(seconds=1), cand, "OK"))
                    # remove any active traces that include this node
                    for t2 in list(active_traces.keys()):
                        if cand == active_traces[t2]["origin"] or cand in active_traces[t2]["hops"]:
                            active_traces.pop(t2, None)
                else:
                    # failed recovery increases severity a bit
                    info["severity_level"] = min(2, info["severity_level"] + 1)
            # age out long traces
            if (cursor - info["last_ts"]).total_seconds() > 600:
                active_traces.pop(tid, None)
            else:
                info["last_ts"] = cursor
        cursor += timedelta(seconds=1)
    # normalize events: ensure ts string and trace_id present
    normalized = []
    for e in events:
        if "ts" not in e or e["ts"] is None:
            e["ts"] = safe_iso(BASE_TS)
        if "trace_id" not in e:
            e["trace_id"] = e.get("trace_id","") or ""
        normalized.append(e)
    # sort by ts ISO string and return
    normalized.sort(key=lambda x: x["ts"])
    return normalized
# ------------- plotting helpers -------------
def get_positions(G):
    return nx.spring_layout(G, seed=42)
def draw_graph(G, positions, status_map, selected_nodes=set(), small=True, active_edges=None):
    edge_x, edge_y = [], []
    for u,v in G.edges():
        x0,y0 = positions[u]; x1,y1 = positions[v]
        edge_x += [x0, x1, None]; edge_y += [y0, y1, None]
    edge_trace = go.Scatter(x=edge_x, y=edge_y, mode="lines", line=dict(width=1, color="#bbb"), hoverinfo="none")
    # overlay active propagation edges in red
    ax, ay = [], []
    active_edges = set(active_edges or [])
    for u,v in G.edges():
        if (u,v) in active_edges:
            x0,y0 = positions[u]; x1,y1 = positions[v]
            ax += [x0, x1, None]; ay += [y0, y1, None]
    active_edge_trace = go.Scatter(x=ax, y=ay, mode="lines", line=dict(width=3, color="#e74c3c"), hoverinfo="none")
    node_x, node_y, texts, sizes, colors = [], [], [], [], []
    for n in G.nodes():
        x,y = positions[n]
        node_x.append(x); node_y.append(y); texts.append(n)
        stt = status_map.get(n, "OK")
        if n in selected_nodes:
            # highlight selected nodes (for animation)
            colors.append("#9b59b6"); sizes.append(28 if not small else 18)
        elif stt == "FAILED":
            colors.append("#e74c3c"); sizes.append(26 if not small else 16)
        elif stt == "DEGRADED":
            colors.append("#f39c12"); sizes.append(20 if not small else 12)
        else:
            colors.append("#2ecc71"); sizes.append(14 if not small else 9)
    node_trace = go.Scatter(x=node_x, y=node_y, mode="markers+text",
                            marker=dict(size=sizes, color=colors, line=dict(width=1, color="#111")),
                            text=texts, textposition="bottom center", hoverinfo="text")
    fig = go.Figure(data=[edge_trace, active_edge_trace, node_trace])
    fig.update_layout(margin=dict(l=10,r=10,t=10,b=10), xaxis=dict(visible=False), yaxis=dict(visible=False), height=420 if small else 640)
    return fig
# ------------- UI -------------
st.set_page_config(layout="wide", page_title="Log Error Cascade Visualizer")
st.title("Rich Cascade Visualizer")
if "events" not in st.session_state:
    st.session_state["events"] = None
if "graph" not in st.session_state:
    st.session_state["graph"] = None
if "positions" not in st.session_state:
    st.session_state["positions"] = None
if "current_time" not in st.session_state:
    st.session_state["current_time"] = None
if "selected_trace_anim" not in st.session_state:
    st.session_state["selected_trace_anim"] = None
if "anim_index" not in st.session_state:
    st.session_state["anim_index"] = 0
left, right = st.columns([1,3])
with left:
    uploaded = st.file_uploader("Upload topology.json", type=["json"])
    local_path = st.text_input("or local path")
    topo_src = uploaded if uploaded is not None else (local_path if local_path.strip() else None)
    minutes = st.number_input("minutes", min_value=1, max_value=240, value=DEFAULT_MINUTES)
    st.markdown("### Propagation parameters")
    base_prop = st.slider("Base propagation probability", 0.0, 1.0, float(BASE_PROP_PROB), 0.01)
    severity_mult = st.slider("Severity multiplier", 0.0, 2.0, float(SEVERITY_MULT), 0.05)
    hop_mult = st.slider("Hop multiplier", 1.0, 2.5, float(HOP_MULT), 0.05)
    st.markdown("### Injection rate scaling")
    stoch_mult = st.slider("Stochastic rate x", 0.0, 200.0, 25.0, 0.5)
    force_demo = st.checkbox("Force at least one demo failure", value=True)
    seed = st.number_input("seed", min_value=0, max_value=999999, value=0)
    small = st.checkbox("compact graph", value=True)
    # injection controls (interactive)
    st.markdown("### Inject faults")
    inject_node = st.text_input("Node id to inject (leave blank to skip)")
    inject_sev = st.selectbox("Severity level", options=[0,1,2], index=2)
    inject_at = st.number_input("Inject at minute (0 for now)", min_value=0, max_value=minutes, value=0)
    if st.button("Schedule injection"):
        if not inject_node:
            st.warning("enter a node id")
        else:
            # attach to topology via fake faulty_nodes in UI run; store in session to include
            if "scheduled_faults" not in st.session_state:
                st.session_state["scheduled_faults"] = []
            st.session_state["scheduled_faults"].append({"node_id":inject_node,"inject_at_minute":int(inject_at),"severity_level":int(inject_sev)})
            st.success(f"Scheduled injection {inject_node} @ {inject_at}m severity {inject_sev}")
    # run simulation
    if st.button("Run simulation"):
        if topo_src is None:
            st.warning("supply topology upload or local path")
        else:
            try:
                G, faulty = load_topology(topo_src)
            except Exception as e:
                st.error("bad topology JSON: " + str(e))
            else:
                # merge scheduled_faults
                ui_faults = st.session_state.get("scheduled_faults", [])
                faulty = faulty + ui_faults
                try:
                    evts = simulate_rich(
                        G,
                        faulty,
                        minutes=int(minutes),
                        seed=int(seed),
                        base_prop=base_prop,
                        severity_mult=severity_mult,
                        hop_mult=hop_mult,
                        stochastic_multiplier=stoch_mult,
                        force_demo=force_demo,
                    )
                except Exception as se:
                    st.error("simulation failed: " + str(se))
                else:
                    df = pd.DataFrame(evts)
                    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
                    # fill missing columns
                    for col in ("node_id","trace_id","event_type"):
                        if col not in df.columns:
                            df[col] = ""
                        df[col] = df[col].fillna("")
                    df = df.sort_values("ts").reset_index(drop=True)
                    st.session_state["events"] = df
                    st.session_state["graph"] = nx.readwrite.json_graph.node_link_data(G)
                    st.session_state["positions"] = get_positions(G)
                    st.session_state["current_time"] = df["ts"].min().to_pydatetime().replace(tzinfo=None)
                    st.success(f"simulated {len(df)} events")
    # quick exports
    if st.button("Export JSONL"):
        if st.session_state.get("events") is None:
            st.warning("run simulation first")
        else:
            buf = io.StringIO()
            for rec in st.session_state["events"].to_dict(orient="records"):
                buf.write(json.dumps({k:v for k,v in rec.items() if pd.notna(v)}) + "\n")
            st.download_button("download", buf.getvalue().encode("utf-8"), file_name="events.jsonl")
with right:
    if st.session_state.get("events") is None:
        st.info("run simulation to visualize")
        st.stop()
    df = st.session_state["events"]
    G = nx.readwrite.json_graph.node_link_graph(st.session_state["graph"])
    positions = st.session_state["positions"]
    tmin = df["ts"].min().to_pydatetime().replace(tzinfo=None)
    tmax = df["ts"].max().to_pydatetime().replace(tzinfo=None)
    if st.session_state["current_time"] is None:
        st.session_state["current_time"] = tmin
    # timeline controls
    st.subheader("Timeline")
    step = st.number_input("step seconds", min_value=1, max_value=60, value=5)
    c1,c2,c3 = st.columns([1,1,1])
    with c1:
        if st.button("<< step back"):
            st.session_state["current_time"] = max(tmin, st.session_state["current_time"] - timedelta(seconds=int(step)))
    with c2:
        if st.button("step forward >>"):
            st.session_state["current_time"] = min(tmax, st.session_state["current_time"] + timedelta(seconds=int(step)))
    with c3:
        autoN = st.number_input("auto steps (limit)", min_value=1, max_value=200, value=6)
        if st.button("auto run (safe)"):
            for _ in range(autoN):
                st.session_state["current_time"] = min(tmax, st.session_state["current_time"] + timedelta(seconds=int(step)))
                # draw frame
                selected_ts = pd.Timestamp(st.session_state["current_time"]).tz_localize("UTC")
                df_time = df[df["ts"] <= selected_ts]
                status_map = {n:"OK" for n in G.nodes()}
                for _,r in df_time[df_time["event_type"]=="status"].iterrows():
                    nid = r.get("node_id")
                    if pd.isna(nid): continue
                    status_map[str(nid)] = r.get("status","OK")
                fig = draw_graph(G, positions, status_map, selected_nodes=set(), small=small)
                st.plotly_chart(fig, use_container_width=True)
                time.sleep(0.12)
            st.success("auto run done")
    # slider
    selected_time = st.slider("selected time", min_value=tmin, max_value=tmax, value=st.session_state["current_time"], format="YYYY-MM-DD HH:mm:ss")
    st.session_state["current_time"] = selected_time
    # build status map up to selected_time
    sel_pd = pd.Timestamp(selected_time).tz_localize("UTC")
    df_time = df[df["ts"] <= sel_pd]
    status_map = {n:"OK" for n in G.nodes()}
    statuses = df_time[df_time["event_type"]=="status"].sort_values("ts")
    for _, r in statuses.iterrows():
        nid = r.get("node_id")
        if pd.isna(nid): continue
        status_map[str(nid)] = r.get("status","OK")
    # graph: show selected_nodes highlight if animating a trace
    selected_nodes = set()
    if st.session_state.get("selected_trace_anim"):
        # while animating, we'll highlight the current node(s)
        traceid = st.session_state["selected_trace_anim"]
        trace_rows = df[df["trace_id"]==traceid].sort_values("ts")
        if not trace_rows.empty:
            idx = st.session_state.get("anim_index",0)
            if idx < len(trace_rows):
                selected_nodes.add(str(trace_rows.iloc[idx]["node_id"]))
    # compute active propagation edges up to selected time
    active_edges = set()
    errs = df_time[df_time["event_type"]=="error"]
    if not errs.empty:
        for _, r in errs.iterrows():
            err = r.get("error")
            if isinstance(err, dict) and err.get("name") in ("PROPAGATED","PROPAGATION"):
                u = r.get("parent_node_id")
                v = r.get("node_id")
                if pd.notna(u) and pd.notna(v) and G.has_edge(str(u), str(v)):
                    active_edges.add((str(u), str(v)))
    fig = draw_graph(G, positions, status_map, selected_nodes=selected_nodes, small=small, active_edges=active_edges)
    st.plotly_chart(fig, use_container_width=True)
    # node inspector
    st.subheader("Node inspector")
    node_sel = st.selectbox("node", options=list(G.nodes))
    recent = df[df["node_id"]==node_sel].sort_values("ts", ascending=False).head(80)
    st.dataframe(recent.reset_index(drop=True))
    metrics = df[(df["node_id"]==node_sel) & (df["event_type"]=="metric")].copy()
    if not metrics.empty:
        metrics["ts_naive"] = metrics["ts"].dt.tz_convert("UTC").dt.tz_localize(None)
        metrics_exp = pd.json_normalize(metrics["metric"])
        metrics_exp["ts"] = metrics["ts_naive"].reset_index(drop=True)
        metrics_exp = metrics_exp.set_index("ts")
        st.line_chart(metrics_exp)
=======
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



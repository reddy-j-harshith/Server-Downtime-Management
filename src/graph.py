from __future__ import annotations

import json
import operator
import re
from typing import Any, Dict, List, TypedDict, Annotated

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from src.config import get_llm
from src.agents.base import make_agent_prompt
from src.tools.actions import WORLD, ALL_TOOLS, WEB_TOOLS, DB_TOOLS
from src.ingest.parser import normalize_event
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from src.orchestrator import default_graph, infer_modules_from_event, execute_recovery
from src.tools.actions import purge_cache, scale_service, restart_service, open_incident, send_notification


class State(TypedDict, total=False):
    # Running conversation (accumulated)
    messages: Annotated[List[Any], operator.add]
    # Input event (log)
    event: Any
    # Router decision
    route: str
    # Collected proposals across events
    proposals: Annotated[List[Dict[str, Any]], operator.add]
    # Recorded actions/decisions for audit
    actions: Annotated[List[str], operator.add]
    # Step cap for ReAct loops
    loops: int


def _has_tool_calls(state: State) -> bool:
    msgs = state.get("messages", [])
    if not msgs:
        return False
    last = msgs[-1]
    return bool(getattr(last, "tool_calls", None))


def router(state: State) -> Dict:
    event = state.get("event")
    norm = normalize_event(event)
    text = f"{norm.get('source','')} {norm.get('channel','')} {norm.get('message','')}".lower()

    route = "unknown"
    # heuristic patterns
    if any(k in text for k in ["5xx", "http", "gateway", "nginx", "upstream", "timeout", "latency", "status"]):
        route = "web"
    if any(k in text for k in ["sql", "db", "postgres", "deadlock", "query", "connection pool", "vacuum"]):
        route = "db"
    if any(k in text for k in ["heartbeat", "online", "offline", "degraded"]):
        route = "status"
    if any(k in text for k in ["sensor", "ingestion"]):
        # favor module-specific handling if status contained
        route = "status" if ("heartbeat" in text or "online" in text or "offline" in text or "degraded" in text) else route

    # break ties using simple precedence if both hit
    if route == "unknown":
        # fallback to source field if present
        if isinstance(event, dict):
            route = event.get("source", "unknown")

    # still unknown? lightweight model classification
    if route not in {"web", "db", "status"}:
        try:
            llm = get_llm()
            resp = llm.invoke([
                ("system", "Classify this log event as 'web', 'db', or 'unknown'. Answer with one word only."),
                ("human", json.dumps(norm)),
            ])
            guess = str(getattr(resp, "content", "")).strip().lower()
            if guess in {"web", "db"}:
                route = guess
        except Exception:
            # no API key or offline; keep unknown
            pass

    if route not in {"web", "db", "status"}:
        route = "web"  # default to web for demo

    return {"route": route}


def web_agent(state: State) -> Dict:
    event = state.get("event")
    llm = get_llm().bind_tools(WEB_TOOLS)
    msgs = state.get("messages", [])
    # First turn: build prompt + context
    if not msgs:
        ctx = {"event": normalize_event(event), "world": WORLD.snapshot()}
        msgs = make_agent_prompt("web") + [HumanMessage(content=f"Context:\n{json.dumps(ctx)}")]
    try:
        ai = llm.invoke(msgs)
    except Exception:
        ai = AIMessage(content="")
    return {"messages": [ai], "loops": state.get("loops", 0) + 1}


def db_agent(state: State) -> Dict:
    event = state.get("event")
    llm = get_llm().bind_tools(DB_TOOLS)
    msgs = state.get("messages", [])
    if not msgs:
        ctx = {"event": normalize_event(event), "world": WORLD.snapshot()}
        msgs = make_agent_prompt("db") + [HumanMessage(content=f"Context:\n{json.dumps(ctx)}")]
    try:
        ai = llm.invoke(msgs)
    except Exception:
        ai = AIMessage(content="")
    return {"messages": [ai], "loops": state.get("loops", 0) + 1}


def coordinator(state: State) -> Dict:
    msgs = state.get("messages", [])
    text = str(getattr(msgs[-1], "content", "")) if msgs else ""
    proposals: List[Dict[str, Any]] = []

    # Try to extract a JSON proposals list from the final message
    try:
        # First attempt: the content is a raw JSON with proposals
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("proposals"), list):
            proposals = data["proposals"]
    except Exception:
        # Second attempt: find a proposals array within text
        m = re.search(r"\"proposals\"\s*:\s*(\[.*?\])", text, flags=re.S)
        if m:
            try:
                proposals = json.loads(m.group(1))
            except Exception:
                proposals = []

    actions: List[str] = []
    # Light policy: record P1/P2 proposals prominently
    for p in proposals:
        svc = p.get("service", "?")
        act = p.get("action", "?")
        pr = p.get("priority", 3)
        actions.append(f"proposal: [{svc}] {act} (p{pr})")

    # Heuristic fallback if the model didn't return proposals
    if not proposals:
        event = state.get("event")
        norm = normalize_event(event)
        route = state.get("route", "unknown")
        msg = (norm.get("message") or "").lower()
        is_error = any(k in msg for k in ["error", "timeout", "5xx", "deadlock"])
        fallback: List[Dict[str, Any]] = []
        if route == "web" and is_error:
            fallback.append({
                "service": "web",
                "action": "purge_cache",
                "rationale": "mitigate transient 5xx/timeout spikes",
                "priority": 2,
            })
            fallback.append({
                "service": "web",
                "action": "scale_service +1",
                "rationale": "add capacity during error surge",
                "priority": 3,
            })
        elif route == "db" and is_error:
            fallback.append({
                "service": "db",
                "action": "restart_service",
                "rationale": "clear stuck connections/deadlocks",
                "priority": 2,
            })
        if fallback:
            proposals = fallback
            actions.extend([f"fallback: [{p['service']}] {p['action']} (p{p['priority']})" for p in fallback])

    return {"proposals": proposals, "actions": actions}


def status_agent(state: State) -> Dict:
    """Update WORLD based on heartbeat/online-status events deterministically."""
    event = state.get("event")
    norm = normalize_event(event)
    msg = (norm.get("message") or "").lower()
    src = (norm.get("source") or "").lower()
    actions: List[str] = []

    # Module updates
    if src in ("sensor", "ingestion"):
        status = ""
        if "offline" in msg:
            status = "down"
        elif "degraded" in msg:
            status = "degraded"
        elif "online" in msg or "healthy" in msg:
            status = "healthy"
        if status:
            WORLD.modules[src] = status
            actions.append(f"module {src} -> {status}")

    # Service updates (web/db)
    if src in ("web", "db"):
        status = ""
        if "offline" in msg:
            status = "down"
        elif "degraded" in msg:
            status = "degraded"
        elif "online" in msg or "healthy" in msg:
            status = "healthy"
        if status and src in WORLD.services:
            WORLD.services[src].status = status
            actions.append(f"service {src} -> {status}")

    return {"actions": actions}


def executor(state: State) -> Dict:
    """Execute proposals by calling simulated tools and record results."""
    proposals = state.get("proposals", []) or []
    results: List[str] = []
    for p in proposals:
        svc = (p.get("service") or "").lower()
        act = (p.get("action") or "").lower()
        try:
            if svc in ("web", "db"):
                if act.startswith("purge_cache") and svc == "web":
                    results.append(purge_cache.invoke({"service": "web"}))
                elif act.startswith("scale_service") and svc == "web":
                    # parse delta from action e.g., "scale_service +1"
                    delta = 1
                    for tok in act.split():
                        if tok.startswith("+") or tok.startswith("-"):
                            try:
                                delta = int(tok)
                            except Exception:
                                pass
                    results.append(scale_service.invoke({"service": "web", "delta": delta}))
                elif act.startswith("restart_service"):
                    results.append(restart_service.invoke({"service": svc}))
                elif act.startswith("open_incident"):
                    results.append(open_incident.invoke({"summary": f"auto-open by executor for {svc}", "severity": "P2"}))
                elif act.startswith("notify"):
                    results.append(send_notification.invoke({"channel": "slack://alerts", "message": f"{svc}: {act}"}))
                else:
                    results.append(f"no-op for {svc}:{act}")
            else:
                results.append(f"unknown service {svc} for action {act}")
        except Exception as e:
            results.append(f"error executing {svc}:{act} -> {e}")

    return {"actions": results}


def orchestrator_node(state: State) -> Dict:
    """Infer failing modules and run bottom-up recovery on each event; append action logs."""
    event = state.get("event")
    g = default_graph()
    updates = infer_modules_from_event(event)
    actions: List[str] = []
    for mod, st in updates:
        g.mark(mod, st)
    failing = g.failing_modules()
    for target in failing:
        plan = g.recovery_plan(target)
        actions.append("plan: " + " -> ".join(plan))
        acts = execute_recovery(plan)
        actions.extend(acts)
    if actions:
        # include a compact snapshot marker
        actions.append("world:updated")
    return {"actions": actions}


def build_app():
    graph = StateGraph(State)

    # Nodes
    graph.add_node("router", router)
    graph.add_node("web_agent", web_agent)
    graph.add_node("db_agent", db_agent)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.add_node("status_agent", status_agent)
    graph.add_node("coordinator", coordinator)
    graph.add_node("executor", executor)
    graph.add_node("orchestrator", orchestrator_node)

    # Entry
    graph.set_entry_point("router")

    # Route to specific agent
    def to_web(state: State) -> bool:
        return state.get("route") == "web"

    def to_db(state: State) -> bool:
        return state.get("route") == "db"

    def to_status(state: State) -> bool:
        return state.get("route") == "status"

    graph.add_conditional_edges(
        "router",
        lambda s: "status" if to_status(s) else ("web" if to_web(s) else ("db" if to_db(s) else "web")),
        {"status": "status_agent", "web": "web_agent", "db": "db_agent"},
    )

    # ReAct loop per agent: agent -> (tools?) -> agent ... -> coordinator
    # Simple single-turn agent -> coordinator flow for runtime stability
    # Agent -> Tools? or Coordinator
    def need_tools_or_done(state: State):
        if state.get("loops", 0) > 4:
            return "coordinator"
        return "tools" if _has_tool_calls(state) else "coordinator"

    graph.add_conditional_edges("web_agent", need_tools_or_done, {"tools": "tools", "coordinator": "coordinator"})
    graph.add_conditional_edges("db_agent", need_tools_or_done, {"tools": "tools", "coordinator": "coordinator"})

    # After tools, go back to the appropriate agent
    graph.add_conditional_edges(
        "tools",
        lambda s: "web_agent" if s.get("route") == "web" else "db_agent",
        {"web_agent": "web_agent", "db_agent": "db_agent"},
    )

    # After coordination, execute actions and finish
    # Coordinator -> Executor -> Orchestrator -> END
    graph.add_edge("coordinator", "executor")
    graph.add_edge("executor", "orchestrator")

    # Finish
    graph.add_edge("orchestrator", END)

    app = graph.compile()
    return app

from __future__ import annotations

import json
from typing import Any, Dict

import argparse
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.graph import build_app
from src.logs.simulator import mixed_log_stream, as_strings, heartbeat_stream
from src.ingest.parser import read_file_stream
from src.orchestrator import default_graph, infer_modules_from_event, execute_recovery
from src.tools.actions import WORLD


console = Console()


def pretty_event(evt: Any) -> str:
    if isinstance(evt, (dict, list)):
        return json.dumps(evt, indent=2, ensure_ascii=False)
    return str(evt)


def main(steps: int = 50, file: str | None = None, orchestrate: bool = True):
    app = build_app()
    if file:
        stream = read_file_stream(file)
    else:
        # interleave heartbeats with mixed logs for a richer demo
        logs = list(as_strings(mixed_log_stream(steps=steps, seed=13, sleep=0.0)))
        beats = list(heartbeat_stream(steps=max(4, steps//2), seed=21, sleep=0.0))
        # simple weave: insert a heartbeat every ~N logs
        stream_list = []
        interval = max(3, len(logs)//max(1, len(beats)))
        bi = 0
        for i, ev in enumerate(logs):
            stream_list.append(ev)
            if bi < len(beats) and (i % interval == interval-1):
                stream_list.append(beats[bi])
                bi += 1
        stream = stream_list

    for idx, event in enumerate(stream, start=1):
        console.rule(f"log {idx}")
        console.print(Panel.fit(pretty_event(event), title="event", subtitle_align="left"))

        state_in: Dict[str, Any] = {"event": event, "messages": [], "proposals": [], "actions": [], "loops": 0}

        # Run the graph once for this event; show a compact summary of coordinator outputs
        out = app.invoke(state_in)

        # Display actions/proposals
        actions = out.get("actions", [])
        proposals = out.get("proposals", [])

        if actions:
            table = Table(title="decisions")
            table.add_column("type")
            table.add_column("value")
            for a in actions:
                table.add_row("action", a)
            console.print(table)

        if proposals:
            console.print(Panel.fit(json.dumps(proposals, indent=2), title="proposals"))

        # Graph-integrated orchestrator now runs inside the graph; print WORLD snapshot when actions occurred
        if out.get("actions"):
            console.print(Panel.fit(json.dumps(WORLD.snapshot(), indent=2), title="world snapshot"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Downtime management agentic demo")
    parser.add_argument("--file", type=str, required=False, help="Path to dataset file (JSONL/CSV/TSV)")
    parser.add_argument("--steps", type=int, default=30, help="Number of simulated steps when no file is provided")
    parser.add_argument("--no-orchestrate", action="store_true", help="Disable dependency-graph orchestrator")
    args = parser.parse_args()
    main(steps=args.steps, file=args.file, orchestrate=not args.no_orchestrate)

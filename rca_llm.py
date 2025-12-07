"""
Lightweight RCA helper.

This module provides `generate_llm_rca`, which produces a deterministic,
LLM-style Root Cause Analysis summary based on the orchestrator report,
events dataframe, and topology.

TODO: Replace the heuristic implementation with a real LLM call
      (e.g., OpenAI, Azure, etc.) while keeping the public API stable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd


def generate_llm_rca(
    report: Dict[str, Any],
    events: pd.DataFrame,
    topology: Dict[str, Any],
    predictive_results: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Generate a heuristic "LLM-style" RCA for the given simulation output.

    Parameters
    ----------
    report:
        The orchestrator report, typically `result["summary"]` and
        `result["details"]` wrapped into a dict.
    events:
        The events dataframe returned from the simulation.
    topology:
        The topology dict that was used for the simulation.

    Returns
    -------
    Dict[str, Any]
        A dictionary with:
          - "root_causes": list of node_ids considered likely root causes
          - "confidence": float in [0, 1]
          - "remediation": list of remediation suggestions
          - "markdown": human-readable RCA explanation in markdown
          - "meta": additional structured data (timeline, stats, etc.)
    """

    summary = report.get("summary", {})
    details = report.get("details", {})

    faults = details.get("faults", [])
    plans = details.get("plans", [])

    # Basic stats from events
    if not events.empty and "ts" in events.columns:
        t_min = int(events["ts"].min())
        t_max = int(events["ts"].max())
    else:
        t_min = 0
        t_max = 0

    # Nodes that experienced high CPU faults
    faulty_nodes = sorted({f.get("node_id") for f in faults if f.get("node_id")})

    # Heuristic: root causes are nodes that appear earliest in time
    root_cause_candidates = []
    if not events.empty and "node_id" in events.columns and "value" in events.columns:
        high_cpu = events[events["value"] > 80.0]
        first_fault_times = (
            high_cpu.groupby("node_id")["ts"].min().sort_values().to_dict()
        )
        # pick top 3 earliest spikes as root causes
        root_cause_candidates = list(first_fault_times.keys())[:3]

    # Simple confidence heuristic
    confidence = min(1.0, 0.3 + 0.1 * len(root_cause_candidates))

    remediation = [
        "Isolate traffic from suspected root-cause nodes.",
        "Restart or gracefully drain services on affected nodes.",
        "Increase monitoring granularity for upstream dependencies.",
        "Review recent deployments or configuration changes affecting root-cause nodes.",
    ]

    # Build markdown explanation
    lines = []
    lines.append("# Root Cause Analysis (Heuristic)")
    lines.append("")
    lines.append("## Timeline Overview")
    lines.append(f"- Simulation window: `{t_min}` → `{t_max}` (time units)")
    lines.append(f"- Total faults detected: **{len(faults)}**")
    lines.append(f"- Recovery plans executed: **{len(plans)}**")
    lines.append("")
    lines.append("## Probable Root Causes")
    if root_cause_candidates:
        lines.append(
            f"- Candidate root-cause nodes (earliest high CPU spikes): "
            + ", ".join(f"`{n}`" for n in root_cause_candidates)
        )
    else:
        lines.append("- No clear root-cause candidates identified from metrics.")
    lines.append(f"- Confidence score: **{confidence:.2f}**")
    lines.append("")
    lines.append("## Affected Nodes and Services")
    if faulty_nodes:
        lines.append(
            "- Nodes with detected high-severity CPU faults: "
            + ", ".join(f"`{n}`" for n in faulty_nodes)
        )
    else:
        lines.append("- No nodes reported high-severity CPU faults.")
    lines.append("")
    lines.append("## Step-by-Step Reasoning")
    lines.append("1. Inspect the CPU metric time-series for all nodes.")
    lines.append(
        "2. Identify nodes where CPU usage exceeds the failure threshold "
        "(e.g., > 80%)."
    )
    lines.append(
        "3. Sort these nodes by the timestamp of their first high-CPU event; "
        "earliest spikes are treated as potential root causes."
    )
    lines.append(
        "4. Correlate these nodes with the dependency graph (upstream/downstream "
        "relationships) to understand blast radius."
    )
    lines.append(
        "5. Recommend remediation focused first on suspected root-cause nodes, "
        "then on downstream dependents."
    )
    lines.append("")
    lines.append("## Remediation Suggestions")
    for r in remediation:
        lines.append(f"- {r}")

    predictive_meta = {}
    if predictive_results:
        lines.append("")
        lines.append("## Predicted High-Risk Nodes")
        for idx, res in enumerate(predictive_results[:5], start=1):
            node_id = res.get("node_id", "unknown")
            score = res.get("final_score", 0.0)
            ttf_val = res.get("ttf")
            ttf = "N/A" if ttf_val is None else f"{ttf_val:.2f}"
            lines.append(f"- #{idx} `{node_id}` — score: {score:.2f}, time-to-failure: {ttf}")
        predictive_meta = {
            "top_nodes": [
                {
                    "node_id": res.get("node_id"),
                    "final_score": res.get("final_score"),
                    "ttf": res.get("ttf"),
                }
                for res in predictive_results[:10]
            ]
        }

    markdown = "\n".join(lines)

    meta = {
        "time_window": {"start": t_min, "end": t_max},
        "fault_count": len(faults),
        "plan_count": len(plans),
        "faulty_nodes": faulty_nodes,
        "predictive": predictive_meta,
    }

    # Structured JSON output
    rca_json = {
        "root_causes": root_cause_candidates,
        "confidence": confidence,
        "remediation": remediation,
        "timeline": {
            "start": t_min,
            "end": t_max,
            "duration": t_max - t_min,
        },
        "affected_nodes": faulty_nodes,
        "fault_count": len(faults),
        "plan_count": len(plans),
        "meta": meta,
    }

    return {
        "root_causes": root_cause_candidates,
        "confidence": confidence,
        "remediation": remediation,
        "markdown": markdown,
        "json": rca_json,
        "meta": meta,
        "predictive": predictive_results or [],
    }



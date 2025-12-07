"""
LLM-powered Root Cause Analysis (RCA) agent.

This module exposes:

    - RCALlmAgent: an agent that calls an LLM to perform RCA
    - generate_llm_rca(...): backwards-compatible helper that instantiates
      the agent and returns its structured RCA output.

The public API is compatible with the previous heuristic implementation,
but the reasoning is now delegated to a real LLM instead of hard-coded rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import json
import os

import pandas as pd

try:
    # Requires: pip install openai
    from openai import OpenAI

    _HAS_OPENAI = True
except Exception:
    # We degrade gracefully to a heuristic fallback if the SDK is missing.
    OpenAI = None  # type: ignore
    _HAS_OPENAI = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class RCALlmConfig:
    """Configuration for the RCA LLM agent."""

    # OpenRouter-compatible model ID
    model: str = "meta-llama/llama-3-8b-instruct"
    temperature: float = 0.1
    max_events: int = 200  # limit rows sent to the LLM
    max_edges: int = 200   # limit topology edges sent to the LLM


# ---------------------------------------------------------------------------
# LLM Agent
# ---------------------------------------------------------------------------


class RCALlmAgent:
    """
    LLM-based RCA agent.

    Given:
      - orchestrator report (faults, plans, summary)
      - raw events dataframe
      - topology dict
      - optional predictive risk results

    it calls an LLM to:
      - identify likely root-cause nodes
      - assign a confidence score
      - describe reasoning and remediation steps
    """

    def __init__(self, config: Optional[RCALlmConfig] = None):
        self.config = config or RCALlmConfig()

        api_key = os.getenv("OPENROUTER_API_KEY")
        if _HAS_OPENAI and api_key:
            # OpenRouter: OpenAI-compatible client with different base_url
            self._client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            )
        else:
            self._client = None  # triggers heuristic fallback

    # ---------- public API ----------

    def run(
        self,
        report: Dict[str, Any],
        events: pd.DataFrame,
        topology: Dict[str, Any],
        predictive_results: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point: perform RCA and return structured result.
        """
        # Basic stats (used in meta + fallback)
        t_min, t_max = self._compute_time_window(events)
        faults = report.get("details", {}).get("faults", [])
        plans = report.get("details", {}).get("plans", [])
        faulty_nodes = sorted({f.get("node_id") for f in faults if f.get("node_id")})

        # If LLM cannot be used (no client), fall back to simple heuristic.
        if not self._client:
            rca = self._heuristic_fallback(events, faults)
        else:
            prompt = self._build_prompt(report, events, topology, predictive_results)
            rca = self._call_llm(prompt)

        # Ensure required fields exist
        root_causes = rca.get("root_causes", [])
        confidence = float(rca.get("confidence", 0.5))
        remediation = rca.get("remediation", [])
        explanation = rca.get("reasoning", "")

        # Build markdown for UI (like old implementation)
        markdown_lines: List[str] = []
        markdown_lines.append("# Root Cause Analysis (LLM-powered)")
        markdown_lines.append("")
        markdown_lines.append("## Timeline Overview")
        markdown_lines.append(f"- Simulation window: `{t_min}` → `{t_max}` (time units)")
        markdown_lines.append(f"- Total faults detected: **{len(faults)}**")
        markdown_lines.append(f"- Recovery plans executed: **{len(plans)}**")
        markdown_lines.append("")
        markdown_lines.append("## Probable Root Causes")
        if root_causes:
            markdown_lines.append(
                "- Candidate root-cause nodes (LLM reasoning): "
                + ", ".join(f"`{n}`" for n in root_causes)
            )
        else:
            markdown_lines.append("- No clear root-cause candidates identified.")
        markdown_lines.append(f"- Confidence score: **{confidence:.2f}**")
        markdown_lines.append("")
        markdown_lines.append("## Affected Nodes and Services")
        if faulty_nodes:
            markdown_lines.append(
                "- Nodes with detected high-severity faults: "
                + ", ".join(f"`{n}`" for n in faulty_nodes)
            )
        else:
            markdown_lines.append("- No nodes reported high-severity faults.")
        markdown_lines.append("")
        markdown_lines.append("## LLM Reasoning Summary")
        markdown_lines.append(explanation or "_No reasoning text returned from LLM._")
        markdown_lines.append("")
        markdown_lines.append("## Remediation Suggestions")
        if remediation:
            for r in remediation:
                markdown_lines.append(f"- {r}")
        else:
            markdown_lines.append("- No remediation suggestions provided.")

        # Add predictive meta for downstream consumers
        predictive_meta: Dict[str, Any] = {}
        if predictive_results:
            top_for_meta = predictive_results[:10]
            predictive_meta = {
                "top_nodes": [
                    {
                        "node_id": res.get("node_id"),
                        "final_score": res.get("final_score"),
                        "ttf": res.get("ttf"),
                    }
                    for res in top_for_meta
                ]
            }

            # Also show them in markdown for convenience
            markdown_lines.append("")
            markdown_lines.append("## Predicted High-Risk Nodes")
            for idx, res in enumerate(predictive_results[:5], start=1):
                node_id = res.get("node_id", "unknown")
                score = res.get("final_score", 0.0)
                ttf_val = res.get("ttf")
                ttf_str = "N/A" if ttf_val is None else f"{ttf_val:.2f}"
                markdown_lines.append(
                    f"- #{idx} `{node_id}` — score: {score:.2f}, time-to-failure: {ttf_str}"
                )

        markdown = "\n".join(markdown_lines)

        meta = {
            "time_window": {"start": t_min, "end": t_max},
            "fault_count": len(faults),
            "plan_count": len(plans),
            "faulty_nodes": faulty_nodes,
            "predictive": predictive_meta,
            "raw_llm_rca": rca,
        }

        rca_json = {
            "root_causes": root_causes,
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
            "root_causes": root_causes,
            "confidence": confidence,
            "remediation": remediation,
            "markdown": markdown,
            "json": rca_json,
            "meta": meta,
            "predictive": predictive_results or [],
        }

    # ---------- internal helpers ----------

    def _compute_time_window(self, events: pd.DataFrame) -> Tuple[int, int]:
        if not events.empty and "ts" in events.columns:
            return int(events["ts"].min()), int(events["ts"].max())
        return 0, 0

    def _build_prompt(
        self,
        report: Dict[str, Any],
        events: pd.DataFrame,
        topology: Dict[str, Any],
        predictive_results: Optional[List[Dict[str, Any]]],
    ) -> str:
        """
        Build a compact but information-rich prompt for the LLM.

        We keep the shape simple: summary, faults, plans, a truncated snapshot
        of the events and edges, and top predictive-risk nodes.
        """
        summary = report.get("summary", {})
        details = report.get("details", {})
        faults = details.get("faults", [])
        plans = details.get("plans", [])

        # Truncate events for token control
        events_view = events.copy()
        cols = [c for c in ["ts", "node_id", "value"] if c in events_view.columns]
        if cols:
            events_view = events_view[cols]
        events_view = events_view.sort_values("ts").head(self.config.max_events)

        # Truncate edges
        edges = topology.get("edges", [])[: self.config.max_edges]

        # Truncate predictive results
        predictive_view = (predictive_results or [])[:10]

        return f"""
You are an expert Site Reliability Engineer performing Root Cause Analysis
for a simulated distributed system outage.

You are given:
  - A dependency graph of services/devices/sensors.
  - A list of injected faults and recovery plans.
  - Observed CPU metric events over time for each node.
  - Predictive risk scores per node (higher = more likely to fail / cause issues).

Your job:
  1. Identify which node(s) are the TRUE root causes of the incident, not just victims.
  2. Use both temporal ordering (who failed first) AND graph structure (who is upstream).
  3. Leverage predictive risk scores to break ties or strengthen hypotheses.
  4. Return a concise JSON object describing your findings.

System summary:
{json.dumps(summary, indent=2)}

Faults (from orchestrator):
{json.dumps(faults, indent=2)}

Recovery plans executed:
{json.dumps(plans, indent=2)}

Dependency edges (from -> to):
{json.dumps(edges, indent=2)}

CPU metric events (truncated):
{events_view.to_string(index=False)}

Predictive risk results (truncated top-N):
{json.dumps(predictive_view, indent=2)}

Now, reason step-by-step (internally) about:
  - Which nodes show the earliest and strongest abnormal CPU behavior.
  - How faults could propagate downstream along the dependency graph.
  - Which nodes are likely just impacted dependents vs actual initiators.
  - Whether the predictive risk scores support your hypothesis.

Then respond ONLY with valid JSON in this exact schema:

{{
  "root_causes": ["n-0005", "n-0026"],  // list of node_ids, 1-3 entries
  "confidence": 0.0,                    // float in [0,1]
  "reasoning": "short explanation in plain language",
  "remediation": [
    "first remediation step",
    "second remediation step"
  ]
}}
"""
    def _call_llm(self, prompt: str) -> Dict[str, Any]:
        """
        Call the underlying LLM and parse its JSON response.

        The model *should* return raw JSON, but we also handle cases where it
        wraps the JSON in extra text like 'Here is the JSON:'.
        """
        try:
            resp = self._client.chat.completions.create(
                model=self.config.model,
                temperature=self.config.temperature,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a precise, JSON-structured Root Cause Analysis "
                            "assistant. Always respond with ONLY a single JSON object, "
                            "with no backticks and no extra text before or after."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )

            content = resp.choices[0].message.content or ""

            # 1) First try to parse the whole thing as JSON
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass

            # 2) If that fails, try to extract the first {...} block
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                snippet = content[start : end + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    pass  # fall through to fallback below

            # 3) Final fallback: treat the whole content as a plain reasoning string
            return {
                "root_causes": [],
                "confidence": 0.5,
                "reasoning": content.strip(),
                "remediation": [],
            }

        except Exception as ex:
            # On any error, fall back to a generic low-confidence result.
            return {
                "root_causes": [],
                "confidence": 0.3,
                "reasoning": f"LLM call failed: {ex}",
                "remediation": [],
            }


    def _heuristic_fallback(
        self, events: pd.DataFrame, faults: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Lightweight fallback that approximates the old heuristic behavior if
        an LLM cannot be used (no API key / offline).
        """
        root_cause_candidates: List[str] = []

        if (
            not events.empty
            and "node_id" in events.columns
            and "value" in events.columns
            and "ts" in events.columns
        ):
            high_cpu = events[events["value"] > 80.0]
            if not high_cpu.empty:
                first_fault_times = (
                    high_cpu.groupby("node_id")["ts"].min().sort_values().to_dict()
                )
                root_cause_candidates = list(first_fault_times.keys())[:3]

        confidence = min(1.0, 0.3 + 0.1 * len(root_cause_candidates))

        remediation = [
            "Isolate traffic from suspected root-cause nodes.",
            "Restart or gracefully drain services on affected nodes.",
            "Increase monitoring granularity for upstream dependencies.",
            "Review recent deployments or configuration changes affecting root-cause nodes.",
        ]

        return {
            "root_causes": root_cause_candidates,
            "confidence": confidence,
            "reasoning": "Heuristic fallback used because LLM client or API key was not available.",
            "remediation": remediation,
        }


# ---------------------------------------------------------------------------
# Backwards-compatible helper
# ---------------------------------------------------------------------------


def generate_llm_rca(
    report: Dict[str, Any],
    events: pd.DataFrame,
    topology: Dict[str, Any],
    predictive_results: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Backwards-compatible wrapper that matches the old signature.

    Existing code in the UI or tests that calls `generate_llm_rca(...)`
    does not need to change. Under the hood, this now uses RCALlmAgent.
    """
    agent = RCALlmAgent()
    return agent.run(report, events, topology, predictive_results)

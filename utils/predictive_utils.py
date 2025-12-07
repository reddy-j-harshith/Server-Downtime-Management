"""
Utility helpers for predictive risk outputs.
"""

from __future__ import annotations

import json
from typing import Iterable, Mapping


def results_to_markdown(results: Iterable[Mapping]) -> str:
    """
    Convert predictive results into a markdown table.
    """
    rows = list(results)
    if not rows:
        return "_No predictive risk results available._"

    header = "| Rank | Node | Final Score | Time-To-Failure |\n| --- | --- | --- | --- |\n"
    lines = []
    for idx, row in enumerate(rows, start=1):
        node = row.get("node_id", "-")
        score = f"{row.get('final_score', 0.0):.2f}"
        ttf_val = row.get("ttf")
        ttf = "N/A" if ttf_val is None else f"{ttf_val:.2f}"
        lines.append(f"| {idx} | {node} | {score} | {ttf} |")
    return header + "\n".join(lines)


def download_json_bytes(obj) -> bytes:
    """
    Serialize an object to JSON bytes suitable for Streamlit download buttons.
    """
    return json.dumps(obj, indent=2, default=str).encode("utf-8")


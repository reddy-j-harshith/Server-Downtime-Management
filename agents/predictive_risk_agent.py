"""
Predictive risk scoring agent.

Complexity: O(N * M) where N = nodes and M = per-node samples (handled via
vectorized pandas operations where possible). Tuning knobs include EWMA span,
slope scaling, and impact blend to balance predictive sensitivity vs. blast
radius emphasis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import networkx as nx
import numpy as np
import pandas as pd

from .base_agent import BaseAgent


@dataclass
class NodeRisk:
    """Container for node-level predictive risk outputs."""

    node_id: str
    last: Optional[float]
    slope: float
    ttf: Optional[float]
    score: float
    impact: float
    final_score: float

    def to_dict(self) -> Dict[str, Optional[float]]:
        return {
            "node_id": self.node_id,
            "last": self.last,
            "slope": self.slope,
            "ttf": self.ttf,
            "score": self.score,
            "impact": self.impact,
            "final_score": self.final_score,
        }


class TrendPredictor:
    """Utility class for computing trends and extrapolations."""

    @staticmethod
    def ewma(series: pd.Series, span: float) -> Optional[float]:
        if series.empty:
            return None
        return series.ewm(span=max(span, 1.0), adjust=False).mean().iloc[-1]

    @staticmethod
    def slope(series: pd.Series) -> float:
        if series.empty or len(series) < 2:
            return 0.0
        x = np.arange(len(series), dtype=float)
        y = series.astype(float).to_numpy()
        coeffs = np.polyfit(x, y, 1)  # type: ignore[arg-type]
        return float(coeffs[0])

    @staticmethod
    def predict_time_to_threshold(
        last: Optional[float], slope_value: float, threshold: float
    ) -> Optional[float]:
        if last is None or slope_value <= 0:
            return None
        delta = threshold - last
        if delta <= 0:
            return 0.0
        return delta / slope_value


class PredictiveRiskAgent(BaseAgent):
    """
    Agent that forecasts CPU breaches and ranks nodes by impact-adjusted risk.
    """

    def __init__(
        self, cpu_threshold: float = 90.0, span: float = 4.0, slope_scale: float = 1.0
    ):
        super().__init__("predictive_risk")
        self.cpu_threshold = cpu_threshold
        self.span = span
        self.slope_scale = slope_scale
        self.impact_blend = 0.35
        self.predictor = TrendPredictor()

    def start(self):  # pragma: no cover - lifecycle noop
        pass

    def stop(self):  # pragma: no cover - lifecycle noop
        pass

    def _ensure_dataframe(self, events_df: pd.DataFrame) -> pd.DataFrame:
        df = events_df.copy()
        if "node_id" not in df.columns:
            df["node_id"] = ""
        if "value" not in df.columns:
            df["value"] = 0.0
        df = df[df["node_id"].astype(str).str.len() > 0]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna(subset=["value"])

    def score_node(self, events_df: pd.DataFrame, node_id: str) -> Dict[str, Optional[float]]:
        df = self._ensure_dataframe(events_df)
        node_df = df[df["node_id"] == node_id].sort_index()
        if node_df.empty:
            return {
                "node_id": node_id,
                "last": None,
                "slope": 0.0,
                "ttf": None,
                "base_score": 0.0,
            }

        series = node_df["value"]
        ewma_val = self.predictor.ewma(series, self.span)
        slope_val = self.predictor.slope(series) * self.slope_scale
        ttf = self.predictor.predict_time_to_threshold(ewma_val, slope_val, self.cpu_threshold)
        normalized_last = 0.0 if ewma_val is None else min(max(ewma_val / self.cpu_threshold, 0.0), 1.5)
        slope_component = min(max(slope_val / 100.0, 0.0), 1.0)
        ttf_component = 0.0 if ttf is None else max(0.0, min(1.0, 1.0 / (1.0 + ttf)))
        base_score = min(1.0, 0.5 * normalized_last + 0.3 * slope_component + 0.2 * ttf_component)

        return {
            "node_id": node_id,
            "last": ewma_val,
            "slope": slope_val,
            "ttf": ttf,
            "base_score": base_score,
        }

    def compute_impact_scores(self, node_ids: Iterable[str], dep_graph: nx.DiGraph) -> Dict[str, float]:
        impact_scores: Dict[str, float] = {}
        total_nodes = max(len(dep_graph.nodes), 1)
        for node in node_ids:
            descendants = nx.descendants(dep_graph, node) if dep_graph.has_node(node) else set()
            impact_scores[node] = min(1.0, len(descendants) / total_nodes)
        return impact_scores

    def evaluate(self, events_df: pd.DataFrame, dep_graph) -> List[Dict[str, Optional[float]]]:
        df = self._ensure_dataframe(events_df)
        if df.empty:
            return []

        grouped = df.groupby("node_id")
        scores: List[NodeRisk] = []
        graph = getattr(dep_graph, "G", dep_graph)
        node_list = grouped.size().index.tolist()
        impact_map = self.compute_impact_scores(node_list, graph)

        for node_id in node_list:
            node_series = grouped.get_group(node_id)["value"]
            last_val = self.predictor.ewma(node_series, self.span)
            slope_val = self.predictor.slope(node_series) * self.slope_scale
            ttf = self.predictor.predict_time_to_threshold(last_val, slope_val, self.cpu_threshold)
            normalized_last = 0.0 if last_val is None else min(max(last_val / self.cpu_threshold, 0.0), 1.5)
            slope_component = min(max(slope_val / 100.0, 0.0), 1.0)
            ttf_component = 0.0 if ttf is None else max(0.0, min(1.0, 1.0 / (1.0 + ttf)))
            base_score = min(1.0, 0.5 * normalized_last + 0.3 * slope_component + 0.2 * ttf_component)
            impact = impact_map.get(node_id, 0.0)
            final_score = min(1.0, (1.0 - self.impact_blend) * base_score + self.impact_blend * impact)
            scores.append(
                NodeRisk(
                    node_id=node_id,
                    last=last_val,
                    slope=slope_val,
                    ttf=ttf,
                    score=base_score,
                    impact=impact,
                    final_score=final_score,
                )
            )

        return [s.to_dict() for s in sorted(scores, key=lambda x: x.final_score, reverse=True)]

    def topk(self, events_df: pd.DataFrame, dep_graph, k: int = 10) -> List[Dict[str, Optional[float]]]:
        evaluated = self.evaluate(events_df, dep_graph)
        if not evaluated:
            return []
        return evaluated[: max(1, k)]


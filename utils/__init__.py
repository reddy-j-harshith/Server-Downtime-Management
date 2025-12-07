"""
Utility helpers for visualization and data conversion.

Currently contains helpers to convert a NetworkX graph into a Plotly figure
for use in the Streamlit UI.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Set

import networkx as nx
import plotly.graph_objects as go


def nx_to_plotly_figure(
    G: nx.DiGraph,
    faulty_nodes: Optional[Sequence[str]] = None,
    rca_nodes: Optional[Sequence[str]] = None,
    risk_nodes: Optional[Sequence[str]] = None,
) -> go.Figure:
    """
    Convert a NetworkX directed graph into a Plotly figure.

    Parameters
    ----------
    G:
        The NetworkX directed graph representing the dependency topology.
    faulty_nodes:
        Optional iterable of node_ids that should be highlighted as faulty.
    rca_nodes:
        Optional iterable of node_ids that should be highlighted as root-cause
        candidates.

    Returns
    -------
    go.Figure
        A Plotly figure with nodes and edges visualized.
    """

    faulty: Set[str] = set(faulty_nodes or [])
    rca: Set[str] = set(rca_nodes or [])
    risk: Set[str] = set(risk_nodes or [])

    if len(G.nodes) == 0:
        return go.Figure()

    pos = nx.spring_layout(G, seed=42)

    # Build edge coordinates
    edge_x: List[float] = []
    edge_y: List[float] = []
    for src, dst in G.edges():
        x0, y0 = pos[src]
        x1, y1 = pos[dst]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        line=dict(width=1, color="#888"),
        hoverinfo="none",
        mode="lines",
    )

    # Separate nodes into categories
    def make_node_trace(nodes: Iterable[str], color: str, name: str, size: int = 14) -> go.Scatter:
        xs: List[float] = []
        ys: List[float] = []
        texts: List[str] = []
        for n in nodes:
            x, y = pos[n]
            xs.append(x)
            ys.append(y)
            meta = G.nodes[n]
            label = f"{n} ({meta.get('node_type', 'unknown')})"
            texts.append(label)
        return go.Scatter(
            x=xs,
            y=ys,
            mode="markers",
            hoverinfo="text",
            marker=dict(size=size, color=color, line_width=1),
            name=name,
            text=texts,
        )

    normal_nodes = [n for n in G.nodes if n not in faulty and n not in rca and n not in risk]
    faulty_only = [n for n in G.nodes if n in faulty and n not in rca and n not in risk]
    rca_only = [n for n in G.nodes if n in rca]
    risk_only = [n for n in G.nodes if n in risk and n not in rca]

    traces: List[go.Scatter] = [edge_trace]
    if normal_nodes:
        traces.append(make_node_trace(normal_nodes, "#1f77b4", "Normal"))
    if faulty_only:
        traces.append(make_node_trace(faulty_only, "#d62728", "Faulty"))
    if rca_only:
        traces.append(make_node_trace(rca_only, "#9467bd", "RCA candidates", size=18))
    if risk_only:
        traces.append(make_node_trace(risk_only, "#ff7f0e", "Predictive risk", size=20))

    fig = go.Figure(data=traces)
    fig.update_layout(
        showlegend=True,
        hovermode="closest",
        margin=dict(b=20, l=5, r=5, t=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        legend=dict(bgcolor="rgba(0,0,0,0.5)", font=dict(color="white")),
    )
    fig.update_xaxes(showticklabels=False, gridcolor="rgba(255,255,255,0.1)")
    fig.update_yaxes(showticklabels=False, gridcolor="rgba(255,255,255,0.1)")

    return fig


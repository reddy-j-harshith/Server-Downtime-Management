import pandas as pd

from agents.predictive_risk_agent import PredictiveRiskAgent, TrendPredictor


def build_events():
    data = []
    for node_id, base in zip(["a", "b", "c"], [50, 60, 70]):
        for idx in range(5):
            data.append({"node_id": node_id, "value": base + idx * 5})
    return pd.DataFrame(data)


def test_trend_predictor_slope_positive_for_increasing_series():
    df = build_events()
    series = df[df["node_id"] == "a"]["value"]
    slope = TrendPredictor.slope(series)
    assert slope > 0


def test_score_node_returns_values():
    df = build_events()
    agent = PredictiveRiskAgent(cpu_threshold=80.0)
    score = agent.score_node(df, "a")
    assert score["node_id"] == "a"
    assert isinstance(score["base_score"], float)
    assert score["ttf"] is None or score["ttf"] >= 0


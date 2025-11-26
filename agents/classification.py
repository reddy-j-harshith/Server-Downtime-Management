from .base_agent import BaseAgent

class ClassificationAgent(BaseAgent):
    def classify_fault(self, fault: dict, context: dict) -> dict:
        # simple heuristic classification
        return {
            "failure_type": "resource_exhaustion",
            "severity": fault.get("severity", "unknown"),
            "recovery_strategy": "restart",
            "priority_score": 80
        }

    def start(self): pass
    def stop(self): pass

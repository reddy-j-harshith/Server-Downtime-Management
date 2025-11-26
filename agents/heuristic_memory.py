from .base_agent import BaseAgent
import json

class HeuristicMemoryAgent(BaseAgent):
    def __init__(self, name="heuristic_memory", kb_file=None):
        super().__init__(name)
        self.kb = []
        self.kb_file = kb_file

    def store_case(self, case):
        self.kb.append(case)

    def recommend_strategy(self, fault):
        # naive: return most frequent strategy
        if not self.kb:
            return {"strategy": "isolate_and_restart", "confidence": 0.5}
        return {"strategy": self.kb[-1].get("strategy", "restart"), "confidence":0.7}

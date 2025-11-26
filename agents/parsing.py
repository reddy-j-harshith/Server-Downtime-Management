from .base_agent import BaseAgent

class ParsingAgent(BaseAgent):
    def parse_event(self, raw_event: dict) -> dict:
        # normalize fields, timestamps, metric names, etc.
        parsed = dict(raw_event)
        # example normalization
        parsed.setdefault("timestamp", parsed.get("ts"))
        return parsed

    def extract_topology_relationships(self, parsed_event: dict):
        # stub
        return []
    def start(self): pass
    def stop(self): pass

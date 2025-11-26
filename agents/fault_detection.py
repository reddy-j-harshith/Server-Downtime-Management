from .base_agent import BaseAgent

class FaultDetectionAgent(BaseAgent):
    def __init__(self, name="fault_detector", cpu_threshold=80.0):
        super().__init__(name)
        self.cpu_threshold = cpu_threshold
        self.active_faults = []

    def detect(self, parsed_event: dict):
        # simple rule: if cpu > threshold -> create fault
        if parsed_event.get("metric") == "cpu" and parsed_event.get("value", 0) > self.cpu_threshold:
            fault = {"node_id": parsed_event["node_id"], "severity": "high"}
            self.active_faults.append(fault)
            return fault
        return None

    def get_active_faults(self):
        return self.active_faults

    def start(self): pass
    def stop(self): pass

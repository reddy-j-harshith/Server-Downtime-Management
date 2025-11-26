from .ingestion import IngestionAgent
from .parsing import ParsingAgent
from .fault_detection import FaultDetectionAgent
from .dep_graph import DependencyGraphAgent
from .classification import ClassificationAgent
from .planner import ReActPlanner
from .domain_recovery import DomainRecoveryAgent
from .status_memory import StatusMemoryAgent
from .heuristic_memory import HeuristicMemoryAgent

class MultiAgentOrchestrator:
    def __init__(self, topology_graph=None):
        self.ingestion = IngestionAgent()
        self.parsing = ParsingAgent()
        self.fault_detector = FaultDetectionAgent()
        self.dep_graph = DependencyGraphAgent()
        self.classifier = ClassificationAgent()
        self.status_memory = StatusMemoryAgent()
        self.heuristic_memory = HeuristicMemoryAgent()
        self.planner = ReActPlanner(self.dep_graph, self.status_memory)
        self.domain = DomainRecoveryAgent()

        self.detected_faults = []
        self.executed_plans = []

    def process_events_from_dataframe(self, df):
        self.ingestion.ingest_from_dataframe(df)
        batch = self.ingestion.get_batch(1000)
        for raw in batch:
            parsed = self.parsing.parse_event(raw)
            self.dep_graph.update_from_event(parsed)
            self.status_memory.update_status(parsed.get("node_id"), {"last_seen": parsed.get("timestamp")})
            fault = self.fault_detector.detect(parsed)
            if fault:
                fault['node_id'] = parsed.get('node_id')
                self.detected_faults.append(fault)
                classified = self.classifier.classify_fault(fault, self.status_memory.get_node_context(fault['node_id']))
                classified.update(fault)
                plan = self.planner.plan_recovery(classified)
                exec_result = self.domain.execute_plan(plan)
                self.executed_plans.append({"plan": plan, "result": exec_result})
                self.heuristic_memory.store_case({"fault": fault, "plan": plan, "strategy": classified.get("recovery_strategy")})

    def generate_report(self):
        return {
            "summary": {
                "faults_detected": len(self.detected_faults),
                "plans_executed": len(self.executed_plans),
                "success_rate": sum(1 for p in self.executed_plans if p["result"]["success"]) / max(1, len(self.executed_plans))
            },
            "details": {
                "faults": self.detected_faults,
                "plans": self.executed_plans
            }
        }

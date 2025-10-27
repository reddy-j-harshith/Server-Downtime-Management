# Downtime Management Demo (Agentic AI with LangGraph + Mistral)

This is a compact, professional demo of an agentic environment for server downtime management. It simulates mixed web/database logs, routes them to specialized agents (web, db), reasons via ReAct (Reason + Action with tools), and produces coordinated proposals/decisions.

## Why this use case is legitimate
- Goal: reduce MTTR during incidents by automating first-response triage.
- Inputs: noisy logs from multiple services (web, db) in varied formats.
- Agents: domain-specific responders (Web SRE, DB SRE) that inspect metrics and take safe actions (restart, scale, purge cache, notify, incident).
- Outcome: a realistic, moderate-scope system that a college project can explain and demo without being toy-level.

## Architecture (at a glance)

```
logs (mixed, any format)
  -> Router (heuristics + LLM fallback)
     -> Web Agent (ReAct + tools)
     -> DB Agent  (ReAct + tools)
        [ToolNode executes actions]
     -> Coordinator summarizes proposals/decisions
```

- ReAct loop per agent: think -> call tools (metrics, actions) -> observe -> repeat (capped) -> propose.
- Tools are simulated but update an in-memory "world" for consistent metrics and effects.

## Setup

1) Python 3.10+
2) Create `.env` at project root:

```
MISTRAL_API_KEY=your_mistral_key_here
MISTRAL_MODEL=mistral-large-latest
```

3) Install dependencies (Windows PowerShell):

```powershell
pip install -r requirements.txt
```

## Run the simulation

```powershell
python -m src.run_simulation
```

You’ll see a stream of events and the agents’ final proposals/decisions per event.

### Run with your dataset file later

If you have a log dataset (JSONL, CSV, or TSV), ensure it has (or can be mapped to) headers like timestamp/ts/time, source, message, channel. Then run:

```powershell
python -m src.run_simulation --file "path\to\your\logs.csv"
```

The parser normalizes fields to { ts, source, message, channel } automatically. Unknown formats fall back to treating each line as a raw message.

## Files
- `src/logs/simulator.py`: generates realistic mixed logs (web/db) with occasional outages.
- `src/tools/actions.py`: simulated monitoring/actuation tools + in-memory world state.
- `src/agents/*`: reusable ReAct prompts for web/db.
- `src/graph.py`: LangGraph wiring (router -> agent -> tools -> coordinator).
- `src/config.py`: environment and LLM factory.
- `src/run_simulation.py`: CLI runner with Rich output.

## Notes
- If `MISTRAL_API_KEY` isn’t set, classification and reasoning calls will be skipped/failed, but the simulator still runs; set the key for full behavior.
- This is deliberately focused (two services) and clear for a demo; you can extend with more agents (infra, cache, queue) by copying patterns.

```text
Tip: Look in tools/actions.py to see exactly what agents can do and how "world" metrics change after actions.
```

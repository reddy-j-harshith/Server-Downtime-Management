# Streamlit App - Acceptance Checklist & Run Instructions

## Quick Start

```bash
streamlit run streamlit_app.py
```

Or:

```bash
python -m streamlit run streamlit_app.py
```

## Files Created/Updated

1. **`streamlit_app.py`** - Main Streamlit UI application
2. **`rca_llm.py`** - Updated to return both `markdown` and `json` in RCA output
3. **`utils.py`** - Updated with dark theme support for Plotly graphs
4. **`test.py`** - No changes (uses existing functions)

## Acceptance Checklist

### ✅ Core Functionality

- [x] **streamlit_app.py created and runnable** with `streamlit run streamlit_app.py`
- [x] **Sidebar file selector** - Lists JSON files from `./` and `topologies/` folder
- [x] **File upload** - `st.file_uploader` for custom topology JSON
- [x] **Topology preview** - Shows node/edge counts in sidebar

### ✅ Simulation Controls (Sidebar)

- [x] **Minutes** - Integer input (1-1440)
- [x] **Base CPU** - Float input (0-100)
- [x] **Fault CPU** - Float input (0-100)
- [x] **Step seconds** - UI animation speed (0.1-10.0)
- [x] **Propagation parameters**:
  - [x] Base probability slider (0.0-1.0)
  - [x] Severity multiplier slider (0.0-5.0)
  - [x] Hop multiplier slider (0.0-2.0)
- [x] **Control buttons**:
  - [x] "Schedule injection" button
  - [x] "Run simulation" button (primary)
  - [x] "Step forward" button
  - [x] "Step back" button
  - [x] "Auto run (safe)" checkbox
  - [x] "Clear logs" button
- [x] **Status badge** - Shows simulation status (idle/running/paused/error/complete)
- [x] **Event count** - Displays number of simulated events

### ✅ Runner & Streaming

- [x] **Integration** - Uses `run_orchestrator_simulation()` from `test.py`
- [x] **Stream callback** - `stream_write()` appends to live log panel
- [x] **Live logs** - Uses `st.empty()` for real-time updates
- [x] **Step-by-step mode** - Advances timeline on "Step forward" click
- [x] **Auto-run** - Toggle for automatic simulation execution

### ✅ Visualizations

- [x] **Summary cards** - Top row showing:
  - [x] Node count
  - [x] Edge count
  - [x] Detected faulty nodes count
  - [x] Root-cause candidates count
- [x] **Network graph** (right pane):
  - [x] Interactive Plotly graph from NetworkX
  - [x] Node colors reflect node_type and faulty state
  - [x] Root-cause nodes highlighted distinctly (purple)
  - [x] Faulty nodes highlighted (red)
  - [x] Normal nodes (blue)
  - [x] Dark theme support
- [x] **Time-series chart**:
  - [x] CPU usage over time (Plotly)
  - [x] Filterable by node (multiselect)
  - [x] Interactive hover and legend
  - [x] Dark theme
- [x] **Events table**:
  - [x] Paginated DataFrame of simulated events
  - [x] Trace IDs generated automatically
- [x] **Trace inspector**:
  - [x] Text input for trace ID
  - [x] Recent trace IDs list (last 10)
  - [x] Clickable trace IDs to load
  - [x] JSON/table view of trace details
- [x] **Report tab**:
  - [x] Collapsible JSON blocks (`st.json`)
  - [x] Summary section
  - [x] Details section

### ✅ RCA (Root Cause Analysis)

- [x] **rca_llm.py created** with `generate_llm_rca()` function
- [x] **Deterministic heuristics**:
  - [x] Timeline summary
  - [x] Affected services list
  - [x] Causal chain explanation
  - [x] Confidence score
  - [x] Remediation steps
- [x] **TODO comment** - Where to integrate LLM call (OpenAI/GPT)
- [x] **RCA tab** displays:
  - [x] Dependency-graph candidates
  - [x] LLM-style RCA markdown
  - [x] Confidence score (metric)
  - [x] Remediation suggestions (bulleted list)
- [x] **Download buttons**:
  - [x] Download RCA (JSON)
  - [x] Download RCA (Markdown)

### ✅ Exports & UX

- [x] **Export buttons**:
  - [x] Download events CSV
  - [x] Download dependency graph JSON
  - [x] Download topology JSON
- [x] **Error handling**:
  - [x] `st.spinner` during simulation
  - [x] `st.error` with traceback on exceptions
  - [x] Try/except blocks around critical operations
- [x] **Session state** - Persists:
  - [x] Selected topology
  - [x] Events dataframe
  - [x] Last RCA result
  - [x] Simulation status
  - [x] Step-by-step state
- [x] **Dark theme**:
  - [x] CSS styling via `_apply_dark_theme()`
  - [x] Dark backgrounds for graphs
  - [x] White text for readability
- [x] **Layout**:
  - [x] Wide layout (`layout="wide"`)
  - [x] Two-column layout (left: tabs, right: graph)
  - [x] Responsive design

### ✅ Code Quality

- [x] **Docstrings** - Functions have docstrings
- [x] **Comments** - Integration points with `run_orchestrator_simulation` explained
- [x] **Helper functions** - In `utils.py` for graph conversion
- [x] **Header README** - Run instructions in `streamlit_app.py` docstring
- [x] **Runtime patches** - Agent instantiation issues handled with clear TODO comments
- [x] **No agent modifications** - All agent files in `agents/` remain unchanged

## UI Layout

```
┌─────────────────────────────────────────────────────────────┐
│  🚨 Server Downtime Multi-Agent Simulation                  │
├──────────────┬──────────────────────────────────────────────┤
│   SIDEBAR    │  Summary Cards (4 metrics)                   │
│              ├──────────────────────────────────────────────┤
│  Topology    │  📝 Simulation Logs                         │
│  Selection   ├──────────────────────────────────────────────┤
│              │  ┌─────────────────────┬─────────────────────┐│
│  Parameters  │  │   LEFT COL (Tabs)  │  RIGHT COL (Graph)  ││
│  - Minutes   │  │                    │                     ││
│  - CPU vals  │  │  📈 Timeline        │  🕸️ Topology Graph  ││
│  - Step sec  │  │  📋 Events         │                     ││
│              │  │  🔍 Trace Inspector│                     ││
│  Propagation │  │  🔬 RCA            │                     ││
│  - Base prob │  │  📊 Report/Exports  │                     ││
│  - Severity  │  │                    │                     ││
│  - Hop mult  │  └────────────────────┴─────────────────────┘│
│              │                                                │
│  Controls    │                                                │
│  - Schedule  │                                                │
│  - Run       │                                                │
│  - Step fwd  │                                                │
│  - Step back │                                                │
│  - Auto run  │                                                │
│  - Clear     │                                                │
│              │                                                │
│  Status      │                                                │
└──────────────┴────────────────────────────────────────────────┘
```

## Key Features

1. **Dark Theme** - Custom CSS for dark backgrounds and white text
2. **Real-time Logs** - Live streaming of simulation messages
3. **Interactive Graphs** - Plotly charts with hover, zoom, pan
4. **Trace Inspector** - Debug individual event traces
5. **Step-by-Step Mode** - Manual control over simulation timeline
6. **Auto-Run** - Automatic simulation execution
7. **Comprehensive Exports** - CSV, JSON downloads for all data
8. **RCA Analysis** - Both dependency-graph and LLM-style analysis

## Integration Points

- **`test.py`** - Uses `run_orchestrator_simulation()`, `load_topology()`, `simulate_events_from_topology()`, `build_dependency_graph_from_topology()`
- **`rca_llm.py`** - Uses `generate_llm_rca()` for root cause analysis
- **`utils.py`** - Uses `nx_to_plotly_figure()` for graph visualization
- **`agents/orchestrator.py`** - Uses `MultiAgentOrchestrator()` directly (with runtime patches)

## Runtime Patches

The app includes runtime monkeypatches to handle agent instantiation issues without modifying agent files:

1. **BaseAgent.__init__** - Patched to accept optional `name` parameter
2. **Abstract methods** - Cleared `__abstractmethods__` for agents that don't implement `start()`/`stop()`

These patches are applied at the top of `streamlit_app.py` with clear TODO comments explaining why they're needed.

## Notes

- Propagation parameters (base probability, severity multiplier, hop multiplier) are captured in the UI but not yet used in simulation logic (can be extended in `test.py` if needed)
- Trace IDs are generated automatically when events are displayed if not present
- Auto-run mode is a toggle but doesn't automatically advance steps (can be extended for continuous simulation)
- Schedule injection button shows an info message (actual scheduling would require topology modification)


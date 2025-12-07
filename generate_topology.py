"""
generate_topology.py

Usage examples:
  # Generate a 100-node topology and write top_100.json
  python generate_topology.py --n 100 --faults 5 --out top_100.json

  # Generate a very large test (1100 nodes)
  python generate_topology.py --n 1100 --faults 25 --out top_1100.json
"""
import json
import random
import argparse
from pathlib import Path

def make_node(node_idx: int, layer_count: int):
    """
    Returns a dict for a node.
    node types chosen roughly: sensors (30%), devices (50%), services (20%)
    """
    if random.random() < 0.3:
        node_type = "sensor"
    elif random.random() < 0.5:
        node_type = "device"
    else:
        node_type = "service"

    # spread nodes across layers 1..layer_count
    layer = f"L{random.randint(1, layer_count)}"
    return {
        "id": f"n-{node_idx:04d}",
        "node_type": node_type,
        "layer": layer,
        "meta": {"loc": f"rack{random.randint(1,200)}", "hw": random.choice(["x86","arm","fpga"])}
    }

def make_edges(nodes, average_out=2, prefer_upward=True):
    """
    Create directed edges between nodes. average_out controls sparsity.
    prefer_upward: if True, bias edges from lower-numbered layers to higher-numbered layers.
    """
    edges = []
    N = len(nodes)
    # map id -> layer index
    layer_index = {}
    for n in nodes:
        # parse Lx -> integer
        li = int(n["layer"].lstrip("L"))
        layer_index[n["id"]] = li

    for i, n in enumerate(nodes):
        src = n["id"]
        # number of out-edges for this node (Poisson-ish)
        k = max(1, int(random.gauss(average_out, 1)))
        candidates = []
        # prefer connecting to nodes in higher layers (if prefer_upward) else random
        for m in nodes:
            if m["id"] == src:
                continue
            if prefer_upward:
                if layer_index[m["id"]] >= layer_index[src]:
                    candidates.append(m["id"])
            else:
                candidates.append(m["id"])
        if not candidates:
            continue
        # choose up to k unique targets
        targets = set(random.choices(candidates, k=min(k, len(candidates))))
        for t in targets:
            edges.append({"from": src, "to": t, "weight": round(random.random(), 2)})
    # dedupe (in case)
    unique = []
    seen = set()
    for e in edges:
        key = (e["from"], e["to"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    return unique

def pick_faulty(nodes, n_faults: int, minutes: int):
    """
    Choose n_faults nodes to be faulty; assign random injection minute between 0 and minutes-1.
    """
    faulty = []
    if n_faults <= 0:
        return faulty
    picks = random.sample(nodes, min(n_faults, len(nodes)))
    for p in picks:
        faulty.append({
            "node_id": p["id"],
            "inject_at_minute": random.randint(0, max(0, minutes-1)),
            # optional severity field
            "severity": random.choice(["high", "medium", "low"])
        })
    return faulty

def build_topology(n_nodes=100, layer_count=3, avg_out=2, n_faults=5, minutes=10):
    nodes = [make_node(i+1, layer_count) for i in range(n_nodes)]
    edges = make_edges(nodes, average_out=avg_out, prefer_upward=True)
    faulty = pick_faulty(nodes, n_faults, minutes)
    topo = {
        "nodes": nodes,
        "edges": edges,
        "faulty_nodes": faulty,
        "meta": {"generated_by": "generate_topology.py", "n_nodes": n_nodes}
    }
    return topo

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=100, help="number of nodes")
    p.add_argument("--layers", type=int, default=3, help="number of layers (L1...Lx)")
    p.add_argument("--avg-out", type=float, default=2.0, help="average outgoing edges per node")
    p.add_argument("--faults", type=int, default=5, help="number of faulty nodes to inject")
    p.add_argument("--minutes", type=int, default=6, help="simulate minutes (used for inject times)")
    p.add_argument("--out", type=str, default="topology_generated.json", help="output filename")
    args = p.parse_args()

    topo = build_topology(n_nodes=args.n, layer_count=args.layers, avg_out=args.avg_out,
                          n_faults=args.faults, minutes=args.minutes)
    outpath = Path(args.out)
    outpath.write_text(json.dumps(topo, indent=2))
    print(f"Wrote {outpath} ({len(topo['nodes'])} nodes, {len(topo['edges'])} edges, {len(topo['faulty_nodes'])} faults)")

if __name__ == "__main__":
    main()

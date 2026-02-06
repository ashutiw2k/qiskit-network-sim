#!/usr/bin/env python3
"""Generate a job list of (code, path) pairs for cloud runs."""

from __future__ import annotations

import argparse
import json
import os
import pickle
import random
from itertools import combinations
from typing import Dict, List

import networkx as nx

try:
    from cloud_runs.codes import AVAILABLE_CODES
    from cloud_runs.common import AVAILABLE_BACKENDS
except ImportError:
    from codes import AVAILABLE_CODES
    from common import AVAILABLE_BACKENDS


def _all_paths_edges(G: nx.Graph, min_hops: int, max_hops: int) -> List[List[int]]:
    """Return all simple paths filtered by edge hops."""
    all_paths: List[List[int]] = []
    for pair in combinations(G.nodes, 2):
        paths = nx.all_simple_paths(G, source=pair[0], target=pair[1], cutoff=max_hops + 1)
        for p in paths:
            hops = len(p) - 1
            if hops < min_hops or hops > max_hops:
                continue
            all_paths.append(p)
    return all_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate job list for cloud runs.")
    parser.add_argument("--graph", required=True, help="Path to network graph pickle file")
    parser.add_argument(
        "--codes",
        nargs="*",
        default=None,
        choices=list(AVAILABLE_CODES.keys()),
        help="Codes to include (default: all available codes)",
    )
    parser.add_argument("--min-hops", type=int, default=2, help="Minimum path length in edges")
    parser.add_argument("--max-hops", type=int, default=3, help="Maximum path length in edges")
    parser.add_argument(
        "--max-per-code",
        type=int,
        default=None,
        help="Optional limit on number of paths per code",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed for deterministic sampling",
    )
    parser.add_argument(
        "--backend",
        type=str,
        default="heron_r2",
        choices=AVAILABLE_BACKENDS,
        help="Fake backend to simulate against (default: heron_r2 = FakeFez)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON file for jobs",
    )

    args = parser.parse_args()

    with open(args.graph, "rb") as f:
        graph = pickle.load(f)

    codes = args.codes or list(AVAILABLE_CODES.keys())

    all_paths = _all_paths_edges(graph, args.min_hops, args.max_hops)
    all_paths.sort(key=lambda p: (len(p), p))

    rng = random.Random(args.seed)

    jobs = []
    for code in codes:
        paths = list(all_paths)
        if args.max_per_code is not None and len(paths) > args.max_per_code:
            rng.shuffle(paths)
            paths = paths[: args.max_per_code]
            paths.sort(key=lambda p: (len(p), p))
        for p in paths:
            jobs.append({"code": code, "path": p})

    payload: Dict[str, object] = {
        "graph_path": args.graph,
        "backend": args.backend,
        "min_hops": args.min_hops,
        "max_hops": args.max_hops,
        "codes": codes,
        "jobs": jobs,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Wrote {len(jobs)} jobs to {args.output}")


if __name__ == "__main__":
    main()

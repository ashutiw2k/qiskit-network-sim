#!/usr/bin/env python3
"""Merge per-job measurement files into measurements.pkl per code (ES protocol)."""

from __future__ import annotations

import argparse
import glob
import json
import os
import pickle
import sys
from datetime import datetime
from typing import Any, Dict, List, Tuple


def _load_job_data(files: List[str]) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """Load job files and extract measurements and timing data.

    Returns:
        Tuple of (measurements list, timing_records list)
    """
    measurements = []
    timing_records = []

    for path in files:
        with open(path, "rb") as f:
            data = pickle.load(f)

        # Handle both old format (just measurement) and new format (dict with timing)
        if isinstance(data, dict) and "measurement" in data:
            measurements.append(data["measurement"])
            if "timing" in data:
                timing_records.append(data["timing"])
        else:
            # Old format - just the measurement object
            measurements.append(data)

    return measurements, timing_records


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs:.1f}s"


def _print_timing_summary(timing_records: List[Dict[str, Any]], code: str) -> Dict[str, Any]:
    """Print and return timing summary for a code."""
    if not timing_records:
        return {}

    elapsed_times = [t["elapsed_seconds"] for t in timing_records]
    start_times = [t["start_time"] for t in timing_records]
    end_times = [t["end_time"] for t in timing_records]

    total_cpu_time = sum(elapsed_times)
    avg_time = total_cpu_time / len(elapsed_times)
    min_time = min(elapsed_times)
    max_time = max(elapsed_times)

    # Wall clock time (from first job start to last job end)
    wall_clock_time = max(end_times) - min(start_times)

    # Parallelization efficiency
    efficiency = (total_cpu_time / wall_clock_time * 100) if wall_clock_time > 0 else 0

    summary = {
        "code": code,
        "protocol": "entanglement_swapping",
        "num_jobs": len(timing_records),
        "total_cpu_time_seconds": total_cpu_time,
        "wall_clock_time_seconds": wall_clock_time,
        "avg_job_time_seconds": avg_time,
        "min_job_time_seconds": min_time,
        "max_job_time_seconds": max_time,
        "parallelization_efficiency_percent": efficiency,
        "first_job_start": datetime.fromtimestamp(min(start_times)).isoformat(),
        "last_job_end": datetime.fromtimestamp(max(end_times)).isoformat(),
    }

    print(f"\n{'='*60}")
    print(f"TIMING SUMMARY (ES): {code}")
    print(f"{'='*60}")
    print(f"  Jobs completed:        {len(timing_records)}")
    print(f"  Wall clock time:       {_format_duration(wall_clock_time)}")
    print(f"  Total CPU time:        {_format_duration(total_cpu_time)}")
    print(f"  Avg time per job:      {_format_duration(avg_time)}")
    print(f"  Min job time:          {_format_duration(min_time)}")
    print(f"  Max job time:          {_format_duration(max_time)}")
    print(f"  Parallel efficiency:   {efficiency:.1f}%")
    print(f"  First job started:     {summary['first_job_start']}")
    print(f"  Last job finished:     {summary['last_job_end']}")
    print(f"{'='*60}")

    return summary


def main() -> None:
    # Ensure repo root is on sys.path so pickle can resolve cloud_runs_es.* classes.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    parser = argparse.ArgumentParser(description="Merge per-job ES outputs into measurements.pkl.")
    parser.add_argument("--input-dir", required=True, help="Base output directory")
    parser.add_argument("--code", default=None, help="Code to merge (default: all subdirs)")
    parser.add_argument(
        "--output-name",
        default="measurements.pkl",
        help="Output filename inside each code directory",
    )

    args = parser.parse_args()

    if args.code:
        codes = [args.code]
    else:
        codes = [d for d in os.listdir(args.input_dir) if os.path.isdir(os.path.join(args.input_dir, d))]

    all_timing_summaries = []

    for code in codes:
        code_dir = os.path.join(args.input_dir, code)
        files = sorted(glob.glob(os.path.join(code_dir, "job_*.pkl")))
        if not files:
            print(f"No job files found in {code_dir}, skipping")
            continue

        measurements, timing_records = _load_job_data(files)

        # Save measurements
        out_path = os.path.join(code_dir, args.output_name)
        with open(out_path, "wb") as f:
            pickle.dump(measurements, f)
        print(f"Wrote {out_path} with {len(measurements)} measurements")

        # Print and collect timing summary
        if timing_records:
            summary = _print_timing_summary(timing_records, code)
            all_timing_summaries.append(summary)

            # Save timing details to JSON for later analysis
            timing_path = os.path.join(code_dir, "timing_summary.json")
            with open(timing_path, "w") as f:
                json.dump({"summary": summary, "jobs": timing_records}, f, indent=2)
            print(f"Wrote timing data to {timing_path}")

    # Print overall summary if multiple codes
    if len(all_timing_summaries) > 1:
        total_jobs = sum(s["num_jobs"] for s in all_timing_summaries)
        total_cpu = sum(s["total_cpu_time_seconds"] for s in all_timing_summaries)
        all_starts = [s["first_job_start"] for s in all_timing_summaries]
        all_ends = [s["last_job_end"] for s in all_timing_summaries]

        print(f"\n{'='*60}")
        print("OVERALL TIMING SUMMARY (ALL CODES - ES)")
        print(f"{'='*60}")
        print(f"  Total jobs:            {total_jobs}")
        print(f"  Total CPU time:        {_format_duration(total_cpu)}")
        print(f"  Earliest start:        {min(all_starts)}")
        print(f"  Latest finish:         {max(all_ends)}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run the existing 960-job workload for each supplied Fez calibration JSON."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import pickle
import shutil
import subprocess
import sys
import time
import uuid

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
import numpy as np
from qiskit import QuantumCircuit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cloud_runs.common import BACKEND_MAP, build_calibrated_simulator

# Reuse the worker and infrastructure from the completed calibration run.
REGION = "us-east-2"
BUCKET = "qiskit-net-sim-ashutosh"
QUEUE = "qec-job-queue"
JOB_DEFINITION = "qec-syndrome-job:21"
IMAGE_DIGEST = "sha256:280cf1bc4f55433abbd17476281ac330486be8416edefbdc36c1849b687743b9"
SHOTS = 2000
POLL_SECONDS = 10
ACTIVE_DATES = 4
MANIFEST = ROOT / "cloud_runs/jobs/jobs_heron_r2.json"


def save_state(out, state):
    temporary = out / "run.json.tmp"
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(out / "run.json")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(noise_location, out):
    files = sorted(noise_location.glob("*.json")) if noise_location.is_dir() else [noise_location]
    if not files:
        raise ValueError(f"No calibration JSON files in {noise_location}")
    snapshots = []
    for index, file in enumerate(files, 1):
        _, metadata = build_calibrated_simulator(file, QuantumCircuit(2), BACKEND_MAP["heron_r2"][1])
        day = metadata["requested_date_utc"]
        if metadata["backend"] != "ibm_fez" or not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError(f"Expected an ibm_fez snapshot with requested_date_utc YYYY-MM-DD: {file}")
        snapshots.append({"date": day, "sha256": metadata["sha256"], "source": str(file.resolve())})
        if index % 25 == 0 or index == len(files):
            print(f"Checked calibration files: {index}/{len(files)}", flush=True)
    snapshots.sort(key=lambda entry: entry["date"])
    if len({entry["date"] for entry in snapshots}) != len(snapshots):
        raise ValueError("Each calibration file must have a distinct requested_date_utc")
    manifest = json.loads(MANIFEST.read_text())
    jobs = manifest["jobs"]
    if len(jobs) != 960 or {job["code"] for job in jobs} != {"513", "713", "823", "913"}:
        raise ValueError("Expected the existing 960-job, four-code Heron-R2 manifest")
    graph = ROOT / manifest["graph_path"]
    identity = {"calibrations": [{k:entry[k] for k in ("date", "sha256")} for entry in snapshots],
                "manifest_sha256": sha256(MANIFEST), "graph_sha256": sha256(graph), "shots": SHOTS}
    state_file = out / "run.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        if state.get("format") != "history-runner-v1" or state.get("inputs") != identity:
            raise ValueError("Output directory belongs to a different run/input set; use its original inputs or a new directory")
        return state, jobs
    if any(path.name != ".history.lock" for path in out.iterdir()):
        raise ValueError("Use an empty output directory, or resume a directory containing this runner's run.json")
    inputs = out / "inputs"
    inputs.mkdir()
    shutil.copyfile(MANIFEST, inputs / "jobs.json")
    shutil.copyfile(graph, inputs / "graph.pkl")
    for entry in snapshots:
        entry["file"] = f"inputs/ibm_fez_{entry['date']}.json"
        shutil.copyfile(entry["source"], out / entry["file"])
        if sha256(out / entry["file"]) != entry["sha256"]:
            raise ValueError(f"Calibration changed while copying: {entry['source']}")
        entry["status"] = "ready"
    run_id = datetime.now(timezone.utc).strftime("history-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    state = {"format": "history-runner-v1", "run_id": run_id, "inputs": identity,
             "region": REGION, "bucket": BUCKET, "queue": QUEUE, "job_definition": JOB_DEFINITION,
             "prefix": f"calibration_runs/{run_id}", "created_utc": datetime.now(timezone.utc).isoformat(),
             "jobs_per_date": len(jobs), "total_jobs": len(jobs)*len(snapshots),
             "total_shots": SHOTS*len(jobs)*len(snapshots), "status": "prepared", "dates": snapshots}
    save_state(out, state)
    return state, jobs


def upload_common_inputs(s3, out, state):
    if state.get("common_inputs_uploaded"):
        return
    for name, expected in [("jobs.json", state["inputs"]["manifest_sha256"]),
                           ("graph.pkl", state["inputs"]["graph_sha256"])]:
        path = out / "inputs" / name
        if sha256(path) != expected:
            raise ValueError(f"Saved input changed: {path}")
        s3.upload_file(str(path), state["bucket"], f"{state['prefix']}/inputs/{name}")
    state["common_inputs_uploaded"] = True
    save_state(out, state)


def submit_date(batch, s3, out, state, entry):
    name = f"{state['run_id']}-{entry['date']}"
    if entry["status"] == "submitting":
        # SubmitJob has no idempotency token. Recover an uncertain response by
        # name; never blindly submit again after a timeout or interruption.
        matches = [job for page in batch.get_paginator("list_jobs").paginate(
            jobQueue=state["queue"], filters=[{"name": "JOB_NAME", "values": [name]}])
            for job in page.get("jobSummaryList", []) if job["jobName"] == name]
        if len(matches) != 1:
            raise RuntimeError(f"Submission outcome unresolved for {name}: found {len(matches)} jobs. "
                               "No replacement submitted; inspect this job name in AWS and retry later.")
        entry["job_id"] = matches[0]["jobId"]
    else:
        path = out / entry["file"]
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"Saved calibration changed: {path}")
        s3.upload_file(str(path), state["bucket"], f"{state['prefix']}/{entry['file']}")
        uri = f"s3://{state['bucket']}/{state['prefix']}"
        environment = {"S3_JOBS": f"{uri}/inputs/jobs.json", "S3_GRAPH": f"{uri}/inputs/graph.pkl",
                       "S3_CALIBRATION": f"{uri}/{entry['file']}",
                       "S3_OUTPUT_PREFIX": f"{uri}/outputs/{entry['date']}/", "SHOTS": str(SHOTS),
                       "BACKEND": "heron_r2", "OPT_LEVEL": "1", "INITIAL_STATE": "0", "JOB_INDEX_OFFSET": "0"}
        entry["status"] = "submitting"
        save_state(out, state)
        response = batch.submit_job(jobName=name, jobQueue=state["queue"], jobDefinition=state["job_definition"],
                                    arrayProperties={"size": state["jobs_per_date"]},
                                    containerOverrides={"environment": [{"name":k,"value":v} for k,v in environment.items()]})
        entry["job_id"] = response["jobId"]
    entry["status"] = "submitted"
    save_state(out, state)
    print(f"Submitted {entry['date']}: {entry['job_id']} ({state['jobs_per_date']} jobs)", flush=True)


def check_result(path, index, job, entry):
    with path.open("rb") as stream:
        result = pickle.load(stream)
    timing, calibration, measurement = result["timing"], result["calibration"], result["measurement"]
    histogram = measurement.histogram
    valid = (timing["job_index"] == index and timing["code_type"] == job["code"] and timing["path"] == job["path"]
             and measurement.code_type == job["code"]
             and measurement.path_edges == list(zip(job["path"], job["path"][1:]))
             and result["shots"] == SHOTS and calibration["sha256"] == entry["sha256"]
             and calibration["requested_date_utc"] == entry["date"] and calibration["backend"] == "ibm_fez"
             and histogram.shape == ({"513":16, "713":64, "823":64, "913":256}[job["code"]],)
             and np.all(np.isfinite(histogram)) and np.all(histogram >= 0)
             and np.all(histogram == np.floor(histogram)) and float(histogram.sum()) == SHOTS)
    if not valid:
        raise ValueError(f"Wrong or incomplete result: {path}")


def collect_date(s3, out, state, entry, jobs, downloaded, pool):
    prefix = f"{state['prefix']}/outputs/{entry['date']}/"
    expected = {f"{job['code']}/job_{index}.pkl": (index, job) for index, job in enumerate(jobs)}
    pending = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=state["bucket"], Prefix=prefix):
        for obj in page.get("Contents", []):
            relative = obj["Key"][len(prefix):]
            if relative not in expected:
                raise ValueError(f"Unexpected result object: {obj['Key']}")
            if relative not in downloaded:
                pending.append((relative, obj))

    def fetch(item):
        relative, obj = item
        path = out / "results" / entry["date"] / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size != obj["Size"]:
            temporary = path.with_suffix(".download")
            s3.download_file(state["bucket"], obj["Key"], str(temporary), Config=TransferConfig(use_threads=False))
            if temporary.stat().st_size != obj["Size"]:
                raise ValueError(f"Incomplete download: {obj['Key']}")
            temporary.replace(path)
        index, job = expected[relative]
        check_result(path, index, job, entry)
        return relative

    for relative in pool.map(fetch, pending):
        downloaded.add(relative)
    entry["downloaded"] = len(downloaded)


def monitor(batch, s3, out, state, jobs):
    downloaded = {}
    missing_polls = {}
    started = time.monotonic()
    state["status"] = "running"
    save_state(out, state)
    with ThreadPoolExecutor(max_workers=8) as pool:
        while True:
            for entry in state["dates"]:
                if entry["status"] == "submitting":
                    submit_date(batch, s3, out, state, entry)
            active = [entry for entry in state["dates"] if entry["status"] == "submitted"]
            for entry in state["dates"]:
                if len(active) >= ACTIVE_DATES:
                    break
                if entry["status"] == "ready":
                    submit_date(batch, s3, out, state, entry)
                    active.append(entry)
            if not active:
                break
            response = batch.describe_jobs(jobs=[entry["job_id"] for entry in active])
            details = {job["jobId"]: job for job in response["jobs"]}
            for entry in active:
                job = details.get(entry["job_id"])
                if job is None:
                    missing_polls[entry["job_id"]] = missing_polls.get(entry["job_id"], 0) + 1
                    if missing_polls[entry["job_id"]] >= 6:
                        raise RuntimeError(f"AWS returned no status for saved job {entry['job_id']} after six polls")
                    print(f"{entry['date']} waiting for AWS to return job status", flush=True)
                    continue
                missing_polls.pop(entry["job_id"], None)
                summary = job.get("arrayProperties", {}).get("statusSummary", {})
                entry["aws_status"] = job["status"]
                entry["counts"] = summary
                collect_date(s3, out, state, entry, jobs, downloaded.setdefault(entry["date"], set()), pool)
                print(f"{entry['date']} succeeded={summary.get('SUCCEEDED', 0)}/{len(jobs)} "
                      f"running={summary.get('RUNNING', 0)} failed={summary.get('FAILED', 0)} "
                      f"downloaded={entry['downloaded']}/{len(jobs)}", flush=True)
                if job["status"] == "FAILED":
                    entry["status"] = "failed"
                    entry["reason"] = job.get("statusReason", "AWS array failed")
                    entry["failed_jobs"] = [child for page in batch.get_paginator("list_jobs").paginate(
                        arrayJobId=entry["job_id"], jobStatus="FAILED") for child in page.get("jobSummaryList", [])]
                elif job["status"] == "SUCCEEDED":
                    if entry["downloaded"] != len(jobs):
                        raise RuntimeError(f"AWS reports success but {entry['date']} has only {entry['downloaded']}/{len(jobs)} outputs")
                    with (out / f"merge-{entry['date']}.log").open("w") as log:
                        subprocess.run([sys.executable, "-B", str(ROOT / "cloud_runs/merge_results.py"),
                                        "--input-dir", str(out / "results" / entry["date"])],
                                       stdout=log, stderr=subprocess.STDOUT, check=True)
                    entry["status"] = "complete"
                    entry["completed_utc"] = datetime.now(timezone.utc).isoformat()
                    print(f"Merged {entry['date']}: results/{entry['date']}/<code>/measurements.pkl", flush=True)
                save_state(out, state)
            complete = sum(entry["status"] == "complete" for entry in state["dates"])
            collected = sum(entry.get("downloaded", 0) for entry in state["dates"])
            print(f"TOTAL dates={complete}/{len(state['dates'])} downloaded={collected}/{state['total_jobs']} "
                  f"session_elapsed={time.monotonic()-started:.0f}s", flush=True)
            if any(entry["status"] == "submitted" for entry in state["dates"]):
                time.sleep(POLL_SECONDS)
    failed = sum(entry["status"] == "failed" for entry in state["dates"])
    state["status"] = "failed" if failed else "complete"
    state["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save_state(out, state)
    if failed:
        raise RuntimeError(f"{failed} calibration dates failed. Downloaded results and failure details are preserved in {out}")
    print(f"Complete: {state['total_jobs']} jobs, {state['total_shots']} shots. Results: {out / 'results'}", flush=True)


def run(noise_location, out):
    out.mkdir(parents=True, exist_ok=True)
    with (out / ".history.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state, jobs = prepare(noise_location, out)
        print(f"{len(state['dates'])} calibration files x {len(jobs)} jobs x {SHOTS} shots = "
              f"{state['total_jobs']} jobs / {state['total_shots']} shots", flush=True)
        if state["status"] == "complete":
            print(f"Already complete: {out / 'results'}", flush=True)
            return
        session = boto3.Session(profile_name="default", region_name=state["region"])
        # Disable SDK retries of non-idempotent SubmitJob. AWS worker retries
        # remain as configured in the existing job definition.
        batch = session.client("batch", config=Config(retries={"total_max_attempts": 1}))
        s3 = session.client("s3")
        definition = batch.describe_job_definitions(jobDefinitions=[state["job_definition"]])["jobDefinitions"]
        if len(definition) != 1 or definition[0]["status"] != "ACTIVE" or not definition[0]["containerProperties"]["image"].endswith("@" + IMAGE_DIGEST):
            raise RuntimeError("The expected deployed calibration worker is unavailable")
        state["image"] = definition[0]["containerProperties"]["image"]
        upload_common_inputs(s3, out, state)
        monitor(batch, s3, out, state, jobs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("noise_location", type=Path, help="Fez calibration JSON, or a directory of dated Fez JSONs")
    parser.add_argument("output_dir", type=Path, help="Local output directory; reuse it to resume")
    args = parser.parse_args()
    try:
        run(args.noise_location.expanduser().resolve(), args.output_dir.expanduser().resolve())
    except KeyboardInterrupt:
        print("\nMonitoring stopped; submitted AWS jobs continue. Run the same command to resume.", file=sys.stderr)
        return 130
    except (BotoCoreError, ClientError, OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}\nSubmitted jobs may still be running. Run the same command to resume.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

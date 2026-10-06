"""Offline orchestration checks; no AWS jobs are submitted."""
import io
import json
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import Mock, patch

import boto3
from botocore.stub import Stubber
import numpy as np

from cloud_runs.codes import TimeAwareMeasurement
from cloud_runs import run_history as history


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        (self.out / "inputs").mkdir()
        (self.out / "inputs/day.json").write_text('{}')
        self.entry = {"date": "2026-10-04", "file": "inputs/day.json", "status": "ready",
                      "sha256": history.sha256(self.out / "inputs/day.json")}
        self.jobs = [{"code": "513", "path": [0, 1, 2]}, {"code": "713", "path": [1, 2, 3]}]
        self.state = {"run_id": "history-test", "queue": "test-queue", "bucket": "test-bucket",
                      "job_definition": "test-definition:1", "prefix": "history-test", "dates": [self.entry],
                      "jobs_per_date": 2, "total_jobs": 2, "total_shots": 4000}

    def result(self, index):
        job = self.jobs[index]
        histogram = np.zeros(16 if job["code"] == "513" else 64, dtype=np.float32)
        histogram[0] = 2000
        return {"measurement": TimeAwareMeasurement(list(zip(job['path'], job['path'][1:])), histogram, 0,
                                                     code_type=job['code']),
                "shots": 2000, "timing": {"job_index": index, "code_type": job["code"], "path": job["path"]},
                "calibration": {"requested_date_utc": self.entry["date"], "sha256": self.entry["sha256"],
                                "backend": "ibm_fez"}}

    def test_submission_overrides_all_inputs_and_shots(self):
        batch, s3 = Mock(), Mock()
        batch.submit_job.return_value = {"jobId": "parent"}
        history.submit_date(batch, s3, self.out, self.state, self.entry)
        request = batch.submit_job.call_args.kwargs
        env = {entry["name"]: entry["value"] for entry in request["containerOverrides"]["environment"]}
        self.assertEqual(env["SHOTS"], "2000")
        self.assertEqual(env["S3_JOBS"], "s3://test-bucket/history-test/inputs/jobs.json")
        self.assertEqual(env["S3_CALIBRATION"], "s3://test-bucket/history-test/inputs/day.json")
        self.assertEqual(env["S3_OUTPUT_PREFIX"], "s3://test-bucket/history-test/outputs/2026-10-04/")
        self.assertEqual(request["arrayProperties"], {"size": 2})
        self.assertEqual(json.loads((self.out / "run.json").read_text())["dates"][0]["job_id"], "parent")
        # Check the real SDK's request schema without accessing AWS.
        client = boto3.client("batch", region_name=history.REGION,
                              aws_access_key_id="test", aws_secret_access_key="test")
        with Stubber(client) as stub:
            stub.add_response("submit_job", {"jobName": request["jobName"], "jobId": "parent"}, request)
            client.submit_job(**request)

    def test_uncertain_submission_recovers_without_resubmitting(self):
        self.entry["status"] = "submitting"
        batch, s3 = Mock(), Mock()
        batch.get_paginator.return_value.paginate.return_value = [{"jobSummaryList": [
            {"jobName": "history-test-2026-10-04", "jobId": "existing-parent"}]}]
        history.submit_date(batch, s3, self.out, self.state, self.entry)
        self.assertEqual(self.entry["job_id"], "existing-parent")
        batch.submit_job.assert_not_called()
        s3.upload_file.assert_not_called()
        self.entry["status"] = "submitting"
        batch.get_paginator.return_value.paginate.return_value = [{"jobSummaryList": []}]
        with self.assertRaisesRegex(RuntimeError, "No replacement submitted"):
            history.submit_date(batch, s3, self.out, self.state, self.entry)
        batch.submit_job.assert_not_called()

    def test_downloads_before_parent_finishes_and_merges_on_success(self):
        self.entry.update(status="submitted", job_id="parent")
        batch, s3 = Mock(), Mock()
        batch.describe_jobs.side_effect = [
            {"jobs": []},  # A newly submitted job can take time to appear.
            {"jobs": [{"jobId": "parent", "status": "PENDING", "arrayProperties": {
                "statusSummary": {"SUCCEEDED": 1, "RUNNING": 1}}}]},
            {"jobs": [{"jobId": "parent", "status": "SUCCEEDED", "arrayProperties": {
                "statusSummary": {"SUCCEEDED": 2}}}]}]
        blobs = {f"history-test/outputs/2026-10-04/{job['code']}/job_{i}.pkl": pickle.dumps(self.result(i))
                 for i,job in enumerate(self.jobs)}
        objects = [{"Key":key, "Size":len(value)} for key,value in blobs.items()]
        s3.get_paginator.return_value.paginate.side_effect = [
            [{"Contents": objects[:1]}], [{"Contents": objects[:1]}, {"Contents": objects[1:]}]]
        s3.download_file.side_effect = lambda bucket,key,path,**kwargs: Path(path).write_bytes(blobs[key])
        first = self.out / "results/2026-10-04/513/job_0.pkl"
        polls = 0
        def between_polls(seconds):
            nonlocal polls
            polls += 1
            if polls == 1:
                self.assertFalse(first.exists())
                return
            self.assertTrue(first.exists())
            self.assertEqual(self.entry["downloaded"], 1)
            self.assertEqual(self.entry["status"], "submitted")
        with patch.object(history.time, "sleep", side_effect=between_polls), \
             patch.object(history.subprocess, "run") as merge, patch("sys.stdout", new_callable=io.StringIO) as output:
            history.monitor(batch, s3, self.out, self.state, self.jobs)
        self.assertEqual(s3.download_file.call_count, 2)
        batch.submit_job.assert_not_called()
        merge.assert_called_once()
        self.assertIn("downloaded=1/2", output.getvalue())
        self.assertEqual(self.state["status"], "complete")

    def test_failed_array_keeps_results_and_does_not_merge_or_resubmit(self):
        self.entry.update(status="submitted", job_id="parent")
        batch, s3 = Mock(), Mock()
        batch.describe_jobs.return_value = {"jobs": [{"jobId":"parent", "status":"FAILED", "statusReason":"worker failed",
                                                     "arrayProperties":{"statusSummary":{"FAILED":2}}}]}
        batch.get_paginator.return_value.paginate.return_value = [{"jobSummaryList":[{"jobId":"parent:0"}]}]
        s3.get_paginator.return_value.paginate.return_value = [{}]
        with patch.object(history.subprocess, "run") as merge, patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(RuntimeError, "1 calibration dates failed"):
                history.monitor(batch, s3, self.out, self.state, self.jobs)
        merge.assert_not_called()
        batch.submit_job.assert_not_called()
        self.assertEqual(self.state["status"], "failed")
        self.assertEqual(self.entry["failed_jobs"], [{"jobId":"parent:0"}])

    def test_mismatched_result_is_rejected(self):
        path = self.out / "result.pkl"
        for modify in [lambda d:d.update(shots=1999), lambda d:d["calibration"].update(sha256="wrong"),
                       lambda d:d["timing"].update(path=[0,3,2])]:
            data = self.result(0)
            modify(data)
            path.write_bytes(pickle.dumps(data))
            with self.assertRaisesRegex(ValueError, "Wrong or incomplete result"):
                history.check_result(path, 0, self.jobs[0], self.entry)

    def test_resume_rejects_changed_inputs(self):
        noise = history.ROOT / "noise_history/ibm_fez_2026-10-04.json"
        # This repository's snapshot supplies the existing downloader schema.
        original = json.loads(noise.read_text())
        local = self.out / "calibration.json"
        local.write_text(json.dumps(original))
        dest = self.out / "run"
        dest.mkdir()
        with patch("sys.stdout", new_callable=io.StringIO):
            state, jobs = history.prepare(local, dest)
            resumed, _ = history.prepare(local, dest)
            self.assertEqual(state["run_id"], resumed["run_id"])
            self.assertEqual(len(jobs), 960)
            original["extra"] = "changed"
            local.write_text(json.dumps(original))
            with self.assertRaisesRegex(ValueError, "different run/input set"):
                history.prepare(local, dest)


if __name__ == "__main__":
    unittest.main()

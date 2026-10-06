#!/usr/bin/env python3
"""Download daily historical IBM backend calibration snapshots.

Usage:
    python download_calibrations.py N OUT [--backend BACKEND]

Examples:
    # Last 10 UTC days from IBM Fez
    python download_calibrations.py 10 noise_history

    # Last 512 UTC days from IBM Fez
    python download_calibrations.py 512 noise_history

    # Another backend
    python download_calibrations.py 30 noise_history --backend ibm-torino

N includes today (UTC).

Credentials are loaded from:

    <repo-root>/secrets/keys.json

Supported keys.json formats:

    {
        "apikey": "...",
        "crn": "..."
    }

or:

    {
        "qiskit-api-key": "...",
        "qiskit-crn-instance": "..."
    }

For completed days, the script requests the latest calibration snapshot before
the following midnight UTC. For today, it requests the latest snapshot before
the script started.

IBM's historical API returns the closest available snapshot older than the
requested datetime, so multiple requested days can resolve to the same actual
calibration snapshot.

Output files:

    OUT/<backend>_YYYY-MM-DD.json

Existing files are preserved. No quantum jobs are submitted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
import sys

from qiskit_ibm_runtime import QiskitRuntimeService


# ---------------------------------------------------------------------------
# Paths / credentials
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
SECRETS_FILE = REPO_ROOT / "secrets" / "qiskit-ibm.json"
PROTECTED_CLOUD_RUNS = REPO_ROOT / "cloud_runs"


def load_credentials() -> tuple[str, str | None]:
    """Load IBM Quantum API key and optional instance CRN."""

    if not SECRETS_FILE.exists():
        raise FileNotFoundError(
            f"IBM credentials file not found:\n"
            f"  {SECRETS_FILE}\n\n"
            f"Expected a JSON file such as:\n"
            f'  {{"apikey": "...", "crn": "..."}}'
        )

    try:
        with SECRETS_FILE.open("r", encoding="utf-8") as f:
            secrets = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {SECRETS_FILE}: {exc}"
        ) from exc

    # Support both naming conventions already referenced in this repository.
    

    return secrets.get("token"), secrets.get("instance")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_backend_name(name: str) -> str:
    """Accept names such as 'ibm-fez' as aliases for 'ibm_fez'."""
    return name.strip().lower().replace("-", "_")


def json_datetime(value):
    """Serialize calibration timestamps as ISO-8601 strings."""
    if isinstance(value, datetime):
        return value.isoformat()

    raise TypeError(
        f"Cannot JSON-serialize {type(value).__name__}"
    )


def create_service() -> QiskitRuntimeService:
    """Create IBM Quantum service using credentials from secrets/keys.json."""

    api_key, crn = load_credentials()

    kwargs = {
        "channel": "ibm_quantum_platform",
        "token": api_key,
    }

    # Supplying the CRN avoids IBM having to choose among accessible instances.
    if crn:
        kwargs["instance"] = crn

    return QiskitRuntimeService(**kwargs)


# ---------------------------------------------------------------------------
# Download logic
# ---------------------------------------------------------------------------

def download_calibrations(
    service: QiskitRuntimeService,
    backend_name: str,
    n: int,
    out: Path,
    *,
    now: datetime | None = None,
) -> int:
    """Download one historical calibration snapshot per requested UTC day."""

    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)

    backend_name = normalize_backend_name(backend_name)

    out = out.expanduser().resolve()

    # Keep generated data out of the protected production directory.
    if out.is_relative_to(PROTECTED_CLOUD_RUNS):
        raise ValueError(
            "cloud_runs/ is read-only. "
            "Choose an output directory outside cloud_runs/."
        )

    out.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to IBM backend: {backend_name}")

    try:
        backend = service.backend(
            backend_name,
            use_fractional_gates=None,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Could not access backend {backend_name!r}: {exc}"
        ) from exc

    print(f"Connected to: {backend.name}")
    print(f"Requested dates: {n}")
    print(f"Output directory: {out}")
    print()

    saved = 0
    skipped = 0
    missing = 0

    # Work backwards: today, yesterday, ...
    for offset in range(n):

        day = now.date() - timedelta(days=offset)

        # For today, use the script's start time.
        if offset == 0:
            requested_at = now

        # For a completed day, request the latest snapshot before
        # the beginning of the next UTC day.
        else:
            requested_at = datetime.combine(
                day + timedelta(days=1),
                time.min,
                tzinfo=timezone.utc,
            )

        destination = out / (
            f"{backend.name}_{day.isoformat()}.json"
        )

        if destination.exists():
            print(
                f"[{offset + 1:>4}/{n}] "
                f"{day}: keeping existing file"
            )
            skipped += 1
            continue

        try:
            properties = backend.properties(
                datetime=requested_at
            )

            if properties is None:
                print(
                    f"[{offset + 1:>4}/{n}] "
                    f"{day}: no historical calibration available",
                    file=sys.stderr,
                )
                missing += 1
                continue

            actual_timestamp = properties.last_update_date

            payload = {
                # Backend being queried.
                "backend": backend.name,

                # Date that this file represents in our experiment.
                "requested_date_utc": day.isoformat(),

                # Exact cutoff supplied to IBM.
                "requested_at_utc": requested_at.isoformat(),

                # Actual timestamp of the calibration snapshot IBM returned.
                "actual_last_update_date": (
                    actual_timestamp.isoformat()
                    if actual_timestamp is not None
                    else None
                ),

                # Original IBM BackendProperties representation.
                "properties": properties.to_dict(),
            }

            content = (
                json.dumps(
                    payload,
                    indent=2,
                    default=json_datetime,
                )
                + "\n"
            )

            # "x" prevents accidental overwriting.
            with destination.open(
                "x",
                encoding="utf-8",
            ) as f:
                f.write(content)

            print(
                f"[{offset + 1:>4}/{n}] "
                f"{day}: saved "
                f"(snapshot {actual_timestamp})"
            )

            saved += 1

        except Exception as exc:
            print(
                f"[{offset + 1:>4}/{n}] "
                f"{day}: FAILED: {exc}",
                file=sys.stderr,
            )
            missing += 1

    print()
    print("=" * 60)
    print("DOWNLOAD COMPLETE")
    print("=" * 60)
    print(f"Backend:           {backend.name}")
    print(f"Requested dates:   {n}")
    print(f"Saved:             {saved}")
    print(f"Already existing:  {skipped}")
    print(f"Missing / failed:  {missing}")
    print(f"Output:            {out}")
    print("=" * 60)

    return 1 if missing else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "n",
        type=int,
        help="Number of UTC dates to download, including today",
    )

    parser.add_argument(
        "out",
        type=Path,
        help="Output directory",
    )

    parser.add_argument(
        "--backend",
        default="ibm-fez",
        help=(
            "IBM hardware backend "
            "(default: ibm-fez; both ibm-fez and ibm_fez are accepted)"
        ),
    )

    args = parser.parse_args()

    if args.n < 1:
        parser.error("n must be a positive integer")

    backend_name = normalize_backend_name(args.backend)

    try:
        service = create_service()

        return download_calibrations(
            service=service,
            backend_name=backend_name,
            n=args.n,
            out=args.out,
        )

    except Exception as exc:
        print(
            f"\nCalibration download failed:\n  {exc}",
            file=sys.stderr,
        )

        print(
            f"\nCredential file used:\n"
            f"  {SECRETS_FILE}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())

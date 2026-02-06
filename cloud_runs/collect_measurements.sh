#!/usr/bin/env bash
# collect_measurements.sh — Copy measurements.pkl from code subdirs into a flat output dir.
#
# After merge_results.py, you have:
#   <input-dir>/513/measurements.pkl
#   <input-dir>/713/measurements.pkl
#   ...
#
# This script copies them to:
#   <output-dir>/measurements_513.pkl
#   <output-dir>/measurements_713.pkl
#   ...
#
# Usage:
#   cloud_runs/collect_measurements.sh <input-dir> <output-dir>
#
# Example:
#   cloud_runs/collect_measurements.sh ./out/heron_r1 ./measurements/heron_r1
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <input-dir> <output-dir>" >&2
  exit 1
fi

INPUT_DIR="$1"
OUTPUT_DIR="$2"

mkdir -p "${OUTPUT_DIR}"

count=0
for code_dir in "${INPUT_DIR}"/*/; do
  code=$(basename "${code_dir}")
  src="${code_dir}measurements.pkl"
  if [[ -f "${src}" ]]; then
    dest="${OUTPUT_DIR}/measurements_${code}.pkl"
    cp "${src}" "${dest}"
    echo "  ${src} -> ${dest}"
    count=$((count + 1))
  fi
done

if [[ "${count}" -eq 0 ]]; then
  echo "No measurements.pkl files found in ${INPUT_DIR}/*/" >&2
  exit 1
fi

echo "Collected ${count} measurement files into ${OUTPUT_DIR}"

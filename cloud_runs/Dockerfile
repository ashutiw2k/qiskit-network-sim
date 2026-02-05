FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY cloud_runs/requirements-cloud.txt /app/cloud_runs/requirements-cloud.txt
RUN pip install -r /app/cloud_runs/requirements-cloud.txt

COPY . /app

ENTRYPOINT ["/app/cloud_runs/batch_entrypoint.sh"]

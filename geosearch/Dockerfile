# The geodata MCP server image. Its own container, not part of the backend's: it carries
# faiss, a 2 GB embedding model and 143 MB of index that the agent has no use for.
#
# Everything the server needs is built beforehand and copied in - the index, the vectors
# and the boundaries by `python -m geosearch.build`, the model by the bake step below.
# The build must NEVER run here: it takes ~25 minutes, it fetches from geo.admin.ch, and
# two runs a week apart produce two different indexes, which is the opposite of an image.
#
# Data vintages are not frozen by this, despite everything else being. The layer catalogue
# is fetched from geo.admin.ch at runtime (geosearch/swisstopo.py), so a six-month-old
# image still queries today's data - only the *searchable* set of layers is as of the
# build.
#
# Build from the repository root, as CI does:
#   python -m geosearch.build            # writes index/, once
#   docker build -f geosearch/Dockerfile -t sgs-llm-geosearch .
#
# CI runs on amd64 so its build is native. From an Apple Silicon machine, add
# --platform linux/amd64 for anything headed to ECS - and expect the model bake to take
# far longer under emulation.
FROM python:3.12-slim

WORKDIR /srv

# Dependencies first so a code change does not reinstall them - and, more to the point
# here, does not redownload the model in the layer after.
COPY geosearch/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8790 \
    GEOSEARCH_MODEL_CACHE=/srv/models

RUN useradd --create-home --uid 10001 sgs && mkdir -p /srv/models && chown sgs /srv/models

COPY geosearch ./geosearch
# The build output: DuckDB rows, three .faiss files, and index/s3 with the 6272 division
# boundaries. They belong to the code that was built against them - row `rid` in DuckDB is
# vector `rid` in the .faiss files - so they ship together or not at all.
COPY index ./index

USER sgs

# Bakes the 2.1 GB ONNX model into the image rather than downloading it on first request.
# Constructing GeoIndex is what fetches it, and it fetches exactly the model recorded in
# the index's `meta` table, which is the only one that can read those vectors. So this
# doubles as a build-time check that the index loads at all: a bad COPY fails here rather
# than in the cluster.
RUN python -c "from pathlib import Path; from geosearch.index import GeoIndex; print(GeoIndex(Path('/srv/index')).counts())"

EXPOSE 8790

# No curl in the slim image, and the MCP endpoint cannot answer a plain GET, so the server
# serves /health beside it. It reports the index counts: a container whose index did not
# load is not healthy, however well uvicorn is running.
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8790')+'/health').read()"]

# `exec` makes uvicorn PID 1, so it receives ECS's SIGTERM directly instead of being
# killed - which matters because shutdown is what closes the httpx client to geo.admin.ch.
CMD ["sh", "-c", "exec python -m geosearch.server --host 0.0.0.0 --port ${PORT:-8790} --index /srv/index"]

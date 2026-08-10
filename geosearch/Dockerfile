# The geodata MCP server image. Its own container, not part of the backend's: it carries
# faiss and 143 MB of index that the agent has no use for.
#
# Everything the server needs is built beforehand and copied in - the index, the vectors
# and the boundaries by `python -m geosearch.build`. The build must NEVER run here: it
# takes ~12 minutes, it fetches from geo.admin.ch and Bedrock, and two runs a week apart
# produce two different indexes, which is the opposite of an image.
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
# --platform linux/amd64 for anything headed to ECS.
FROM python:3.12-slim

WORKDIR /srv

# Dependencies first so a code change does not reinstall them.
COPY geosearch/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8790

RUN useradd --create-home --uid 10001 sgs

COPY geosearch ./geosearch
# The build output: DuckDB rows, three .faiss files, and index/s3 with the 6272 division
# boundaries. They belong to the code that was built against them - row `rid` in DuckDB is
# vector `rid` in the .faiss files - so they ship together or not at all.
COPY index ./index

USER sgs

# Build-time check that the index loads: it opens DuckDB, reads the three .faiss files and
# asserts their vector counts match the row counts, so a truncated COPY or a stale .faiss
# fails here rather than in the cluster. Nothing is embedded, so this needs no credentials
# - boto3 resolves those on the first call, which does not happen until a real query.
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

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
FROM mambaorg/micromamba:debian12-slim

USER root
WORKDIR /srv

# Dependencies first so a code change does not reinstall them. Conda owns one
# compiled geospatial stack, including the separately packaged Parquet driver;
# pip retains FAISS and every pure-Python SGS pin.
COPY geosearch/requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsqlite3-0 libstdc++6 zlib1g \
    && rm -rf /var/lib/apt/lists/*

RUN micromamba create -y -p /venv -c conda-forge \
        python=3.12 \
        pip \
        'libgdal-core=3.10.*' \
        'libgdal-arrow-parquet=3.10.*' \
        'gdal=3.10.*' \
        'pyarrow=18.1.*' \
        'numpy=2.3.5' \
        'shapely=2.1.*' \
        'pyproj=3.7.*' \
    && micromamba clean --all --yes

ENV PATH="/venv/bin:$PATH" \
    VIRTUAL_ENV="/venv" \
    LD_LIBRARY_PATH="/venv/lib" \
    GDAL_DATA="/venv/share/gdal" \
    PROJ_DATA="/venv/share/proj" \
    PROJ_LIB="/venv/share/proj"

RUN grep -Ev "^(numpy|shapely|pyproj|pyarrow)==" requirements.txt > requirements-pip.txt \
    && pip install --no-cache-dir -r requirements-pip.txt \
    && rm requirements-pip.txt \
    && python -c "import numpy,pyarrow,pyproj,shapely; assert numpy.__version__ == '2.3.5'; assert pyarrow.__version__ == '18.1.0'; assert shapely.__version__.startswith('2.1.'); assert pyproj.__version__.startswith('3.7.')" \
    && ogrinfo --format Parquet >/dev/null

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8790

RUN useradd --create-home --uid 10001 sgs

COPY tile_server ./tile_server
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

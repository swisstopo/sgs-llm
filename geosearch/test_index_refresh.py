"""Offline acceptance of refresh safeguards, provenance and atomic publication."""

import json
import shutil
from datetime import datetime

import boto3
import pytest
from moto import mock_aws

from . import refresh_index
from .index import build
from .index_metadata import INDEX_FILES, health_metadata, records, validate_bundle
from .index_release import fetch, publish
from .test_geosearch import StubEmbedder, _layer


@pytest.fixture
def bundle(tmp_path):
    directory = tmp_path / "published"
    layers = [_layer(f"ch.test.{i}", f"Title {i}", "Description") for i in range(20)]
    division = {
        "name": "Bern",
        "kind": "kanton",
        "canton": "BE",
        "bbox": [7, 46, 8, 47],
        "layer_id": "boundaries",
        "s3_key": "layers/divisions/kanton/bern.geojson",
        "feature_count": 1,
    }
    build(directory, layers, [division], StubEmbedder())
    boundary = directory / "s3" / division["s3_key"]
    boundary.parent.mkdir(parents=True)
    boundary.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[7, 46], [8, 46], [8, 47], [7, 46]]],
                        },
                    }
                ],
            }
        )
    )
    return directory


def test_metadata_matches_loaded_counts_and_legacy_date_is_unknown(bundle):
    meta = validate_bundle(bundle)
    assert meta["catalogue_layers"] == 20
    assert meta["divisions"] == 1
    assert meta["model"] == StubEmbedder.model_name
    assert datetime.fromisoformat(meta["built_at"]).tzinfo is not None
    (bundle / "meta.json").unlink()
    assert validate_bundle(bundle, require_metadata=False)["built_at"] is None
    with pytest.raises(ValueError, match="meta.json"):
        validate_bundle(bundle)


@pytest.mark.parametrize(
    "name", [*INDEX_FILES, "s3/layers/divisions/kanton/bern.geojson"]
)
def test_missing_bundle_member_aborts(bundle, name):
    (bundle / name).unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        validate_bundle(bundle)


def test_metadata_count_mismatch_aborts(bundle):
    with pytest.raises(ValueError, match="does not describe"):
        health_metadata(bundle, {"layers": 21, "divisions": 1}, StubEmbedder.model_name)


@pytest.mark.parametrize(
    "old,new,ok",
    [(100, 95, True), (100, 94, False), (0, 10, False), (20, 0, False), (20, 21, True)],
)
def test_drop_threshold(old, new, ok):
    if ok:
        refresh_index.check_count(old, new)
    else:
        with pytest.raises(ValueError):
            refresh_index.check_count(old, new)


def fake_source(monkeypatch, bundle, layers):
    class API:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def catalog(self, lang):
            return layers

    async def collect(api, lang, with_divisions, mirror, *, layers):
        shutil.copytree(bundle / "s3", mirror, dirs_exist_ok=True)
        return layers, records(bundle, "divisions")

    monkeypatch.setattr(refresh_index, "Swisstopo", API)
    monkeypatch.setattr(refresh_index, "collect", collect)
    monkeypatch.setattr(refresh_index, "DEFAULT_MODEL", StubEmbedder.model_name)
    calls = []

    class Embedder(StubEmbedder):
        def __init__(self, model):
            assert model == self.model_name

        def encode_documents(self, texts):
            calls.append(list(texts))
            return super().encode_documents(texts)

    monkeypatch.setattr(refresh_index, "Embedder", Embedder)
    return calls


@pytest.mark.anyio
async def test_unchanged_schedule_skips_and_manual_reuses_in_original_order(
    bundle, monkeypatch
):
    layers = list(reversed(records(bundle, "layers")))
    calls = fake_source(monkeypatch, bundle, layers)
    candidate = bundle.parent / "candidate"
    assert not await refresh_index.refresh(bundle, candidate)
    assert not candidate.exists()
    assert calls == []
    assert await refresh_index.refresh(bundle, candidate, force=True)
    assert [len(batch) for batch in calls] == [8, 1]  # reuse check, then division name
    assert records(candidate, "layers") == records(bundle, "layers")
    assert (candidate / "layer_title.faiss").read_bytes() == (
        bundle / "layer_title.faiss"
    ).read_bytes()
    assert validate_bundle(candidate)["built_at"] != validate_bundle(bundle)["built_at"]


@pytest.mark.anyio
async def test_changed_catalogue_rebuilds_and_excessive_drop_never_embeds(
    bundle, monkeypatch
):
    layers = records(bundle, "layers")
    layers[0]["description"] = "New description"
    calls = fake_source(monkeypatch, bundle, layers)
    assert await refresh_index.refresh(bundle, bundle.parent / "changed")
    assert [len(batch) for batch in calls] == [20, 20, 1]
    calls = fake_source(monkeypatch, bundle, layers[:18])
    with pytest.raises(ValueError, match="more than 5%"):
        await refresh_index.refresh(bundle, bundle.parent / "truncated")
    assert not (bundle.parent / "truncated").exists()
    assert calls == []


@pytest.fixture
def storage():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-index")
        yield client


def test_publish_fetch_and_failed_upload_preserves_old_pointer(
    bundle, storage, monkeypatch
):
    uri = "s3://test-index/index"
    prefix = publish(storage, uri, bundle)
    old = storage.get_object(Bucket="test-index", Key="index/current.json")[
        "Body"
    ].read()
    assert json.loads(old)["prefix"] == prefix
    output = bundle.parent / "downloaded"
    fetch(storage, uri, output)
    assert validate_bundle(output) == validate_bundle(bundle)
    for path in bundle.rglob("*"):
        if path.is_file():
            assert (output / path.relative_to(bundle)).read_bytes() == path.read_bytes()
    upload = storage.upload_file
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("upload interrupted")
        return upload(*args, **kwargs)

    monkeypatch.setattr(storage, "upload_file", fail_second)
    with pytest.raises(OSError, match="interrupted"):
        publish(storage, uri, bundle)
    assert (
        storage.get_object(Bucket="test-index", Key="index/current.json")["Body"].read()
        == old
    )


def test_corrupted_release_does_not_overwrite_existing_download(bundle, storage):
    uri = "s3://test-index/index"
    prefix = publish(storage, uri, bundle)
    storage.put_object(
        Bucket="test-index", Key=prefix + "layer_title.faiss", Body=b"corrupted"
    )
    output = bundle.parent / "existing"
    output.mkdir()
    sentinel = output / "geosearch.duckdb"
    sentinel.write_bytes(b"existing database")
    with pytest.raises(ValueError, match="corrupt"):
        fetch(storage, uri, output)
    assert sentinel.read_bytes() == b"existing database"


def test_legacy_prefix_ignores_abandoned_release_files(bundle, storage):
    for path in bundle.rglob("*"):
        if path.is_file():
            storage.upload_file(
                str(path), "test-index", "index/" + path.relative_to(bundle).as_posix()
            )
    storage.put_object(
        Bucket="test-index", Key="index/releases/abandoned/junk", Body=b"junk"
    )
    output = bundle.parent / "legacy"
    fetch(storage, "s3://test-index/index", output)
    assert validate_bundle(output) == validate_bundle(bundle)
    assert not (output / "releases").exists()


def test_served_health_reports_bundle_provenance(bundle, storage, monkeypatch):
    import httpx
    import uvicorn

    from . import server

    expected = validate_bundle(bundle)
    monkeypatch.setenv("GEOSEARCH_S3_BUCKET", "test-index")
    monkeypatch.setattr("sys.argv", ["geosearch", "--index", str(bundle)])
    observed = {}

    async def inspect_health(instance):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=instance.config.app),
            base_url="http://localhost",
        ) as client:
            response = await client.get("/health")
            assert response.status_code == 200
            observed.update(response.json())

    monkeypatch.setattr(uvicorn.Server, "serve", inspect_health)
    server.main()
    assert observed == {"status": "ok", "layers": 20, **expected}

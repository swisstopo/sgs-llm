"""Stable MCP input and output schemas for the public exploration tools."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, RootModel


class WGS84Point(BaseModel):
    """An explicitly labelled longitude/latitude point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    longitude: float = Field(ge=-180, le=180, description="Longitude in decimal degrees.")
    latitude: float = Field(ge=-90, le=90, description="Latitude in decimal degrees.")
    crs: Literal["EPSG:4326"] = Field(
        default="EPSG:4326",
        description="Coordinate reference system for longitude and latitude.",
    )


class LV95Point(BaseModel):
    """An explicitly labelled Swiss LV95 easting/northing point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    easting: float = Field(
        ge=2_450_000,
        le=2_900_000,
        description="Swiss LV95 easting in metres.",
    )
    northing: float = Field(
        ge=1_050_000,
        le=1_350_000,
        description="Swiss LV95 northing in metres.",
    )
    crs: Literal["EPSG:2056"] = Field(
        default="EPSG:2056",
        description="Coordinate reference system for easting and northing.",
    )


PointInput = WGS84Point | LV95Point


class ErrorDetails(TypedDict):
    code: str
    message: str
    retryable: bool
    upstream_status: int | None


class ErrorResult(TypedDict):
    error: ErrorDetails


class SearchDatasetsSuccess(TypedDict):
    query: str
    language: str
    datasets: list[dict[str, Any]]
    result_count: int
    low_confidence: bool
    score_margin: float | None
    catalog_snapshot: str | None
    live_catalog: dict[str, Any]
    map_link_note: str
    note: str | None


class SearchDatasetsOutput(RootModel[SearchDatasetsSuccess | ErrorResult]):
    model_config = ConfigDict(json_schema_extra={"type": "object"})


class DescribeDatasetSuccess(TypedDict):
    dataset: dict[str, Any]
    live_metadata: dict[str, Any]
    map_link_note: str


class DescribeDatasetOutput(RootModel[DescribeDatasetSuccess | ErrorResult]):
    model_config = ConfigDict(json_schema_extra={"type": "object"})


class SearchDivisionsSuccess(TypedDict):
    query: str
    divisions: list[dict[str, Any]]
    result_count: int
    snapshot_date: str | None
    bbox_note: str
    note: str | None


class SearchDivisionsOutput(RootModel[SearchDivisionsSuccess | ErrorResult]):
    model_config = ConfigDict(json_schema_extra={"type": "object"})


class DatasetMapLink(TypedDict):
    dataset_id: str
    url: str


class ViewerCenter(TypedDict):
    easting: float
    northing: float
    crs: Literal["EPSG:2056"]


class MapPreviewLinksSuccess(TypedDict):
    dataset_ids: list[str]
    individual_links: list[DatasetMapLink]
    combined_link: str | None
    focus: dict[str, Any]
    center: ViewerCenter
    map_preview_scope: str
    presentation_note: str
    map_link_note: str


class MapPreviewLinksOutput(RootModel[MapPreviewLinksSuccess | ErrorResult]):
    model_config = ConfigDict(json_schema_extra={"type": "object"})


class GeocodeLocationSuccess(TypedDict):
    query: str
    language: str
    locations: list[dict[str, Any]]
    result_count: int
    note: str
    map_link_note: str


class GeocodeLocationOutput(RootModel[GeocodeLocationSuccess | ErrorResult]):
    model_config = ConfigDict(json_schema_extra={"type": "object"})


class IdentifyAtPointSuccess(TypedDict):
    point: dict[str, Any]
    selection: dict[str, Any]
    dataset_ids: list[str]
    map_preview_url: str
    feature_count: int
    features: list[dict[str, Any]]
    geometry_omitted: bool
    map_link_note: str
    oereb_note: str | None


class IdentifyAtPointOutput(RootModel[IdentifyAtPointSuccess | ErrorResult]):
    model_config = ConfigDict(json_schema_extra={"type": "object"})

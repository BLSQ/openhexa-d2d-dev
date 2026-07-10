import json
import logging
from unittest.mock import patch

import pandas as pd
import polars as pl

from d2d_development.org_unit_aligner import DHIS2PyramidAligner
from tests.mock_dhis2_get import MockDHIS2Client
from tests.mock_dhis2_post import MOCK_DHIS2_OK_RESPONSE, MockDHIS2Response


def _source_records() -> list[dict]:
    return [
        # Matches target OU002's id but with a different name -> triggers an UPDATE.
        {
            "id": "OU002",
            "name": "District 2 new name",
            "shortName": "D2",
            "openingDate": "2020-01-01",
            "closedDate": None,
            "parent": "{'id': 'COUNTRY'}",
            "level": 2,
            "path": "/COUNTRY/OU002",
            "geometry": None,
        },
        # Not present in the target pyramid -> triggers a CREATE.
        {
            "id": "OU003",
            "name": "District 3",
            "shortName": "D3",
            "openingDate": "2021-01-01",
            "closedDate": None,
            "parent": "{'id': 'COUNTRY'}",
            "level": 2,
            "path": "/COUNTRY/OU003",
            "geometry": None,
        },
    ]


def _run_align_to(source_pyramid: pd.DataFrame | pl.DataFrame) -> dict:
    dhis2_client = MockDHIS2Client()
    aligner = DHIS2PyramidAligner(logger=logging.getLogger("test_org_unit_aligner"))

    with patch.object(dhis2_client.api.session, "post", return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE)):
        aligner.align_to(target_dhis2=dhis2_client, source_pyramid=source_pyramid)

    return aligner.summary


def test_align_to_accepts_pandas_dataframe():
    """Test that align_to() accepts a pandas DataFrame and produces the expected CREATE/UPDATE counts."""
    summary = _run_align_to(pd.DataFrame(_source_records()))

    assert len(summary["CREATE"]["CREATED"]) == 1
    assert len(summary["UPDATE"]["UPDATED"]) == 1
    assert len(summary["CREATE"]["INVALID"]) == 0
    assert len(summary["UPDATE"]["INVALID"]) == 0


def test_align_to_accepts_polars_dataframe():
    """Test that align_to() accepts a polars DataFrame and produces the expected CREATE/UPDATE counts."""
    summary = _run_align_to(pl.DataFrame(_source_records()))

    assert len(summary["CREATE"]["CREATED"]) == 1
    assert len(summary["UPDATE"]["UPDATED"]) == 1
    assert len(summary["CREATE"]["INVALID"]) == 0
    assert len(summary["UPDATE"]["INVALID"]) == 0


def test_align_to_pandas_and_polars_inputs_agree():
    """Test that pandas and polars inputs to align_to() produce identical summaries."""
    pandas_summary = _run_align_to(pd.DataFrame(_source_records()))
    polars_summary = _run_align_to(pl.DataFrame(_source_records()))

    assert pandas_summary == polars_summary


def test_align_to_handles_mixed_geometry_shapes_in_source_pyramid():
    """Test that Point/Polygon/MultiPolygon-as-JSON-strings, plus None, can coexist in one source pyramid.

    The real source pyramid always stores `geometry` as a JSON string (or None), never as a raw
    dict, so a plain pl.DataFrame(records) construction is safe here regardless of which geometry
    type each string encodes (no Struct schema inference is involved for a string column). None
    of these org unit ids exist in the target pyramid, so all should be CREATEd.
    """
    point = {"type": "Point", "coordinates": [1.0, 2.0]}
    polygon = {"type": "Polygon", "coordinates": [[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [1.0, 2.0]]]}
    multipolygon = {"type": "MultiPolygon", "coordinates": [[[[1.0, 2.0], [3.0, 4.0]]], [[[7.0, 8.0], [9.0, 10.0]]]]}

    def record(ou_id: str, geometry: str | None) -> dict:
        return {
            "id": ou_id,
            "name": ou_id,
            "shortName": ou_id,
            "openingDate": "2020-01-01",
            "closedDate": None,
            "parent": "{'id': 'COUNTRY'}",
            "level": 2,
            "path": f"/COUNTRY/{ou_id}",
            "geometry": geometry,
        }

    records = [
        record("GEO_POINT", json.dumps(point)),
        record("GEO_POLYGON", json.dumps(polygon)),
        record("GEO_MULTIPOLYGON", json.dumps(multipolygon)),
        record("GEO_NONE", None),
    ]

    dhis2_client = MockDHIS2Client()
    aligner = DHIS2PyramidAligner(logger=logging.getLogger("test_org_unit_aligner"))
    with patch.object(
        dhis2_client.api.session, "post", return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE)
    ) as mock_post:
        aligner.align_to(target_dhis2=dhis2_client, source_pyramid=pl.DataFrame(records))

    assert len(aligner.summary["CREATE"]["CREATED"]) == len(records)
    assert len(aligner.summary["CREATE"]["ERROR"]) == 0
    assert len(aligner.summary["CREATE"]["INVALID"]) == 0

    payloads = {call.kwargs["json"]["id"]: call.kwargs["json"] for call in mock_post.call_args_list}
    assert payloads["GEO_POINT"]["geometry"] == point
    assert payloads["GEO_POLYGON"]["geometry"] == polygon
    assert payloads["GEO_MULTIPOLYGON"]["geometry"] == multipolygon
    assert "geometry" not in payloads["GEO_NONE"]


def test_align_to_handles_mixed_geometry_shapes_in_target_pyramid():
    """Test that a target pyramid with varying geometry shapes doesn't break polars construction.

    Unlike the source pyramid, the target pyramid comes straight from a live DHIS2 API response
    (`target_dhis2.meta.organisation_units(...)`), where `parent`/`geometry` are already native
    Python dicts, not strings. Nested geometry shapes differ in list-nesting depth across org unit
    types (e.g. Point vs MultiPolygon), which is exactly what previously risked breaking polars'
    automatic Struct schema inference when building the target pyramid DataFrame.
    """
    point = {"type": "Point", "coordinates": [1.0, 2.0]}
    polygon = {"type": "Polygon", "coordinates": [[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [1.0, 2.0]]]}
    multipolygon = {"type": "MultiPolygon", "coordinates": [[[[1.0, 2.0], [3.0, 4.0]]], [[[7.0, 8.0], [9.0, 10.0]]]]}

    def target_record(ou_id: str, geometry: dict | None) -> dict:
        return {
            "id": ou_id,
            "name": ou_id,
            "shortName": ou_id,
            "openingDate": "2020-01-01",
            "closedDate": None,
            "parent": {"id": "COUNTRY"},
            "level": 2,
            "path": f"/COUNTRY/{ou_id}",
            "geometry": geometry,
        }

    target_records = [
        target_record("GEO_POINT", point),
        target_record("GEO_POLYGON", polygon),
        target_record("GEO_MULTIPOLYGON", multipolygon),
        target_record("GEO_NONE", None),
    ]

    # Source pyramid has one org unit matching a target id (with a changed name, to trigger an
    # UPDATE) so the comparison logic also runs against the mixed-shape target OrgUnit instances.
    source_records = [
        {
            "id": "GEO_POLYGON",
            "name": "GEO_POLYGON renamed",
            "shortName": "GEO_POLYGON",
            "openingDate": "2020-01-01",
            "closedDate": None,
            "parent": "{'id': 'COUNTRY'}",
            "level": 2,
            "path": "/COUNTRY/GEO_POLYGON",
            "geometry": json.dumps(polygon),
        }
    ]

    dhis2_client = MockDHIS2Client()
    aligner = DHIS2PyramidAligner(logger=logging.getLogger("test_org_unit_aligner"))
    with (
        patch.object(dhis2_client.meta, "organisation_units", return_value=target_records),
        patch.object(dhis2_client.api.session, "post", return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE)),
    ):
        aligner.align_to(target_dhis2=dhis2_client, source_pyramid=pl.DataFrame(source_records))

    assert len(aligner.summary["UPDATE"]["UPDATED"]) == 1
    assert len(aligner.summary["UPDATE"]["ERROR"]) == 0
    assert len(aligner.summary["UPDATE"]["INVALID"]) == 0


def test_align_to_target_pyramid_geometry_not_dropped_when_first_record_lacks_it():
    """Test that geometry isn't silently discarded when the DHIS2 API omits it for some org units.

    The raw target pyramid comes straight from an external API response, so records aren't
    guaranteed to be uniform: some org units may omit a field entirely (e.g. no `geometry` key at
    all) rather than setting it to null. If the first org unit in the response happens to omit
    `geometry`, later org units' real geometry values must still be preserved, not dropped.
    """
    point = {"type": "Point", "coordinates": [1.0, 2.0]}
    target_records = [
        {
            "id": "GEO_ABSENT",
            "name": "GEO_ABSENT",
            "shortName": "GEO_ABSENT",
            "openingDate": "2020-01-01",
            "closedDate": None,
            "parent": {"id": "COUNTRY"},
            "level": 2,
            "path": "/COUNTRY/GEO_ABSENT",
            # No "geometry" key at all for this org unit.
        },
        {
            "id": "GEO_POINT",
            "name": "GEO_POINT",
            "shortName": "GEO_POINT",
            "openingDate": "2020-01-01",
            "closedDate": None,
            "parent": {"id": "COUNTRY"},
            "level": 2,
            "path": "/COUNTRY/GEO_POINT",
            "geometry": point,
        },
    ]

    # Matches target's GEO_POINT id but with a changed name, to trigger an UPDATE and force a
    # comparison against the real (materialized) OrgUnit built from the target pyramid.
    source_records = [
        {
            "id": "GEO_POINT",
            "name": "GEO_POINT renamed",
            "shortName": "GEO_POINT",
            "openingDate": "2020-01-01",
            "closedDate": None,
            "parent": "{'id': 'COUNTRY'}",
            "level": 2,
            "path": "/COUNTRY/GEO_POINT",
            "geometry": json.dumps(point),
        }
    ]

    dhis2_client = MockDHIS2Client()
    aligner = DHIS2PyramidAligner(logger=logging.getLogger("test_org_unit_aligner"))
    with (
        patch.object(dhis2_client.meta, "organisation_units", return_value=target_records),
        patch.object(
            dhis2_client.api.session, "post", return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE)
        ) as mock_post,
    ):
        aligner.align_to(target_dhis2=dhis2_client, source_pyramid=pl.DataFrame(source_records))

    # Source and target GEO_POINT geometries are identical, only the name changed, so the
    # comparison must be based on the target's real (non-dropped) geometry to detect the UPDATE.
    assert len(aligner.summary["UPDATE"]["UPDATED"]) == 1
    assert len(aligner.summary["UPDATE"]["ERROR"]) == 0
    # UPDATE posts to the "metadata" endpoint, which wraps the org unit under "organisationUnits".
    pushed_org_unit = mock_post.call_args.kwargs["json"]["organisationUnits"][0]
    assert pushed_org_unit["geometry"] == point


def test_align_to_realistic_parquet_source_with_stringified_parent_and_geometry():
    """Test the actual source pyramid format: parent/geometry stored as strings, not dicts.

    The real source pyramid is a polars parquet file where `parent` is a Python dict-repr string
    (single-quoted, e.g. "{'id': 'PARENT1'}") and `geometry` is either a JSON string or None.
    Since both columns are uniformly strings, this constructs directly as a plain pl.DataFrame
    (no struct-inference concerns) and should parse correctly end to end.
    """
    polygon_json = json.dumps({"type": "Polygon", "coordinates": [[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]]})
    records = [
        {
            "id": "OU005",
            "name": "District 5",
            "shortName": "D5",
            "openingDate": "2020-01-01",
            "closedDate": None,
            "parent": "{'id': 'COUNTRY'}",
            "level": 2,
            "path": "/COUNTRY/OU005",
            "geometry": polygon_json,
        },
        {
            "id": "OU006",
            "name": "District 6",
            "shortName": "D6",
            "openingDate": "2020-01-01",
            "closedDate": None,
            "parent": "{'id': 'COUNTRY'}",
            "level": 2,
            "path": "/COUNTRY/OU006",
            "geometry": None,
        },
    ]

    # These are neither in the mocked target pyramid, so both are expected to be CREATEd.
    source_pyramid = pl.DataFrame(records)

    dhis2_client = MockDHIS2Client()
    aligner = DHIS2PyramidAligner(logger=logging.getLogger("test_org_unit_aligner"))
    with patch.object(
        dhis2_client.api.session, "post", return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE)
    ) as mock_post:
        aligner.align_to(target_dhis2=dhis2_client, source_pyramid=source_pyramid)

    assert len(aligner.summary["CREATE"]["CREATED"]) == 2
    assert len(aligner.summary["CREATE"]["INVALID"]) == 0

    payloads = {call.kwargs["json"]["id"]: call.kwargs["json"] for call in mock_post.call_args_list}
    assert payloads["OU005"]["parent"] == {"id": "COUNTRY"}
    assert payloads["OU005"]["geometry"] == {"type": "Polygon", "coordinates": [[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]]}
    assert payloads["OU006"]["parent"] == {"id": "COUNTRY"}
    assert "geometry" not in payloads["OU006"]


def test_align_to_pandas_nan_closed_date_not_sent_as_literal_string():
    """Test that a pandas-induced NaN for a missing closedDate isn't pushed as the text "NaN".

    When a pandas DataFrame is built from records where one row has a real closedDate and
    another has None, pandas silently turns that None into a bare float NaN
    (`pd.DataFrame(...).to_dict(orient="records")`). Without normalization, that NaN would
    either crash validation elsewhere or, for a plain string field like closedDate, get
    stringified by polars into the literal text "NaN" and pushed to the DHIS2 API as if it were
    a real closing date.
    """
    records = [
        {
            "id": "OU003",
            "name": "District 3",
            "shortName": "D3",
            "openingDate": "2021-01-01",
            "closedDate": "2022-01-01",
            "parent": "{'id': 'COUNTRY'}",
            "level": 2,
            "path": "/COUNTRY/OU003",
            "geometry": None,
        },
        {
            "id": "OU004",
            "name": "District 4",
            "shortName": "D4",
            "openingDate": "2021-01-01",
            "closedDate": None,
            "parent": "{'id': 'COUNTRY'}",
            "level": 2,
            "path": "/COUNTRY/OU004",
            "geometry": None,
        },
    ]

    dhis2_client = MockDHIS2Client()
    aligner = DHIS2PyramidAligner(logger=logging.getLogger("test_org_unit_aligner"))

    with patch.object(
        dhis2_client.api.session, "post", return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE)
    ) as mock_post:
        aligner.align_to(target_dhis2=dhis2_client, source_pyramid=pd.DataFrame(records))

    assert len(aligner.summary["CREATE"]["CREATED"]) == 2
    payloads = [call.kwargs["json"] for call in mock_post.call_args_list]
    ou004_payload = next(payload for payload in payloads if payload["id"] == "OU004")
    ou003_payload = next(payload for payload in payloads if payload["id"] == "OU003")

    assert "closedDate" not in ou004_payload
    assert ou003_payload["closedDate"] == "2022-01-01"


def test_align_to_empty_source_pyramid_skips_alignment():
    """Test that an empty source pyramid short-circuits without contacting the target DHIS2."""
    dhis2_client = MockDHIS2Client()
    aligner = DHIS2PyramidAligner(logger=logging.getLogger("test_org_unit_aligner"))

    aligner.align_to(target_dhis2=dhis2_client, source_pyramid=pl.DataFrame({"id": []}))

    assert len(aligner.summary["CREATE"]["CREATED"]) == 0
    assert len(aligner.summary["UPDATE"]["UPDATED"]) == 0

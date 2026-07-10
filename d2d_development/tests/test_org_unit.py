import json

import pytest

from d2d_development.data_models import OrgUnit
from d2d_development.exceptions import OrgUnitError


def _base_record(**overrides: object) -> dict:
    record = {
        "id": "OU001",
        "name": "District 1",
        "shortName": "D1",
        "openingDate": "2020-01-01",
        "closedDate": None,
        "parent": None,
        "level": 2,
        "path": "/COUNTRY/OU001",
        "geometry": None,
    }
    record.update(overrides)
    return record


def test_org_unit_from_camel_case_kwargs():
    """Test construction of an OrgUnit from DHIS2 camelCase field names."""
    ou = OrgUnit(**_base_record())

    assert ou.id == "OU001"
    assert ou.name == "District 1"
    assert ou.short_name == "D1"
    assert ou.opening_date == "2020-01-01"


def test_org_unit_from_snake_case_kwargs():
    """Test construction of an OrgUnit from snake_case field names."""
    ou = OrgUnit(
        id="OU001",
        name="District 1",
        short_name="D1",
        opening_date="2020-01-01",
        level=2,
        path="/COUNTRY/OU001",
    )

    assert ou.short_name == "D1"
    assert ou.opening_date == "2020-01-01"


def test_org_unit_geometry_parsed_from_json_string():
    """Test that a JSON-encoded geometry string is parsed into a dict."""
    geometry = {"type": "Point", "coordinates": [1.0, 2.0]}
    ou = OrgUnit.model_validate(_base_record(geometry=json.dumps(geometry)))

    assert ou.geometry == geometry


def test_org_unit_geometry_none_stays_none():
    """Test that a missing geometry stays None instead of raising."""
    ou = OrgUnit.model_validate(_base_record(geometry=None))

    assert ou.geometry is None


def test_org_unit_geometry_parsed_from_python_repr_string():
    """Test that a single-quoted Python dict repr geometry string (not valid JSON) is parsed."""
    ou = OrgUnit.model_validate(_base_record(geometry="{'type': 'Point', 'coordinates': [1.0, 2.0]}"))

    assert ou.geometry == {"type": "Point", "coordinates": [1.0, 2.0]}


def test_org_unit_parent_parsed_from_json_string():
    """Test that a JSON-encoded parent string is parsed into a dict."""
    ou = OrgUnit.model_validate(_base_record(parent='{"id": "PARENT1"}'))

    assert ou.parent == {"id": "PARENT1"}


def test_org_unit_parent_parsed_from_python_repr_string():
    """Test that a single-quoted Python dict repr parent string (not valid JSON) is parsed.

    This is the actual format the source pyramid parquet file stores `parent` in: a stringified
    Python dict repr, e.g. "{'id': 'PARENT1'}", which `json.loads` cannot parse (JSON requires
    double-quoted keys/strings).
    """
    ou = OrgUnit.model_validate(_base_record(parent="{'id': 'PARENT1'}"))

    assert ou.parent == {"id": "PARENT1"}


def test_org_unit_parent_none_stays_none():
    """Test that a missing parent stays None instead of raising."""
    ou = OrgUnit.model_validate(_base_record(parent=None))

    assert ou.parent is None


def test_org_unit_nan_values_normalized_to_none():
    """Test that bare float NaN (pandas' None-in-an-object-column stand-in) is treated as absent.

    A pandas DataFrame built from records containing None can silently turn those into
    float('nan') (e.g. via to_dict(orient="records")); without normalization this would either
    raise a ValidationError (for dict-typed fields) or leak the literal text "NaN" into to_json().
    """
    ou = OrgUnit.model_validate(_base_record(closedDate=float("nan"), parent=float("nan"), geometry=float("nan")))

    assert ou.closed_date is None
    assert ou.parent is None
    assert ou.geometry is None
    assert ou.to_json() == {
        "id": "OU001",
        "name": "District 1",
        "shortName": "D1",
        "openingDate": "2020-01-01",
    }


def test_org_unit_is_valid_true_when_required_fields_set():
    """Test is_valid() returns True when id/name/short_name/opening_date are all set."""
    ou = OrgUnit.model_validate(_base_record())

    assert ou.is_valid() is True


@pytest.mark.parametrize("field", ["id", "name", "shortName", "openingDate"])
@pytest.mark.parametrize("missing_value", [None, float("nan"), ""], ids=["none", "nan", "empty-string"])
def test_org_unit_is_valid_false_when_required_field_is_missing(field: str, missing_value: object):
    """Test is_valid() returns False when a required field is None, NaN, or an empty string."""
    ou = OrgUnit.model_validate(_base_record(**{field: missing_value}))

    assert ou.is_valid() is False


def test_org_unit_to_json_omits_absent_optional_fields():
    """Test to_json() omits closedDate/parent/geometry when they are absent."""
    ou = OrgUnit.model_validate(_base_record())

    payload = ou.to_json()

    assert payload == {
        "id": "OU001",
        "name": "District 1",
        "shortName": "D1",
        "openingDate": "2020-01-01",
    }


def test_org_unit_to_json_round_trips_polygon_and_multipolygon_geometry():
    """Test that Polygon/MultiPolygon geometries (deeper nesting than Point) round-trip correctly."""
    polygon = {"type": "Polygon", "coordinates": [[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [1.0, 2.0]]]}
    multipolygon = {
        "type": "MultiPolygon",
        "coordinates": [[[[1.0, 2.0], [3.0, 4.0]]], [[[7.0, 8.0], [9.0, 10.0]]]],
    }

    ou_polygon = OrgUnit.model_validate(_base_record(geometry=polygon))
    ou_multipolygon = OrgUnit.model_validate(_base_record(geometry=multipolygon))

    assert ou_polygon.to_json()["geometry"] == polygon
    assert ou_multipolygon.to_json()["geometry"] == multipolygon


def test_org_unit_to_json_includes_present_optional_fields():
    """Test to_json() includes closedDate/parent/geometry with the correct shaping when present."""
    geometry = {"type": "Point", "coordinates": [1.0, 2.0], "extraneousKey": "ignored"}
    ou = OrgUnit.model_validate(
        _base_record(
            closedDate="2024-01-01",
            parent={"id": "PARENT001", "name": "Parent OU"},
            geometry=geometry,
        )
    )

    payload = ou.to_json()

    assert payload["closedDate"] == "2024-01-01"
    assert payload["parent"] == {"id": "PARENT001"}
    assert payload["geometry"] == {"type": "Point", "coordinates": [1.0, 2.0]}


def test_org_unit_equality_ignores_level_and_path():
    """Test that two OrgUnits with different level/path but same other fields compare equal."""
    ou_a = OrgUnit.model_validate(_base_record(level=2, path="/COUNTRY/OU001"))
    ou_b = OrgUnit.model_validate(_base_record(level=3, path="/COUNTRY/REGION/OU001"))

    assert ou_a == ou_b


def test_org_unit_equality_detects_changed_attribute():
    """Test that two OrgUnits differing on a compared attribute are not equal."""
    ou_a = OrgUnit.model_validate(_base_record(name="District 1"))
    ou_b = OrgUnit.model_validate(_base_record(name="District 1 renamed"))

    assert ou_a != ou_b


@pytest.mark.parametrize("other", [None, "not an OrgUnit", 42, {"id": "OU001"}])
def test_org_unit_equality_raises_when_compared_with_a_different_type(other: object):
    """Test that comparing an OrgUnit with a non-OrgUnit value raises OrgUnitError."""
    ou = OrgUnit.model_validate(_base_record())

    with pytest.raises(OrgUnitError, match=r"Cannot compare OrgUnit with"):
        _ = ou == other

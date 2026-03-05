from unittest.mock import patch

import polars as pl

from d2d_development.extract import DHIS2Extractor
from d2d_development.push import DHIS2Pusher
from tests.mock_dhis2_get import MockDHIS2Client
from tests.mock_dhis2_post import MOCK_DHIS2_OK_RESPONSE, MockDHIS2Response


def test_push_serialize_data_point_valid():
    """Test the serialization of a DataPointModel to JSON format for DHIS2."""
    data_point = (
        DHIS2Extractor(dhis2_client=MockDHIS2Client())
        .data_elements._retrieve_data(data_elements=["AAA111"], org_units=[], period="202501")
        .slice(0, 1)
    )

    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    json_payload = pusher._serialize_data_points(data_point)

    assert json_payload[0]["dataElement"] == "AAA111"
    assert json_payload[0]["period"] == "202501"
    assert json_payload[0]["orgUnit"] == "ORG001"
    assert json_payload[0]["categoryOptionCombo"] == "CAT001"
    assert json_payload[0]["attributeOptionCombo"] == "ATTR001"
    assert json_payload[0]["value"] == "12"


def test_push_serialize_data_point_to_delete():
    """Test the serialization of a DataPointModel to delete JSON format for DHIS2."""
    data_point = (
        DHIS2Extractor(dhis2_client=MockDHIS2Client())
        .data_elements._retrieve_data(data_elements=["AAA111"], org_units=[], period="202501")
        .slice(3, 1)
    )

    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    json_payload = pusher._serialize_data_points(data_point)

    assert json_payload[0]["dataElement"] == "DELETE1"
    assert json_payload[0]["period"] == "202501"
    assert json_payload[0]["orgUnit"] == "ORG004"
    assert json_payload[0]["categoryOptionCombo"] == "CAT004"
    assert json_payload[0]["attributeOptionCombo"] == "ATTR004"
    assert not json_payload[0]["value"]
    assert json_payload[0]["comment"] == "deleted value"


def test_push_classify_points():
    """Test the mapping of data elements."""
    data_points = DHIS2Extractor(dhis2_client=MockDHIS2Client()).data_elements._retrieve_data(
        data_elements=["AAA111", "BBB222", "CCC333"], org_units=[], period="202501"
    )
    assert isinstance(data_points, pl.DataFrame)
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    valid, to_delete, not_valid = pusher._classify_data_points(data_points)

    # Verify no overlaps and all rows accounted for
    assert len(valid) + len(to_delete) + len(not_valid) == len(data_points), (
        "Row count mismatch! Check for overlaps or missing rows."
    )
    assert len(valid) == 3, "Expected 3 valid data points."
    assert len(to_delete) == 1, "Expected 1 data point marked for deletion"
    assert len(not_valid) == 5, "Expected 4 invalid data points."


def test_push_data_points():
    """Test the push of data points to DHIS2."""
    data_points = DHIS2Extractor(dhis2_client=MockDHIS2Client()).data_elements._retrieve_data(
        data_elements=["AAA111"], org_units=[], period="202501"
    )
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())

    valid, _, _ = pusher._classify_data_points(data_points=data_points)
    valid_data_points = pusher._serialize_data_points(valid)

    with patch.object(pusher.dhis2_client.api.session, "post", return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE)):
        pusher._push_data_points(valid_data_points)
        print(pusher.summary)
        assert pusher.summary["import_counts"]["imported"] == 1

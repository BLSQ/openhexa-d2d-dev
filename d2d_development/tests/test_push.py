from unittest.mock import patch

import polars as pl
import pytest

from d2d_development.extract import DHIS2Extractor
from d2d_development.push import DHIS2Pusher, PusherError
from tests.mock_dhis2_get import MockDHIS2Client
from tests.mock_dhis2_post import (
    MOCK_DHIS2_ERROR_409_RESPONSE_AOC,
    MOCK_DHIS2_ERROR_409_RESPONSE_COC,
    MOCK_DHIS2_ERROR_409_RESPONSE_DE,
    MOCK_DHIS2_ERROR_409_RESPONSE_ORG_UNITS,
    MOCK_DHIS2_ERROR_409_RESPONSE_PERIOD,
    MOCK_DHIS2_ERROR_409_RESPONSE_VALUE_FORMAT,
    MOCK_DHIS2_ERROR_503_RESPONSE,
    MOCK_DHIS2_OK_RESPONSE,
    MockDHIS2Response,
)


def test_push_no_data_to_push():
    """Test the push of data points to DHIS2."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    cols = ["dx", "period", "orgUnit", "categoryOptionCombo", "attributeOptionCombo", "value"]
    empty_df = pl.DataFrame({col: [] for col in cols})
    # pusher.push_data(empty_df)
    with patch("d2d_development.push.current_run.log_info") as mock_log_info:
        pusher.push_data(empty_df)
        mock_log_info.assert_any_call("Input DataFrame is empty. No data to push.")
    assert pusher.summary["import_counts"]["imported"] == 0


def test_push_missing_mandatory_columns():
    """Test the push of data points to DHIS2."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    cols = ["period", "orgUnit", "categoryOptionCombo", "attributeOptionCombo", "value"]
    empty_df = pl.DataFrame({col: [] for col in cols})
    with pytest.raises(PusherError, match=r"Input data is missing mandatory columns: dx"):
        pusher.push_data(df_data=empty_df)


def test_push_wrong_input_type():
    """Test the push of data points to DHIS2."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    with pytest.raises(PusherError, match=r"Input data must be a pandas or polars DataFrame."):
        pusher.push_data(df_data=[])
    with pytest.raises(PusherError, match=r"Input data must be a pandas or polars DataFrame."):
        pusher.push_data(df_data="not a dataframe")
    with pytest.raises(PusherError, match=r"Input data must be a pandas or polars DataFrame."):
        pusher.push_data(df_data={})


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


def test_push_data_point():
    """Test the push of data points to DHIS2."""
    # 1 valid datapoint
    data_points = (
        DHIS2Extractor(dhis2_client=MockDHIS2Client())
        .data_elements._retrieve_data(data_elements=["AAA111"], org_units=[], period="202501")
        .slice(0, 1)
    )

    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    # MOCK_DHIS2_OK_RESPONSE was manually manufactured to simulate a successful import response from DHIS2 for tests
    with patch.object(pusher.dhis2_client.api.session, "post", return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE)):
        pusher.push_data(data_points)
        assert pusher.summary["import_counts"]["imported"] == 1
        assert pusher.summary["import_counts"]["ignored"] == 0
        assert pusher.summary["import_counts"]["updated"] == 0
        assert pusher.summary["import_counts"]["deleted"] == 0
        assert pusher.summary["import_options"] == {
            "importStrategy": "CREATE_AND_UPDATE",
            "dryRun": True,
            "preheatCache": True,
            "skipAudit": True,
        }


def test_push_data_points_connection_error():
    """Test the error handling of error 503 to DHIS2."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_ERROR_503_RESPONSE, status_code=503),
    ):
        with pytest.raises(PusherError, match=r"Server error: Service temporarily unavailable"):
            pusher._push_data_points([{"dummy_datapoint": "1"}])
        # After the exception, check the summary
        assert len(pusher.summary["ERRORS"]) == 1
        assert pusher.summary["ERRORS"][0]["message"] == "Server error: Service temporarily unavailable"
        assert pusher.summary["ERRORS"][0]["server_error_code"] == "503"


def test_push_data_points_data_element_error():
    """Test the error handling push of data points with wrong data elements."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())

    # NOTE: This fake input is just to pass validation and
    #  match the information manufactured in the response
    invalid_data_points = [
        {
            "dataElement": "VALID",
            "period": "202501",
            "orgUnit": "ORG001",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        {
            "dataElement": "INVALID_1",
            "period": "202501",
            "orgUnit": "ORG001",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        {
            "dataElement": "INVALID_2",
            "period": "202501",
            "orgUnit": "ORG001",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
    ]

    # MOCK_DHIS2_ERROR_409_RESPONSE_DE was manually manufactured to simulate a 409 Conflict from DHIS2.
    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_ERROR_409_RESPONSE_DE, status_code=409),
    ):
        pusher._push_data_points(invalid_data_points)  # access private method for error handling testing
        assert pusher.summary["import_counts"]["imported"] == 1
        assert pusher.summary["import_counts"]["updated"] == 0
        assert pusher.summary["import_counts"]["ignored"] == 2
        assert pusher.summary["import_counts"]["deleted"] == 0
        assert len(pusher.summary["ERRORS"]) == 2
        assert pusher.summary["ERRORS"][0]["object"] == "INVALID_1"
        assert pusher.summary["ERRORS"][1]["object"] == "INVALID_2"


def test_push_data_points_org_unit_error():
    """Test the error handling push of data points with wrong org units."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())

    # NOTE: This fake input is just to pass validation and
    #  match the information manufactured in the response
    invalid_data_points = [
        {
            "dataElement": "VALID",
            "period": "202501",
            "orgUnit": "ORG001",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        {
            "dataElement": "VALID",
            "period": "202501",
            "orgUnit": "INVALID_1",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        {
            "dataElement": "VALID",
            "period": "202501",
            "orgUnit": "INVALID_2",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
    ]

    # MOCK_DHIS2_ERROR_409_RESPONSE_ORG_UNITS was manually manufactured to simulate a Conflict from DHIS2.
    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_ERROR_409_RESPONSE_ORG_UNITS, status_code=409),
    ):
        pusher._push_data_points(invalid_data_points)  # access private method for error handling testing
        assert pusher.summary["import_counts"]["imported"] == 1
        assert pusher.summary["import_counts"]["updated"] == 0
        assert pusher.summary["import_counts"]["ignored"] == 2
        assert pusher.summary["import_counts"]["deleted"] == 0
        assert len(pusher.summary["ERRORS"]) == 2
        assert pusher.summary["ERRORS"][0]["object"] == "INVALID_1_OU"
        assert pusher.summary["ERRORS"][1]["object"] == "INVALID_2_OU"


def test_push_data_points_period_error():
    """Test the error handling push of data points with wrong periods."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())

    # NOTE: This fake input is just to pass validation and
    #  match the information manufactured in the response
    invalid_data_points = [
        {
            "dataElement": "VALID",
            "period": "202501",
            "orgUnit": "ORG001",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        {
            "dataElement": "VALID",
            "period": "INVALID_PERIOD_1",
            "orgUnit": "VALID_OU",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        {
            "dataElement": "VALID",
            "period": "INVALID_PERIOD_2",
            "orgUnit": "VALID_OU",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
    ]

    # MOCK_DHIS2_ERROR_409_RESPONSE_PERIOD was manually manufactured to simulate a Conflict from DHIS2.
    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_ERROR_409_RESPONSE_PERIOD, status_code=409),
    ):
        pusher._push_data_points(invalid_data_points)  # access private method for error handling testing
        assert pusher.summary["import_counts"]["imported"] == 1
        assert pusher.summary["import_counts"]["updated"] == 0
        assert pusher.summary["import_counts"]["ignored"] == 2
        assert pusher.summary["import_counts"]["deleted"] == 0
        assert len(pusher.summary["ERRORS"]) == 2
        assert pusher.summary["ERRORS"][0]["object"] == "INVALID_PERIOD_1"
        assert pusher.summary["ERRORS"][1]["object"] == "INVALID_PERIOD_2"


def test_push_data_points_coc_error():
    """Test the error handling push of data points with wrong COC."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())

    # NOTE: This fake input is just to pass validation and
    #  match the information manufactured in the response
    invalid_data_points = [
        {
            "dataElement": "VALID1",
            "period": "202501",
            "orgUnit": "ORG001",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        {
            "dataElement": "VALID2",
            "period": "202501",
            "orgUnit": "ORG002",
            "categoryOptionCombo": "INVALID_COC_1",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        {
            "dataElement": "VALID3",
            "period": "202501",
            "orgUnit": "ORG003",
            "categoryOptionCombo": "INVALID_COC_2",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
    ]

    # MOCK_DHIS2_ERROR_409_RESPONSE_COC was manually manufactured to simulate a Conflict from DHIS2.
    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_ERROR_409_RESPONSE_COC, status_code=409),
    ):
        pusher._push_data_points(invalid_data_points)  # access private method for error handling testing
        assert pusher.summary["import_counts"]["imported"] == 1
        assert pusher.summary["import_counts"]["updated"] == 0
        assert pusher.summary["import_counts"]["ignored"] == 2
        assert pusher.summary["import_counts"]["deleted"] == 0
        assert len(pusher.summary["ERRORS"]) == 2
        assert pusher.summary["ERRORS"][0]["object"] == "INVALID_COC_1"
        assert pusher.summary["ERRORS"][1]["object"] == "INVALID_COC_2"


def test_push_data_points_aoc_error():
    """Test the error handling push of data points with wrong AOC."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())

    # NOTE: This fake input is just to pass validation and
    #  match the information manufactured in the response
    invalid_data_points = [
        {
            "dataElement": "VALID1",
            "period": "202501",
            "orgUnit": "ORG001",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        {
            "dataElement": "VALID2",
            "period": "202501",
            "orgUnit": "ORG002",
            "categoryOptionCombo": "INVALID_AOC_1",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        {
            "dataElement": "VALID3",
            "period": "202501",
            "orgUnit": "ORG003",
            "categoryOptionCombo": "INVALID_AOC_2",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
    ]

    # MOCK_DHIS2_ERROR_409_RESPONSE_AOC was manually manufactured to simulate a Conflict from DHIS2.
    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_ERROR_409_RESPONSE_AOC, status_code=409),
    ):
        pusher._push_data_points(invalid_data_points)  # access private method for error handling testing
        assert pusher.summary["import_counts"]["imported"] == 1
        assert pusher.summary["import_counts"]["updated"] == 0
        assert pusher.summary["import_counts"]["ignored"] == 2
        assert pusher.summary["import_counts"]["deleted"] == 0
        assert len(pusher.summary["ERRORS"]) == 2
        assert pusher.summary["ERRORS"][0]["object"] == "INVALID_AOC_1"
        assert pusher.summary["ERRORS"][1]["object"] == "INVALID_AOC_2"


def test_push_data_points_value_format_error():
    """Test the error handling push of data points with value not numeric."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())

    # NOTE: This fake input is just to pass validation and
    #  match the information manufactured in the response
    invalid_data_points = [
        {
            "dataElement": "VALID1",
            "period": "202501",
            "orgUnit": "ORG001",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        {
            "dataElement": "VALID2",
            "period": "202501",
            "orgUnit": "ORG002",
            "categoryOptionCombo": "CAT002",
            "attributeOptionCombo": "ATTR002",
            "value": "0.0000e15",  # Non numeric format for DHIS2 API
        },
        {
            "dataElement": "VALID3",
            "period": "202501",
            "orgUnit": "ORG003",
            "categoryOptionCombo": "CAT003",
            "attributeOptionCombo": "ATTR003",
            "value": "1",
        },
    ]

    # MOCK_DHIS2_ERROR_409_RESPONSE_VALUE_FORMAT was manually manufactured to simulate a Conflict from DHIS2.
    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_ERROR_409_RESPONSE_VALUE_FORMAT, status_code=409),
    ):
        pusher._push_data_points(invalid_data_points)  # access private method for error handling testing
        assert pusher.summary["import_counts"]["imported"] == 2
        assert pusher.summary["import_counts"]["updated"] == 0
        assert pusher.summary["import_counts"]["ignored"] == 1
        assert pusher.summary["import_counts"]["deleted"] == 0
        assert len(pusher.summary["ERRORS"]) == 1
        assert pusher.summary["ERRORS"][0]["object"] == "VALID2"

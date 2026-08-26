from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest

from d2d_development.extract import DHIS2Extractor
from d2d_development.push import DHIS2Pusher, PusherError
from d2d_development.push_cache import DHIS2PushCache
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
    cols = [
        "dx",
        "period",
        "org_unit",
        "category_option_combo",
        "attribute_option_combo",
        "value",
    ]
    empty_df = pl.DataFrame({col: [] for col in cols})
    with patch.object(DHIS2Pusher, "_log_message") as mock_log_message:
        pusher.push_data(empty_df)
        mock_log_message.assert_any_call("Input DataFrame is empty. No data to push.")
    assert pusher.summary["import_counts"]["imported"] == 0


def test_push_missing_mandatory_columns():
    """Test the push of data points to DHIS2."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    cols = ["period", "org_unit", "category_option_combo", "attribute_option_combo", "value"]
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
        .slice(4, 1)
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
    assert len(valid) == 4, "Expected 4 valid data points."
    assert len(to_delete) == 1, "Expected 1 data point marked for deletion"
    assert len(not_valid) == 5, "Expected 4 invalid data points."


def test_push_log_invalid_data_points():
    """Test the logging of invalid data points."""
    data_points = (
        DHIS2Extractor(dhis2_client=MockDHIS2Client())
        .data_elements._retrieve_data(data_elements=[], org_units=[], period="202501")
        .slice(5, 4)  # Select invalid data points (rows 4 to 7) for testing
    )
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    _, _, not_valid = pusher._classify_data_points(data_points)

    with patch.object(pusher, "_log_message") as mock_log_message:
        pusher._log_ignored_or_na(not_valid)
        assert mock_log_message.call_count == 5, "Expected a log message for each invalid data point."
        for idx, call in enumerate(mock_log_message.call_args_list):
            if idx == 0:
                log_message = call.args[0]
                assert "4 data points will be ignored" in log_message, f"Unexpected log message: {log_message}"
            else:
                log_message = call.args[0]
                assert f"Data point ignored: dx=INVALID{idx}" in log_message, f"Unexpected log message: {log_message}"
        # Extra check for number of ignored data points in summary
        assert "ignored_data_points" in pusher.summary, "summary should contain 'ignored_data_points' key"
        assert len(pusher.summary["ignored_data_points"]) == 4, "Expected 4 ignored data points in summary"


def test_push_log_delete_data_points():
    """Test the logging of invalid data points."""
    data_points = (
        DHIS2Extractor(dhis2_client=MockDHIS2Client())
        .data_elements._retrieve_data(data_elements=[], org_units=[], period="202501")
        .slice(4, 1)  # Select invalid data points (rows 4 to 7) for testing
    )
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    _, to_delete, _ = pusher._classify_data_points(data_points)

    with patch.object(pusher, "_log_message") as mock_log_message:
        pusher._log_ignored_or_na(to_delete, is_na=True)
        assert mock_log_message.call_count == 2, "Expected a log message for each invalid data point."
        for idx, call in enumerate(mock_log_message.call_args_list):
            if idx == 0:
                log_message = call.args[0]
                assert "1 data points will be set to NA" in log_message, f"Unexpected log message: {log_message}"
            else:
                log_message = call.args[0]
                assert "Data point NA: dx=DELETE1" in log_message, f"Unexpected log message: {log_message}"
        # Extra check for number of ignored data points in summary
        assert "delete_data_points" in pusher.summary, "summary should contain 'delete_data_points' key"
        assert len(pusher.summary["delete_data_points"]) == 1, "Expected 4 ignored data points in summary"


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
    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE),
    ):
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
        assert len(pusher.summary["import_errors"]) == 1
        assert pusher.summary["import_errors"][0]["message"] == "Server error: Service temporarily unavailable"
        assert pusher.summary["import_errors"][0]["server_error_code"] == "503"


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
        assert len(pusher.summary["import_errors"]) == 2
        assert pusher.summary["import_errors"][0]["object"] == "INVALID_1"
        assert pusher.summary["import_errors"][1]["object"] == "INVALID_2"


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
        assert len(pusher.summary["import_errors"]) == 2
        assert pusher.summary["import_errors"][0]["object"] == "INVALID_1_OU"
        assert pusher.summary["import_errors"][1]["object"] == "INVALID_2_OU"


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
        assert len(pusher.summary["import_errors"]) == 2
        assert pusher.summary["import_errors"][0]["object"] == "INVALID_PERIOD_1"
        assert pusher.summary["import_errors"][1]["object"] == "INVALID_PERIOD_2"


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
        assert len(pusher.summary["import_errors"]) == 2
        assert pusher.summary["import_errors"][0]["object"] == "INVALID_COC_1"
        assert pusher.summary["import_errors"][1]["object"] == "INVALID_COC_2"


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
        assert len(pusher.summary["import_errors"]) == 2
        assert pusher.summary["import_errors"][0]["object"] == "INVALID_AOC_1"
        assert pusher.summary["import_errors"][1]["object"] == "INVALID_AOC_2"


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
        assert len(pusher.summary["import_errors"]) == 1
        assert pusher.summary["import_errors"][0]["object"] == "VALID2"


def test_push_summary_rejected_points():
    """Test that rejected data points are correctly tracked in the summary."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    # NOTE: This fake input is just to pass validation and
    #  match the information manufactured in the response
    invalid_dp_1 = {
        "dataElement": "VALID2",
        "period": "202501",
        "orgUnit": "ORG002",
        "categoryOptionCombo": "INVALID_AOC_1",
        "attributeOptionCombo": "ATTR001",
        "value": "1",
    }
    invalid_dp_2 = {
        "dataElement": "VALID3",
        "period": "202501",
        "orgUnit": "ORG003",
        "categoryOptionCombo": "INVALID_AOC_2",
        "attributeOptionCombo": "ATTR001",
        "value": "1",
    }
    invalid_data_points = [
        {
            "dataElement": "VALID1",
            "period": "202501",
            "orgUnit": "ORG001",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "1",
        },
        invalid_dp_1,
        invalid_dp_2,
    ]

    # MOCK_DHIS2_ERROR_409_RESPONSE_AOC was manually manufactured to simulate a Conflict from DHIS2.
    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_ERROR_409_RESPONSE_AOC, status_code=409),
    ):
        pusher._push_data_points(invalid_data_points)  # access private method for error handling testing
        assert pusher.summary["rejected_datapoints"][0] == invalid_dp_1
        assert pusher.summary["rejected_datapoints"][1] == invalid_dp_2


def test_remove_rejected_points_matches_by_datapoint_identity():
    """Test that _remove_rejected_points() removes rejected rows from data by their actual identity.

    rejected_datapoints entries are the serialized DHIS2 payload (DHIS2-cased keys), so this also
    locks in that they get correctly remapped to the internal snake_case key columns before matching.
    """
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    data = pl.DataFrame(
        {
            "dx": ["AAA111", "BBB222", "CCC333"],
            "period": ["202501", "202501", "202501"],
            "org_unit": ["ORG001", "ORG002", "ORG003"],
            "category_option_combo": ["CAT001", "CAT002", "CAT003"],
            "attribute_option_combo": ["ATTR001", "ATTR002", "ATTR003"],
            "value": ["10", "20", "30"],
        }
    )
    pusher.summary["rejected_datapoints"] = [
        {
            "dataElement": "AAA111",
            "period": "202501",
            "orgUnit": "ORG001",
            "categoryOptionCombo": "CAT001",
            "attributeOptionCombo": "ATTR001",
            "value": "10",
        },
        {
            "dataElement": "BBB222",
            "period": "202501",
            "orgUnit": "ORG002",
            "categoryOptionCombo": "CAT002",
            "attributeOptionCombo": "ATTR002",
            "value": "20",
        },
    ]

    result = pusher._remove_rejected_points(data)

    assert result.height == 1
    assert result["dx"].to_list() == ["CCC333"]


def test_remove_rejected_points_with_no_rejections_returns_data_unchanged():
    """Test that _remove_rejected_points() returns the input unchanged when nothing was rejected."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client())
    data = pl.DataFrame(
        {
            "dx": ["AAA111"],
            "period": ["202501"],
            "org_unit": ["ORG001"],
            "category_option_combo": ["CAT001"],
            "attribute_option_combo": ["ATTR001"],
            "value": ["10"],
        }
    )

    result = pusher._remove_rejected_points(data)

    assert result.height == 1
    assert result["dx"].to_list() == ["AAA111"]


def test_push_data_with_cache_skips_unchanged_datapoints_on_second_run(tmp_path: Path):
    """Test that a second push_data() call with a real cache_path skips datapoints unchanged since the first."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client(), cache_path=tmp_path, dry_run=False)
    data = pl.DataFrame(
        {
            "dx": ["AAA111", "BBB222"],
            "period": ["202501", "202501"],
            "org_unit": ["ORG001", "ORG002"],
            "category_option_combo": ["CAT001", "CAT002"],
            "attribute_option_combo": ["ATTR001", "ATTR002"],
            "value": ["10", "20"],
        }
    )

    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE),
    ) as mock_post:
        pusher.push_data(data)
        assert mock_post.call_count == 1

        pusher.push_data(data)  # same data again - nothing changed since the first run
        assert mock_post.call_count == 1, "No new POST should happen: both datapoints were already cached."


def test_push_data_with_cache_writes_pushed_datapoints_to_disk(tmp_path: Path):
    """Test that a successful push_data() call with cache_path persists the pushed datapoints to disk."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client(), cache_path=tmp_path, dry_run=False)
    data = pl.DataFrame(
        {
            "dx": ["AAA111"],
            "period": ["202501"],
            "org_unit": ["ORG001"],
            "category_option_combo": ["CAT001"],
            "attribute_option_combo": ["ATTR001"],
            "value": ["10"],
        }
    )

    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE),
    ):
        pusher.push_data(data)

    # read back the cache independently, from a fresh instance, to confirm it was actually persisted to disk
    cache = DHIS2PushCache(cache_path=tmp_path)
    cache._load(["202501"])
    assert cache._cache_data is not None
    assert cache._cache_data["dx"].to_list() == ["AAA111"]
    assert cache._cache_data["value"].to_list() == ["10"]


def test_push_data_with_cache_excludes_rejected_datapoint_from_disk_cache(tmp_path: Path):
    """Test that a datapoint rejected by DHIS2 is excluded from the cache, while accepted ones are kept."""
    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client(), cache_path=tmp_path, dry_run=False)
    data = pl.DataFrame(
        {
            "dx": ["VALID1", "VALID2", "VALID3"],
            "period": ["202501", "202501", "202501"],
            "org_unit": ["ORG001", "ORG002", "ORG003"],
            "category_option_combo": ["CAT001", "CAT002", "CAT003"],
            "attribute_option_combo": ["ATTR001", "ATTR002", "ATTR003"],
            "value": ["1", "0.0000e15", "1"],  # VALID2's value format gets rejected by DHIS2
        }
    )

    # MOCK_DHIS2_ERROR_409_RESPONSE_VALUE_FORMAT rejects the datapoint at index 1 (VALID2)
    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_ERROR_409_RESPONSE_VALUE_FORMAT, status_code=409),
    ):
        pusher.push_data(data)

    cache = DHIS2PushCache(cache_path=tmp_path)
    cache._load(["202501"])
    assert cache._cache_data is not None
    assert sorted(cache._cache_data["dx"].to_list()) == ["VALID1", "VALID3"]


def test_push_data_with_dry_run_bypasses_cache_entirely(tmp_path: Path):
    """Test that dry_run=True disables the cache even when a cache_path is given.

    Seeds the cache with AAA111=10 and BBB222=20, then pushes AAA111=10 (unchanged) and
    BBB222=99 (changed) with dry_run=True. If the cache were active, filter_new() would drop
    AAA111 as unchanged and only push BBB222. With the cache disabled, both rows must be pushed
    unfiltered, and the on-disk cache must remain exactly as seeded.
    """
    seed_cache = DHIS2PushCache(cache_path=tmp_path)
    seed_cache.mark_pushed(
        pl.DataFrame(
            {
                "dx": ["AAA111", "BBB222"],
                "period": ["202501", "202501"],
                "org_unit": ["ORG001", "ORG002"],
                "category_option_combo": ["CAT001", "CAT002"],
                "attribute_option_combo": ["ATTR001", "ATTR002"],
                "value": ["10", "20"],
            }
        )
    )

    pusher = DHIS2Pusher(dhis2_client=MockDHIS2Client(), cache_path=tmp_path, dry_run=True)
    assert pusher.push_cache is None

    data = pl.DataFrame(
        {
            "dx": ["AAA111", "BBB222"],
            "period": ["202501", "202501"],
            "org_unit": ["ORG001", "ORG002"],
            "category_option_combo": ["CAT001", "CAT002"],
            "attribute_option_combo": ["ATTR001", "ATTR002"],
            "value": ["10", "99"],
        }
    )

    with patch.object(
        pusher.dhis2_client.api.session,
        "post",
        return_value=MockDHIS2Response(MOCK_DHIS2_OK_RESPONSE),
    ) as mock_post:
        pusher.push_data(data)

    pushed = mock_post.call_args.kwargs["json"]["dataValues"]
    assert sorted(dv["dataElement"] for dv in pushed) == ["AAA111", "BBB222"]

    cache_after = DHIS2PushCache(cache_path=tmp_path)
    cache_after._load(["202501"])
    cached = cache_after._cache_data.sort("dx")
    assert cached["dx"].to_list() == ["AAA111", "BBB222"]
    assert cached["value"].to_list() == ["10", "20"]

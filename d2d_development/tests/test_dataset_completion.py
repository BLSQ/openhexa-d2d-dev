from unittest.mock import MagicMock

import pytest
import requests

from d2d_development.dataset_completion import DatasetCompletionSync
from tests.mock_dhis2_responses import (
    MOCK_DHIS2_COMPLETION_200_IMP_RESPONSE_V2_37,
    MOCK_DHIS2_COMPLETION_200_IMP_RESPONSE_V2_40,
    MOCK_DHIS2_COMPLETION_200_UPD_RESPONSE_V2_37,
    MOCK_DHIS2_COMPLETION_200_UPD_RESPONSE_V2_40,
    MOCK_DHIS2_COMPLETION_CONFLICT_409_DS_RESPONSE_V2_37,
    MOCK_DHIS2_COMPLETION_CONFLICT_409_DS_RESPONSE_V2_40,
    MOCK_DHIS2_COMPLETION_CONFLICT_409_OU_RESPONSE_V2_37,
    MOCK_DHIS2_COMPLETION_CONFLICT_409_OU_RESPONSE_V2_40,
    MOCK_DHIS2_COMPLETION_CONFLICT_409_PE_RESPONSE_V2_37,
    MOCK_DHIS2_COMPLETION_CONFLICT_409_PE_RESPONSE_V2_40,
    MOCK_DHIS2_COMPLETION_EMPTY_RESPONSE,
)

# TODO: missing test for processing file load and save.


def test_log_and_append_error_updates_summary_and_logs():
    """Test that _log_and_append_error correctly updates the import summary and logs the error."""
    # Arrange
    dummy_logger = MagicMock()
    sync = DatasetCompletionSync(
        source_dhis2=None,  # You can use None or a mock if not used in this test
        target_dhis2=None,
        logger=dummy_logger,
    )
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync._log_and_append_error(error_type="fetch_errors", ds="DS1", pe="202601", ou="OU1", error_msg="Test error")

    # Assert
    assert sync.import_summary["errors"]["fetch_errors"] == [
        {"ds": "DS1", "pe": "202601", "ou": "OU1", "error": "Test error"}
    ]
    sync.log_function.assert_called_once()
    log_args = sync.log_function.call_args[1]
    assert "[fetch_errors]" in log_args["message"]
    assert "DS1" in log_args["message"]
    assert "Test error" in log_args["message"]


def test_log_and_append_error_different_types():
    """Test that _log_and_append_error can handle different error types."""
    sync = DatasetCompletionSync(None, None)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync._log_and_append_error("push_errors", "DS2", "202602", "OU2", "Push error")
    assert sync.import_summary["errors"]["push_errors"] == [
        {"ds": "DS2", "pe": "202602", "ou": "OU2", "error": "Push error"}
    ]


def test_log_and_append_error_log_level_and_flag():
    """Test that _log_and_append_error correctly handles log level and log_current_run flag."""
    sync = DatasetCompletionSync(None, None)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync._log_and_append_error(
        "fetch_errors", "DS4", "202604", "OU4", "Another error", level="warning", log_current_run=True
    )
    log_args = sync.log_function.call_args[1]
    assert log_args["level"] == "warning"
    assert log_args["log_current_run"] is True


def test_log_and_append_error_multiple_errors():
    """Test that multiple calls to _log_and_append_error append errors correctly."""
    sync = DatasetCompletionSync(None, None)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync._log_and_append_error("fetch_errors", "DS5", "202605", "OU5", "First error")
    sync._log_and_append_error("fetch_errors", "DS5", "202605", "OU6", "Second error")
    assert len(sync.import_summary["errors"]["fetch_errors"]) == 2


@pytest.mark.parametrize(
    "mock_response", [MOCK_DHIS2_COMPLETION_200_IMP_RESPONSE_V2_37, MOCK_DHIS2_COMPLETION_200_IMP_RESPONSE_V2_40]
)
def test_sync_completion_post_import_success_response(mock_response: dict):
    """Test that _sync_completion handles an import response correctly."""
    dhis2_source = MagicMock()
    dhis2_target = MagicMock()
    # Mock GET response
    mock_get_response = MagicMock()
    mock_get_response.json.return_value = {
        "completeDataSetRegistrations": [
            {
                "period": "202601",
                "dataSet": "DS1",
                "organisationUnit": "ou1",
                "attributeOptionCombo": "HllvX50cXC0",
                "date": "2026-01-31",
                "storedBy": "OpenHexa",
                "completed": True,
            }
        ]
    }
    dhis2_source.api.session.get.return_value = mock_get_response

    # Mock POST response
    mock_post_response = MagicMock()
    mock_post_response.json.return_value = mock_response
    dhis2_target.api.session.post.return_value = mock_post_response

    # Run the sync method
    sync = DatasetCompletionSync(dhis2_source, dhis2_target)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync.sync(source_dataset_id="DS1", target_dataset_id="DS2", org_units=["ou1"], period="202601")
    assert sync.import_summary["import_counts"]["imported"] == 1
    assert sync.import_summary["import_counts"]["updated"] == 0
    assert sync.import_summary["import_counts"]["ignored"] == 0
    assert sync.import_summary["import_counts"]["deleted"] == 0


@pytest.mark.parametrize(
    "mock_response", [MOCK_DHIS2_COMPLETION_200_UPD_RESPONSE_V2_37, MOCK_DHIS2_COMPLETION_200_UPD_RESPONSE_V2_40]
)
def test_sync_completion_post_update_success_response(mock_response: dict):
    """Test that sync completion handles an update response correctly."""
    dhis2_source = MagicMock()
    dhis2_target = MagicMock()
    # Mock GET response
    mock_get_response = MagicMock()
    mock_get_response.json.return_value = {
        "completeDataSetRegistrations": [
            {
                "period": "202601",
                "dataSet": "DS1",
                "organisationUnit": "ou1",
                "attributeOptionCombo": "HllvX50cXC0",
                "date": "2026-01-31",
                "storedBy": "OpenHexa",
                "completed": True,
            }
        ]
    }
    dhis2_source.api.session.get.return_value = mock_get_response

    # Mock POST response
    mock_post_response = MagicMock()
    mock_post_response.json.return_value = mock_response
    dhis2_target.api.session.post.return_value = mock_post_response

    # Run the sync method
    sync = DatasetCompletionSync(dhis2_source, dhis2_target)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync.sync(source_dataset_id="DS1", target_dataset_id="DS2", org_units=["ou1"], period="202601")
    assert sync.import_summary["import_counts"]["imported"] == 0
    assert sync.import_summary["import_counts"]["updated"] == 1
    assert sync.import_summary["import_counts"]["ignored"] == 0
    assert sync.import_summary["import_counts"]["deleted"] == 0


def test_sync_completion_post_error_empty_json():
    """Test the sync completion handles an empty JSON response gracefully."""
    dhis2_source = MagicMock()
    dhis2_target = MagicMock()
    # Mock GET response
    mock_get_response = MagicMock()
    mock_get_response.json.return_value = {
        "completeDataSetRegistrations": [
            {
                "period": "202601",
                "dataSet": "DS1",
                "organisationUnit": "ou1",
                "attributeOptionCombo": "HllvX50cXC0",
                "date": "2026-01-31",
                "storedBy": "OpenHexa",
                "completed": True,
            }
        ]
    }
    dhis2_source.api.session.get.return_value = mock_get_response

    # Mock POST response
    mock_post_response = MagicMock()
    mock_post_response.json.return_value = MOCK_DHIS2_COMPLETION_EMPTY_RESPONSE
    dhis2_target.api.session.post.return_value = mock_post_response

    # Run the sync method
    sync = DatasetCompletionSync(dhis2_source, dhis2_target)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync.sync(source_dataset_id="DS1", target_dataset_id="DS2", org_units=["ou1"], period="202601")
    assert sync.import_summary["import_counts"]["imported"] == 0
    assert sync.import_summary["import_counts"]["updated"] == 0
    assert sync.import_summary["import_counts"]["ignored"] == 0
    assert sync.import_summary["import_counts"]["deleted"] == 0
    assert sync.import_summary["errors"]["push_errors"] == [
        {"ds": "DS2", "pe": "202601", "ou": "ou1", "error": "No JSON response received for completion request"}
    ]


@pytest.mark.parametrize(
    "mock_response,expected_error",  # noqa: PT006
    [
        # v2.37
        (
            MOCK_DHIS2_COMPLETION_CONFLICT_409_OU_RESPONSE_V2_37,
            "{'object': 'WRONG', 'value': 'Organisation unit not found or not accessible'}",
        ),
        (MOCK_DHIS2_COMPLETION_CONFLICT_409_PE_RESPONSE_V2_37, "{'object': 'WRONG', 'value': 'Period not valid'}"),
        (
            MOCK_DHIS2_COMPLETION_CONFLICT_409_DS_RESPONSE_V2_37,
            "{'object': 'WRONG', 'value': 'Data set not found or not accessible'}",
        ),
        # v2.40
        (
            MOCK_DHIS2_COMPLETION_CONFLICT_409_OU_RESPONSE_V2_40,
            "{'object': 'WRONG', 'value': 'Organisation unit not found or not accessible'}",
        ),
        (MOCK_DHIS2_COMPLETION_CONFLICT_409_PE_RESPONSE_V2_40, "{'object': 'WRONG', 'value': 'Period not valid'}"),
        (
            MOCK_DHIS2_COMPLETION_CONFLICT_409_DS_RESPONSE_V2_40,
            "{'value': 'Data set not found or not accessible'}",
        ),  # just different
    ],
)
def test_sync_completion_post_error_wrong_value(mock_response: dict, expected_error: str):
    """Test the sync completion handles a wrong value response.

    Values such as: ds id, ou and period produce a similar error.
    """
    dhis2_source = MagicMock()
    dhis2_target = MagicMock()
    # Mock GET response
    mock_get_response = MagicMock()
    mock_get_response.json.return_value = {
        "completeDataSetRegistrations": [
            {
                "period": "202601",
                "dataSet": "DS1",
                "organisationUnit": "ou1",
                "attributeOptionCombo": "HllvX50cXC0",
                "date": "2026-01-31",
                "storedBy": "OpenHexa",
                "completed": True,
            }
        ]
    }
    dhis2_source.api.session.get.return_value = mock_get_response

    # Mock POST response
    mock_post_response = MagicMock()
    mock_post_response.json.return_value = mock_response
    dhis2_target.api.session.post.return_value = mock_post_response

    # Run the sync method
    sync = DatasetCompletionSync(dhis2_source, dhis2_target)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync.sync(source_dataset_id="DS1", target_dataset_id="DS2", org_units=["ou1"], period="202601")
    assert sync.import_summary["import_counts"]["imported"] == 0
    assert sync.import_summary["import_counts"]["updated"] == 0
    assert sync.import_summary["import_counts"]["ignored"] == 1
    assert sync.import_summary["import_counts"]["deleted"] == 0
    error_entry = sync.import_summary["errors"]["push_errors"][0]
    assert expected_error in error_entry["error"]


def test_sync_completion_get_missing_key_error():
    """Test the sync completion handles an empty JSON response gracefully."""
    dhis2_source = MagicMock()
    dhis2_target = MagicMock()
    # Mock GET response
    mock_get_response = MagicMock()
    completion_source = {
        "completeDataSetRegistrations": [
            {
                "period": "202601",
                "dataSet": "DS1",
                "organisationUnit": "ou1",
                "attributeOptionCombo": "HllvX50cXC0",
                # "date": "2026-01-31", -> Missing 'date' field to simulate error
                "storedBy": "OpenHexa",
                "completed": True,
            }
        ]
    }
    mock_get_response.json.return_value = completion_source
    dhis2_source.api.session.get.return_value = mock_get_response

    # Run the sync method
    sync = DatasetCompletionSync(dhis2_source, dhis2_target)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync.sync(source_dataset_id="DS1", target_dataset_id="DS2", org_units=["ou1"], period="202601")
    assert sync.import_summary["import_counts"]["imported"] == 0
    assert sync.import_summary["import_counts"]["updated"] == 0
    assert sync.import_summary["import_counts"]["ignored"] == 0
    assert sync.import_summary["import_counts"]["deleted"] == 0
    assert sync.import_summary["errors"]["fetch_errors"] == [
        {
            "ds": "DS1",
            "pe": "202601",
            "ou": "ou1",
            "error": "Missing keys 'date' or 'completed' from completion response",
        }
    ]


def test_mark_uncompleted_as_processed_add_ou_processed_list():
    """Test that the mark_uncompleted_as_processed adds org units without completion to the processed list."""
    dhis2_source = MagicMock()
    dhis2_target = MagicMock()
    # Simulate no completion status for the org unit
    mock_get_response = MagicMock()
    mock_get_response.json.return_value = {"completeDataSetRegistrations": []}
    dhis2_source.api.session.get.return_value = mock_get_response
    dhis2_target.api.session.post = MagicMock()

    # Case 1: mark_uncompleted_as_processed=True
    sync = DatasetCompletionSync(dhis2_source, dhis2_target)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync.sync(
        source_dataset_id="DS1",
        target_dataset_id="DS2",
        org_units=["ou1"],
        period="202601",
        mark_uncompleted_as_processed=True,
    )
    assert "ou1" in sync.processed

    # Case 2: mark_uncompleted_as_processed=False
    sync = DatasetCompletionSync(dhis2_source, dhis2_target)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync.sync(
        source_dataset_id="DS1",
        target_dataset_id="DS2",
        org_units=["ou1"],
        period="202601",
        mark_uncompleted_as_processed=False,
    )
    assert "ou1" not in sync.processed


def test_sync_completion_get_409_error():
    """Test the sync completion handles fetch error response gracefully."""
    dhis2_source = MagicMock()
    dhis2_target = MagicMock()
    # Mock GET response
    mock_get_response = MagicMock()
    mock_get_response.status_code = 409
    mock_get_response.raise_for_status.side_effect = requests.HTTPError("409 Client Error: Conflict for url")
    # error valid for v2.37 and v2.40
    completion_source = {
        "httpStatus": "Conflict",
        "httpStatusCode": 409,
        "status": "ERROR",
        "message": "At least one data set must be specified",
        "errorCode": "E2013",
    }
    mock_get_response.json.return_value = completion_source
    dhis2_source.api.session.get.return_value = mock_get_response

    # Run the sync method
    sync = DatasetCompletionSync(dhis2_source, dhis2_target)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync.sync(source_dataset_id="DS1", target_dataset_id="DS2", org_units=["ou1"], period="202601")
    assert sync.import_summary["import_counts"]["imported"] == 0
    assert sync.import_summary["import_counts"]["updated"] == 0
    assert sync.import_summary["import_counts"]["ignored"] == 0
    assert sync.import_summary["import_counts"]["deleted"] == 0
    assert sync.import_summary["errors"]["fetch_errors"] == [
        {
            "ds": "DS1",
            "pe": "202601",
            "ou": "ou1",
            "error": (
                "GET request with (param: children=False) failed to retrieve "
                "completion status 409 Client Error: Conflict for url"
            ),
        }
    ]


def test_sync_completion_get_empty_error():
    """Test the sync completion handles fetch error response gracefully."""
    dhis2_source = MagicMock()
    dhis2_target = MagicMock()
    # Mock GET response
    mock_get_response = MagicMock()
    # error valid for v2.37 and v2.40
    completion_source = {}
    mock_get_response.json.return_value = completion_source
    dhis2_source.api.session.get.return_value = mock_get_response

    # Run the sync method
    sync = DatasetCompletionSync(dhis2_source, dhis2_target)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync.sync(source_dataset_id="DS1", target_dataset_id="DS2", org_units=["ou1"], period="202601")
    assert sync.import_summary["import_counts"]["imported"] == 0
    assert sync.import_summary["import_counts"]["updated"] == 0
    assert sync.import_summary["import_counts"]["ignored"] == 0
    assert sync.import_summary["import_counts"]["deleted"] == 0
    assert sync.import_summary["errors"]["fetch_errors"] == [
        {
            "ds": "DS1",
            "pe": "202601",
            "ou": "ou1",
            "error": ("GET request (param: children=False): Invalid or empty JSON response"),
        }
    ]
    assert sync.processed == []


@pytest.mark.parametrize(
    "mock_response", [MOCK_DHIS2_COMPLETION_200_IMP_RESPONSE_V2_37, MOCK_DHIS2_COMPLETION_200_IMP_RESPONSE_V2_40]
)
def test_sync_completion_processed_ous(mock_response: dict):
    """Test the correct count of processed org units is logged and saved during the sync process."""
    dhis2_source = MagicMock()
    dhis2_target = MagicMock()
    # Mock GET response with multiple org units
    mock_get_response = MagicMock()
    mock_get_response.json.return_value = {
        "completeDataSetRegistrations": [
            {
                "period": "202601",
                "dataSet": "DS1",
                "organisationUnit": f"ou{i}",
                "attributeOptionCombo": "HllvX50cXC0",
                "date": "2026-01-31",
                "storedBy": "OpenHexa",
                "completed": True,
            }
            for i in range(1, 11)
        ]
    }
    dhis2_source.api.session.get.return_value = mock_get_response

    # Mock POST response
    mock_post_response = MagicMock()
    mock_post_response.json.return_value = mock_response
    dhis2_target.api.session.post.return_value = mock_post_response

    # Run the sync method with a small saving interval to test intermediate saves
    sync = DatasetCompletionSync(dhis2_source, dhis2_target)
    sync.log_function = MagicMock()
    sync._reset_summary()
    sync.sync(
        source_dataset_id="DS1",
        target_dataset_id="DS2",
        org_units=[f"ou{i}" for i in range(1, 11)],
        period="202601",
        saving_interval=5,
    )

    # Check that the log function was called with the correct progress messages
    expected_calls = [f"{i} / 10 OUs processed" for i in range(5, 11, 5)]  # Logs at 5 and 10 processed OUs
    actual_calls = [
        call[1]["message"] for call in sync.log_function.call_args_list if call[1]["message"].endswith("OUs processed")
    ]
    assert actual_calls == expected_calls
    assert sync.processed == [f"ou{i}" for i in range(1, 11)]


@pytest.mark.parametrize(
    "mock_response", [MOCK_DHIS2_COMPLETION_200_IMP_RESPONSE_V2_37, MOCK_DHIS2_COMPLETION_200_IMP_RESPONSE_V2_40]
)
def test_sync_completion_false_status_not_added_to_processed(mock_response: dict):
    """Test that org units with completed=False are not added to the processed list.

    Even if the push to the target succeeds, OUs with completed=False must remain
    untracked so they are retried on the next run in case their status changes.
    """
    dhis2_source = MagicMock()
    dhis2_target = MagicMock()

    mock_get_response = MagicMock()
    mock_get_response.json.return_value = {
        "completeDataSetRegistrations": [
            {
                "period": "202601",
                "dataSet": "DS1",
                "organisationUnit": "ou1",
                "attributeOptionCombo": "HllvX50cXC0",
                "date": "2026-01-31",
                "storedBy": "OpenHexa",
                "completed": False,
            },
            {
                "period": "202601",
                "dataSet": "DS1",
                "organisationUnit": "ou2",
                "attributeOptionCombo": "HllvX50cXC0",
                "date": "2026-01-31",
                "storedBy": "OpenHexa",
                "completed": True,
            },
        ]
    }
    dhis2_source.api.session.get.return_value = mock_get_response

    mock_post_response = MagicMock()
    mock_post_response.json.return_value = mock_response
    dhis2_target.api.session.post.return_value = mock_post_response

    sync = DatasetCompletionSync(dhis2_source, dhis2_target)
    sync.log_function = MagicMock()
    sync.sync(source_dataset_id="DS1", target_dataset_id="DS2", org_units=["ou1", "ou2"], period="202601")

    assert "ou1" not in sync.processed  # completed=False → must not be tracked
    assert "ou2" in sync.processed  # completed=True → must be tracked

import time
from unittest.mock import patch

import polars as pl

from d2d_development.extract import DHIS2Extractor
from tests.mock_dhis2 import MockDHIS2Client


def test_extract_map_data_elements():
    """Test the mapping of data elements."""
    result = DHIS2Extractor(dhis2_client=MockDHIS2Client()).data_elements._retrieve_data(
        data_elements=["AAA111"], org_units=[], period="202501"
    )
    assert isinstance(result, pl.DataFrame)
    assert result.shape == (9, 9)
    assert result.columns == [
        "dataType",
        "dx",
        "period",
        "orgUnit",
        "categoryOptionCombo",
        "attributeOptionCombo",
        "rateMetric",
        "domainType",
        "value",
    ]
    assert set(result["dataType"]) == {"DATA_ELEMENT"}
    assert set(result["dx"].drop_nulls()) == {
        "AAA111",
        "BBB222",
        "CCC333",
        "DELETE1",
        "INVALID1",
        "INVALID2",
        "INVALID3",
        "INVALID4",
    }
    assert set(result["period"].drop_nulls()) == {"202501"}
    assert set(result["orgUnit"].drop_nulls()) == {
        "ORG001",
        "ORG003",
        "ORG005",
        "ORG006",
        "ORG002",
        "ORG004",
    }
    assert set(result["categoryOptionCombo"].drop_nulls()) == {
        "CAT006",
        "CAT005",
        "CAT003",
        "CAT002",
        "CAT001",
        "CAT004",
    }
    assert set(result["attributeOptionCombo"].drop_nulls()) == {
        "ATTR001",
        "ATTR002",
        "ATTR003",
        "ATTR004",
        "ATTR005",
        "ATTR006",
    }
    assert set(result["rateMetric"]) == {None}
    assert set(result["domainType"]) == {"AGGREGATED"}
    assert set(result["value"].drop_nulls()) == {"12", "18", "25", "55.0"}


def test_extract_map_reporting_rates():
    """Test the mapping of reporting rates."""
    result = DHIS2Extractor(dhis2_client=MockDHIS2Client()).reporting_rates._retrieve_data(
        reporting_rates=["AAA111.REPORTING_RATE", "BBB222.EXPECTED_REPORTS", "CCC333.REPORTING_RATE"],
        org_units=[],
        period="202409",
    )
    assert isinstance(result, pl.DataFrame)
    assert result.shape == (3, 9)
    assert result.columns == [
        "dataType",
        "dx",
        "period",
        "orgUnit",
        "categoryOptionCombo",
        "attributeOptionCombo",
        "rateMetric",
        "domainType",
        "value",
    ]
    assert result["dataType"].unique().to_list() == ["REPORTING_RATE"]
    assert result["dx"].to_list() == ["AAA111", "BBB222", "CCC333"]
    assert result["period"].to_list() == ["202409", "202409", "202409"]
    assert result["orgUnit"].to_list() == ["OU001", "OU002", "OU003"]
    assert result["categoryOptionCombo"].to_list() == [None, None, None]
    assert result["attributeOptionCombo"].to_list() == [None, None, None]
    assert result["rateMetric"].to_list() == ["REPORTING_RATE", "EXPECTED_REPORTS", "REPORTING_RATE"]
    assert result["domainType"].to_list() == ["AGGREGATED", "AGGREGATED", "AGGREGATED"]
    assert result["value"].to_list() == ["100", "0", "100"]


def test_extract_map_indicator():
    """Test the mapping of indicators."""
    result = DHIS2Extractor(dhis2_client=MockDHIS2Client()).indicators._retrieve_data(
        indicators=["INDICATOR1", "INDICATOR2", "INDICATOR3"], org_units=[], period="202501"
    )
    assert isinstance(result, pl.DataFrame)
    assert result.shape == (3, 9)
    assert result.columns == [
        "dataType",
        "dx",
        "period",
        "orgUnit",
        "categoryOptionCombo",
        "attributeOptionCombo",
        "rateMetric",
        "domainType",
        "value",
    ]
    assert result["dataType"].unique().to_list() == ["INDICATOR"]
    assert result["dx"].to_list() == ["INDICATOR1", "INDICATOR2", "INDICATOR3"]
    assert result["period"].to_list() == ["202501", "202501", "202501"]
    assert result["orgUnit"].to_list() == ["ORG001", "ORG002", "ORG003"]
    assert result["categoryOptionCombo"].to_list() == [None, None, None]
    assert result["attributeOptionCombo"].to_list() == [None, None, None]
    assert result["rateMetric"].to_list() == [None, None, None]
    assert result["domainType"].to_list() == ["AGGREGATED", "AGGREGATED", "AGGREGATED"]
    assert result["value"].to_list() == ["5.0", "7.0", "9.0"]


def test_extract_download_replace_no_file(tmp_path):  # noqa: ANN001
    """Test DOWNLOAD_REPLACE mode, downloads and saves data to a Parquet file."""
    extractor = DHIS2Extractor(dhis2_client=MockDHIS2Client(), download_mode="DOWNLOAD_REPLACE")
    filename = "test_extract_202501.parquet"

    # Call download_period
    result_path = extractor.data_elements.download_period(
        data_elements=[], org_units=[], period="202501", output_dir=tmp_path, filename=filename
    )

    # Assert file is created
    assert result_path.exists()
    assert result_path.name == filename


def test_download_replace_replaces_file_and_logs(tmp_path):  # noqa: ANN001
    """Test DOWNLOAD_REPLACE mode, replaces the file if it already exists and logs the replacement."""
    extractor = DHIS2Extractor(dhis2_client=MockDHIS2Client(), download_mode="DOWNLOAD_REPLACE")
    output_dir = tmp_path
    period = "202501"
    filename = "test_extract.parquet"

    # First call creates the file
    file_path = extractor.data_elements.download_period(
        data_elements=[], org_units=[], period=period, output_dir=output_dir, filename=filename
    )
    assert file_path.exists()
    mtime_before = file_path.stat().st_mtime

    time.sleep(1)  # Ensure the filesystem timestamp will change

    # Patch current_run.log_info to capture log messages
    with patch("d2d_development.extract.current_run.log_info") as mock_log:
        # Second call should replace the file and log the replacement
        extractor.data_elements.download_period(
            data_elements=[], org_units=[], period=period, output_dir=output_dir, filename=filename
        )
        mtime_after = file_path.stat().st_mtime
        # Check that the log message about replacing the extract was called
        found = any("Replacing extract for period 202501" in str(call.args[0]) for call in mock_log.call_args_list)
        assert found, "Expected log message about replacing extract not found"
        # Check that the file was actually replaced (mtime changed)
        assert mtime_after > mtime_before, "File was not actually replaced"


def test_extract_download_new_file_exists(tmp_path):  # noqa: ANN001
    """Test DOWNLOAD_NEW mode, creates a new file if it does not exist, and skips if it does."""
    extractor = DHIS2Extractor(dhis2_client=MockDHIS2Client(), download_mode="DOWNLOAD_NEW", return_existing_file=True)
    filename = "test_extract_202501.parquet"

    # First call: file is created
    result_new_path = extractor.data_elements.download_period(
        data_elements=[], org_units=[], period="202501", output_dir=tmp_path, filename=filename
    )
    assert result_new_path.exists()
    assert result_new_path.name == filename

    # Second call: should skip and log the skip message
    with patch("d2d_development.extract.current_run.log_info") as mock_log:
        result_path = extractor.data_elements.download_period(
            data_elements=[], org_units=[], period="202501", output_dir=tmp_path, filename=filename
        )
        assert result_path == result_new_path
        found = any(
            "Extract for period 202501 already exists, download skipped." in str(call.args[0])
            for call in mock_log.call_args_list
        )
        assert found, "Expected log message about skipping extract not found"


def test_extract_download_new_return_existing_file(tmp_path):  # noqa: ANN001
    """Test DOWNLOAD_NEW mode with return_existing_file True and False."""
    filename = "test_extract_202501.parquet"

    # True: should return the file path if it exists
    extractor_true = DHIS2Extractor(
        dhis2_client=MockDHIS2Client(), download_mode="DOWNLOAD_NEW", return_existing_file=True
    )
    # Create the file
    path_true = extractor_true.data_elements.download_period(
        data_elements=[], org_units=[], period="202501", output_dir=tmp_path, filename=filename
    )
    # Second call: should return the same file path
    result_true = extractor_true.data_elements.download_period(
        data_elements=[], org_units=[], period="202501", output_dir=tmp_path, filename=filename
    )
    assert result_true == path_true

    # False: should return None if the file exists
    extractor_false = DHIS2Extractor(
        dhis2_client=MockDHIS2Client(), download_mode="DOWNLOAD_NEW", return_existing_file=False
    )
    # Create the file
    _ = extractor_false.data_elements.download_period(
        data_elements=[], org_units=[], period="202501", output_dir=tmp_path, filename=filename
    )
    # Second call: should return None
    result_false = extractor_false.data_elements.download_period(
        data_elements=[], org_units=[], period="202501", output_dir=tmp_path, filename=filename
    )
    assert result_false is None


def test_extract_get_data_elements_with_indicator_extractor():
    """Test that we can retrieve data elements using the indicators extractor.

    Passing valid data element ids to the indicators parameter and including
    the `include_cocs=True` flag should allow us to retrieve data elements with the indicators endpoint.
    """
    result = DHIS2Extractor(dhis2_client=MockDHIS2Client()).indicators._retrieve_data(
        indicators=["DATAELEMENT1", "DATAELEMENT2", "DATAELEMENT3"],
        org_units=[],
        period="202501",
        include_cocs=True,  # Include category option combo in the response
    )

    assert result.shape == (3, 9)
    assert result.columns == [
        "dataType",
        "dx",
        "period",
        "orgUnit",
        "categoryOptionCombo",
        "attributeOptionCombo",
        "rateMetric",
        "domainType",
        "value",
    ]
    assert result["dataType"].unique().to_list() == ["INDICATOR"]
    assert result["dx"].to_list() == ["DATAELEMENT1", "DATAELEMENT2", "DATAELEMENT3"]
    assert result["categoryOptionCombo"].to_list() == ["COC001", "COC002", "COC003"]

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import polars as pl
from openhexa.toolbox.dhis2 import DHIS2

from .data_models import DataType
from .exceptions import ExtractorError
from .utils import log_message, save_to_parquet


class DataElementsExtractor:
    """Handles downloading and formatting of data elements from DHIS2."""

    def __init__(self, extractor: DHIS2Extractor):
        self.extractor = extractor

    def download_period(
        self,
        data_elements: list[str],
        org_units: list[str],
        period: str,
        output_dir: Path,
        filename: str | None = None,
        **kwargs,  # noqa: ANN003
    ) -> Path | None:
        """Download and handle data extracts for the specified period, saving them to the output directory.

        Parameters
        ----------
        data_elements : list[str]
            List of DHIS2 data element UIDs to extract.
        org_units : list[str]
            List of DHIS2 organization unit UIDs to extract data for.
        period : str
            DHIS2 period (valid format) to extract data for.
        output_dir : Path
            Directory where extracted data files will be saved.
        filename : str | None
            Optional filename for the extracted data file. If None, a default name will be used.
        kwargs : dict
            Additional keyword arguments for data retrieval, such as `last_updated` for filtering data.

        Returns
        -------
        Path | None
            The path to the extracted data file, or None if no data was extracted.

        Raises
        ------
        ExtractorError
            If an error occurs during the extract process.
        """
        try:
            self.extractor._log_message(f"Retrieving data elements extract for period : {period}")
            return self.extractor._handle_extract_for_period(
                handler=self,
                data_products=data_elements,
                org_units=org_units,
                period=period,
                output_dir=output_dir,
                filename=filename,
                **kwargs,
            )
        except Exception as e:
            self.extractor._log_message(
                "Extract data elements download error.", log_current_run=False, error_details=str(e), level="error"
            )
            raise ExtractorError(f"Extract data elements download error : {e}") from e

    def _retrieve_data(self, data_elements: list[str], org_units: list[str], period: str, **kwargs) -> pl.DataFrame:  # noqa: ANN003
        """Retrieve data from DHIS2 for the specified data elements, organization units, and period.

        Parameters
        ----------
        data_elements : list[str]
            List of DHIS2 data element UIDs to extract.
        org_units : list[str]
            List of DHIS2 organization unit UIDs to extract data for.
        period : str
            DHIS2 period (valid format) to extract data for.
        kwargs : dict
            Additional keyword arguments for data retrieval, only `last_updated` available but not impemented yet.

        Returns
        -------
        pl.DataFrame A DataFrame containing the retrieved data, formatted according to DHIS2 naming standards.
        """
        if not self.extractor._valid_dhis2_period_format(period):
            raise ExtractorError(f"Invalid DHIS2 period format: {period}")
        last_updated = kwargs.get("last_updated")
        try:
            response = self.extractor.dhis2_client.data_value_sets.get(
                data_elements=data_elements,
                periods=[period],
                org_units=org_units,
                last_updated=last_updated,  # not implemented yet
            )
        except Exception as e:
            msg = "Error retrieving data elements data"
            self.extractor._log_message(msg, log_current_run=False, error_details=str(e), level="error")
            raise ExtractorError(msg) from e

        if not response:
            return None

        # Transform to pandas first to handle automatic polars schema inference
        return self.extractor._map_to_dhis2_format(
            pl.from_pandas(pd.DataFrame(response).astype({"value": str})), data_type=DataType.DATA_ELEMENT
        )


class IndicatorsExtractor:
    """Handles downloading and formatting of indicators from DHIS2."""

    def __init__(self, extractor: DHIS2Extractor):
        """Initialize the IndicatorsExtractor with a reference to the main DHIS2Extractor."""
        self.extractor = extractor

    def download_period(
        self,
        indicators: list[str],
        org_units: list[str],
        period: str,
        output_dir: Path,
        filename: str | None = None,
        **kwargs,  # noqa: ANN003
    ) -> Path | None:
        """Download and handle data extracts for the specified periods, saving them to the output directory.

        Parameters
        ----------
        indicators : list[str]
            List of DHIS2 indicators UIDs to extract.
        org_units : list[str]
            List of DHIS2 organization unit UIDs to extract data for.
        period : str
            DHIS2 period (valid format) to extract data for.
        output_dir : Path
            Directory where extracted data files will be saved.
        filename : str | None
            Optional filename for the extracted data file. If None, a default name will be used.
        kwargs : dict
            Additional keyword arguments for data retrieval from analytics like:
              -include_cocs: bool, whether to include category option combo mapping for indicators.
              -last_updated: datetime, not implemented yet, placeholder for future use to filter data
                based on last updated timestamp.

        Returns
        -------
        Path | None
            The path to the extracted data file, or None if no data was extracted.

        Raises
        ------
        ExtractorError
            If an error occurs during the extract process.
        """
        try:
            self.extractor._log_message(f"Retrieving indicators extract for period : {period}")
            return self.extractor._handle_extract_for_period(
                handler=self,
                data_products=indicators,
                org_units=org_units,
                period=period,
                output_dir=output_dir,
                filename=filename,
                **kwargs,
            )
        except Exception as e:
            self.extractor._log_message(
                "Extract indicators download error.", log_current_run=False, error_details=str(e), level="error"
            )
            raise ExtractorError(f"Extract indicators download error : {e}") from e

    def _retrieve_data(self, indicators: list[str], org_units: list[str], period: str, **kwargs) -> pl.DataFrame:  # noqa: ANN003
        """Retrieve data from DHIS2 for the specified indicators, organization units, and period.

        Parameters
        ----------
        indicators : list[str]
            List of DHIS2 indicator UIDs to extract.
        org_units : list[str]
            List of DHIS2 organization unit UIDs to extract data for.
        period : str
            DHIS2 period (valid format) to extract data for.
        kwargs : dict
            Additional keyword arguments for data retrieval, only `include_cocs` currently implemented
             to include category option combo mapping for data element ids passed to the DHIS2 client.

        Returns
        -------
        pl.DataFrame A DataFrame containing the retrieved data, formatted according to DHIS2 naming standards.
        """
        if not self.extractor._valid_dhis2_period_format(period):
            raise ExtractorError(f"Invalid DHIS2 period format: {period}")

        # NOTE: This option is usefull to retrieve data Elements using the analytics endpoint.
        include_cocs = kwargs.get("include_cocs", False)
        try:
            response = self.extractor.dhis2_client.analytics.get(
                indicators=indicators,
                periods=[period],
                org_units=org_units,
                include_cocs=include_cocs,
            )
        except Exception as e:
            msg = "Error retrieving indicators data"
            self.extractor._log_message(msg, log_current_run=False, error_details=str(e), level="error")
            raise ExtractorError(msg) from e

        if not response:
            return None

        # Transform to pandas first to handle automatic polars schema inference
        raw_data_formatted = pl.from_pandas(pd.DataFrame(response).astype({"value": str})).rename(
            {"pe": "period", "ou": "orgUnit"}
        )
        if "co" in raw_data_formatted.columns:
            raw_data_formatted = raw_data_formatted.rename({"co": "categoryOptionCombo"})
        return self.extractor._map_to_dhis2_format(
            raw_data_formatted, data_type=DataType.INDICATOR, map_cocs=include_cocs
        )


class ReportingRatesExtractor:
    """Handles downloading and formatting of reporting rates from DHIS2."""

    def __init__(self, extractor: DHIS2Extractor):
        """Initialize the ReportingRatesExtractor with a reference to the main DHIS2Extractor."""
        self.extractor = extractor

    def download_period(
        self,
        reporting_rates: list[str],
        org_units: list[str],
        period: str,
        output_dir: Path,
        filename: str | None = None,
        **kwargs,  # noqa: ANN003
    ) -> Path | None:
        """Download and handle data extracts for the specified periods, saving them to the output directory.

        Parameters
        ----------
        reporting_rates : list[str]
            List of DHIS2 reporting rates UIDs.RATE to extract.
        org_units : list[str]
            List of DHIS2 organization unit UIDs to extract data for.
        period : str
            DHIS2 period (valid format) to extract data for.
        output_dir : Path
            Directory where extracted data files will be saved.
        filename : str | None
            Optional filename for the extracted data file. If None, a default name will be used.
        kwargs : dict
            Additional keyword arguments for data retrieval, such as `last_updated` for filtering data.

        Returns
        -------
        Path | None
            The path to the extracted data file, or None if no data was extracted.

        Raises
        ------
        ExtractorError
            If an error occurs during the extract process.
        """
        try:
            self.extractor._log_message(f"Retrieving reporting rates extract for period : {period}")
            return self.extractor._handle_extract_for_period(
                handler=self,
                data_products=reporting_rates,
                org_units=org_units,
                period=period,
                output_dir=output_dir,
                filename=filename,
                **kwargs,
            )
        except Exception as e:
            self.extractor._log_message(
                "Extract reporting rates download error.", log_current_run=False, error_details=str(e), level="error"
            )
            raise ExtractorError(f"Extract reporting rates download error : {e}") from e

    def _retrieve_data(self, reporting_rates: list[str], org_units: list[str], period: str, **kwargs) -> pl.DataFrame:  # noqa: ANN003
        """Retrieve data from DHIS2 for the specified reporting rates, organization units, and period.

        Parameters
        ----------
        reporting_rates : list[str]
            List of DHIS2 reporting rate UIDs to extract.
        org_units : list[str]
            List of DHIS2 organization unit UIDs to extract data for.
        period : str
            DHIS2 period (valid format) to extract data for.
        kwargs : dict
            Additional keyword arguments for data retrieval (not impemented).

        Returns
        -------
        pl.DataFrame A DataFrame containing the retrieved data, formatted according to DHIS2 naming standards.
        """
        if not self.extractor._valid_dhis2_period_format(period):
            raise ExtractorError(f"Invalid DHIS2 period format: {period}")

        try:
            response = self.extractor.dhis2_client.analytics.get(
                data_elements=reporting_rates,
                periods=[period],
                org_units=org_units,
                include_cocs=False,  # avoid client error
            )
        except Exception as e:
            msg = "Error retrieving reporting rates data"
            self.extractor._log_message(msg, log_current_run=False, error_details=str(e), level="error")
            raise ExtractorError(msg) from e

        if not response:
            return None

        # Transform to pandas first to handle automatic polars schema inference
        raw_data_formatted = pl.from_pandas(pd.DataFrame(response).astype({"value": str})).rename(
            {"pe": "period", "ou": "orgUnit"}
        )
        return self.extractor._map_to_dhis2_format(raw_data_formatted, data_type=DataType.REPORTING_RATE)


class DHIS2Extractor:
    """Extracts data from DHIS2 using various handlers for data elements, indicators, and reporting rates.

    Attributes
    ----------
    client : object
        The DHIS2 client used for data extraction.
    queue : object | None
        Optional queue for managing extracted files.
    download_mode : str
        Mode for downloading files ("DOWNLOAD_REPLACE" or "DOWNLOAD_NEW").
    last_updated : None
        Placeholder for future use.
    return_existing_file : bool
        When DOWNLOAD_NEW mode is used:
            True: returns the path to existing files.
            False: returns None if the file already exists.
        Default is False.

    Handlers
    --------
    data_elements : DataElementsExtractor
        Handler for extracting data elements.
    indicators : IndicatorsExtractor
        Handler for extracting indicators.
    reporting_rates : ReportingRatesExtractor
        Handler for extracting reporting rates.
    """

    def __init__(
        self,
        dhis2_client: DHIS2,
        download_mode: str = "DOWNLOAD_REPLACE",
        return_existing_file: bool = False,
        logger: logging.Logger | None = None,
    ):
        """Initialize the DHIS2Extractor with the given DHIS2 client and configuration."""
        self.dhis2_client = dhis2_client
        if download_mode not in {"DOWNLOAD_REPLACE", "DOWNLOAD_NEW"}:
            raise ExtractorError("Invalid 'download_mode', use 'DOWNLOAD_REPLACE' or 'DOWNLOAD_NEW'.")
        self.download_mode = download_mode
        self.last_updated = None  # NOTE: Placeholder for future use
        self.data_elements = DataElementsExtractor(self)
        self.indicators = IndicatorsExtractor(self)
        self.reporting_rates = ReportingRatesExtractor(self)
        self.return_existing_file = return_existing_file
        self.logger = logger or logging.getLogger(__name__)
        self.log_function = log_message

    def _handle_extract_for_period(
        self,
        handler: DataElementsExtractor | IndicatorsExtractor | ReportingRatesExtractor,
        data_products: list[str],
        org_units: list[str],
        period: str,
        output_dir: Path,
        filename: str | None = None,
        **kwargs,  # noqa: ANN003
    ) -> Path | None:
        """Handles the extract process for a given period, including data retrieval, file saving, and logging.

        Parameters
        ----------
        handler : DataElementsExtractor | IndicatorsExtractor | ReportingRatesExtractor
            The specific handler to use for data retrieval.
        data_products : list[str]
            List of data product UIDs to extract (e.g., data elements, indicators, or reporting rates).
        org_units : list[str]
            List of DHIS2 organization unit UIDs to extract data for.
        period : str
            DHIS2 period (valid format) to extract data for.
        output_dir : Path
            Directory where extracted data files will be saved.
        filename : str | None
            Optional filename for the extracted data file. If None, a default name will be used.
        kwargs : dict
            Additional keyword arguments for data retrieval, such as `last_updated` for filtering data.

        Returns
        -------
        Path | None
            The path to the extracted data file, or None if no data was extracted or if
            the file already exists and `return_existing_file` is False.

        """
        output_dir.mkdir(parents=True, exist_ok=True)
        if filename:
            extract_fname = output_dir / filename
        else:
            extract_fname = output_dir / f"data_{period}.parquet"

        # Skip if already exists and mode is DOWNLOAD_NEW
        if self.download_mode == "DOWNLOAD_NEW" and extract_fname.exists():
            self._log_message(f"Extract for period {period} already exists, download skipped.")
            return extract_fname if self.return_existing_file else None

        raw_data = handler._retrieve_data(data_products, org_units, period, **kwargs)

        if raw_data is None:
            self._log_message(f"Nothing to save for period {period}.")
            return None

        if extract_fname.exists():
            self._log_message(f"Replacing extract for period {period}.")

        save_to_parquet(raw_data, extract_fname)
        return extract_fname

    def _map_to_dhis2_format(
        self,
        dhis_data: pl.DataFrame,
        data_type: DataType = DataType.DATA_ELEMENT,
        domain_type: str = "AGGREGATED",
        map_cocs: bool = False,
    ) -> pl.DataFrame:
        """Maps DHIS2 data to a standardized data extraction table.

        Parameters
        ----------
        dhis_data : pd.DataFrame
            Input DataFrame containing DHIS2 data. Must include columns like `period`, `orgUnit`,
            `categoryOptionCombo(DATA_ELEMENT)`, `attributeOptionCombo(DATA_ELEMENT)`, `dataElement`
            and `value` based on the data type.
        data_type : str
            The type of data being mapped. Supported values are:
            - "DATA_ELEMENT": Includes `categoryOptionCombo` and maps `dataElement` to `dx`.
            - "INDICATOR": Maps `dx` to `dx`.
            - "REPORTING_RATE": Maps `dx` to `dx` and `rateType` by split the string by `.`.
            Default is "DATA_ELEMENT".
        domain_type : str, optional
            The domain of the data if its per period (Agg ex: monthly) or datapoint (Tracker ex: per day):
            - "AGGREGATED": For aggregated data (default).
            - "TRACKER": For tracker data.
            **NOTE: THIS IS WORK IN PROGRESS AND NOT USED YET**
        map_cocs : bool, optional
            NOTE: IndicatorsExtractor can be used to retrieve data elements by passing valid data element ids
             to the indicators parameter. Therefore we can use the client flag `include_coc` to include `co` column.
            *Only applicable if `data_type` is "INDICATOR". Default is False.

        Returns
        -------
        pl.DataFrame
            A DataFrame formatted to SNIS standards, with the following columns (snake_case):
            - "data_type": The type of data (DATA_ELEMENT, REPORTING_RATE, or INDICATOR).
            - "dx": Data element, dataset, or indicator UID.
            - "period": Reporting period.
            - "org_unit": Organization unit.
            - "category_option_combo": (Only for DATA_ELEMENT) Category option combo UID.
            - "attribute_option_combo": (Only for DATA_ELEMENT) Attribute option combo UID.
            - "rate_metric": (Only for REPORTING_RATE) Rate metric.
            - "domain_type": Data domain (AGGREGATED or TRACKER).
            - "value": Data value.
        """
        if dhis_data.height == 0:
            return None

        if data_type not in DataType:
            raise ExtractorError(
                "Incorrect 'data_type' configuration use: "
                "(DataType.DATA_ELEMENT, DataType.REPORTING_RATE, DataType.INDICATOR)."
            )

        try:
            n = dhis_data.height
            data = {
                "data_type": [data_type.value] * n,
                "dx": None,
                "period": dhis_data["period"] if "period" in dhis_data.columns else None,
                "org_unit": dhis_data["orgUnit"] if "orgUnit" in dhis_data.columns else None,
                "category_option_combo": None,
                "attribute_option_combo": None,
                "rate_metric": None,
                "domain_type": [domain_type] * n,
                "value": dhis_data["value"] if "value" in dhis_data.columns else None,
            }
        except AttributeError as e:
            msg = (
                f"Failed to map DHIS2 data to the expected format. "
                f"Input columns: {list(dhis_data.columns)}. "
                f"Expected columns depend on data_type: {data_type}."
            )
            self._log_message(msg, log_current_run=False, error_details=f"AttributeError: {e}", level="error")
            raise ExtractorError(msg) from e

        if data_type == DataType.DATA_ELEMENT:
            data["dx"] = dhis_data["dataElement"] if "dataElement" in dhis_data.columns else None
            data["category_option_combo"] = (
                dhis_data["categoryOptionCombo"] if "categoryOptionCombo" in dhis_data.columns else None
            )
            data["attribute_option_combo"] = (
                dhis_data["attributeOptionCombo"] if "attributeOptionCombo" in dhis_data.columns else None
            )
        elif data_type == DataType.REPORTING_RATE:
            if "dx" in dhis_data.columns:
                split = dhis_data["dx"].str.split_exact(".", 1)
                data["dx"] = split.struct.field("field_0")
                data["rate_metric"] = split.struct.field("field_1")
        elif data_type == DataType.INDICATOR:
            data["dx"] = dhis_data["dx"] if "dx" in dhis_data.columns else None
            if map_cocs and "categoryOptionCombo" in dhis_data.columns:
                data["category_option_combo"] = dhis_data["categoryOptionCombo"]
        return pl.DataFrame(data)

    def _log_message(self, message: str, level: str = "info", log_current_run: bool = True, error_details: str = ""):
        """Log a message using the configured logging function."""
        self.log_function(
            logger=self.logger,
            message=message,
            error_details=error_details,
            level=level,
            log_current_run=log_current_run,
            exception_class=ExtractorError,
        )

    def _valid_dhis2_period_format(self, dhis2_period: str) -> bool:
        """Validate if the given period string is in a valid DHIS2 format.

        Returns
        -------
        bool
        True if valid, False otherwise.
        """
        # TODO: Expand this function to cover more DHIS2 period formats as needed
        return True

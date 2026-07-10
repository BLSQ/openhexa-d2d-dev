import json
import logging
import math

import pandas as pd
import polars as pl
import requests
from openhexa.toolbox.dhis2 import DHIS2
from packaging import version
from requests import Response
from requests.structures import CaseInsensitiveDict

from .data_models import OrgUnit
from .exceptions import OrgUnitAlignError, OrgUnitError
from .utils import log_message

# `parent` and `geometry` are nested dict-or-None fields whose shape varies across rows
# (DHIS2 geometry coordinates nest differently for Point vs Polygon org units). Letting polars
# auto-infer a Struct schema for them risks the same schema-inference failures already hit in
# extract.py, so they're built as an explicit Object-dtype Series instead (see
# `_records_to_polars`), keeping them as opaque Python objects exactly like pandas' `object` dtype.
_OBJECT_DTYPE_COLUMNS = ("parent", "geometry")


def _is_nan(value: object) -> bool:
    """Check whether a value is a bare float NaN (pandas' stand-in for a missing value).

    Args:
        value: The value to check.

    Returns:
        bool: True if value is a float NaN.
    """
    return isinstance(value, float) and math.isnan(value)


def _records_to_polars(records: list[dict]) -> pl.DataFrame:
    """Build a polars DataFrame from row records, keeping nested columns as Object dtype.

    A missing value coming from `pd.DataFrame.to_dict("records")` surfaces as a bare float NaN
    rather than None. Left as-is, building a typed (e.g. string) column from such a record makes
    polars silently stringify it to the literal text "NaN" instead of a null, so NaN is normalized
    to None here before any DataFrame gets built.

    Args:
        records: Row records, e.g. a raw DHIS2 API response or `pd.DataFrame.to_dict("records")`.

    Returns:
        pl.DataFrame: DataFrame with `parent`/`geometry` (if present) kept as Object dtype so
        polars never attempts Struct schema inference on them.
    """
    if not records:
        return pl.DataFrame(records)

    records = [{k: (None if _is_nan(v) else v) for k, v in record.items()} for record in records]

    # Check every record, not just the first: records can be ragged (e.g. a raw DHIS2 API
    # response where a field is omitted entirely for some org units rather than set to null).
    present_object_columns = [col for col in _OBJECT_DTYPE_COLUMNS if any(col in record for record in records)]
    object_columns = {col: [record.get(col) for record in records] for col in present_object_columns}
    plain_records = [{k: v for k, v in record.items() if k not in _OBJECT_DTYPE_COLUMNS} for record in records]

    df = pl.DataFrame(plain_records)
    if object_columns:
        df = df.with_columns([pl.Series(col, values, dtype=pl.Object) for col, values in object_columns.items()])
    return df


class DHIS2PyramidAligner:
    """Align organisation units (OUs) between two DHIS2 instances.

    Compares source and target pyramids (hierarchies) and:
      - Creates OUs missing in the target
      - Updates OUs with changed attributes
      - Tracks actions and errors in a summary attribute for reporting
    Supports validation, logging, and dry-run mode.

    Usage: Instantiate with a logger and call align_to().
    """

    def __init__(self, logger: logging.Logger):
        self.logger = logger if logger else logging.getLogger(__name__)
        self.log_function = log_message
        self._initialize_summary()

    def _initialize_summary(self):
        self.summary = {
            "CREATE": {"CREATED": [], "ERRORS": []},
            "UPDATE": {"UPDATED": [], "ERRORS": []},
            "INVALID": [],
            "MALFORMED": [],
        }

    def align_to(
        self,
        target_dhis2: DHIS2,
        source_pyramid: pd.DataFrame | pl.DataFrame,
    ):
        """Syncs the extracted pyramid data with the target DHIS2 instance."""
        records = (
            source_pyramid.to_dict(orient="records")
            if isinstance(source_pyramid, pd.DataFrame)
            else source_pyramid.to_dicts()
        )
        source_pyramid = _records_to_polars(records)

        if source_pyramid.is_empty():
            self._log_message("Source pyramid is empty. Organisation units alignment skipped.", level="warning")
            return

        self._initialize_summary()

        self._log_message(f"Retrieving organisation units from target DHIS2: {target_dhis2.api.url}")
        # Retrieve all organisation units from the target DHIS2
        target_pyramid = target_dhis2.meta.organisation_units(
            fields="id,name,shortName,openingDate,closedDate,parent,level,path,geometry"
        )
        target_pyramid = _records_to_polars(target_pyramid)
        self._log_message(f"Shape target pyramid: {target_pyramid.shape}")

        # Select new OU: all OU in source not in target (set difference)
        ou_new = list(set(source_pyramid["id"]) - set(target_pyramid["id"]))
        ou_to_create = source_pyramid.filter(pl.col("id").is_in(ou_new))
        self._push_org_units_create(
            ou_to_create=ou_to_create,
            target_dhis2=target_dhis2,
        )

        # Select matching OU: all OU uid that match between DHIS2 source and target (set intersection)
        matching_ou_ids = list(set(source_pyramid["id"]).intersection(set(target_pyramid["id"])))
        self._push_org_units_update(
            org_unit_source=source_pyramid,
            org_unit_target=target_pyramid,
            ou_ids_to_check=matching_ou_ids,
            target_dhis2=target_dhis2,
        )

    def _log_message(
        self,
        message: str,
        level: str = "info",
        log_current_run: bool = True,
        error_details: str = "",
    ):
        """Log a message using the configured logging function."""
        self.log_function(
            logger=self.logger,
            message=message,
            error_details=error_details,
            level=level,
            log_current_run=log_current_run,
            exception_class=OrgUnitAlignError,
        )

    def _push_org_units_create(self, ou_to_create: pl.DataFrame, target_dhis2: DHIS2) -> None:
        """Create organisation units in the target DHIS2 instance.

        Args:
            ou_to_create: DataFrame containing organisation unit data to be created.
            target_dhis2: DHIS2 client for the target instance.

        This function iterates over the organisation units, validates them, and
        attempts to create them in the target DHIS2.
        Logs errors and information about the creation process.
        """
        if ou_to_create.is_empty():
            self._log_message("No new organisation units to create.")
            return

        # NOTE: Geometry is valid for versions > 2.32
        if version.parse(target_dhis2.version) <= version.parse("2.32"):
            ou_to_create = ou_to_create.with_columns(pl.lit(None).alias("geometry"))
            self._log_message(
                "DHIS2 version not compatible with geometry. Geometry will not be pushed.", level="warning"
            )
        self._log_message(f"Creating {len(ou_to_create)} organisation units.")

        for record in ou_to_create.to_dicts():
            try:
                ou = OrgUnit.model_validate(record)
            except OrgUnitError as e:
                self._handle_malformed_ou(record, error_details=str(e))
                continue

            if ou.is_valid():
                self._handle_org_unit_push(ou=ou, target_dhis2=target_dhis2, action="CREATE")
            else:
                self._handle_invalid_ou(ou)

    def _handle_malformed_ou(self, record: dict, error_details: str) -> None:
        self.summary["INVALID"]["MALFORMED_COUNT"] += 1
        self.summary["INVALID"]["MALFORMED_DETAILS"].append(record)
        msg = f"Invalid organisation unit data: {error_details}. Record: {record}"
        self._log_message(msg, level="error", error_details=error_details, log_current_run=True)

    def _handle_org_unit_push(self, ou: OrgUnit, target_dhis2: DHIS2, action: str) -> None:
        """Handle the creation of an organisation unit in the target DHIS2 instance."""
        try:
            self._push_org_unit(
                dhis2_client=target_dhis2,
                org_unit=ou,
                strategy=action,
            )
        except Exception as e:
            msg = f"An error occurred while pushing organisation unit {ou.id}: {e}."
            self._log_message(msg, level="error", error_details=str(e), log_current_run=True)

    def _handle_response(self, response: dict, ou: OrgUnit, action: str) -> None:
        response = self._build_formatted_response(response=response, strategy=action, ou_id=ou.id)
        if response.get("status") not in ("SUCCESS", "OK"):
            self.summary["CREATE"]["ERROR_COUNT"] += 1
            self.summary["CREATE"]["ERROR_DETAILS"].append(response)
            self._log_message(f"Error creating org unit: {response}", level="error")
        else:
            created_ou = {"ACTION": "CREATE", "OU": str(ou.to_json()), "RESPONSE": response}
            self.summary["CREATE"]["CREATE_COUNT"] += 1
            self.summary["CREATE"]["CREATE_DETAILS"].append(created_ou)
            self._log_message(created_ou)

    def _handle_invalid_ou(self, ou: OrgUnit) -> None:
        invalid_ou = {"ACTION": "CREATE", "STATUS": "INVALID", "OU": str(ou.to_json())}
        self.summary["INVALID"]["INVALID_COUNT"] += 1
        self.summary["INVALID"]["INVALID_DETAILS"].append(invalid_ou)
        self._log_message(invalid_ou, "warning")

    def _push_org_units_update(
        self,
        org_unit_source: pl.DataFrame,
        org_unit_target: pl.DataFrame,
        ou_ids_to_check: list[str],
        target_dhis2: DHIS2,
        logging_interval: int = 5000,
    ):
        """Update org units based on matching id list."""
        if not len(ou_ids_to_check) > 0:
            self._log_message("No organisation units to update.")
            return

        try:
            self._log_message(f"Checking for updates in {len(ou_ids_to_check)} organisation units.")
            # NOTE: Geometry is valid for versions > 2.32
            if version.parse(target_dhis2.version) <= version.parse("2.32"):
                org_unit_source = org_unit_source.with_columns(pl.lit(None).alias("geometry"))
                org_unit_target = org_unit_target.with_columns(pl.lit(None).alias("geometry"))
                self._log_message(
                    "DHIS2 version not compatible with geometry. Geometry will be ignored.", level="warning"
                )

            # build id dictionary (faster) to compare source vs target OU
            index_dictionary = self._build_id_indexes(org_unit_source, org_unit_target, ou_ids_to_check)

            # Materialize each DataFrame into OrgUnit instances once, instead of rebuilding a row
            # (via .iloc) for every matching id inside the loop below.
            source_ous = [OrgUnit.model_validate(record) for record in org_unit_source.to_dicts()]
            target_ous = [OrgUnit.model_validate(record) for record in org_unit_target.to_dicts()]

            total_ou = len(ou_ids_to_check)
            for progress_count, (_, indices) in enumerate(index_dictionary.items(), start=1):
                # Create the OU and check if there are differences
                # NOTE: See OrgUnit.__eq__() to check the comparison logic
                ou_source = source_ous[indices["source"]]
                ou_target = target_ous[indices["target"]]

                if ou_source != ou_target:
                    response = self._push_org_unit(
                        dhis2_client=target_dhis2,
                        org_unit=ou_source,
                        strategy="UPDATE",
                        is_testing=False,
                    )
                    if response.get("status") not in ("SUCCESS", "OK"):
                        self.summary["UPDATE"]["ERROR_COUNT"] += 1
                        self.summary["UPDATE"]["ERROR_DETAILS"].append(response)
                        self.logger.error(str(response))
                    else:
                        updated_ou = {
                            "ACTION": "UPDATE",
                            "OLD_OU": str(ou_target.to_json()),
                            "NEW_OU": str(ou_source.to_json()),
                            "RESPONSE": str(response),
                        }
                        self.summary["UPDATE"]["UPDATE_COUNT"] += 1
                        self.summary["UPDATE"]["UPDATE_DETAILS"].append(updated_ou)
                        self.logger.info(str(updated_ou))

                if progress_count % logging_interval == 0 or progress_count == total_ou:
                    self._log_message(f"Organisation units checked: {progress_count}/{total_ou} for update.")

        except Exception as e:
            msg = "Unexpected error occurred while updating organisation units."
            self.logger.exception(msg)
            raise OrgUnitAlignError(f"{msg} Check logs for details.") from e

    def _push_org_unit(
        self,
        dhis2_client: DHIS2,
        org_unit: OrgUnit,
        strategy: str = "CREATE",
    ) -> dict:
        """Pushes an organisation unit to the DHIS2 instance using the specified strategy."""
        if strategy == "CREATE":
            endpoint = "organisationUnits"
            payload = org_unit.to_json()

        if strategy == "UPDATE":
            endpoint = "metadata"
            payload = {"organisationUnits": [org_unit.to_json()]}

        try:
            r = dhis2_client.api.session.post(
                f"{dhis2_client.api.url}/{endpoint}",
                json=payload,
                params={"importStrategy": f"{strategy}"},
            )
            r.raise_for_status()
        except requests.RequestException as e:
            msg = f"HTTP request failed while trying to {strategy} organisation unit {org_unit.id}."
            raise OrgUnitAlignError(f"{msg} Check logs for details.") from e

        self._handle_response(response=r, ou=org_unit, strategy=strategy)

    def _build_formatted_response(self, response: requests.Response, strategy: str, ou_id: str) -> dict:
        """Build a formatted response dictionary from a requests.Response object.

        Args:
            response: The HTTP response object from the requests library.
            strategy: The strategy or action performed.
            ou_id: The organisational unit ID related to the response.

        Returns:
            dict: A dictionary containing the action, status code, status, response, and organisational unit ID.
        """
        return {
            "action": strategy,
            "statusCode": response.status_code,
            "status": response.json().get("status"),
            "response": response.json().get("response"),
            "ou_id": ou_id,
        }

    def _build_id_indexes(self, ou_source: pl.DataFrame, ou_target: pl.DataFrame, ou_matching_ids: list) -> dict:
        """Build a dictionary mapping matching OU IDs to their index positions in source and target DataFrames.

        Args:
            ou_source: Source DataFrame containing organisation units with an 'id' column.
            ou_target: Target DataFrame containing organisation units with an 'id' column.
            ou_matching_ids: List of organisation unit IDs to match between source and target.

        Returns:
            dict: Dictionary where keys are matching IDs and values are dicts with 'source' and 'target' index
            positions.
        """
        # Set "id" as the index for faster lookup
        df1_lookup = {val: idx for idx, val in enumerate(ou_source["id"])}
        df2_lookup = {val: idx for idx, val in enumerate(ou_target["id"])}

        # Build the dictionary using prebuilt lookups
        return {
            match_id: {"source": df1_lookup[match_id], "target": df2_lookup[match_id]}
            for match_id in ou_matching_ids
            if match_id in df1_lookup and match_id in df2_lookup
        }

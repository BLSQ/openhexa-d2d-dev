import logging
import math

import pandas as pd
import polars as pl
import requests
from openhexa.toolbox.dhis2 import DHIS2
from packaging import version
from pydantic import ValidationError

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
    Supports validation and logging.

    Usage: Instantiate with a logger and call align_to().
    """

    def __init__(self, logger: logging.Logger):
        self.logger = logger if logger else logging.getLogger(__name__)
        self.log_function = log_message
        self._initialize_summary()

    def _initialize_summary(self):
        self.summary = {
            "CREATE": {"CREATED": [], "INVALID": [], "MALFORMED": [], "ERROR": []},
            "UPDATE": {"UPDATED": [], "INVALID": [], "MALFORMED": [], "ERROR": []},
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
        self._log_message(f"Retrieving organisation units from target DHIS2: {target_dhis2.api.url}")
        self._initialize_summary()

        try:
            # Retrieve all organisation units from the target DHIS2
            target_pyramid = target_dhis2.meta.organisation_units(
                fields="id,name,shortName,openingDate,closedDate,parent,level,path,geometry"
            )
            target_pyramid = _records_to_polars(target_pyramid)
        except Exception as e:
            msg = "Unexpected error occurred while retrieving organisation units from target DHIS2."
            self._log_message(message=msg, level="error", error_details=str(e))
            raise OrgUnitAlignError(f"{msg} {e}") from e

        self._log_message(f"Shape target pyramid: {target_pyramid.shape}")

        # Select new OU: all OU in source not in target (set difference)
        ou_new = list(set(source_pyramid["id"]) - set(target_pyramid["id"]))
        ou_to_create = source_pyramid.filter(pl.col("id").is_in(ou_new))
        try:
            self._push_org_units_create(
                ou_to_create=ou_to_create,
                target_dhis2=target_dhis2,
            )
        except Exception as e:
            msg = "Unexpected error occurred while creating new organisation units."
            self._log_message(message=msg, level="error", error_details=str(e))
            raise OrgUnitAlignError(f"{msg} {e}") from e

        # Select matching OU: all OU uid that match between DHIS2 source and target (set intersection)
        matching_ou_ids = list(set(source_pyramid["id"]).intersection(set(target_pyramid["id"])))
        try:
            self._push_org_units_update(
                org_unit_source=source_pyramid,
                org_unit_target=target_pyramid,
                ou_ids_to_check=matching_ou_ids,
                target_dhis2=target_dhis2,
            )
        except Exception as e:
            msg = "Unexpected error occurred while updating organisation units."
            self._log_message(message=msg, level="error", error_details=str(e))
            raise OrgUnitAlignError(f"{msg} {e}") from e

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
            except (OrgUnitError, ValidationError) as e:
                self._log_error_ou(record, import_strategy="CREATE", error_type="MALFORMED", error_details=str(e))
                continue

            if ou.is_valid():
                self._handle_org_unit_push(ou=ou, target_dhis2=target_dhis2, import_strategy="CREATE")
            else:
                self._log_error_ou(ou.to_json(), import_strategy="CREATE", error_type="INVALID")

    def _handle_org_unit_push(self, ou: OrgUnit, target_dhis2: DHIS2, import_strategy: str) -> None:
        """Handle the creation of an organisation unit in the target DHIS2 instance."""
        try:
            response = self._push_org_unit(
                dhis2_client=target_dhis2,
                org_unit=ou,
                import_strategy=import_strategy,
            )
        except Exception as e:
            self._log_error_ou(ou.to_json(), import_strategy=import_strategy, error_type="ERROR", error_details=str(e))
            return

        self._handle_response(response=response, ou=ou, import_strategy=import_strategy)

    def _handle_response(self, response: dict, ou: OrgUnit, import_strategy: str) -> None:
        """Handle the response from the DHIS2 API after attempting to create or update an organisation unit."""
        if response is None:
            self._log_error_ou(
                ou.to_json(),
                import_strategy=import_strategy,
                error_type="ERROR",
                error_details="No response received from DHIS2 API",
            )
            return

        if not isinstance(response, dict):
            self._log_error_ou(
                ou.to_json(),
                import_strategy=import_strategy,
                error_type="ERROR",
                error_details="Invalid response format",
            )
            return

        if response.get("status") not in ("SUCCESS", "OK"):
            self._log_error_ou(
                ou.to_json(),
                import_strategy=import_strategy,
                error_type="ERROR",
                error_details=f"Failed to {import_strategy.lower()} organisation unit: {response}",
            )
            return

        action_str = "CREATED" if import_strategy == "CREATE" else "UPDATED"
        self.summary[import_strategy][action_str].append(ou.to_json())
        self._log_message(
            f"Organisation unit {action_str.lower()}: {ou.to_json()}", level="info", log_current_run=False
        )

    def _log_error_ou(self, ou: dict, import_strategy: str, error_type: str, error_details: str | None) -> None:
        self.summary[import_strategy][error_type].append(ou)
        error_str = f"Error: {error_details}" if error_details else None
        self._log_message(
            f"{error_type} organisation unit: {ou}.",
            level="error",
            error_details=error_str,
            log_current_run=False,
        )

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

        self._log_message(f"Checking for updates in {len(ou_ids_to_check)} organisation units.")
        # NOTE: Geometry is valid for versions > 2.32
        if version.parse(target_dhis2.version) <= version.parse("2.32"):
            org_unit_source = org_unit_source.with_columns(pl.lit(None).alias("geometry"))
            org_unit_target = org_unit_target.with_columns(pl.lit(None).alias("geometry"))
            self._log_message("DHIS2 version not compatible with geometry. Geometry will be ignored.", level="warning")

        # Target org units come straight from the DHIS2 API: trusted shape, validate in bulk.
        try:
            target_by_id = {record["id"]: OrgUnit.model_validate(record) for record in org_unit_target.to_dicts()}
        except Exception as e:
            self._log_message(
                "Unexpected error occurred while preparing target organisation units for update.",
                level="error",
                error_details=str(e),
            )
            raise OrgUnitAlignError from e

        # Source org units are external input: validate one record at a time so a single
        # malformed row is logged and skipped instead of aborting every update.
        source_by_id: dict[str, OrgUnit] = {}
        for record in org_unit_source.to_dicts():
            try:
                source_by_id[record["id"]] = OrgUnit.model_validate(record)
            except (OrgUnitError, ValidationError) as e:
                self._log_error_ou(record, import_strategy="UPDATE", error_type="MALFORMED", error_details=str(e))

        total_ou = len(ou_ids_to_check)
        for progress_count, ou_id in enumerate(ou_ids_to_check, start=1):
            ou_source = source_by_id.get(ou_id)
            ou_target = target_by_id.get(ou_id)
            if ou_source is not None and ou_target is not None:
                if not ou_source.is_valid():
                    self._log_error_ou(ou_source.to_json(), import_strategy="UPDATE", error_type="INVALID")
                # NOTE: See OrgUnit.__eq__() to check the comparison logic
                elif ou_source != ou_target:
                    self._handle_org_unit_push(ou=ou_source, target_dhis2=target_dhis2, import_strategy="UPDATE")

            if progress_count % logging_interval == 0 or progress_count == total_ou:
                self._log_message(f"Organisation units checked: {progress_count}/{total_ou} for update.")

    def _push_org_unit(
        self,
        dhis2_client: DHIS2,
        org_unit: OrgUnit,
        import_strategy: str = "CREATE",
    ) -> dict:
        """Pushes an organisation unit to the DHIS2 instance using the specified strategy.

        Args:
            dhis2_client: The DHIS2 client instance to use for the API call.
            org_unit: The organisation unit to push.
            import_strategy: The strategy to use for the import ("CREATE" or "UPDATE").

        Returns:
            dict: The response from the DHIS2 API.
        """
        if import_strategy == "CREATE":
            endpoint = "organisationUnits"
            payload = org_unit.to_json()

        if import_strategy == "UPDATE":
            endpoint = "metadata"
            payload = {"organisationUnits": [org_unit.to_json()]}

        try:
            r = dhis2_client.api.session.post(
                f"{dhis2_client.api.url}/{endpoint}",
                json=payload,
                params={"importStrategy": f"{import_strategy}"},
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            raise OrgUnitAlignError from e

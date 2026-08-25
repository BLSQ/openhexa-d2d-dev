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
# extract.py, so they're stringified instead (see `_records_to_polars`) and parsed back by
# `OrgUnit`'s `parent`/`geometry` field validator.
_STRINGIFIED_COLUMNS = ("parent", "geometry")


def _is_nan(value: object) -> bool:
    """Check whether a value is a bare float NaN (pandas' stand-in for a missing value).

    Args:
        value: The value to check.

    Returns:
        bool: True if value is a float NaN.
    """
    return isinstance(value, float) and math.isnan(value)


def _records_to_polars(records: list[dict]) -> pl.DataFrame:
    """Build a polars DataFrame from row records, guarding against two silent-corruption pitfalls.

    `parent`/`geometry` are converted to their Python `str()` representation before polars ever
    sees them, since their nested shape varies by row (e.g. Point vs Polygon geometry) and would
    otherwise risk a Struct schema-inference crash; `OrgUnit`'s field validator parses that
    representation back into a dict. Separately, a missing value from
    `pd.DataFrame.to_dict("records")` surfaces as a bare float NaN rather than None, which would
    otherwise get silently stringified to the literal text "NaN" in a typed column, so it's
    normalized to None here too.

    Args:
        records: Row records, e.g. a raw DHIS2 API response or `pd.DataFrame.to_dict("records")`.

    Returns:
        pl.DataFrame: Records converted to columns, safe from both pitfalls above.
    """
    if not records:
        return pl.DataFrame(records)

    records = [
        {k: (None if _is_nan(v) else (str(v) if k in _STRINGIFIED_COLUMNS else v)) for k, v in record.items()}
        for record in records
    ]
    return pl.DataFrame(records)


class DHIS2PyramidAligner:
    """Align organisation units (OUs) between two DHIS2 instances.

    Compares source and target pyramids (hierarchies) and:
      - Creates OUs missing in the target
      - Updates OUs with changed attributes
      - Tracks actions and errors in a summary attribute for reporting
    Supports validation and logging.

    Usage: Instantiate with a logger and call align_to().
    """

    def __init__(self, logger: logging.Logger, clear_missing_fields: bool = False):
        """Initialize the aligner.

        Args:
            logger: Logger to use for reporting progress and errors.
            clear_missing_fields: Controls how an UPDATE handles a nullable field
                (`closedDate`/`parent`/`geometry`) that is unset in the source but set on the
                target. By default (False), the source is treated as additive/corrective only:
                such a field is omitted from the payload and DHIS2 keeps the target's existing
                value untouched. Set to True to treat the source as fully authoritative instead:
                the field is sent as an explicit `null`, clearing the target's existing value.
        """
        self.logger = logger if logger else logging.getLogger(__name__)
        self.log_function = log_message
        self.clear_missing_fields = clear_missing_fields
        self._initialize_summary()

    def _initialize_summary(self):
        self.summary = {
            "create": {"created": [], "invalid": [], "malformed": [], "error": []},
            "update": {"updated": [], "invalid": [], "malformed": [], "error": []},
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

        if "id" not in target_pyramid.columns:
            # In case of an empty target (e.g. a new DHIS2 instance)
            target_pyramid = pl.DataFrame({"id": []}, schema={"id": pl.String})

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
                self._log_error_ou(record, import_strategy="create", error_type="malformed", error_details=str(e))
                continue

            if ou.is_valid():
                self._handle_org_unit_push(ou=ou, target_dhis2=target_dhis2, import_strategy="create")
            else:
                self._log_error_ou(ou.to_json(), import_strategy="create", error_type="invalid")

    def _handle_org_unit_push(self, ou: OrgUnit, target_dhis2: DHIS2, import_strategy: str) -> None:
        """Handle the creation of an organisation unit in the target DHIS2 instance."""
        try:
            response = self._push_org_unit(
                dhis2_client=target_dhis2,
                org_unit=ou,
                import_strategy=import_strategy,
            )
        except Exception as e:
            self._log_error_ou(ou.to_json(), import_strategy=import_strategy, error_type="error", error_details=str(e))
            return

        self._handle_response(response=response, ou=ou, import_strategy=import_strategy)

    def _handle_response(self, response: dict, ou: OrgUnit, import_strategy: str) -> None:
        """Handle the response from the DHIS2 API after attempting to create or update an organisation unit."""
        if response is None:
            self._log_error_ou(
                ou.to_json(),
                import_strategy=import_strategy,
                error_type="error",
                error_details="No response received from DHIS2 API",
            )
            return

        if not isinstance(response, dict):
            self._log_error_ou(
                ou.to_json(),
                import_strategy=import_strategy,
                error_type="error",
                error_details="Invalid response format",
            )
            return

        if response.get("status") not in ("SUCCESS", "OK"):
            self._log_error_ou(
                ou.to_json(),
                import_strategy=import_strategy,
                error_type="error",
                error_details=f"Failed to {import_strategy} organisation unit: {response}",
            )
            return

        action_str = "created" if import_strategy == "create" else "updated"
        self.summary[import_strategy][action_str].append(ou.to_json())
        self._log_message(f"Organisation unit {action_str}: {ou.to_json()}", level="info", log_current_run=False)

    def _log_error_ou(
        self, ou: dict, import_strategy: str, error_type: str, error_details: str | None = None
    ) -> None:
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
                self._log_error_ou(record, import_strategy="update", error_type="malformed", error_details=str(e))

        total_ou = len(ou_ids_to_check)
        for progress_count, ou_id in enumerate(ou_ids_to_check, start=1):
            ou_source = source_by_id.get(ou_id)
            ou_target = target_by_id.get(ou_id)
            if ou_source is not None and ou_target is not None:
                if not ou_source.is_valid():
                    self._log_error_ou(ou_source.to_json(), import_strategy="update", error_type="invalid")
                # NOTE: See OrgUnit.__eq__() to check the comparison logic
                elif ou_source != ou_target:
                    self._handle_org_unit_push(ou=ou_source, target_dhis2=target_dhis2, import_strategy="update")

            if progress_count % logging_interval == 0 or progress_count == total_ou:
                self._log_message(f"Organisation units checked: {progress_count}/{total_ou} for update.")

    def _push_org_unit(
        self,
        dhis2_client: DHIS2,
        org_unit: OrgUnit,
        import_strategy: str = "create",
    ) -> dict:
        """Pushes an organisation unit to the DHIS2 instance using the specified strategy.

        Args:
            dhis2_client: The DHIS2 client instance to use for the API call.
            org_unit: The organisation unit to push.
            import_strategy: The strategy to use for the import ("create" or "update").

        Returns:
            dict: The response from the DHIS2 API.
        """
        if import_strategy == "create":
            endpoint = "organisationUnits"
            payload = org_unit.to_json()

        if import_strategy == "update":
            endpoint = "metadata"
            payload = {"organisationUnits": [org_unit.to_json(include_none_fields=self.clear_missing_fields)]}

        try:
            r = dhis2_client.api.session.post(
                f"{dhis2_client.api.url}/{endpoint}",
                json=payload,
                # DHIS2's importStrategy query param is a fixed, uppercase vocabulary
                # (CREATE/UPDATE/...); import_strategy is kept lowercase internally.
                params={"importStrategy": import_strategy.upper()},
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            raise OrgUnitAlignError from e

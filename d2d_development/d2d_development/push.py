import json
import logging
from pathlib import Path

import pandas as pd
import polars as pl
import requests
from openhexa.toolbox.dhis2 import DHIS2

from .data_models import DataPointModel
from .exceptions import PusherError
from .push_cache import DHIS2PushCache
from .utils import log_message


class DHIS2Pusher:
    """Main class to handle pushing data to DHIS2."""

    def __init__(
        self,
        dhis2_client: DHIS2,
        import_strategy: str = "CREATE_AND_UPDATE",
        dry_run: bool = True,
        max_post: int = 500,
        logging_interval: int = 50000,
        logger: logging.Logger | None = None,
        cache_path: Path | None = None,
    ):
        """Initialize the DHIS2Pusher."""
        self.dhis2_client = dhis2_client

        if import_strategy not in {"CREATE", "UPDATE", "CREATE_AND_UPDATE"}:
            raise PusherError("Invalid import strategy (use 'CREATE', 'UPDATE' or 'CREATE_AND_UPDATE')")

        self.mandatory_fields = ["dx", "period", "org_unit", "category_option_combo", "attribute_option_combo", "value"]
        self.import_strategy = import_strategy
        self.dry_run = dry_run
        self.max_post = max_post
        self.logging_interval = logging_interval
        self.summary = {}
        self._reset_summary()
        self.logger = logger if logger else logging.getLogger(__name__)
        self.log_function = log_message
        self._initialize_cache(cache_path)

    def push_data(
        self,
        df_data: pd.DataFrame | pl.DataFrame,
    ) -> None:
        """Push formatted data to DHIS2.

        Parameters
        ----------
        df_data : pd.DataFrame or pl.DataFrame
            DataFrame containing the data points to be pushed. Must include the following columns:
            'dx', 'period', 'orgUnit', 'categoryOptionCombo', 'attributeOptionCombo', and 'value'.

        Raises
        ------
        PusherError
            If the input data is not a DataFrame or if mandatory fields are missing.
        """
        self._reset_summary()
        self._set_summary_import_options()

        if isinstance(df_data, pd.DataFrame):
            df_data = pl.from_pandas(df_data)

        self._validate_input_data(df_data)

        if df_data.height == 0:
            self._log_message("Input DataFrame is empty. No data to push.")
            return

        if self.push_cache:
            df_data = self.push_cache.filter_new(df_data)
            if df_data.height == 0:
                self._log_message("All data points already pushed to DHIS2 (cache hit). Nothing to push.")
                return

        valid, to_delete, to_ignore = self._classify_data_points(df_data)

        self._push_valid(valid)
        self._push_to_delete(to_delete)
        self._log_summary_errors()
        self._log_ignored_or_na(to_ignore)
        self._update_cache_with(pl.concat([valid, to_delete]))

    def _validate_input_data(self, df_data: pl.DataFrame) -> None:
        """Validate that the input DataFrame contains all mandatory fields.

        Raises
        ------
            PusherError: If any mandatory field is missing from the DataFrame.
        """
        if not isinstance(df_data, pl.DataFrame):
            raise PusherError("Input data must be a pandas or polars DataFrame.")

        missing_fields = [field for field in self.mandatory_fields if field not in df_data.columns]
        if missing_fields:
            raise PusherError(f"Input data is missing mandatory columns: {', '.join(missing_fields)}")

    def _classify_data_points(self, data_points: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
        """Classify data points into valid, to delete, and to ignore based on mandatory fields.

        Returns
        -------
            tuple: A tuple containing three lists: (valid_data_points, to_delete_data_points, to_ignore_data_points).
        """
        # Valid data points have all mandatory fields non-null
        valid_mask = pl.all_horizontal([pl.col(col).is_not_null() for col in self.mandatory_fields])
        valid = data_points.filter(valid_mask).select(self.mandatory_fields)

        # Data points to delete have all mandatory fields non-null except 'value' which is null
        mandatory_fields_without_value = [col for col in self.mandatory_fields if col != "value"]
        delete_mask = (
            pl.all_horizontal([pl.col(col).is_not_null() for col in mandatory_fields_without_value])
            & pl.col("value").is_null()
        )
        to_delete = data_points.filter(delete_mask).select(self.mandatory_fields)

        # To ignore are those that don't fit either of the above criteria
        not_valid = data_points.filter(~valid_mask & ~delete_mask).select(self.mandatory_fields)

        return valid, to_delete, not_valid

    def _set_summary_import_options(self):
        """Set the import options in the summary dictionary based on the current configuration."""
        self.summary["import_options"] = {
            "importStrategy": self.import_strategy,
            "dryRun": self.dry_run,
            "preheatCache": True,  # hardcoded for now, could be made configurable if needed
            "skipAudit": True,  # hardcoded for now, could be made configurable if needed
        }

    def _push_valid(self, data_points_valid: pl.DataFrame) -> None:
        """Push valid values to DHIS2.

        Parameters
        ----------
        data_points_valid: pl.DataFrame
            DataFrame containing valid data points to be pushed to DHIS2.
        """
        if len(data_points_valid) == 0:
            self._log_message("No data to push.")
            return

        self._log_message(f"Pushing {data_points_valid.height} data points.")
        periods = sorted(data_points_valid["period"].unique().to_list())
        self._log_message(f"Period(s): {', '.join(periods)}.")
        self._push_data_points(data_point_list=self._serialize_data_points(data_points_valid))
        self._log_message(f"Data points push summary:  {self.summary['import_counts']}")

    def _push_to_delete(self, data_points_to_delete: pl.DataFrame) -> None:
        """Push data points with NA values to DHIS2 to delete them."""
        if data_points_to_delete.height == 0:
            return

        self._log_message(f"Pushing {len(data_points_to_delete)} data points with NA values.")
        self._log_ignored_or_na(data_points_to_delete, is_na=True)
        self._push_data_points(data_point_list=self._serialize_data_points(data_points_to_delete))
        self._log_message(f"Data points delete summary: {self.summary['import_counts']}")

    def _initialize_cache(self, cache_path: Path | None) -> None:
        """Initialize the cache for tracking pushed data points."""
        if cache_path is None or self.dry_run:
            self.push_cache = None
            return

        self.push_cache = DHIS2PushCache(cache_path=cache_path, logger=self.logger)

    def _update_cache_with(self, data: pl.DataFrame) -> None:
        """Update the cache with the latest pushed data points."""
        if self.push_cache is not None:
            self.push_cache.mark_pushed(self._remove_rejected_points(data))

    def _remove_rejected_points(self, data: pl.DataFrame) -> pl.DataFrame:
        """Remove data points that were rejected by DHIS2 from the DataFrame before updating the cache.

        `rejected_datapoints` entries are the *serialized* DHIS2 payload (DHIS2-cased keys), so
        rejected points are matched back to `data` by remapping to the internal key columns.

        Returns
        -------
            pl.DataFrame: A DataFrame containing only the data points that were successfully pushed to DHIS2.
        """
        rejected = self.summary.get("rejected_datapoints", [])
        if not rejected:
            return data

        key_columns = [c for c in self.mandatory_fields if c != "value"]
        rejected_keys = pl.DataFrame(
            [
                {
                    "dx": r["dataElement"],
                    "period": r["period"],
                    "org_unit": r["orgUnit"],
                    "category_option_combo": r["categoryOptionCombo"],
                    "attribute_option_combo": r["attributeOptionCombo"],
                }
                for r in rejected
            ]
        ).unique()

        return data.join(rejected_keys, on=key_columns, how="anti")

    def _log_ignored_or_na(self, data_points: pl.DataFrame, is_na: bool = False):
        """Logs ignored or NA data points.

        Parameters
        ----------
        data_points: pl.DataFrame
            DataFrame containing the data points to be logged as ignored or NA.
        is_na: bool
            Flag whether the data points are NA (to be deleted) or ignored. Defaults to False (ignored).
        """
        data_points_list = data_points.to_dicts()
        if len(data_points_list) > 0:
            self._log_message(
                f"{len(data_points_list)} data points will be {'set to NA' if is_na else 'ignored'}. "
                "Please check the last execution report for details.",
                level="warning",
            )
            for i, ignored in enumerate(data_points_list, start=1):
                row_str = ", ".join(f"{k}={v}" for k, v in ignored.items())
                self._log_message(
                    f"{i}. Data point {'NA' if is_na else 'ignored'}: {row_str}", log_current_run=False, level="warning"
                )
                if is_na:
                    self.summary["delete_data_points"].append(ignored)
                self.summary["ignored_data_points"].append(ignored)

    def _log_message(self, message: str, level: str = "info", log_current_run: bool = True, error_details: str = ""):
        """Log a message using the configured logging function."""
        self.log_function(
            logger=self.logger,
            message=message,
            error_details=error_details,
            level=level,
            log_current_run=log_current_run,
            exception_class=PusherError,
        )

    def _serialize_data_points(self, data_points: pl.DataFrame) -> list[dict]:
        """Convert a Polars DataFrame of data points into a list of dictionaries for DHIS2 API.

        Returns
        -------
            list[dict]: A list of dictionaries, each representing a data point formatted for DHIS2.
        """
        return [
            DataPointModel(
                dataElement=row["dx"],
                period=row["period"],
                orgUnit=row["org_unit"],
                categoryOptionCombo=row["category_option_combo"],
                attributeOptionCombo=row["attribute_option_combo"],
                value=row["value"],
            ).to_json()
            for row in data_points.to_dicts()
        ]

    def _log_summary_errors(self):
        """Logs all the errors in the summary dictionary using the configured logging."""
        errors = self.summary.get("import_errors", [])
        if not errors:
            self._log_message("No errors found in the summary.")
        else:
            self._log_message(f"Logging {len(errors)} error(s) from import summary.", level="error")
            for i_e, error in enumerate(errors, start=1):
                self._log_message(f"Error response {i_e}: {error}", log_current_run=False, level="error")

    def _post(self, chunk: list[dict]) -> requests.Response:
        """Send a POST request to DHIS2 for a chunk of data values.

        Returns
        -------
            requests.Response: The response object from the DHIS2 API.
        """
        return self.dhis2_client.api.session.post(
            f"{self.dhis2_client.api.url}/dataValueSets",
            json={"dataValues": chunk},
            params={
                "dryRun": self.dry_run,
                "importStrategy": self.import_strategy,
                "preheatCache": True,
                "skipAudit": True,
            },
        )

    def _push_data_points(
        self,
        data_point_list: list[dict],
    ) -> None:
        """Push data points to DHIS2 in chunks, handling responses and logging progress.

        Parameters
        ----------
        data_point_list: list[dict]
            A list of dictionaries, each representing a data point formatted for DHIS2.
        """
        total_data_points = len(data_point_list)
        processed_points = 0
        last_logged_at = 0

        for chunk_id, chunk in enumerate(self._split_list(data_point_list, self.max_post), start=1):
            r = None
            response = None
            try:
                r = self._post(chunk)
                r.raise_for_status()
                response = self._safe_json(r)

                if response:
                    self._update_import_counts(response)

            except requests.exceptions.RequestException as e:
                self._raise_server_errors(r)  # Stop the process if there's a server error
                response = self._safe_json(r)
                if response:
                    self._update_import_counts(response)
                else:
                    # No response JSON, at least log the request error msg
                    self.summary["import_errors"].extend(
                        [{"chunk": chunk_id, "period": chunk[0].get("period", "-"), "exception": str(e)}]
                    )
            finally:
                # Capture conflicts/errorReports if present
                self._extract_conflicts(response, chunk)

            processed_points += len(chunk)

            # Log every logging_interval points
            if processed_points - last_logged_at >= self.logging_interval:
                progress_pct = (processed_points / total_data_points) * 100
                self._log_message(
                    f"{processed_points} / {total_data_points} data points ({progress_pct:.1f}%) "
                    f" summary: {self.summary['import_counts']}"
                )
                last_logged_at = processed_points

        # Final summary
        self._log_message(
            f"{processed_points} / {total_data_points} data points processed."
            f" Final summary: {self.summary['import_counts']}"
        )

    def _raise_server_errors(self, r: requests.Response) -> None:
        """Check if the response indicates a server error (stop process)."""
        if r is not None and 500 <= r.status_code < 600:
            response = self._safe_json(r)
            if response and "message" in response:
                message = response["message"]
            else:
                message = f"HTTP {r.status_code} error with no message"

            error_info = {
                "server_error_code": f"{r.status_code}",
                "message": f"Server error: {message}",
            }
            self.summary["import_errors"].append(error_info)
            raise PusherError(f"Server error: {message}") from None

    def _reset_summary(self) -> None:
        """Reset the summary dictionary to its initial state before starting a new push operation."""
        self.summary = {
            "import_counts": {"imported": 0, "updated": 0, "ignored": 0, "deleted": 0},
            "import_options": {},
            "import_errors": [],
            "rejected_datapoints": [],
            "ignored_data_points": [],
            "delete_data_points": [],
        }

    def _split_list(self, src_list: list, length: int):
        """Split list into chunks.

        Yields:
            list: A chunk of the source list of the specified length.
        """
        for i in range(0, len(src_list), length):
            yield src_list[i : i + length]

    def _safe_json(self, r: requests.Response) -> dict | None:
        """Safely parse the JSON response from a requests.Response object.

        Returns:
            dict: The parsed JSON response if successful, or None if parsing fails or if the response is None.
        """
        if r is None:
            return None

        try:
            return r.json()
        except (ValueError, json.JSONDecodeError):
            return None

    def _update_import_counts(self, response: dict) -> None:
        """Update the import counts in the summary dictionary based on the response from DHIS2."""
        if not response:
            return
        if "importCount" in response:
            import_counts = response.get("importCount", {})
        elif "response" in response and "importCount" in response["response"]:
            import_counts = response["response"].get("importCount", {})
        else:
            import_counts = {}
        for key in ["imported", "updated", "ignored", "deleted"]:
            self.summary["import_counts"][key] += import_counts.get(key, 0)

    def _extract_conflicts(self, response: dict, chunk: list) -> None:
        """Extract all conflicts and errorReports from a DHIS2 API response.

        This method looks for 'conflicts' and 'errorReports' at both the top level and within a nested
        'response' object. It also extracts 'rejectedIndexes' from the nested 'response' to identify which data
        points were rejected by DHIS2, and adds them to the summary under 'rejected_datapoints'.

        Parameters
        ----------
        response: dict
            The JSON response from the DHIS2 API after attempting to push data points.
        chunk: list
            The list of data points that were included in the API request corresponding to the response.
        """
        if not response:
            return

        conflicts = response.get("conflicts", [])
        error_reports = response.get("errorReports", [])

        nested = response.get("response", {})
        conflicts += nested.get("conflicts", [])
        error_reports += nested.get("errorReports", [])
        rejected_indexes = nested.get("rejectedIndexes", [])

        all_errors = conflicts + error_reports

        if all_errors:
            self.summary.setdefault("import_errors", []).extend(all_errors)

        # Extract rejected datapoints
        if rejected_indexes:
            rejected_datapoints = [chunk[idx] for idx in rejected_indexes if 0 <= idx < len(chunk)]
            if rejected_datapoints:
                self.summary.setdefault("rejected_datapoints", []).extend(rejected_datapoints)

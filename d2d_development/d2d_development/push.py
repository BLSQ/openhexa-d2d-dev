import json
import logging

import pandas as pd
import polars as pl
import requests
from openhexa.sdk import current_run
from openhexa.toolbox.dhis2 import DHIS2

from .data_models import DataPointModel


class DHIS2Pusher:
    """Main class to handle pushing data to DHIS2."""

    def __init__(
        self,
        dhis2_client: DHIS2,
        import_strategy: str = "CREATE_AND_UPDATE",
        dry_run: bool = True,
        max_post: int = 500,
        logging_interval: int = 50000,
        mandatory_fields: list[str] | None = None,
        logger: logging.Logger | None = None,
    ):
        self.dhis2_client = dhis2_client

        if import_strategy not in {"CREATE", "UPDATE", "CREATE_AND_UPDATE"}:
            raise ValueError("Invalid import strategy (use 'CREATE', 'UPDATE' or 'CREATE_AND_UPDATE')")

        if mandatory_fields is None:
            self.mandatory_fields = ["dx", "period", "orgUnit", "categoryOptionCombo", "attributeOptionCombo", "value"]
        else:
            self.mandatory_fields = mandatory_fields

        self.import_strategy = import_strategy
        self.dry_run = dry_run
        self.max_post = max_post
        self.logging_interval = logging_interval
        self.summary = {}
        self._reset_summary()
        self.logger = logger if logger else logging.getLogger(__name__)

    def push_data(
        self,
        df_data: pd.DataFrame | pl.DataFrame,
    ) -> None:
        """Push formatted data to DHIS2."""
        if isinstance(df_data, pd.DataFrame):
            df_data = pl.from_pandas(df_data)

        if not isinstance(df_data, pl.DataFrame):
            raise ValueError("Input data must be a pandas or polars DataFrame.")

        if df_data.height == 0:
            current_run.log_info("Input DataFrame is empty. No data to push.")
            return

        valid, to_delete, to_ignore = self._classify_data_points(df_data)

        self._push_valid(valid)
        self._push_to_delete(to_delete)
        self._log_ignored_or_na(to_ignore)

    def _classify_data_points(self, data_points: pl.DataFrame) -> tuple[list, list, list]:
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

    def _push_valid(self, data_points_valid: list, logging_interval: int = 50000) -> None:
        """Push valid values to DHIS2."""
        if len(data_points_valid) == 0:
            current_run.log_info("No data to push.")
            return

        msg = f"Pushing {len(data_points_valid)} data points."
        current_run.log_info(msg)
        self.logger.info(msg)
        self._push_data_points(data_point_list=self._serialize_data_points(data_points_valid))
        msg = f"Data points push summary:  {self.summary['import_counts']}"
        current_run.log_info(msg)
        self.logger.info(msg)
        self._log_summary_errors()

    def _push_to_delete(self, data_points_to_delete: pl.DataFrame) -> None:
        if data_points_to_delete.height == 0:
            return

        current_run.log_info(f"Pushing {len(data_points_to_delete)} data points with NA values.")
        self.logger.info(f"Pushing {len(data_points_to_delete)} data points with NA values.")
        self._log_ignored_or_na(data_points_to_delete, is_na=True)
        self._push_data_points(data_point_list=self._serialize_data_points(data_points_to_delete))

        current_run.log_info(f"Data points delete summary: {self.summary['import_counts']}")
        self.logger.info(f"Data points delete summary: {self.summary['import_counts']}")
        self._log_summary_errors()

    def _log_ignored_or_na(self, data_point_list: list, is_na: bool = False):
        """Logs ignored or NA data points."""
        if len(data_point_list) > 0:
            current_run.log_info(
                f"{len(data_point_list)} data points will be  {'set to NA' if is_na else 'ignored'}. "
                "Please check the last execution report for details."
            )
            self.logger.warning(f"{len(data_point_list)} data points to be {'set to NA' if is_na else 'ignored'}: ")
            for i, ignored in enumerate(data_point_list, start=1):
                row_str = ", ".join(f"{k}={v}" for k, v in ignored.items())
                self.logger.warning(f"{i}. Data point {'NA' if is_na else 'ignored'}: {row_str}")

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
                orgUnit=row["orgUnit"],
                categoryOptionCombo=row["categoryOptionCombo"],
                attributeOptionCombo=row["attributeOptionCombo"],
                value=row["value"],
            ).to_json()
            for row in data_points.to_dicts()
        ]

    def _log_summary_errors(self):
        """Logs all the errors in the summary dictionary using the configured logging."""
        errors = self.summary.get("ERRORS", [])
        if not errors:
            self.logger.info("No errors found in the summary.")
        else:
            self.logger.error(f"Logging {len(errors)} error(s) from export summary.")
            for i_e, error in enumerate(errors, start=1):
                self.logger.error(f"Error response {i_e}: {error}")

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
        """dry_run: Set to true to get an import summary without actually importing data (DHIS2)."""
        self._reset_summary()
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

                # Capture conflicts/errorReports if present
                self._extract_conflicts(response)

            except requests.exceptions.RequestException as e:
                response = self._safe_json(r)
                if response:
                    self._update_import_counts(response)
                else:
                    # No response JSON, at least log the request error msg
                    self.summary["ERRORS"].extend(
                        [{"chunk": chunk_id, "period": chunk[0].get("period", "-"), "exception": str(e)}]
                    )
                self._extract_conflicts(response)

            processed_points += len(chunk)

            # Log every logging_interval points
            if processed_points - last_logged_at >= self.logging_interval:
                progress_pct = (processed_points / total_data_points) * 100
                current_run.log_info(
                    f"{processed_points} / {total_data_points} data points ({progress_pct:.1f}%) "
                    f" summary: {self.summary['import_counts']}"
                )
                last_logged_at = processed_points

        # Final summary
        current_run.log_info(
            f"{processed_points} / {total_data_points} data points processed."
            f" Final summary: {self.summary['import_counts']}"
        )

    def _reset_summary(self) -> None:
        self.summary = {
            "import_counts": {"imported": 0, "updated": 0, "ignored": 0, "deleted": 0},
            "import_options": {},
            "ERRORS": [],
        }

    def _split_list(self, src_list: list, length: int):
        """Split list into chunks.

        Yields:
            list: A chunk of the source list of the specified length.
        """
        for i in range(0, len(src_list), length):
            yield src_list[i : i + length]

    def _safe_json(self, r: requests.Response) -> dict | None:
        if r is None:
            return None

        try:
            return r.json()
        except (ValueError, json.JSONDecodeError):
            return None

    def _update_import_counts(self, response: dict) -> None:
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

    def _extract_conflicts(self, response: dict) -> None:
        """Extract all conflicts and errorReports from a DHIS2 API response.

        Handles both top-level and nested 'response' nodes. Optionally updates the summary.

        Parameters
        ----------
        response : dict
            The JSON response from DHIS2 after an import.
        """
        if not response:
            return
        conflicts = response.get("conflicts", [])
        error_reports = response.get("errorReports", [])

        # Check if nested under "response"
        nested = response.get("response", {})
        conflicts += nested.get("conflicts", [])
        error_reports += nested.get("errorReports", [])
        all_errors = conflicts + error_reports

        if all_errors:
            self.summary.setdefault("ERRORS", []).extend(all_errors)

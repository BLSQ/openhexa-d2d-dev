import json
import logging
from pathlib import Path

import pandas as pd
import requests
from openhexa.toolbox.dhis2 import DHIS2

from .exceptions import DHIS2DatasetCompletionError
from .utils import log_message


class DatasetCompletionSync:
    """Main class to handle pushing data to DHIS2.

    NOTE: This syncer is experimental and should be used with caution.

    NOTE: This syncer assumes the source and target DHIS2 instances
     should have the same dataset structure and org unit structure.
    """

    def __init__(
        self,
        source_dhis2: DHIS2,
        target_dhis2: DHIS2,
        import_strategy: str = "CREATE_AND_UPDATE",
        dry_run: bool = True,
        logger: logging.Logger | None = None,
    ):
        if import_strategy not in {"CREATE", "UPDATE", "CREATE_AND_UPDATE"}:
            raise ValueError("Invalid import strategy (use 'CREATE', 'UPDATE' or 'CREATE_AND_UPDATE')")
        self.source_dhis2 = source_dhis2
        self.target_dhis2 = target_dhis2
        self.import_strategy = import_strategy
        self.dry_run = dry_run
        self.processed = []
        self.completion_table = pd.DataFrame()
        self._reset_summary()
        self.logger = logger if logger else logging.getLogger(__name__)
        self.log_function = log_message

    def _reset_summary(self) -> None:
        """Reset the import summary to its initial state."""
        self.import_summary = {
            "import_counts": {"imported": 0, "updated": 0, "ignored": 0, "deleted": 0},
            "errors": {"fetch_errors": [], "no_completion": [], "push_errors": []},
        }

    def _update_import_summary(self, response: dict) -> None:
        if response:
            import_counts = response.get("importCount", {})
            if not import_counts:
                import_counts = response.get("response", {}).get("importCount", {})
            for key in ["imported", "updated", "ignored", "deleted"]:
                self.import_summary["import_counts"][key] += import_counts.get(key, 0)

    def _log_message(self, message: str, level: str = "info", log_current_run: bool = True, error_details: str = ""):
        """Log a message using the configured logging function."""
        self.log_function(
            logger=self.logger,
            message=message,
            error_details=error_details,
            level=level,
            log_current_run=log_current_run,
            exception_class=DHIS2DatasetCompletionError,
        )

    def _log_and_append_error(
        self,
        error_type: str,
        ds: str,
        pe: str,
        ou: str,
        error_msg: str,
        level: str = "error",
        log_current_run: bool = False,
    ):
        """Helper function to log an error message and append it to the import summary."""
        error_dict = {"ds": ds, "pe": pe, "ou": ou, "error": error_msg}
        self.import_summary["errors"][error_type].append(error_dict)
        self._log_message(
            f"[{error_type}] {error_msg} ds={ds} pe={pe}, ou={ou}", level=level, log_current_run=log_current_run
        )

    def _log_summary(self, org_units: list, period: str) -> None:
        """Log a summary of the dataset completion sync process."""
        self._log_message(
            f"Dataset completion period {period} summary: {self.import_summary['import_counts']} "
            f"total org units: {len(org_units)} "
        )

        total_no_completion = len(self.import_summary["errors"]["no_completion"])
        if total_no_completion > 0:
            self._log_message(
                f"{total_no_completion} out of "
                f"{len(org_units)} completion statuses failed to be retrieved from source.",
                level="warning",
            )

        total_fetch_errors = len(self.import_summary["errors"]["fetch_errors"])
        if total_fetch_errors > 0:
            self._log_message(
                f"{total_fetch_errors} out of {len(org_units)} completion statuses failed to fetch.",
                level="warning",
            )

        total_push_errors = len(self.import_summary["errors"]["push_errors"])
        if total_push_errors > 0:
            self._log_message(
                f"{total_push_errors} out of {len(org_units)} completion statuses failed to push.",
                level="warning",
            )

    def _fetch_completion_status_from_source(
        self,
        dataset_id: str,
        period: str,
        org_unit: str,
        children: bool = True,
        timeout: int = 5,
    ) -> list[dict]:
        """Fetch completion status from source DHIS2.

        Args:
            dataset_id: The dataset ID to fetch completion status for.
            period: The period for which to fetch the completion status.
            org_unit: The organisation unit to fetch completion status for.
            children: Whether to include child org units in the fetch.
            timeout: Timeout for the request in seconds.

        Returns:
            list[dict]: A list of completion status dictionaries from the DHIS2 API.
                Returns an empty list if the request fails or no data is found.
        """
        endpoint = f"{self.source_dhis2.api.url}/completeDataSetRegistrations"
        params = {
            "period": period,
            "orgUnit": org_unit,
            "children": "true" if children else "false",
            "dataSet": dataset_id,
        }

        try:
            response = self.source_dhis2.api.session.get(endpoint, params=params, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as e:
            self._log_and_append_error(
                error_type="fetch_errors",
                ds=dataset_id,
                pe=period,
                ou=org_unit,
                error_msg=(f"GET request with (param: children={children}) failed to retrieve completion status {e!s}"),
            )
            return []

        data = self._try_parse_json(response)
        if data is None:
            self._log_and_append_error(
                error_type="fetch_errors",
                ds=dataset_id,
                pe=period,
                ou=org_unit,
                error_msg=(f"GET request (param: children={children}): Invalid or empty JSON response"),
            )
            return []

        completion = data.get("completeDataSetRegistrations", [])
        if not completion and not children:
            self._log_and_append_error(
                error_type="no_completion",
                ds=dataset_id,
                pe=period,
                ou=org_unit,
                error_msg=(f"GET request (param: children={children}): Empty completion status"),
            )

        return completion

    def _push_completion_status_to_target(
        self,
        dataset_id: str,
        period: str,
        org_unit: str,
        date: str,
        completed: bool,
        timeout: int = 5,
    ) -> None:
        """Perform a PUT request (or POST with importStrategy) to a DHIS2 API endpoint.

        Args:
        dataset_id: The dataset ID to push completion status for.
        period: The period for which to push the completion status.
        org_unit: The organisation unit to push completion status for.
        date: The date of completion.
        completed: Whether the dataset is marked as completed.
        timeout: Timeout for the request in seconds.

        Raises:
            requests.HTTPError if the request fails after retries.
        """
        endpoint = f"{self.target_dhis2.api.url}/completeDataSetRegistrations"
        payload = self._build_completion_payload(
            dataset_id=dataset_id, period=period, org_unit=org_unit, date=date, completed=completed
        )
        params = self._build_push_params()
        response = None
        try:
            response = self.target_dhis2.api.session.post(endpoint, json=payload, params=params, timeout=timeout)
            response.raise_for_status()
            self._handle_push_response(ds=dataset_id, pe=period, ou=org_unit, response=response)
        except requests.RequestException:
            self._handle_push_error_response(ds=dataset_id, pe=period, ou=org_unit, response=response)

    def _build_completion_payload(
        self, dataset_id: str, period: str, org_unit: str, date: str, completed: bool
    ) -> dict:
        """Build the payload for the completion status request.

        Returns:
            dict: The payload to be sent with the completion status request.
        """
        return {
            "completeDataSetRegistrations": [
                {
                    "organisationUnit": org_unit,
                    "period": period,
                    "completed": completed,
                    "date": date,
                    "dataSet": dataset_id,
                }
            ]
        }

    def _build_push_params(self) -> dict:
        """Build the parameters for the push request.

        Returns:
            dict: The parameters to be sent with the push request.
        """
        return {
            "dryRun": self.dry_run,
            "importStrategy": self.import_strategy,
            "preheatCache": True,
            "skipAudit": True,
            "reportMode": "FULL",
        }

    def _try_build_source_completion_table(self, org_units: list[str], dataset_id: str, period: str) -> None:
        """Build a completion status table for all organisation units provided.

        Args:
            org_units: List of organisation unit IDs to fetch completion status for (NOTE: use OU parents).
            dataset_id: The dataset ID to fetch completion status for.
            period: The period for which to fetch the completion status.
        """
        if not org_units:
            return

        completion_statuses = []
        for ou in org_units:
            completion = self._fetch_completion_status_from_source(
                dataset_id=dataset_id, period=period, org_unit=ou, children=True, timeout=30
            )
            if completion:
                completion_statuses.extend(completion)

        self.completion_table = pd.DataFrame(completion_statuses)

    def _get_source_completion_status_for(self, dataset_id: str, period: str, org_unit: str) -> dict | None:
        """Handle fetching completion status for a specific org unit.

        Returns:
            list: The completion status as dictionaries for the specified org unit (children) if found, otherwise [].
        """
        if not self.completion_table.empty:
            completion_status = self.completion_table[self.completion_table["organisationUnit"] == org_unit]
            if not completion_status.empty:
                return completion_status.iloc[0].to_dict()

        results = self._fetch_completion_status_from_source(
            dataset_id=dataset_id, period=period, org_unit=org_unit, children=False
        )
        for item in results or []:
            if item.get("organisationUnit") == org_unit:
                return item

        return None

    def _handle_empty_completion_status(self, ds: str, pe: str, ou: str, uncompleted_as_processed: bool) -> None:
        """Handle the case when no completion status is found for an org unit."""
        cp = {"ds": ds, "pe": pe, "ou": ou, "error": "empty completion status"}
        if uncompleted_as_processed:
            self._log_message(
                f"No completion, setting point as processed: {cp}", level="warning", log_current_run=False
            )
            self.processed.append(ou)  # if True, empty completion -> mark as processed

    def sync(
        self,
        source_dataset_id: str,
        target_dataset_id: str,
        org_units: list[str] | None,
        period: str,
        parent_ou: list[str] | None = None,
        saving_interval: int = 1000,
        ds_processed_path: Path | None = None,
        mark_uncompleted_as_processed: bool = False,
    ) -> None:
        """Sync completion status between datasets.

        source_dataset_id: The dataset ID in the source DHIS2 instance.
        target_dataset_id: The dataset ID in the target DHIS2 instance.
        org_units: List of organisation unit IDs to sync.
        parent_ou: List of parent organisation unit IDs to build completion table (if None, no table built).
        period: The period for which to sync the completion status.
        saving_interval: Interval for saving progress (defaults to 2000).
        ds_processed_path: Path to save processed org units (if None, no file saving nor comparison).
        mark_uncompleted_as_processed: If True, org units with no completion status will be marked as processed.

        Note: Only org units pushed with completed=True are written to the processed file. Org units pushed
        with completed=False are intentionally excluded so they are retried on the next run, in case their
        completion status has changed.
        """
        self._reset_summary()

        if not org_units:
            self._log_message(f"No org units provided for period {period}. DS sync skipped.", level="warning")
            return

        org_units_to_process = self._get_unprocessed_org_units(org_units, ds_processed_path, period)
        if not org_units_to_process:
            self._log_message(f"All org units already processed for period {period}. DS sync skipped.")
            return

        self._log_message(
            f"Starting dataset '{target_dataset_id}' completion process for period: "
            f"{period} org units: {len(org_units_to_process)}."
        )

        self._try_build_source_completion_table(org_units=parent_ou, dataset_id=source_dataset_id, period=period)

        try:
            self.processed = []
            total_ou = len(org_units_to_process)
            for idx, ou in enumerate(org_units_to_process, start=1):
                self._process_org_unit(
                    ou=ou,
                    source_dataset_id=source_dataset_id,
                    target_dataset_id=target_dataset_id,
                    period=period,
                    mark_uncompleted_as_processed=mark_uncompleted_as_processed,
                )
                self._save_progress_if_needed(
                    idx=idx,
                    total=total_ou,
                    saving_interval=saving_interval,
                    period=period,
                    processed_path=ds_processed_path,
                )
        except Exception as e:
            error_msg = (
                f"Dataset completion sync failed for dataset {target_dataset_id}, pe: {period} ou: {ou}. Error: {e}"
            )
            self._log_message(error_msg, level="error", log_current_run=False)
            raise DHIS2DatasetCompletionError(error_msg) from e
        finally:
            # repetitive save, but safer
            self._update_processed_ds_sync_file(
                period=period,
                processed_path=ds_processed_path,
            )
            self._log_summary(org_units=org_units_to_process, period=period)

    def _process_org_unit(
        self,
        ou: str,
        source_dataset_id: str,
        target_dataset_id: str,
        period: str,
        mark_uncompleted_as_processed: bool,
    ) -> None:
        completion_status = self._get_source_completion_status_for(
            dataset_id=source_dataset_id,
            period=period,
            org_unit=ou,
        )

        if not completion_status:
            self._handle_empty_completion_status(
                ds=source_dataset_id,
                pe=period,
                ou=ou,
                uncompleted_as_processed=mark_uncompleted_as_processed,
            )
            return

        if "date" not in completion_status or "completed" not in completion_status:
            self._log_and_append_error(
                error_type="fetch_errors",
                ds=source_dataset_id,
                pe=period,
                ou=ou,
                error_msg="Missing keys 'date' or 'completed' from completion response",
            )
            return

        try:
            self._push_completion_status_to_target(
                dataset_id=target_dataset_id,
                period=period,
                org_unit=ou,
                date=completion_status.get("date"),
                completed=completion_status.get("completed"),
            )
            if completion_status.get("completed") is not None and completion_status.get("completed"):
                self.processed.append(ou)
        except DHIS2DatasetCompletionError:
            pass
        except Exception as e:
            raise DHIS2DatasetCompletionError(f"Unexpected error pushing completion status: {e!s}") from e

    def _save_progress_if_needed(
        self,
        idx: int,
        total: int,
        saving_interval: int,
        period: str,
        processed_path: Path | None,
    ) -> None:
        """Save progress at specified intervals."""
        if idx % saving_interval == 0:
            self._log_message(f"{idx} / {total} OUs processed")
            self._update_processed_ds_sync_file(period=period, processed_path=processed_path)

    def _get_unprocessed_org_units(self, org_units: list, processed_path: Path | None, period: str) -> list:
        if processed_path is None:
            return org_units

        ds_processed_fname = processed_path / f"ds_ou_processed_{period}.parquet"
        if not ds_processed_fname.exists():
            self._log_message(
                f"No processed file found for {period}, processing {len(org_units)} org units.",
            )
            return list(set(org_units))

        try:
            processed_df = pd.read_parquet(ds_processed_fname)
            if "ORG_UNIT" not in processed_df.columns:
                raise KeyError("Missing ORG_UNIT column")

            processed_set = set(processed_df["ORG_UNIT"].dropna().unique())
            remaining = [ou for ou in org_units if ou not in processed_set]
        except Exception as e:
            self._log_message(
                f"Error loading processed file: {ds_processed_fname}. Returning all org units to process.",
                level="error",
                error_details=str(e),
            )
            return list(set(org_units))

        self._log_message(
            f"Loaded {len(processed_set)} processed org units, {len(remaining)} to process for period {period}."
        )
        return list(set(remaining))

    def _update_processed_ds_sync_file(
        self,
        period: str,
        processed_path: Path | None,
    ) -> None:
        """Save the processed org units to a parquet file."""
        if processed_path is None:
            self._log_message("No processed path provided, skipping save.", level="info")
            return

        try:
            processed_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._log_message(f"Failed to create directory {processed_path}: {e}", level="error")
            return

        ds_processed_file = processed_path / f"ds_ou_processed_{period}.parquet"

        self._log_message(f"Period {period}: Current interval processed {len(self.processed)} OUs.", level="debug")

        existing_org_units = set()
        if ds_processed_file.exists():
            try:
                existing_df = pd.read_parquet(ds_processed_file)
                if "ORG_UNIT" in existing_df.columns:
                    existing_org_units = set(existing_df["ORG_UNIT"].unique())
                else:
                    self._log_message(
                        f"File {ds_processed_file} missing ORG_UNIT column, treating as empty.", level="warning"
                    )
            except Exception as e:
                self._log_message(f"Error reading {ds_processed_file}: {e}", level="error")

        # Calculate new OUs
        new_org_units = set(self.processed) - existing_org_units

        if not new_org_units:
            self._log_message(f"No new OUs to save for period {period}.", level="debug")
            self.processed = []
            return

        # Merge and save
        final_processed = list(existing_org_units | new_org_units)

        try:
            df_processed = pd.DataFrame({"ORG_UNIT": final_processed})
            df_processed.to_parquet(ds_processed_file, index=False)
            self._log_message(
                f"Saved {ds_processed_file.name}: "
                f"{len(existing_org_units)} existing + {len(new_org_units)} new = {len(final_processed)} total OUs."
            )
            self.processed = []  # Reset after successful save
        except Exception as e:
            self._log_message(f"Error writing {ds_processed_file}: {e}", level="error")

    def _handle_push_response(self, ds: str, pe: str, ou: str, response: requests.Response) -> None:
        """Handle a successful DHIS2 completion status push response.

        Args:
            ds (str): Dataset ID.
            pe (str): Period.
            ou (str): Organisation unit ID.
            response (Response): The response from the DHIS2 API.
        """
        json_data = self._try_parse_json(response)
        status = (json_data.get("status") or "").upper() if json_data else None
        if status in ("SUCCESS", "OK"):
            self._log_message(f"Successful POST response for ds: {ds} pe:{pe} ou: {ou}", log_current_run=False)
            self._update_import_summary(response=json_data)
            return

        raise requests.RequestException("Unexpected DHIS2 status")

    def _handle_push_error_response(self, ds: str, pe: str, ou: str, response: requests.Response) -> None:
        """Log the response from the DHIS2 API after pushing completion status.

        Raise DHIS2DatasetCompletionError if the response indicates an error or warning,
        or if the response format is invalid.
        """
        json_data = self._try_parse_json(response)

        if json_data is None:
            self._log_and_append_error(
                error_type="push_errors",
                ds=ds,
                pe=pe,
                ou=ou,
                error_msg="No JSON response received for completion request",
            )
            raise DHIS2DatasetCompletionError("No JSON response received for completion request")

        if not isinstance(json_data, dict):
            self._log_and_append_error(
                error_type="push_errors",
                ds=ds,
                pe=pe,
                ou=ou,
                error_msg=f"Invalid JSON response format (expected dict): {json_data!s}",
            )
            raise DHIS2DatasetCompletionError(f"Invalid JSON response format (expected dict): {json_data!s}")

        conflicts: list[str] = json_data.get("conflicts", [])
        if not conflicts:
            conflicts: list[str] = json_data.get("response", {}).get("conflicts", [])
        if not isinstance(conflicts, list):
            conflicts = [str(conflicts)]
        status = (json_data.get("status") or "").upper()

        if status in {"ERROR", "WARNING"} or conflicts:
            conflict_str = "; ".join(str(conflict) for conflict in conflicts)
            self._log_and_append_error(
                error_type="push_errors",
                ds=ds,
                pe=pe,
                ou=ou,
                error_msg=f"Status ({status}): {conflict_str}",
            )
            self._update_import_summary(response=json_data)
            raise DHIS2DatasetCompletionError(f"Failed to push completion status: {json_data!s}")

        self._log_and_append_error(
            error_type="push_errors",
            ds=ds,
            pe=pe,
            ou=ou,
            error_msg=f"Unexpected DHIS2 status ({status}), treating as error",
        )
        raise DHIS2DatasetCompletionError(f"Unexpected DHIS2 status ({status}): {json_data!s}")

    def _try_parse_json(self, r: requests.Response) -> dict | None:
        if r is None:
            return None
        try:
            data = r.json()
            if not data:
                return None
            return data
        except (ValueError, json.JSONDecodeError):
            return None

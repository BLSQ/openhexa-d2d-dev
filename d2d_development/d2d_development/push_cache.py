import logging
from pathlib import Path

import polars as pl

from .exceptions import PusherCacheError
from .utils import log_message


class DHIS2PushCache:
    """Tracks datapoints already pushed to DHIS2 to avoid re-pushing unchanged records.

    A datapoint is identified by hashing the metadata columns of each row in the data to push.
    Columns:
     ["dx", "period", "org_unit", "category_option_combo", "attribute_option_combo"]
    A row is only considered "pushed" when the value in the "value" column, is identical to the cached value.
    A row is considered "new" if any the value columns has changed since the last push.
    Any difference in the value column, including None, is treated as a new.
    The cache data is updated with the new value after a successful push (mark_pushed(data pushed)).
    """

    def __init__(self, cache_path: Path, logger: logging.Logger | None = None, verbose: bool = False):
        self.cache_path = Path(cache_path)
        self.logger = logger if logger else logging.getLogger(__name__)
        self.verbose = verbose
        self._cache_data: pl.DataFrame | None = None
        self._mandatory_fields = [
            "dx",
            "period",
            "org_unit",
            "category_option_combo",
            "attribute_option_combo",
            "value",
        ]
        self._log_function = log_message

    def filter_new(self, data: pl.DataFrame) -> pl.DataFrame:
        """Returns the rows of `data` that have not already been pushed.

        Args:
            data: Datapoints (serialized DataPointModel) about to be pushed.

        Returns:
            Subset of `data` whose rows have no exact match in the cache.
        """
        if data.height == 0:
            self._log_message("No data to push.", log_current_run=self.verbose)
            return data

        self._load(self._resolve_data_periods(data))
        if self._cache_data is None or self._cache_data.height == 0:
            self._log_message("No cache data found. All rows will be pushed.", log_current_run=self.verbose)
            return data

        to_push = data.join(
            self._cache_data,
            on=[c for c in self._mandatory_fields if c != "value"],
            how="left",
            suffix="_cached",
        ).filter(pl.col("value_cached").is_null() | pl.col("value").ne_missing(pl.col("value_cached")))

        self._log_message(
            f"Filtered {data.height - to_push.height} rows already pushed to DHIS2.", log_current_run=self.verbose
        )
        return to_push

    def mark_pushed(self, data: pl.DataFrame) -> None:
        """Records `data` as pushed, so filter_new() skips it on the next run.

        Call this only after a push has been confirmed successful - marking
        rows before that risks silently dropping datapoints whose push failed.

        Args:
            data: Datapoints that were just pushed successfully.
        """
        if data.height > 0:
            self.cache_path.mkdir(parents=True, exist_ok=True)
            data = data.select(self._mandatory_fields)
            if self._cache_data is None:
                self._create_cache(data)
            else:
                self._update_cache(data)

    def _resolve_data_periods(self, data: pl.DataFrame) -> list[str]:
        """Returns the periods present in the data.

        Args:
            data: Datapoints to be pushed.

        Returns:
            The periods present in the data.
        """
        return data["period"].unique().to_list()

    def _load(self, periods: list[str]) -> None:
        """Reads cache_<period>.parquet files matching `periods` into self._cache_data.

        This always reads fresh from disk on every call - it does not skip periods
        that were already loaded by a previous call.
        """
        if self.cache_path.exists():
            file_paths = []
            data_list = []
            for period in periods:
                file_paths.extend(self.cache_path.glob(f"cache_{period}.parquet"))
            for fname in file_paths:
                try:
                    data_list.append(pl.read_parquet(fname))
                except Exception as e:
                    self._log_message(
                        f"Failed to load cache file {fname}.",
                        level="error",
                        error_details=str(e),
                    )
            self._cache_data = pl.concat(data_list) if data_list else None
        else:
            self._log_message(
                f"Cache path {self.cache_path} does not exist. No cache data loaded.", log_current_run=self.verbose
            )

    def _create_cache(self, data: pl.DataFrame) -> None:
        """Creates a new cache from the provided data."""
        periods = data["period"].unique().to_list()
        key_columns = [c for c in self._mandatory_fields if c != "value"]
        for period in periods:
            period_data = data.filter(pl.col("period") == period).unique(subset=key_columns, keep="last")
            period_data.write_parquet(self.cache_path / f"cache_{period}.parquet")

    def _update_cache(self, data_pushed: pl.DataFrame) -> None:
        """Updates the cache with the newly pushed data.

        For each period, cached rows whose datapoint key matches a newly pushed row
        are dropped and replaced by the pushed row's new value; rows whose key was
        not previously cached are simply added.
        """
        key_columns = [c for c in self._mandatory_fields if c != "value"]
        periods = data_pushed["period"].unique().to_list()
        for period in periods:
            period_data = data_pushed.filter(pl.col("period") == period).unique(subset=key_columns, keep="last")
            cached_period_data = self._cache_data.filter(pl.col("period") == period)
            other_periods_data = self._cache_data.filter(pl.col("period") != period)

            # remove any cached rows matching the newly pushed rows, and then add the new ones.
            updated_period_data = pl.concat(
                [cached_period_data.join(period_data.select(key_columns), on=key_columns, how="anti"), period_data]
            )
            self._cache_data = pl.concat([other_periods_data, updated_period_data])

            try:
                updated_period_data.write_parquet(self.cache_path / f"cache_{period}.parquet")
            except Exception as e:
                self._log_message(
                    f"Failed to update cache file for period {period}.",
                    level="error",
                    error_details=str(e),
                )

    def _log_message(self, message: str, level: str = "info", log_current_run: bool = True, error_details: str = ""):
        """Log a message using the configured logging function."""
        self._log_function(
            logger=self.logger,
            message=message,
            error_details=error_details,
            level=level,
            log_current_run=log_current_run,
            exception_class=PusherCacheError,
        )

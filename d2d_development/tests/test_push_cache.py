from pathlib import Path
from unittest.mock import patch

import polars as pl

from d2d_development.push_cache import DHIS2PushCache

CACHE_COLUMNS = ["dx", "period", "org_unit", "category_option_combo", "attribute_option_combo", "value"]


def _write_cache_file(cache_path: Path, period: str, dx_values: list[str]) -> pl.DataFrame:
    """Write a cache_<period>.parquet file with one row per value in `dx_values`.

    Returns:
        The DataFrame that was written to the cache file.
    """
    cache_df = pl.DataFrame(
        {
            "dx": dx_values,
            "period": [period] * len(dx_values),
            "org_unit": [f"OU{i}" for i in range(len(dx_values))],
            "category_option_combo": ["COC1"] * len(dx_values),
            "attribute_option_combo": ["AOC1"] * len(dx_values),
            "value": [str(i * 10) for i in range(len(dx_values))],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )
    cache_df.write_parquet(cache_path / f"cache_{period}.parquet")
    return cache_df


def test_filter_new_keeps_changed_and_new_rows(tmp_path: Path):
    """Test that filter_new() drops rows unchanged since the last push and keeps the rest."""
    cached_data = pl.DataFrame(
        {
            "dx": ["DE1", "DE2", "DE3", "DE4"],
            "period": ["202501", "202501", "202501", "202501"],
            "org_unit": ["OU1", "OU2", "OU3", "OU4"],
            "category_option_combo": ["COC1", "COC1", "COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1", "AOC1", "AOC1"],
            "value": ["10", "20", "30", "40"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )
    cached_data.write_parquet(tmp_path / "cache_202501.parquet")

    data = pl.DataFrame(
        {
            "dx": ["DE1", "DE2", "DE5"],
            "period": ["202501", "202501", "202501"],
            "org_unit": ["OU1", "OU2", "OU5"],
            "category_option_combo": ["COC1", "COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1", "AOC1"],
            "value": ["10", "25", "50"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    push_cache = DHIS2PushCache(cache_path=tmp_path)
    result = push_cache.filter_new(data).sort("dx")

    assert result.height == 2
    assert result["dx"].to_list() == ["DE2", "DE5"]
    assert result["value"].to_list() == ["25", "50"]


def test_filter_new_across_multiple_periods_some_without_cache(tmp_path: Path):
    """Test filter_new() with 3 periods: 2 with a cache file each, and 1 with no cache file at all."""
    cache_202501 = pl.DataFrame(
        {
            "dx": ["DE1", "DE2"],
            "period": ["202501", "202501"],
            "org_unit": ["OU1", "OU2"],
            "category_option_combo": ["COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1"],
            "value": ["10", "20"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )
    cache_202501.write_parquet(tmp_path / "cache_202501.parquet")

    cache_202502 = pl.DataFrame(
        {
            "dx": ["DE3", "DE4"],
            "period": ["202502", "202502"],
            "org_unit": ["OU3", "OU4"],
            "category_option_combo": ["COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1"],
            "value": ["30", "40"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )
    cache_202502.write_parquet(tmp_path / "cache_202502.parquet")
    # 202503 has no cache file

    data = pl.DataFrame(
        {
            "dx": ["DE1", "DE2", "DE3", "DE4", "DE5", "DE6"],
            "period": ["202501", "202501", "202502", "202502", "202503", "202503"],
            "org_unit": ["OU1", "OU2", "OU3", "OU4", "OU5", "OU6"],
            "category_option_combo": ["COC1"] * 6,
            "attribute_option_combo": ["AOC1"] * 6,
            # DE1 and DE3 are unchanged vs. cache; DE2 and DE4 have a changed value; DE5/DE6 are new (no cache)
            "value": ["10", "99", "30", "88", "50", "60"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    push_cache = DHIS2PushCache(cache_path=tmp_path)
    result = push_cache.filter_new(data).sort(["period", "dx"])

    # only the 2 periods with a cache file get loaded (2 datapoints each); 202503 contributes nothing
    assert push_cache._cache_data.height == 4
    assert sorted(push_cache._cache_data["period"].unique().to_list()) == ["202501", "202502"]

    # 1 changed datapoint per cached period, plus both datapoints from the uncached period
    assert result.height == 4
    assert result["dx"].to_list() == ["DE2", "DE4", "DE5", "DE6"]
    assert result["value"].to_list() == ["99", "88", "50", "60"]


def test_filter_new_keeps_rows_where_value_is_none_on_either_side(tmp_path: Path):
    """Test that filter_new() keeps rows where only one side of the value comparison is None.

    Locks in the use of `ne_missing()` instead of a plain `!=` comparison: `!=` propagates null when
    either side is None (yielding null, not True), which would silently drop these rows instead of
    treating them as changed. Covers both directions: a cached value replaced by None, and a cached
    None replaced by a real value.
    """
    cached_data = pl.DataFrame(
        {
            "dx": ["DE1", "DE2", "DE3"],
            "period": ["202501", "202501", "202501"],
            "org_unit": ["OU1", "OU2", "OU3"],
            "category_option_combo": ["COC1", "COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1", "AOC1"],
            "value": ["10", "20", None],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )
    cached_data.write_parquet(tmp_path / "cache_202501.parquet")

    data = pl.DataFrame(
        {
            "dx": ["DE1", "DE3"],
            "period": ["202501", "202501"],
            "org_unit": ["OU1", "OU3"],
            "category_option_combo": ["COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1"],
            # DE1: had a real cached value, now pushed as None
            # DE3: was cached as None, now pushed with a real value
            "value": [None, "30"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    push_cache = DHIS2PushCache(cache_path=tmp_path)
    result = push_cache.filter_new(data).sort("dx")

    assert result.height == 2
    assert result["dx"].to_list() == ["DE1", "DE3"]
    assert result["value"].to_list() == [None, "30"]

    # filter_new() only reads the cache - it should still hold all 3 original datapoints, untouched
    cached = push_cache._cache_data.sort("dx")
    assert cached.height == 3
    assert cached["dx"].to_list() == ["DE1", "DE2", "DE3"]
    assert cached["value"].to_list() == ["10", "20", None]


def test_filter_new_drops_row_where_value_is_none_on_both_sides(tmp_path: Path):
    """Test that filter_new() drops a row whose value is None in both the cache and the incoming data.

    A matched row whose cached value is None is indistinguishable from "no cache match at all" using
    a plain null check on the joined value column - both produce a null after the left join. Guards
    against that ambiguity causing an already-deleted datapoint (None on both sides, i.e. unchanged)
    to be treated as new and re-pushed on every run. Also checks that filter_new() returns exactly the
    mandatory columns, with no join artifacts (e.g. `value_cached`) leaked into the result.
    """
    cached_data = pl.DataFrame(
        {
            "dx": ["DE1"],
            "period": ["202501"],
            "org_unit": ["OU1"],
            "category_option_combo": ["COC1"],
            "attribute_option_combo": ["AOC1"],
            "value": [None],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )
    cached_data.write_parquet(tmp_path / "cache_202501.parquet")

    data = pl.DataFrame(
        {
            "dx": ["DE1", "DE2"],
            "period": ["202501", "202501"],
            "org_unit": ["OU1", "OU2"],
            "category_option_combo": ["COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1"],
            # DE1: cached as None, pushed as None again -> unchanged, must be dropped
            # DE2: not in the cache at all -> new, must be kept
            "value": [None, "30"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    push_cache = DHIS2PushCache(cache_path=tmp_path)
    result = push_cache.filter_new(data)

    assert result["dx"].to_list() == ["DE2"]
    assert result.columns == CACHE_COLUMNS


def test_filter_new_with_empty_data_short_circuits_before_loading_cache(tmp_path: Path):
    """Test that filter_new() returns immediately on an empty input, without touching the cache."""
    push_cache = DHIS2PushCache(cache_path=tmp_path)
    empty_data = pl.DataFrame(schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8))

    with patch.object(push_cache, "_load") as mock_load, patch.object(push_cache, "_log_message") as mock_log_message:
        result = push_cache.filter_new(empty_data)
        mock_load.assert_not_called()
        mock_log_message.assert_called_once_with("No data to push.", log_current_run=push_cache.verbose)

    assert result.height == 0


def test_filter_new_with_no_matching_cache_file_returns_all_rows(tmp_path: Path):
    """Test that filter_new() returns the input unchanged when no cache file matches its period."""
    # cache exists on disk, but only for an unrelated period
    _write_cache_file(tmp_path, "202412", ["DE9"])

    data = pl.DataFrame(
        {
            "dx": ["DE1", "DE2"],
            "period": ["202501", "202501"],
            "org_unit": ["OU1", "OU2"],
            "category_option_combo": ["COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1"],
            "value": ["10", "20"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    push_cache = DHIS2PushCache(cache_path=tmp_path)
    with patch.object(push_cache, "_log_message") as mock_log_message:
        result = push_cache.filter_new(data)
        mock_log_message.assert_called_once_with(
            "No cache data found. All rows will be pushed.", log_current_run=push_cache.verbose
        )

    assert result.height == 2
    assert sorted(result["dx"].to_list()) == ["DE1", "DE2"]


def test_update_cache_replaces_stale_value_and_adds_new_datapoint(tmp_path: Path):
    """Test that _update_cache() swaps in the new value for a stale datapoint and appends a brand-new one.

    Leaves unrelated cached datapoints untouched, with no duplicates in the result.
    """
    push_cache = DHIS2PushCache(cache_path=tmp_path)
    push_cache._cache_data = pl.DataFrame(
        {
            "dx": ["DE1", "DE2", "DE3"],
            "period": ["202501", "202501", "202501"],
            "org_unit": ["OU1", "OU2", "OU3"],
            "category_option_combo": ["COC1", "COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1", "AOC1"],
            # DE1: matched a previous filter_new() call, untouched by this push
            # DE2: stale value, about to be updated by this push
            # DE3: unrelated to this push, should remain untouched
            "value": ["10", "20", "30"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    data_pushed = pl.DataFrame(
        {
            "dx": ["DE2", "DE4"],
            "period": ["202501", "202501"],
            "org_unit": ["OU2", "OU4"],
            "category_option_combo": ["COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1"],
            # DE2: the just-pushed, updated value for an existing cached datapoint
            # DE4: a brand-new datapoint, not previously cached
            "value": ["25", "40"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    push_cache._update_cache(data_pushed)
    result = push_cache._cache_data.sort("dx")

    assert result.height == 4
    assert result["dx"].to_list() == ["DE1", "DE2", "DE3", "DE4"]
    assert result["value"].to_list() == ["10", "25", "30", "40"]


def test_update_cache_deduplicates_pushed_rows_with_same_key(tmp_path: Path):
    """Test that _update_cache() collapses duplicate-key rows in data_pushed, keeping the last value."""
    push_cache = DHIS2PushCache(cache_path=tmp_path)
    push_cache._cache_data = pl.DataFrame(
        {
            "dx": ["DE1"],
            "period": ["202501"],
            "org_unit": ["OU1"],
            "category_option_combo": ["COC1"],
            "attribute_option_combo": ["AOC1"],
            "value": ["10"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    data_pushed = pl.DataFrame(
        {
            "dx": ["DE2", "DE2"],
            "period": ["202501", "202501"],
            "org_unit": ["OU2", "OU2"],
            "category_option_combo": ["COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1"],
            # DE2 is pushed twice in the same batch with different values - the last one should win
            "value": ["25", "26"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    push_cache._update_cache(data_pushed)
    result = push_cache._cache_data.sort("dx")

    assert result.height == 2
    assert result["dx"].to_list() == ["DE1", "DE2"]
    assert result["value"].to_list() == ["10", "26"]


def test_update_cache_updates_rows_where_value_is_none_on_either_side(tmp_path: Path):
    """Test that _update_cache() correctly replaces a cached value with None, and a cached None with a value.

    _update_cache() replaces cached rows wholesale by key (dx/period/org_unit/coc/aoc) and never
    compares the "value" column directly, so it isn't exposed to the null-propagation pitfall that
    affects filter_new()'s value comparison - this locks in that a None value round-trips correctly
    either way.
    """
    push_cache = DHIS2PushCache(cache_path=tmp_path)
    push_cache._cache_data = pl.DataFrame(
        {
            "dx": ["DE1", "DE2"],
            "period": ["202501", "202501"],
            "org_unit": ["OU1", "OU2"],
            "category_option_combo": ["COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1"],
            "value": ["10", None],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    data_pushed = pl.DataFrame(
        {
            "dx": ["DE1", "DE2"],
            "period": ["202501", "202501"],
            "org_unit": ["OU1", "OU2"],
            "category_option_combo": ["COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1"],
            # DE1: had a real cached value, pushed as a deletion (None)
            # DE2: was cached as None, pushed with a real value
            "value": [None, "50"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    push_cache._update_cache(data_pushed)
    result = push_cache._cache_data.sort("dx")

    assert result.height == 2
    assert result["dx"].to_list() == ["DE1", "DE2"]
    assert result["value"].to_list() == [None, "50"]


def test_update_cache_handles_multiple_periods_in_one_call(tmp_path: Path):
    """Test that _update_cache() updates multiple periods independently within a single call.

    Guards against the loop's mid-iteration reassignment of self._cache_data accidentally
    dropping or cross-contaminating a period that hasn't been processed yet.
    """
    push_cache = DHIS2PushCache(cache_path=tmp_path)
    push_cache._cache_data = pl.DataFrame(
        {
            "dx": ["DE1", "DE2", "DE3", "DE4"],
            "period": ["202501", "202501", "202502", "202502"],
            "org_unit": ["OU1", "OU2", "OU3", "OU4"],
            "category_option_combo": ["COC1", "COC1", "COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1", "AOC1", "AOC1"],
            # DE1/DE3 are untouched by this push; DE2/DE4 are stale and about to be updated
            "value": ["10", "20", "30", "40"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    data_pushed = pl.DataFrame(
        {
            "dx": ["DE2", "DE4"],
            "period": ["202501", "202502"],
            "org_unit": ["OU2", "OU4"],
            "category_option_combo": ["COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1"],
            "value": ["99", "88"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    push_cache._update_cache(data_pushed)
    result = push_cache._cache_data.sort("dx")

    assert result.height == 4
    assert result["dx"].to_list() == ["DE1", "DE2", "DE3", "DE4"]
    assert result["value"].to_list() == ["10", "99", "30", "88"]


def test_mark_pushed_with_empty_data_does_not_touch_cache(tmp_path: Path):
    """Test that mark_pushed() is a no-op on an empty DataFrame - no directory or files get created."""
    cache_path = tmp_path / "cache_dir"
    push_cache = DHIS2PushCache(cache_path=cache_path)
    empty_data = pl.DataFrame(schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8))

    push_cache.mark_pushed(empty_data)

    assert not cache_path.exists()
    assert push_cache._cache_data is None


def test_mark_pushed_first_write_creates_dir_and_deduplicates(tmp_path: Path):
    """Test that mark_pushed()'s first write creates the cache directory and dedupes duplicate keys."""
    cache_path = tmp_path / "new_cache_dir"
    push_cache = DHIS2PushCache(cache_path=cache_path)

    data = pl.DataFrame(
        {
            "dx": ["DE1", "DE1", "DE2"],
            "period": ["202501", "202501", "202501"],
            "org_unit": ["OU1", "OU1", "OU2"],
            "category_option_combo": ["COC1", "COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1", "AOC1"],
            # DE1 is pushed twice in the same batch with different values - the last one should win
            "value": ["10", "15", "20"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )

    push_cache.mark_pushed(data)

    assert cache_path.exists()
    push_cache._load(["202501"])
    result = push_cache._cache_data.sort("dx")
    assert result.height == 2
    assert result["dx"].to_list() == ["DE1", "DE2"]
    assert result["value"].to_list() == ["15", "20"]


def test_load_reads_matching_period_file(tmp_path: Path):
    """Test that _load() populates _cache_data from the file matching the requested period."""
    _write_cache_file(tmp_path, "202501", ["DE1", "DE2"])

    push_cache = DHIS2PushCache(cache_path=tmp_path)
    push_cache._load(["202501"])

    assert push_cache._cache_data is not None
    assert push_cache._cache_data.height == 2
    assert push_cache._cache_data["dx"].to_list() == ["DE1", "DE2"]


def test_load_no_matching_period_file(tmp_path: Path):
    """Test that _load() leaves _cache_data as None when no file matches the requested period."""
    _write_cache_file(tmp_path, "202501", ["DE1"])

    push_cache = DHIS2PushCache(cache_path=tmp_path)
    push_cache._load(["202502"])

    assert push_cache._cache_data is None


def test_load_cache_path_does_not_exist(tmp_path: Path):
    """Test that _load() leaves _cache_data as None and logs it when the cache directory doesn't exist."""
    missing_dir = tmp_path / "missing_dir"
    push_cache = DHIS2PushCache(cache_path=missing_dir)
    with patch.object(push_cache, "_log_message") as mock_log_message:
        push_cache._load(["202501"])
        mock_log_message.assert_called_once_with(
            f"Cache path {missing_dir} does not exist. No cache data loaded.", log_current_run=push_cache.verbose
        )

    assert push_cache._cache_data is None


def test_verbose_true_logs_to_current_run(tmp_path: Path):
    """Test that verbose=True causes informational cache messages to also log to the current run."""
    missing_dir = tmp_path / "missing_dir"
    push_cache = DHIS2PushCache(cache_path=missing_dir, verbose=True)

    with patch.object(push_cache, "_log_message") as mock_log_message:
        push_cache._load(["202501"])
        mock_log_message.assert_called_once_with(
            f"Cache path {missing_dir} does not exist. No cache data loaded.", log_current_run=True
        )


def test_load_corrupted_cache_file_is_skipped_and_logged(tmp_path: Path):
    """Test that _load() logs and skips a cache file that fails to parse, without crashing."""
    (tmp_path / "cache_202501.parquet").write_bytes(b"not a parquet file")

    push_cache = DHIS2PushCache(cache_path=tmp_path)
    with patch.object(push_cache, "_log_message") as mock_log_message:
        push_cache._load(["202501"])
        mock_log_message.assert_called_once()
        assert "Failed to load cache file" in mock_log_message.call_args.args[0]
        assert mock_log_message.call_args.kwargs["level"] == "error"

    assert push_cache._cache_data is None


def test_load_partial_failure_keeps_valid_files_and_logs_the_bad_one(tmp_path: Path):
    """Test that _load() still loads the valid cache files when only one of several is corrupted."""
    _write_cache_file(tmp_path, "202501", ["DE1", "DE2"])
    (tmp_path / "cache_202502.parquet").write_bytes(b"not a parquet file")

    push_cache = DHIS2PushCache(cache_path=tmp_path)
    with patch.object(push_cache, "_log_message") as mock_log_message:
        push_cache._load(["202501", "202502"])
        mock_log_message.assert_called_once()
        assert "Failed to load cache file" in mock_log_message.call_args.args[0]
        assert mock_log_message.call_args.kwargs["level"] == "error"

    assert push_cache._cache_data is not None
    assert push_cache._cache_data.height == 2
    assert push_cache._cache_data["dx"].to_list() == ["DE1", "DE2"]


def test_filter_new_and_mark_pushed_round_trip_across_runs(tmp_path: Path):
    """Test that filter_new() and mark_pushed() work together correctly across separate pipeline runs.

    Simulates 3 separate runs against the same on-disk cache, using only the public API
    (plus _load() at the end, to confirm the persisted state without relying on in-memory state).
    """
    # Run 1: no cache exists yet - everything is new and gets pushed and marked
    run_1_cache = DHIS2PushCache(cache_path=tmp_path)
    run_1_data = pl.DataFrame(
        {
            "dx": ["DE1", "DE2"],
            "period": ["202501", "202501"],
            "org_unit": ["OU1", "OU2"],
            "category_option_combo": ["COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1"],
            "value": ["10", "20"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )
    to_push_1 = run_1_cache.filter_new(run_1_data)
    assert to_push_1.height == 2
    run_1_cache.mark_pushed(to_push_1)

    # Run 2: a fresh instance reads the cache written by run 1
    run_2_cache = DHIS2PushCache(cache_path=tmp_path)
    run_2_data = pl.DataFrame(
        {
            "dx": ["DE1", "DE2", "DE3"],
            "period": ["202501", "202501", "202501"],
            "org_unit": ["OU1", "OU2", "OU3"],
            "category_option_combo": ["COC1", "COC1", "COC1"],
            "attribute_option_combo": ["AOC1", "AOC1", "AOC1"],
            # DE1: unchanged; DE2: changed; DE3: brand new
            "value": ["10", "99", "30"],
        },
        schema=dict.fromkeys(CACHE_COLUMNS, pl.Utf8),
    )
    to_push_2 = run_2_cache.filter_new(run_2_data).sort("dx")
    assert to_push_2["dx"].to_list() == ["DE2", "DE3"]
    assert to_push_2["value"].to_list() == ["99", "30"]
    run_2_cache.mark_pushed(to_push_2)

    # Run 3: a third fresh instance confirms the on-disk cache reflects both prior runs
    run_3_cache = DHIS2PushCache(cache_path=tmp_path)
    run_3_cache._load(["202501"])
    cached = run_3_cache._cache_data.sort("dx")
    assert cached.height == 3
    assert cached["dx"].to_list() == ["DE1", "DE2", "DE3"]
    assert cached["value"].to_list() == ["10", "99", "30"]

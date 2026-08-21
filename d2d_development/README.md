# d2d_development

DHIS2-to-DHIS2 development utility library maintained by Bluesquare Data Services team.

## Installation

Install this library on its own:

```bash
pip install git+https://github.com/BLSQ/openhexa-ds-developments.git#subdirectory=d2d_development
```

> **Note:**  
> Additional classes in `dataset_completion.py` and `org_unit_aligner.py` are included in this package.  
> These classes are still in beta and may change; they are usable but should be used with caution.


## Main Classes

### DHIS2Extractor

**Description:**  
Main class to extract data from DHIS2. It provides unified handlers for extracting data elements, indicators, and reporting rates, saving them to disk in a standardized format.

**Configuration Parameters:**
When initializing `DHIS2Extractor`, you can configure the following parameters:

- `dhis2_client` (required): The DHIS2 client instance.
- `download_mode`: Controls how files are saved when extracting data. Use `"DOWNLOAD_REPLACE"` (default) to always overwrite files, or `"DOWNLOAD_NEW"` to skip downloading if the file already exists.
- `return_existing_file`: If `True` and using `DOWNLOAD_NEW`, returns the path to the existing file instead of `None` when a file already exists (default: `False`).
- `logger`: Optional custom logger instance.

Example:
```python
extractor = DHIS2Extractor(dhis2_client, download_mode="DOWNLOAD_NEW", return_existing_file=True)
```

**Parameters for `download_period` (DataElementsExtractor, IndicatorsExtractor, ReportingRatesExtractor):**

- **data_elements / indicators / reporting_rates** (`list[str]`):  
  A list of DHIS2 UIDs to extract.  
  - For `data_elements.download_period`, use `data_elements=["de1", "de2"]`.
  - For `indicators.download_period`, use `indicators=["ind1", ...]`.
  - For `reporting_rates.download_period`, use `reporting_rates=["rr1", ...]`.

- **org_units** (`list[str]`):  
  List of DHIS2 organisation unit UIDs to extract data for (e.g., `["ou1", "ou2"]`).

- **period** (`str`):  
  The DHIS2 period to extract data for (e.g., `"202401"` for January 2024). Must be a valid DHIS2 period string.

- **output_dir** (`Path`):  
  The directory where the extracted data file will be saved. The file will be named `data_<period>.parquet` by default unless you specify a custom filename.

- **filename** (`str | None`, optional):  
  Custom filename for the output file. If not provided, the default is `data_<period>.parquet`. Using the default is recommended when extracting multiple periods.

- **kwargs** (`dict`, optional):  
  Additional keyword arguments for advanced extraction options.  
  - For data elements: `last_updated` (not yet implemented).
  - For indicators: `include_cocs` (bool, whether to include category option combo, use only together with data element ids).
  - For reporting rates: currently no extra options.

**Returns:**  
- The path to the saved Parquet file (`Path`), or `None` if no data was extracted or the file already exists and `return_existing_file` is `False`.

**Output Format:**
The extraction methods always save the data in a table with a fixed column structure. Each extraction creates a separate .parquet file, where each row represents a data point and the columns are always:

- **dx**: Data element, indicator, or reporting rate UID
- **period**: Period (e.g., `"202401"`)
- **orgUnit**: Organisation unit UID
- **categoryOptionCombo**: Category option combo UID 
- **attributeOptionCombo**: Attribute option combo UID 
- **rateMetric**: Rate metric (for reporting rates)
- **domainType**: Data domain (e.g., `"AGGREGATED"`)
- **value**: The value for the data point

The file path to the saved Parquet file is returned by the extraction method. You can load the output using pandas, polars, or any tool that supports Parquet files.

**Usage Example:**
```python
from d2d_development.extract import DHIS2Extractor
from openhexa.sdk import workspace
from openhexa.toolbox.dhis2 import DHIS2
from pathlib import Path

dhis2_client = DHIS2(workspace.get_connection("dhis2-connection"))
extractor = DHIS2Extractor(dhis2_client, download_mode="DOWNLOAD_REPLACE")

# Extract several periods of data elements
for period in ["202401", "202402", "202403"]:
    extractor.data_elements.download_period(
        data_elements=["de1", "de2"],
        org_units=["ou1", "ou2"],
        period=period,
        output_dir=Path("/output")
    )

# Extract one period of indicators
extractor.indicators.download_period(
	indicators=["ind1"],
	org_units=["ou1"],
	period="202401",
	output_dir=Path("/tmp")
)

# Extract one period of reporting rates
extractor.reporting_rates.download_period(
	reporting_rates=["rr1"],
	org_units=["ou1"],
	period="202401",
	output_dir=Path("/tmp")
)

# Example load the output file
import polars as pl
df = pl.read_parquet(Path(/tmp) / f"data_{period}.parquet")  # Default naming
print(df.head())
```

**Note:**  
- The same pattern applies for `extractor.indicators.download_period` and `extractor.reporting_rates.download_period`, just change the first argument name accordingly.
- All extracted files are saved in Parquet format by default.


---


### DHIS2Pusher

**Description:**  
Main class to handle pushing data to DHIS2. It validates and pushes formatted data (pandas or polars DataFrame) to a DHIS2 instance.

**Input Data Format for `DHIS2Pusher`**

The `push_data` method expects a pandas or polars DataFrame with the following columns (all required):

- **dx**: Data element, indicator, or reporting rate UID
- **period**: Period (e.g., `"202401"`)
- **orgUnit**: Organisation unit UID
- **categoryOptionCombo**: Category option combo UID
- **attributeOptionCombo**: Attribute option combo UID
- **value**: The value to be pushed (numeric or string, depending on DHIS2 configuration)

If any of these columns are missing, or if the input is not a pandas or polars DataFrame, a `PusherError` will be raised.

**Configuration Parameters:**
When initializing `DHIS2Pusher`, you can configure the following parameters:

- `dhis2_client` (required): The DHIS2 client instance.
- `import_strategy`: Strategy flag passed to the DHIS2 API for data import. Accepts "CREATE", "UPDATE", or "CREATE_AND_UPDATE" (default: "CREATE_AND_UPDATE"). **NOTE:** This only controls how the DHIS2 server processes the data; it does not affect client-side logic.
- `dry_run`: If `True`, simulates the push without making changes on the server (default: `True`).
- `max_post`: Maximum number of data points per POST request (default: `500`).
- `logging_interval`: Log progress every N data points (default: `50000`).
- `logger`: Optional custom logger instance.
- `cache_path`: Optional `Path`. If provided, enables push caching so datapoints that haven't changed since the last successful push are skipped (default: `None`, caching disabled). See [Caching Pushed Datapoints](#caching-pushed-datapoints-avoid-re-pushing-unchanged-data) below.

**Usage Example:**
```python
from d2d_development.push import DHIS2Pusher
from openhexa.sdk import workspace
from openhexa.toolbox.dhis2 import DHIS2
import polars as pl

dhis2_client = DHIS2(workspace.get_connection("dhis2-connection"))

df = pl.DataFrame({
    "dx": ["de1"], 
    "period": ["202401"], 
    "orgUnit": ["ou1"], 
    "categoryOptionCombo": ["coc"], 
    "attributeOptionCombo": ["aoc"], 
    "value": [123]})
	
pusher = DHIS2Pusher(
	dhis2_client,
	import_strategy="CREATE_AND_UPDATE",  # or "CREATE", "UPDATE"
	dry_run=False,
	max_post=1000,
	logging_interval=10000,
)

pusher.push_data(df)
```

**Accessing Push Summary Information**

After calling `push_data`, the `DHIS2Pusher` instance provides detailed results of the push operation in its `summary` attribute. This dictionary contains:

- `import_counts`: Number of data points imported, updated, ignored, or deleted (dict with keys: `imported`, `updated`, `ignored`, `deleted`).
- `import_options`: The options used for the import (strategy, dry run, etc).
- `import_errors`: List of errors, conflicts, or error reports returned by DHIS2 or encountered during the push.
- `rejected_datapoints`: List of data points that were rejected by DHIS2 itself (e.g. a conflict on a specific value), identified from the API response.
- `ignored_data_points`: List of data points that were ignored due to missing or invalid fields.
- `delete_data_points`: List of data points that were marked for deletion (value is NA/null).

**Example:**
```python
pusher.push_data(df)
print(pusher.summary)
# Example output:
# {
#   'import_counts': {'imported': 1, 'updated': 0, 'ignored': 0, 'deleted': 0},
#   'import_options': {'importStrategy': 'CREATE_AND_UPDATE', 'dryRun': False, ...},
#   'import_errors': [],
#   'rejected_datapoints': [],
#   'ignored_data_points': [],
#   'delete_data_points': []
# }
```

You can use these fields to programmatically inspect the results of your push, handle errors, or log/report the outcome. For example, to check if any data points were ignored:

```python
if pusher.summary["ignored_data_points"]:
    print(f"Ignored {len(pusher.summary['ignored_data_points'])} data points:")
    for dp in pusher.summary["ignored_data_points"]:
        print(dp)
```

---

### Caching Pushed Datapoints (avoid re-pushing unchanged data)

**Description:**
`DHIS2Pusher` can optionally track which datapoints have already been successfully pushed to DHIS2, so that subsequent runs only push datapoints that are new or have changed. This is useful for pipelines that run repeatedly (e.g. on a schedule) over largely the same data, where re-sending unchanged values on every run wastes time and DHIS2 API calls.

A datapoint is identified by its key columns (`dx`, `period`, `orgUnit`, `categoryOptionCombo`, `attributeOptionCombo`). It's considered unchanged, and therefore skipped, only if its `value` is identical to the last successfully pushed value for that same key. Any difference in `value` - including a change to or from a null/NA value (a deletion) - is treated as new and gets pushed.

**Enabling the cache:**
Pass a `cache_path` when creating `DHIS2Pusher`:

```python
from pathlib import Path
from d2d_development.push import DHIS2Pusher

pusher = DHIS2Pusher(
	dhis2_client,
	cache_path=Path("/path/to/persistent/cache"),  # must persist across runs
)

pusher.push_data(df)
```

If `cache_path` is omitted (the default), caching is disabled entirely and `push_data` behaves exactly as without this feature - every call pushes the full input.

**How it works:**
- Before pushing, `push_data` filters out any datapoint whose key and value exactly match what's cached from a previous run.
- After a push, only datapoints that DHIS2 actually accepted are recorded in the cache - a datapoint rejected by DHIS2 (see `rejected_datapoints` in the summary above) is left out, so it will be attempted again on the next run instead of being silently treated as done.
- The cache is stored on disk as one `cache_<period>.parquet` file per period inside `cache_path`, so `cache_path` should point to a location that persists between pipeline runs (not a temporary directory), otherwise the cache provides no benefit.

**Performance tip:** if you push several distinct datasets (e.g. different extract groups) to the same DHIS2 instance, use a separate `cache_path` per dataset rather than sharing one. Each `cache_<period>.parquet` file is fully read and rewritten on every push, so a shared cache grows with the combined size of every dataset using it, not just the size of the one being pushed.

```python
base_cache_dir = Path("/path/to/persistent/cache")

pusher_dataset_a = DHIS2Pusher(dhis2_client, cache_path=base_cache_dir / "dataset_a")
pusher_dataset_a.push_data(df_a)

pusher_dataset_b = DHIS2Pusher(dhis2_client, cache_path=base_cache_dir / "dataset_b")
pusher_dataset_b.push_data(df_b)
```
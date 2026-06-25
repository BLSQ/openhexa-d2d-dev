import logging
import tempfile
from pathlib import Path

import pandas as pd
import polars as pl
from openhexa.sdk import current_run

from .exceptions import ExtractorError


def log_message(
    logger: logging.Logger,
    message: str,
    error_details: str = "",
    log_current_run: bool = True,
    level: str = "info",
    exception_class: type[Exception] = Exception,
) -> None:
    """Log a message to both the current run and the configured logger.

    Parameters
    ----------
    logger : logging.Logger
        The logger to use for logging the message.
    message : str
        The message to log.
    error_details : str, optional
        Additional details to include in error logs, by default "".
    log_current_run : bool, optional
        Whether to log the message to the current run, by default True.
    level : str, optional
        The logging level ('info', 'warning', 'error'), by default 'info'.
    exception_class : Exception, optional
        The exception class type to raise for invalid logging levels, by default Exception.
    """
    if level == "info":
        logger.info(message)
    elif level == "warning":
        logger.warning(message)
    elif level == "error":
        logger.error(f"{message}. {error_details}")
    elif level == "debug":
        logger.debug(message)
    else:
        raise exception_class(f"Invalid logging level: {level}")

    # Log to current_run only if it exists
    if log_current_run and "current_run" in globals() and current_run is not None:
        if level == "info":
            current_run.log_info(message)
        elif level == "warning":
            current_run.log_warning(message)
        elif level == "error":
            current_run.log_error(message)
        elif level == "debug":
            current_run.log_debug(message)


def save_to_parquet(data: pl.DataFrame | pd.DataFrame, filename: Path) -> None:
    """Safely saves a Pandas or Polars DataFrame to a Parquet file using a temporary file and atomic replace.

    Args:
        data (Union[pl.DataFrame, pd.DataFrame]): The DataFrame to save.
        filename (Path): The path where the Parquet file will be saved.

    Raises:
        ValueError: If data is not a valid DataFrame.
        Exception: If saving fails.
    """
    temp_filename = None
    try:
        # Validate input type
        if not isinstance(data, (pl.DataFrame, pd.DataFrame)):
            raise ValueError("The 'data' parameter must be a Pandas or Polars DataFrame.")

        # Write to a temporary file in the same directory
        with tempfile.NamedTemporaryFile(suffix=".parquet", dir=filename.parent, delete=False) as tmp_file:
            temp_filename = Path(tmp_file.name)

        # Use appropriate write method based on DataFrame type
        if isinstance(data, pl.DataFrame):
            data.write_parquet(temp_filename)
        else:  # pd.DataFrame
            data.to_parquet(temp_filename, index=False)

        # Atomically replace the old file with the new one
        temp_filename.replace(filename)
        temp_filename = None  # Mark as successfully moved

    except Exception as e:
        # Clean up the temp file if it exists
        if temp_filename is not None and temp_filename.exists():
            temp_filename.unlink()
        raise ExtractorError(f"Failed to save parquet file to {filename}") from e

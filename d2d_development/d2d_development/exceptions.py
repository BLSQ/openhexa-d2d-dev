class ExtractorError(Exception):
    """Custom exception for all DHIS2Extractor errors."""


class PusherError(Exception):
    """Custom exception for all DHIS2Pusher errors."""


class OrgUnitError(Exception):
    """Custom exception for all OrgUnit errors."""


class OrgUnitAlignError(Exception):
    """Custom error for organisation unit create failures."""

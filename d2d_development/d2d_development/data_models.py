import ast
import json
import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from pydantic.alias_generators import to_camel

from .exceptions import OrgUnitError


class DataType(StrEnum):
    """Enumeration of supported DHIS2 data types for extraction."""

    DATA_ELEMENT = "DATA_ELEMENT"
    REPORTING_RATE = "REPORTING_RATE"
    INDICATOR = "INDICATOR"


class DataPointModel(BaseModel):
    """Data model representing a DHIS2 data point."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    data_element: str
    period: str
    org_unit: str
    category_option_combo: str
    attribute_option_combo: str
    value: str | None

    def to_json(self) -> dict:
        """Return a dictionary representation of the data point for DHIS2 payload.

        Returns
        -------
        dict
            A dictionary with keys corresponding to DHIS2 data value fields.
        """
        base = {
            "dataElement": self.data_element,
            "period": self.period,
            "orgUnit": self.org_unit,
            "categoryOptionCombo": self.category_option_combo,
            "attributeOptionCombo": self.attribute_option_combo,
        }

        if self.value is None or not self.value.strip():
            return {**base, "value": "", "comment": "deleted value"}

        return {**base, "value": self.value}

    def __str__(self) -> str:
        return str(self.model_dump(by_alias=True))


class OrgUnit(BaseModel):  # noqa: PLW1641 (no hashing)
    """Data model representing a DHIS2 organisation unit.

    Built directly from a mapping (e.g. a dict produced by `polars.DataFrame.to_dicts()`), using
    either the DHIS2 camelCase field names or the snake_case attribute names below.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str | None = None
    name: str | None = None
    short_name: str | None = None
    opening_date: str | None = None
    closed_date: str | None = None
    parent: dict | None = None
    level: int
    path: str
    geometry: dict | None = None

    @model_validator(mode="before")
    @classmethod
    def _nan_to_none(cls, data: object) -> object:
        """Normalize bare float NaN values (pandas' missing-value stand-in) to None.

        A pandas DataFrame built from records containing None can silently turn those into
        `float('nan')` (e.g. via `to_dict(orient="records")`), which would otherwise fail
        validation on optional dict/str fields instead of being treated as absent.

        Args:
            data: The raw input mapping passed to the model.

        Returns:
            object: The same mapping with any float NaN values replaced by None, or `data`
            unchanged if it isn't a mapping.
        """
        if isinstance(data, dict):
            return {
                key: (None if isinstance(value, float) and math.isnan(value) else value) for key, value in data.items()
            }
        return data

    @field_validator("parent", "geometry", mode="before")
    @classmethod
    def _parse_nested_dict(cls, value: object) -> dict | None:
        """Parse a stringified dict into a dict, passing actual dicts and None through.

        The source pyramid stores `parent`/`geometry` as strings rather than native struct
        columns, in either of two formats: valid JSON (e.g. '{"type": "Point", ...}') or a
        Python dict repr with single quotes (e.g. "{'id': 'PARENT1'}"), which `json.loads` can't
        parse. `ast.literal_eval` is tried as a fallback to cover that second format.

        Args:
            value: The raw parent/geometry value from the input mapping.

        Returns:
            dict | None: The parsed dict, or None if absent/unparseable.
        """
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return None
            return parsed if isinstance(parsed, dict) else None
        return value

    def is_valid(self) -> bool:
        """Check if the OrgUnit instance has all required attributes set.

        Returns:
            bool: True if id, name, short_name and opening_date are all non-empty (i.e. neither
            None nor an empty string; NaN is normalized to None before this runs), False otherwise.
        """
        return bool(self.id) and bool(self.name) and bool(self.short_name) and bool(self.opening_date)

    def to_json(self, include_none_fields: bool = False) -> dict:
        """Return a dictionary representation of the organisation unit suitable for the DHIS2 API.

        Args:
            include_none_fields: If True, `closedDate`/`parent`/`geometry` are included as an
                explicit `null` when unset instead of being omitted. Omitting a field leaves
                DHIS2's existing value untouched on UPDATE; including it as `null` clears it. Has
                no effect for a CREATE payload, since there is no existing value to clear.

        Returns:
            dict: Dictionary containing the organisation unit's attributes formatted for DHIS2.
        """
        json_dict = {
            "id": self.id,
            "name": self.name,
            "shortName": self.short_name,
            "openingDate": self.opening_date,
        }

        if self.closed_date is not None:
            json_dict["closedDate"] = self.closed_date
        elif include_none_fields:
            json_dict["closedDate"] = None

        if self.parent and self.parent.get("id") is not None:
            json_dict["parent"] = {"id": self.parent.get("id")}
        elif include_none_fields:
            json_dict["parent"] = None

        if self.geometry is not None:
            json_dict["geometry"] = {
                "type": self.geometry["type"],
                "coordinates": self.geometry["coordinates"],
            }
        elif include_none_fields:
            json_dict["geometry"] = None
        return json_dict

    def __str__(self) -> str:
        return f"OrgUnit({self.id}, {self.name})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OrgUnit):
            raise OrgUnitError(f"Cannot compare OrgUnit with {type(other)}")
        return (
            self.id == other.id
            and self.name == other.name
            and self.short_name == other.short_name
            and self.opening_date == other.opening_date
            and self.closed_date == other.closed_date
            and self.parent == other.parent
            and self.geometry == other.geometry
        )

import json
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

import pandas as pd


class DataType(Enum):
    """Enumeration of supported DHIS2 data types for extraction."""

    DATA_ELEMENT = "DATA_ELEMENT"
    REPORTING_RATE = "REPORTING_RATE"
    INDICATOR = "INDICATOR"


@dataclass
class DataPointModel:
    """Data model representing a DHIS2 data point.

    Attributes
    ----------
    dataElement : str
        The unique identifier for the data element.
    period : str
        The reporting period for the data point.
    orgUnit : str
        The organizational unit associated with the data point.
    categoryOptionCombo : str
        The category option combination identifier.
    attributeOptionCombo : str
        The attribute option combination identifier.
    value : float
        The value of the data point.
    """

    dataElement: str  # noqa: N815
    period: str
    orgUnit: str  # noqa: N815
    categoryOptionCombo: str  # noqa: N815
    attributeOptionCombo: str  # noqa: N815
    value: str

    def to_json(self) -> dict:
        """Return a dictionary representation of the data point suitable for DHIS2 JSON format.

        Returns
        -------
        dict
            A dictionary with keys corresponding to DHIS2 data value fields.
        """
        if self.value is None or (isinstance(self.value, str) and not self.value.strip()):
            return {
                "dataElement": self.dataElement,
                "period": self.period,
                "orgUnit": self.orgUnit,
                "categoryOptionCombo": self.categoryOptionCombo,
                "attributeOptionCombo": self.attributeOptionCombo,
                "value": "",
                "comment": "deleted value",
            }

        return {
            "dataElement": self.dataElement,
            "period": self.period,
            "orgUnit": self.orgUnit,
            "categoryOptionCombo": self.categoryOptionCombo,
            "attributeOptionCombo": self.attributeOptionCombo,
            "value": self.value,
        }

    def __str__(self) -> str:
        return (
            f"DataPointModel("
            f"dataElement={self.dataElement}, "
            f"period={self.period}, "
            f"orgUnit={self.orgUnit}, "
            f"categoryOptionCombo={self.categoryOptionCombo}, "
            f"attributeOptionCombo={self.attributeOptionCombo}, "
            f"value={self.value})"
        )


@dataclass
class OrgUnitModel:
    """Helper object definition to represent an organizational unit."""

    id: str
    name: str
    shortName: str  # noqa: N815
    openingDate: str  # noqa: N815
    closedDate: str  # noqa: N815
    parent: dict
    level: int
    path: str
    geometry: str


class OrgUnitRow(NamedTuple):
    """Helper object definition to represent an organizational unit."""

    id: str
    name: str
    shortName: str  # noqa: N815
    openingDate: str  # noqa: N815
    closedDate: str | None  # noqa: N815
    parent: dict | None
    level: int
    path: str
    geometry: str | dict | None


class OrgUnitObj:  # noqa: PLW1641 (no hashing)
    """Helper class definition to store/create the correct OrgUnit JSON format."""

    def __init__(self, org_unit: OrgUnitRow | pd.Series | tuple):
        """Create a new org unit instance.

        Parameters
        ----------
        org_unit : OrgUnitRow | pd.Series
            The organizational unit data.
            Expects columns with names :
                ['id', 'name', 'shortName', 'openingDate', 'closedDate', 'parent','level', 'path', 'geometry']
        """
        if isinstance(org_unit, pd.Series):
            # Convert Series to OrgUnitRow
            org_unit = OrgUnitRow(
                id=org_unit["id"],
                name=org_unit["name"],
                shortName=org_unit["shortName"],
                openingDate=org_unit["openingDate"],
                closedDate=org_unit["closedDate"],
                parent=org_unit["parent"],
                level=org_unit["level"],
                path=org_unit["path"],
                geometry=org_unit["geometry"],
            )
        elif isinstance(org_unit, tuple) and hasattr(org_unit, "_fields"):
            org_unit = OrgUnitRow(**org_unit._asdict())
        elif not isinstance(org_unit, OrgUnitRow):
            raise TypeError(f"Expected OrgUnitRow, pd.Series, or tuple, got {type(org_unit)}")

        self.initialize_from(org_unit_tuple=org_unit)

    def initialize_from(self, org_unit_tuple: OrgUnitRow):
        """Initialize the OrgUnitObj instance from an OrgUnitRow tuple.

        This object should represent a DHIS2 organizational unit with the same attribute naming.

        Parameters
        ----------
        org_unit_tuple : tuple
            A tuple containing organizational unit attributes.
        """
        # Keep names consistent
        self.id = org_unit_tuple.id
        self.name = org_unit_tuple.name
        self.shortName = org_unit_tuple.shortName
        self.openingDate = org_unit_tuple.openingDate
        self.closedDate = org_unit_tuple.closedDate
        self.parent = org_unit_tuple.parent
        # Parse geometry safely
        geometry = org_unit_tuple.geometry
        if pd.notna(geometry):
            if isinstance(geometry, str):
                try:
                    self.geometry = json.loads(geometry)
                except json.JSONDecodeError:
                    self.geometry = None
            else:
                self.geometry = geometry
        else:
            self.geometry = None

    def to_json(self) -> dict:
        """Return a dictionary representation of the organizational unit suitable for DHIS2 API.

        Returns
        -------
        dict
            Dictionary containing the organizational unit's attributes formatted for DHIS2.
        """
        json_dict = {
            "id": self.id,
            "name": self.name,
            "shortName": self.shortName,
            "openingDate": self.openingDate,
        }

        if pd.notna(self.closedDate):
            json_dict["closedDate"] = self.closedDate

        if self.parent and self.parent.get("id") and pd.notna(self.parent.get("id")):
            json_dict["parent"] = {"id": self.parent.get("id")}

        if self.geometry and pd.notna(self.geometry):
            json_dict["geometry"] = {
                "type": self.geometry["type"],
                "coordinates": self.geometry["coordinates"],
            }
        return json_dict

    def is_valid(self) -> bool:
        """Check if the OrgUnitObj instance has all required attributes set.

        Returns
        -------
        bool
            True if all required attributes are not None, False otherwise.
        """
        return pd.notna(self.id) and pd.notna(self.name) and pd.notna(self.shortName) and pd.notna(self.openingDate)

    def __str__(self) -> str:
        return f"OrgUnitObj({self.id}, {self.name})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OrgUnitObj):
            return NotImplemented
        return (
            self.id == other.id
            and self.name == other.name
            and self.shortName == other.shortName
            and self.openingDate == other.openingDate
            and self.closedDate == other.closedDate
            and self.parent == other.parent
            and self.geometry == other.geometry
        )

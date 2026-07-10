class MockDataValueSets:
    """Mock class to simulate DHIS2 DataValueSets API responses for testing purposes."""

    def get(
        self,
        data_elements: list[str] = None,  # noqa: RUF013
        periods: list[str] = None,  # noqa: RUF013
        org_units: list[str] = None,  # noqa: RUF013
        last_updated: str = None,  # noqa: RUF013
    ) -> list[dict]:
        """Simulate the retrieval of data values from DHIS2 based on the provided parameters.

        Returns
        -------
        list[dict]
            A list of dictionaries representing data values, formatted similarly to what the DHIS2 API would
        """
        # Return a mock response for data elements
        # You can customize the returned data for your tests
        return [
            {
                "dataElement": "AAA111",
                "period": "202501",
                "orgUnit": "ORG001",
                "categoryOptionCombo": "CAT001",
                "attributeOptionCombo": "ATTR001",
                "value": 12,  # Polars infer the type as integer for this column
                "storedBy": "user1",
                "created": "2025-01-01T10:00:00.000+0000",
                "lastUpdated": "2025-01-01T10:05:00.000+0000",
                "comment": None,
                "followup": False,
            },
            {
                "dataElement": "BBB222",
                "period": "202501",
                "orgUnit": "ORG002",
                "categoryOptionCombo": "CAT002",
                "attributeOptionCombo": "ATTR002",
                "value": "18",
                "storedBy": "user2",
                "created": "2025-01-02T11:00:00.000+0000",
                "lastUpdated": "2025-01-02T11:05:00.000+0000",
                "comment": None,
                "followup": False,
            },
            {
                "dataElement": "CCC333",
                "period": "202501",
                "orgUnit": "ORG003",
                "categoryOptionCombo": "CAT003",
                "attributeOptionCombo": "ATTR003",
                "value": 25,
                "storedBy": "user3",
                "created": "2025-01-03T12:00:00.000+0000",
                "lastUpdated": "2025-01-03T12:05:00.000+0000",
                "comment": None,
                "followup": False,
            },
            {
                "dataElement": "DDD444",
                "period": "202501",
                "orgUnit": "ORG003",
                "categoryOptionCombo": "CAT003",
                "attributeOptionCombo": "ATTR003",
                "value": "A COMMENT INSTEAD OF A NUMBER",
                "storedBy": "user3",
                "created": "2025-01-03T12:00:00.000+0000",
                "lastUpdated": "2025-01-03T12:05:00.000+0000",
                "comment": None,
                "followup": False,
            },
            {
                "dataElement": "DELETE1",
                "period": "202501",
                "orgUnit": "ORG004",
                "categoryOptionCombo": "CAT004",
                "attributeOptionCombo": "ATTR004",
                "value": None,
                "storedBy": "user3",
                "created": "2025-01-03T12:00:00.000+0000",
                "lastUpdated": "2025-01-03T12:05:00.000+0000",
                "comment": None,
                "followup": False,
            },
            {
                "dataElement": "INVALID1",
                "period": None,
                "orgUnit": "ORG005",
                "categoryOptionCombo": "CAT005",
                "attributeOptionCombo": "ATTR005",
                "value": "55.0",
                "storedBy": "user3",
                "created": "2025-01-03T12:00:00.000+0000",
                "lastUpdated": "2025-01-03T12:05:00.000+0000",
                "comment": None,
                "followup": False,
            },
            {
                "dataElement": "INVALID2",
                "period": "202501",
                "orgUnit": None,
                "categoryOptionCombo": "CAT005",
                "attributeOptionCombo": "ATTR005",
                "value": "55.0",
                "storedBy": "user3",
                "created": "2025-01-03T12:00:00.000+0000",
                "lastUpdated": "2025-01-03T12:05:00.000+0000",
                "comment": None,
                "followup": False,
            },
            {
                "dataElement": "INVALID3",
                "period": "202501",
                "orgUnit": "ORG005",
                "categoryOptionCombo": None,
                "attributeOptionCombo": "ATTR005",
                "value": "55.0",
                "storedBy": "user3",
                "created": "2025-01-03T12:00:00.000+0000",
                "lastUpdated": "2025-01-03T12:05:00.000+0000",
                "comment": None,
                "followup": False,
            },
            {
                "dataElement": "INVALID4",
                "period": "202501",
                "orgUnit": "ORG005",
                "categoryOptionCombo": "CAT005",
                "attributeOptionCombo": None,
                "value": "55.0",
                "storedBy": "user3",
                "created": "2025-01-03T12:00:00.000+0000",
                "lastUpdated": "2025-01-03T12:05:00.000+0000",
                "comment": None,
                "followup": False,
            },
            {
                "dataElement": None,
                "period": "202501",
                "orgUnit": "ORG006",
                "categoryOptionCombo": "CAT006",
                "attributeOptionCombo": "ATTR006",
                "value": "55.0",
                "storedBy": "user3",
                "created": "2025-01-03T12:00:00.000+0000",
                "lastUpdated": "2025-01-03T12:05:00.000+0000",
                "comment": None,
                "followup": False,
            },
        ]


class MockAnalytics:
    """Mock class to simulate DHIS2 Analytics API responses for testing purposes."""

    def get(
        self,
        indicators: list[str] = None,  # noqa: RUF013
        data_elements: list[str] = None,  # noqa: RUF013
        periods: list[str] = None,  # noqa: RUF013
        org_units: list[str] = None,  # noqa: RUF013
        include_cocs: bool = False,
    ) -> list[dict]:
        """Simulate the retrieval of analytics data from DHIS2 based on the provided parameters.

        Returns
        -------
        list[dict]
            A list of dictionaries representing analytics data, formatted similarly to what the DHIS2 API would
        """
        if data_elements:
            return [
                {
                    "dx": "AAA111.REPORTING_RATE",
                    "pe": "202409",
                    "ou": "OU001",
                    "value": "100",
                },
                {
                    "dx": "BBB222.EXPECTED_REPORTS",
                    "pe": "202409",
                    "ou": "OU002",
                    "value": "0",
                },
                {
                    "dx": "CCC333.REPORTING_RATE",
                    "pe": "202409",
                    "ou": "OU003",
                    "value": "100",
                },
            ]

        if include_cocs:
            return [
                {
                    "dx": "DATAELEMENT1",
                    "pe": "202501",
                    "ou": "ORG001",
                    "co": "COC001",
                    "value": "6.0",
                },
                {
                    "dx": "DATAELEMENT2",
                    "pe": "202501",
                    "ou": "ORG002",
                    "co": "COC002",
                    "value": "7.0",
                },
                {
                    "dx": "DATAELEMENT3",
                    "pe": "202501",
                    "ou": "ORG003",
                    "co": "COC003",
                    "value": "8.0",
                },
            ]
        return [
            {
                "dx": "INDICATOR1",
                "pe": "202501",
                "ou": "ORG001",
                "value": "5.0",
            },
            {
                "dx": "INDICATOR2",
                "pe": "202501",
                "ou": "ORG002",
                "value": "7.0",
            },
            {
                "dx": "INDICATOR3",
                "pe": "202501",
                "ou": "ORG003",
                "value": "9.0",
            },
        ]


class MockMeta:
    """Mock class to simulate DHIS2 metadata API responses for testing purposes."""

    def organisation_units(self, fields: str = "") -> list[dict]:
        """Simulate the retrieval of organisation units from DHIS2.

        Returns:
            list[dict]: A list of dictionaries representing organisation units, formatted similarly to
            what the DHIS2 API would return.
        """
        return [
            {
                "id": "OU001",
                "name": "District 1",
                "shortName": "D1",
                "openingDate": "2020-01-01",
                "closedDate": None,
                "parent": {"id": "COUNTRY"},
                "level": 2,
                "path": "/COUNTRY/OU001",
                "geometry": None,
            },
            {
                "id": "OU002",
                "name": "District 2 old name",
                "shortName": "D2",
                "openingDate": "2020-01-01",
                "closedDate": None,
                "parent": {"id": "COUNTRY"},
                "level": 2,
                "path": "/COUNTRY/OU002",
                "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
            },
        ]


class MockSession:
    """Mock class to simulate a requests.Session for testing purposes."""

    def post(self, *args, **kwargs: object) -> None:  # noqa: ANN002
        """Simulate a POST request to the DHIS2 API."""
        # This will be patched in your test
        pass


class MockAPI:
    """Mock class to simulate a DHIS2 API client for testing purposes."""

    def __init__(self):
        self.session = MockSession()
        self.url = "https://mock-dhis2-instance.org/api"


class MockDHIS2Client:
    """Mock class to simulate a DHIS2 client for testing purposes."""

    def __init__(self):
        self.data_value_sets = MockDataValueSets()
        self.analytics = MockAnalytics()
        self.meta = MockMeta()
        self.api = MockAPI()
        self.session = MockSession()
        self.version = "2.40.9"

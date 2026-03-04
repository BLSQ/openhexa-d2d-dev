class MockDataValueSets:
    """Mock class to simulate DHIS2 DataValueSets API responses for testing purposes."""

    def get(self, data_elements=None, periods=None, org_units=None, last_updated=None) -> list[dict]:  # noqa: ANN001
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
                "value": "12",
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
                "value": "25",
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

    def get(self, indicators=None, data_elements=None, periods=None, org_units=None, include_cocs=False) -> list[dict]:  # noqa: ANN001
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


class MockDHIS2Client:
    """Mock class to simulate a DHIS2 client for testing purposes."""

    def __init__(self):
        self.data_value_sets = MockDataValueSets()
        self.analytics = MockAnalytics()

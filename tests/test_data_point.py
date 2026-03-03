import polars as pl

from d2d_development.data_models import DataPointModel
from tests.mock_dhis2 import MockDHIS2Client


def test_data_point_model_to_str():
    """Test conversion of a Polars DataFrame to JSON using the DataPointModel."""
    single_point = DataPointModel(
        dataElement="de1",
        period="202601",
        orgUnit="OU1",
        categoryOptionCombo="coc1",
        attributeOptionCombo="aoc1",
        value="100.2",
    )

    assert "dataElement=de1" in str(single_point)
    assert "period=202601" in str(single_point)
    assert "orgUnit=OU1" in str(single_point)
    assert "categoryOptionCombo=coc1" in str(single_point)
    assert "attributeOptionCombo=aoc1" in str(single_point)
    assert "value=100.2" in str(single_point)


def test_data_point_model_to_json():
    """Test conversion of a Polars DataFrame to JSON using the DataPointModel."""
    data_elements = pl.DataFrame(MockDHIS2Client().data_value_sets.get())
    single_point = DataPointModel(
        dataElement=data_elements[0]["dataElement"].item(),
        period=data_elements[0]["period"].item(),
        orgUnit=data_elements[0]["orgUnit"].item(),
        categoryOptionCombo=data_elements[0]["categoryOptionCombo"].item(),
        attributeOptionCombo=data_elements[0]["attributeOptionCombo"].item(),
        value=data_elements[0]["value"].item(),
    )

    payload = single_point.to_json()
    assert payload["dataElement"] == data_elements[0]["dataElement"].item()
    assert payload["period"] == data_elements[0]["period"].item()
    assert payload["orgUnit"] == data_elements[0]["orgUnit"].item()
    assert payload["categoryOptionCombo"] == data_elements[0]["categoryOptionCombo"].item()
    assert payload["attributeOptionCombo"] == data_elements[0]["attributeOptionCombo"].item()
    assert payload["value"] == data_elements[0]["value"].item()


def test_data_point_model_to_json_delete():
    """Test conversion of a Polars DataFrame to JSON using the DataPointModel."""
    data_elements = pl.DataFrame(MockDHIS2Client().data_value_sets.get())
    points_list = [
        DataPointModel(
            dataElement=row["dataElement"],
            period=row["period"],
            orgUnit=row["orgUnit"],
            categoryOptionCombo=row["categoryOptionCombo"],
            attributeOptionCombo=row["attributeOptionCombo"],
            value=row["value"],
        ).to_json()
        for row in data_elements.to_dicts()
    ]

    # append a deleted value at idx 3
    points_list.append(
        DataPointModel(
            dataElement="AAA111",
            period="202601",
            orgUnit="OU1",
            categoryOptionCombo="coc1",
            attributeOptionCombo="aoc1",
            value=None,
        ).to_json()
    )

    assert len(points_list) == 4
    assert points_list[0]["dataElement"] == "AAA111"
    assert points_list[0]["period"] == "202501"
    assert points_list[0].get("comment") is None
    assert not points_list[3]["value"]
    assert points_list[3]["comment"] == "deleted value"

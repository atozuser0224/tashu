import pytest

from app.tashu import TashuApiError, TashuClient


def test_normalizes_official_tashu_field_names():
    station = TashuClient._normalize_station(
        {
            "id": 1042,
            "name": "충남대 정문",
            "name_en": "CNU main gate",
            "name_cn": None,
            "x_pos": "36.3665",
            "y_pos": "127.3445",
            "address": "대전광역시 유성구",
            "parking_count": "7",
        }
    )

    assert station.station_id == "1042"
    assert station.location.lat == 36.3665
    assert station.location.lng == 127.3445
    assert station.available_bikes == 7


@pytest.mark.asyncio
async def test_requires_api_token():
    client = TashuClient(token=None)
    client.token = None
    with pytest.raises(TashuApiError, match="TASHU_API_TOKEN"):
        await client.fetch_stations()

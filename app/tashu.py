from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from app.models import Location, TashuLiveStation


TASHU_STATIONS_URL = "https://bikeapp.tashu.or.kr:50041/v1/openapi/station"


class TashuApiError(RuntimeError):
    pass


class TashuClient:
    """Small adapter for the official Tashu station API.

    The official schema names x_pos/y_pos unusually: x_pos is latitude and
    y_pos is longitude. Normalizing that once here keeps the rest of the server
    and the frontend on explicit lat/lng fields.
    """

    def __init__(
        self,
        token: str | None = None,
        timeout_seconds: float = 10.0,
        cache_ttl_seconds: float = 60.0,
    ):
        self.token = token or os.getenv("TASHU_API_TOKEN")
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: list[TashuLiveStation] | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def fetch_stations(self) -> list[TashuLiveStation]:
        if not self.token:
            raise TashuApiError("TASHU_API_TOKEN is not configured")

        now = time.monotonic()
        if self._cache is not None and now - self._cached_at < self.cache_ttl_seconds:
            return list(self._cache)

        async with self._lock:
            now = time.monotonic()
            if self._cache is not None and now - self._cached_at < self.cache_ttl_seconds:
                return list(self._cache)
            stations = await self._fetch_uncached()
            self._cache = stations
            self._cached_at = time.monotonic()
            return list(stations)

    async def _fetch_uncached(self) -> list[TashuLiveStation]:

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    TASHU_STATIONS_URL,
                    headers={"api-token": self.token},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TashuApiError(f"official Tashu API request failed: {exc}") from exc

        results = payload.get("results")
        if not isinstance(results, list):
            raise TashuApiError("official Tashu API response has no results list")

        stations: list[TashuLiveStation] = []
        for raw in results:
            try:
                stations.append(self._normalize_station(raw))
            except (KeyError, TypeError, ValueError) as exc:
                raise TashuApiError(f"invalid Tashu station row: {exc}") from exc
        return stations

    @staticmethod
    def _normalize_station(raw: dict[str, Any]) -> TashuLiveStation:
        lat = float(raw["x_pos"])
        lng = float(raw["y_pos"])
        if not (35.8 <= lat <= 36.7 and 127.0 <= lng <= 127.7):
            raise ValueError(f"coordinates outside Daejeon range: {lat}, {lng}")
        return TashuLiveStation(
            station_id=str(raw["id"]),
            station_name=str(raw["name"]),
            station_name_en=raw.get("name_en"),
            station_name_cn=raw.get("name_cn"),
            location=Location(lat=lat, lng=lng),
            address=raw.get("address"),
            available_bikes=int(raw["parking_count"]),
        )

from __future__ import annotations

import csv
import importlib
import importlib.util
import math
import sys
from datetime import timedelta
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from threading import RLock
from types import ModuleType
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from app.models import ApiModel, CorePayload


CORE_MODEL_DIR = Path(__file__).resolve().parent.parent / "Hosu"
CORE_MODEL_SOURCE = (
    "github-pr-1@b3e9133726b5eee5ac3472f7282dcc5d5bb16f09/"
    "Hosu/snapshot_engine.py"
)
CORE_MODEL_INVENTORY_SOURCE = "synthetic_daily_baseline_8_plus_observed_flow"
CORE_MODEL_LIMITATIONS = (
    "가용 재고는 실제 과거 재고가 아니라 일별 8대 기준값에 관측 flow를 누적한 데모 복원값입니다.",
    "고장 의심 피처는 전체 수집기간 집계값을 포함하므로 과거 시점 성능평가에는 사용할 수 없습니다.",
    "D 회차는 서비스일 다음 날 03:00으로 해석합니다.",
)
CORE_MODEL_REQUIRED_FILES = (
    "model.py",
    "snapshot_engine.py",
    "processed/adjacency.npy",
    "processed/node_index.csv",
    "processed/norm_stats.json",
    "processed/a3tgcn_v2.pt",
    "processed/X_node.npy",
    "processed/X_global.npy",
    "processed/flow_mean_n.npy",
    "processed/flow_std_n.npy",
    "processed/timeline.csv",
    "processed/station_master.csv",
    "processed/weather_rounds.parquet",
    "processed/bike_features.parquet",
    "processed/flow.npy",
)
ROUND_TIMES: dict[str, str] = {
    "A": "07:00",
    "B": "11:30",
    "C": "16:00",
    "D": "03:00",
}
RoundId = Literal["A", "B", "C", "D"]


class CoreModelError(RuntimeError):
    pass


class CoreModelStatus(ApiModel):
    available: bool
    loaded: bool
    source: str = CORE_MODEL_SOURCE
    inventory_source: str = CORE_MODEL_INVENTORY_SOURCE
    limitations: list[str] = Field(default_factory=lambda: list(CORE_MODEL_LIMITATIONS))
    missing_files: list[str] = Field(default_factory=list)
    missing_dependencies: list[str] = Field(default_factory=list)
    available_dates: list[str] = Field(default_factory=list)
    available_rounds: list[RoundId] = Field(default_factory=list)
    available_rounds_by_date: dict[str, list[RoundId]] = Field(default_factory=dict)
    error: str | None = None


class CoreModelSnapshot(ApiModel):
    source: str = CORE_MODEL_SOURCE
    inventory_source: str = CORE_MODEL_INVENTORY_SOURCE
    limitations: list[str] = Field(default_factory=lambda: list(CORE_MODEL_LIMITATIONS))
    date: str
    round_id: RoundId
    assumed_at: datetime
    core: CorePayload
    priority_bikes: list[dict[str, Any]] = Field(default_factory=list)
    raw_meta: dict[str, Any] = Field(default_factory=dict)


class CoreModelAdapter:
    """Loads the core model contributed in PR #1 and adapts its snapshot JSON."""

    def __init__(self, model_dir: Path = CORE_MODEL_DIR):
        self.model_dir = model_dir
        self._lock = RLock()
        self._engine: Any | None = None
        self._load_error: str | None = None

    def status(self) -> CoreModelStatus:
        missing_files, missing_dependencies = self._missing_requirements()
        dates, rounds, rounds_by_date = self._timeline_options()
        return CoreModelStatus(
            available=(
                not missing_files
                and not missing_dependencies
                and self._load_error is None
            ),
            loaded=self._engine is not None,
            missing_files=missing_files,
            missing_dependencies=missing_dependencies,
            available_dates=dates,
            available_rounds=rounds,
            available_rounds_by_date=rounds_by_date,
            error=self._load_error,
        )

    def load(self) -> None:
        with self._lock:
            if self._engine is not None:
                return
            missing_files, missing_dependencies = self._missing_requirements()
            if missing_files or missing_dependencies:
                details = [
                    *(f"missing file: {item}" for item in missing_files),
                    *(f"missing dependency: {item}" for item in missing_dependencies),
                ]
                raise CoreModelError("Core model is unavailable (" + ", ".join(details) + ")")
            try:
                snapshot_engine = self._import_engine()
                snapshot_engine.load_artifacts()
                self._engine = snapshot_engine
                self._load_error = None
            except Exception as exc:  # pragma: no cover - dependency/runtime detail
                self._load_error = str(exc)
                raise CoreModelError(f"Core model load failed: {exc}") from exc

    def snapshot(self, date: str, round_id: str) -> CoreModelSnapshot:
        normalized_round = round_id.upper()
        if normalized_round not in ROUND_TIMES:
            raise CoreModelError("round_id must be one of A, B, C, D")
        try:
            parsed_date = Date.fromisoformat(date)
        except ValueError as exc:
            raise CoreModelError("date must use YYYY-MM-DD format") from exc
        _, _, rounds_by_date = self._timeline_options()
        if normalized_round not in rounds_by_date.get(parsed_date.isoformat(), []):
            raise CoreModelError(
                f"Core snapshot frame is unavailable for {date} {normalized_round}"
            )
        self.load()
        try:
            raw = self._engine.compute_snapshot(
                date=parsed_date.isoformat(),
                round_id=normalized_round,
                mode="demo",
                demo_mode=True,
            )
        except Exception as exc:
            raise CoreModelError(f"Core snapshot failed for {date} {normalized_round}: {exc}") from exc
        assumed_at = datetime.fromisoformat(
            f"{parsed_date.isoformat()}T{ROUND_TIMES[normalized_round]}:00"
        ).replace(tzinfo=ZoneInfo("Asia/Seoul"))
        if normalized_round == "D":
            assumed_at += timedelta(days=1)
        raw_meta = dict(raw.get("meta") or {})
        raw_meta.update(
            {
                "source": CORE_MODEL_SOURCE,
                "inventory_source": CORE_MODEL_INVENTORY_SOURCE,
                "limitations": list(CORE_MODEL_LIMITATIONS),
                "assumed_at": assumed_at.isoformat(),
            }
        )
        try:
            core = _adapt_core_payload(raw, assumed_at)
        except CoreModelError:
            raise
        except Exception as exc:
            raise CoreModelError(f"Core snapshot schema adaptation failed: {exc}") from exc
        return CoreModelSnapshot(
            date=parsed_date.isoformat(),
            round_id=normalized_round,
            assumed_at=assumed_at,
            core=core,
            priority_bikes=list(raw.get("priority_bikes") or []),
            raw_meta=raw_meta,
        )

    def _missing_requirements(self) -> tuple[list[str], list[str]]:
        missing_files = [
            relative
            for relative in CORE_MODEL_REQUIRED_FILES
            if not (self.model_dir / relative).is_file()
        ]
        missing_dependencies = [
            name
            for name in ("numpy", "pandas", "pyarrow", "torch")
            if importlib.util.find_spec(name) is None
        ]
        return missing_files, missing_dependencies

    def _import_engine(self) -> ModuleType:
        if self.model_dir.resolve() == CORE_MODEL_DIR.resolve():
            return importlib.import_module("Hosu.snapshot_engine")
        package_name = f"_tashu_core_{abs(hash(str(self.model_dir.resolve())))}"
        module_name = f"{package_name}.snapshot_engine"
        cached = sys.modules.get(module_name)
        if cached is not None:
            return cached
        package = ModuleType(package_name)
        package.__path__ = [str(self.model_dir)]  # type: ignore[attr-defined]
        package.__package__ = package_name
        sys.modules[package_name] = package
        spec = importlib.util.spec_from_file_location(
            module_name,
            self.model_dir / "snapshot_engine.py",
        )
        if spec is None or spec.loader is None:
            raise CoreModelError("Core model module could not be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _timeline_options(
        self,
    ) -> tuple[list[str], list[RoundId], dict[str, list[RoundId]]]:
        timeline_path = self.model_dir / "processed" / "timeline.csv"
        if not timeline_path.is_file():
            return [], [], {}
        frames: dict[str, set[str]] = {}
        rounds: set[str] = set()
        try:
            with timeline_path.open(encoding="utf-8-sig", newline="") as source:
                for index, row in enumerate(csv.DictReader(source)):
                    # compute_snapshot needs the previous eight rounds as its
                    # inference window, so those rows are not selectable.
                    if index < 8:
                        continue
                    raw_date = (row.get("service_date") or "").split(" ", 1)[0]
                    raw_round = (row.get("round_id") or "").upper()
                    if raw_date and raw_round in ROUND_TIMES:
                        frames.setdefault(raw_date, set()).add(raw_round)
                        rounds.add(raw_round)
        except (OSError, csv.Error):
            return [], [], {}
        ordered_rounds = [item for item in ROUND_TIMES if item in rounds]
        rounds_by_date = {
            frame_date: [
                item for item in ROUND_TIMES if item in available_rounds
            ]
            for frame_date, available_rounds in sorted(frames.items())
        }
        return (
            list(rounds_by_date),
            ordered_rounds,  # type: ignore[return-value]
            rounds_by_date,  # type: ignore[return-value]
        )


def _adapt_core_payload(raw: dict[str, Any], assumed_at: datetime) -> CorePayload:
    stations: list[dict[str, Any]] = []
    for station in raw.get("stations") or []:
        weather = station.get("current_weather") or {}
        correction = station.get("ml_correction") or {}
        prediction = station.get("stgnn_prediction") or {}
        precipitation = float(weather.get("precipitation_mm") or 0)
        precip_band = "heavy" if precipitation >= 5 else "light" if precipitation > 0 else "none"
        # The planner subtracts broken_suspected_count itself, so feed the
        # model's pre-correction inventory and avoid excluding bikes twice.
        broken = max(0, int(correction.get("broken_suspected") or 0))
        available = correction.get("api_available")
        if available is None:
            real_available = max(0, int(correction.get("real_available") or 0))
            available = real_available + broken
        available = max(0, int(available or 0))
        predicted_value = float(prediction.get("predicted_net_flow") or 0)
        predicted = (
            math.floor(predicted_value + 0.5)
            if predicted_value >= 0
            else math.ceil(predicted_value - 0.5)
        )
        pressure = min(1.0, max(0.0, float(prediction.get("shortage_pressure") or 0)))
        stations.append(
            {
                "station_id": str(station["station_id"]),
                "station_name": str(station["station_name"]),
                "location": station["location"],
                "available_bikes": available,
                "capacity": max(20, available),
                "weather": {
                    "precip_band": precip_band,
                    "temperature_c": weather.get("temperature_c"),
                },
                "ml": {
                    "broken_suspected_count": broken
                },
                "stgnn": {
                    "predicted_net_flow": predicted,
                    "shortage_pressure": pressure,
                },
            }
        )
    if not stations:
        raise CoreModelError("Core model returned no stations")
    raw_meta = dict(raw.get("meta") or {})
    return CorePayload.model_validate(
        {
            "meta": {
                "generated_at": assumed_at.isoformat(),
                "horizon": f"{raw_meta.get('round_id', '')} {raw_meta.get('time', '')}".strip(),
                "demo_mode": True,
                "source": CORE_MODEL_SOURCE,
                "inventory_source": CORE_MODEL_INVENTORY_SOURCE,
                "limitations": list(CORE_MODEL_LIMITATIONS),
                "core_model_meta": raw_meta,
            },
            "stations": stations,
        }
    )

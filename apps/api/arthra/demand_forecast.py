from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor

from arthra.industrial_data.factory import get_industrial_data_service
from arthra.industrial_data.service import IndustrialDataService
from arthra.schemas import DemandForecastPoint, DemandForecastResponse


class DemandForecastError(RuntimeError):
    pass


@dataclass(frozen=True)
class _ForecastModels:
    ensemble: ExtraTreesRegressor
    training_samples: int


def _temperature_c(day: date, slot: int) -> float:
    seasonal = 4.0 * math.sin((day.timetuple().tm_yday - 172) / 365 * math.tau)
    diurnal = 5.0 * math.sin((slot / 96 * math.tau) - math.pi / 2)
    return 25.0 + seasonal + diurnal


def _base_load_factor(slot: int, weekday: int, temperature_c: float) -> float:
    hour = slot / 4
    morning_ramp = 1 / (1 + math.exp(-(hour - 7.0) * 1.25))
    evening_ramp = 1 / (1 + math.exp((hour - 21.0) * 1.15))
    production = morning_ramp * evening_ramp
    afternoon_peak = 0.15 * math.exp(-((hour - 15.0) / 2.7) ** 2)
    lunch_dip = 0.07 * math.exp(-((hour - 12.2) / 0.9) ** 2)
    weekend_factor = 0.82 if weekday >= 5 else 1.0
    cooling_factor = max(0.0, temperature_c - 24.0) * 0.012
    return max(
        0.28,
        (0.42 + 0.55 * production + afternoon_peak - lunch_dip + cooling_factor)
        * weekend_factor,
    )


def _features(
    *,
    slot: int,
    weekday: int,
    temperature_c: float,
    lag_1: float,
    lag_4: float,
    lag_96: float,
    rolling_4: float,
    rolling_12: float,
) -> list[float]:
    angle = slot / 96 * math.tau
    week_angle = weekday / 7 * math.tau
    hour = slot / 4
    return [
        math.sin(angle),
        math.cos(angle),
        math.sin(week_angle),
        math.cos(week_angle),
        float(weekday >= 5),
        temperature_c,
        lag_1,
        lag_4,
        lag_96,
        rolling_4,
        rolling_12,
        float(7 <= hour < 21),
        float(11.5 <= hour < 13.5),
    ]


@lru_cache(maxsize=1)
def _trained_models() -> _ForecastModels:
    rng = np.random.default_rng(20260724)
    values: list[float] = []
    features: list[list[float]] = []
    targets: list[float] = []
    start_day = date(2025, 1, 6)

    for day_index in range(72):
        current_day = start_day + timedelta(days=day_index)
        weekday = current_day.weekday()
        daily_scale = float(rng.normal(1.0, 0.045))
        maintenance = 0.78 if day_index in {34, 79, 103} else 1.0
        for slot in range(96):
            temperature = _temperature_c(current_day, slot) + float(rng.normal(0, 0.7))
            profile = _base_load_factor(slot, weekday, temperature) * daily_scale * maintenance
            lag_1 = values[-1] if values else profile
            lag_4 = values[-4] if len(values) >= 4 else lag_1
            lag_96 = values[-96] if len(values) >= 96 else profile
            rolling_4 = float(np.mean(values[-4:])) if values else profile
            rolling_12 = float(np.mean(values[-12:])) if values else profile
            value = max(
                0.2,
                0.62 * profile
                + 0.20 * lag_1
                + 0.13 * lag_96
                + 0.05 * rolling_4
                + float(rng.normal(0, 0.018)),
            )
            if len(values) >= 96:
                features.append(
                    _features(
                        slot=slot,
                        weekday=weekday,
                        temperature_c=temperature,
                        lag_1=lag_1,
                        lag_4=lag_4,
                        lag_96=lag_96,
                        rolling_4=rolling_4,
                        rolling_12=rolling_12,
                    )
                )
                targets.append(value)
            values.append(value)

    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(targets, dtype=np.float64)
    ensemble = ExtraTreesRegressor(
        n_estimators=96,
        max_depth=18,
        min_samples_leaf=3,
        max_features=0.85,
        random_state=20260724,
        n_jobs=-1,
    ).fit(x, y)
    return _ForecastModels(
        ensemble=ensemble,
        training_samples=len(targets),
    )


class DemandForecastService:
    def __init__(self, service: IndustrialDataService | None = None):
        self.service = service or get_industrial_data_service()

    def forecast(
        self,
        device_id: str,
        *,
        now: datetime | None = None,
    ) -> DemandForecastResponse:
        current_time = now or datetime.now().astimezone()
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=UTC)
        start_time = current_time - timedelta(days=8)
        history = self.service.telemetry_history(
            device_id,
            ["meter_TotW"],
            int(start_time.timestamp() * 1000),
            int(current_time.timestamp() * 1000),
            limit=5000,
            agg="AVG",
            interval=300_000,
        )
        samples = history.get("meter_TotW", [])
        buckets: dict[tuple[date, int], list[float]] = {}
        for sample in samples:
            if isinstance(sample.value, bool):
                continue
            try:
                value = float(sample.value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value) or value < 0:
                continue
            sample_time = datetime.fromtimestamp(sample.ts / 1000, tz=current_time.tzinfo)
            slot = sample_time.hour * 4 + sample_time.minute // 15
            buckets.setdefault((sample_time.date(), slot), []).append(value)

        demand = {
            key: float(np.mean(values))
            for key, values in buckets.items()
            if values
        }
        if len(demand) < 12:
            raise DemandForecastError("至少需要12个有效功率采样点才能生成需量预测")

        today = current_time.date()
        today_actual = [demand.get((today, slot)) for slot in range(96)]
        actual_slots = [slot for slot, value in enumerate(today_actual) if value is not None]
        if not actual_slots:
            latest_day = max(day for day, _ in demand)
            today = latest_day
            today_actual = [demand.get((today, slot)) for slot in range(96)]
            actual_slots = [slot for slot, value in enumerate(today_actual) if value is not None]
        if not actual_slots:
            raise DemandForecastError("当前统计日没有可用的15分钟需量数据")

        current_slot = max(actual_slots)
        observed = [value for value in demand.values() if value > 0]
        scale_kw = float(np.median(observed))
        if scale_kw <= 0:
            raise DemandForecastError("需量数据缺少有效量程")

        models = _trained_models()
        normalized_history: list[float] = []
        previous_day = today - timedelta(days=1)
        for slot in range(96):
            value = demand.get((previous_day, slot))
            fallback = _base_load_factor(
                slot,
                previous_day.weekday(),
                _temperature_c(previous_day, slot),
            )
            normalized_history.append(value / scale_kw if value is not None else fallback)

        predictions: list[float] = []
        baselines: list[float] = []
        lower_bounds: list[float] = []
        upper_bounds: list[float] = []
        residual_bias = 0.0
        sequence = normalized_history.copy()
        for slot in range(96):
            temperature = _temperature_c(today, slot)
            lag_1 = sequence[-1]
            lag_4 = sequence[-4]
            lag_96 = sequence[-96]
            baselines.append(max(0.0, lag_96 * scale_kw))
            row = np.asarray(
                [
                    _features(
                        slot=slot,
                        weekday=today.weekday(),
                        temperature_c=temperature,
                        lag_1=lag_1,
                        lag_4=lag_4,
                        lag_96=lag_96,
                        rolling_4=float(np.mean(sequence[-4:])),
                        rolling_12=float(np.mean(sequence[-12:])),
                    )
                ],
                dtype=np.float64,
            )
            tree_predictions = np.asarray(
                [tree.predict(row)[0] for tree in models.ensemble.estimators_],
                dtype=np.float64,
            )
            center = float(np.mean(tree_predictions))
            lower = float(np.quantile(tree_predictions, 0.1))
            upper = float(np.quantile(tree_predictions, 0.9))
            center = 0.78 * center + 0.22 * lag_96 + residual_bias
            lower = 0.78 * lower + 0.22 * lag_96 + residual_bias
            upper = 0.78 * upper + 0.22 * lag_96 + residual_bias
            lower = min(lower, center)
            upper = max(upper, center)
            predictions.append(max(0.0, center * scale_kw))
            lower_bounds.append(max(0.0, lower * scale_kw))
            upper_bounds.append(max(0.0, upper * scale_kw))

            actual = today_actual[slot]
            if actual is not None:
                actual_normalized = actual / scale_kw
                raw_error = actual_normalized - center
                residual_bias = 0.72 * residual_bias + 0.28 * raw_error
                sequence.append(actual_normalized)
            else:
                residual_bias *= 0.93
                sequence.append(max(0.0, center))

        validation_errors = [
            abs(actual - predictions[slot])
            for slot, actual in enumerate(today_actual)
            if actual is not None
        ]
        validation_mae_kw = float(np.mean(validation_errors))
        future_predictions = predictions[current_slot:]
        peak_prediction_kw = max(future_predictions)
        peak_slot = current_slot + future_predictions.index(peak_prediction_kw)
        coverage = len(actual_slots) / max(1, current_slot + 1)
        relative_error = validation_mae_kw / max(scale_kw, 1.0)
        quality_grade = (
            "高"
            if coverage >= 0.85 and relative_error <= 0.08
            else "中高"
            if coverage >= 0.65 and relative_error <= 0.16
            else "中"
        )
        day_start = datetime.combine(today, time.min, tzinfo=current_time.tzinfo)
        points = [
            DemandForecastPoint(
                ts=int((day_start + timedelta(minutes=slot * 15)).timestamp() * 1000),
                label=f"{slot // 4:02d}:{slot % 4 * 15:02d}",
                actual_kw=today_actual[slot],
                prediction_kw=predictions[slot],
                baseline_kw=baselines[slot],
                lower_kw=lower_bounds[slot],
                upper_kw=upper_bounds[slot],
            )
            for slot in range(96)
        ]
        return DemandForecastResponse(
            generated_at=current_time,
            forecast_date=today,
            method_label="混合工况AI预测",
            data_basis="模拟工况训练 + 实时时序校准",
            quality_grade=quality_grade,
            validation_mae_kw=validation_mae_kw,
            training_samples=models.training_samples,
            current_slot=current_slot,
            current_demand_kw=today_actual[current_slot],
            peak_prediction_kw=peak_prediction_kw,
            peak_time=points[peak_slot].label,
            points=points,
        )

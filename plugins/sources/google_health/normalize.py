"""Google Health API data point payloads -> IngestStorage sample shapes."""

from __future__ import annotations

from typing import Any

SOURCE_TAG = "Google Health"
ORIGIN_PROVIDER = "google-health-api"


def _maybe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _provider_device_id(data_source: dict[str, Any]) -> str | None:
    device = data_source.get("device")
    if not isinstance(device, dict):
        return None
    display_name = device.get("displayName")
    if display_name:
        return str(display_name)
    manufacturer = device.get("manufacturer")
    form_factor = device.get("formFactor")
    if manufacturer and form_factor:
        return f"{manufacturer}:{form_factor}"
    if manufacturer:
        return str(manufacturer)
    return None


def _source_application(data_source: dict[str, Any]) -> str | None:
    application = data_source.get("application")
    if not isinstance(application, dict):
        return None
    package_name = application.get("packageName")
    return str(package_name) if package_name else None


def normalize_step_points(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Normalize Google Health ``steps`` points to ``step_count`` samples."""

    rows: list[dict[str, Any]] = []
    for item in items:
        point_name = item.get("name")
        steps = item.get("steps")
        if not point_name or not isinstance(steps, dict):
            continue

        interval = steps.get("interval")
        if not isinstance(interval, dict):
            continue

        start = interval.get("startTime")
        count = _maybe_float(steps.get("count"))
        if not start or count is None:
            continue

        data_source = item.get("dataSource") if isinstance(item.get("dataSource"), dict) else {}
        source_application = _source_application(data_source)
        provider_device_id = _provider_device_id(data_source)
        platform = data_source.get("platform")

        row: dict[str, Any] = {
            "date": str(start),
            "qty": count,
            "unit": "count",
            "source": SOURCE_TAG,
            "provider_object_id": str(point_name),
            "origin_provider": ORIGIN_PROVIDER,
        }
        if provider_device_id:
            row["provider_device_id"] = provider_device_id
        if source_application:
            row["source_application"] = source_application
        if platform:
            row["source_platform"] = str(platform)
        rows.append(row)

    return {"step_count": rows}

"""Read-only availability check for one train; no booking, login, or seat selection."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from notifier import NotificationError, availability_message, send_notification, test_message
from state_store import GitHubIssueStateStore, StateStoreError

API_URL = "https://eticket.railway.uz/api/v3/handbook/trains/list"
DEPARTURE = datetime(2026, 11, 10, 10, 57, tzinfo=ZoneInfo("Asia/Tashkent"))
TARGET_DATE = "2026-11-10"
DEP_CODE = "2900800"
ARV_CODE = "2900000"
LOGGER = logging.getLogger("train_monitor")


class MonitorError(Exception):
    def __init__(self, result: str, reason: str, *, http_status: int | None = None, data=None):
        super().__init__(reason)
        self.result = result
        self.reason = reason
        self.http_status = http_status
        self.data = data
        self.target_found = "unknown"
        self.train_number = "unknown"
        self.departure_time = "unknown"
        self.arrival_time = "unknown"


@dataclass(frozen=True)
class Availability:
    result: str
    available_seats: int
    train_number: str
    departure_time: str
    arrival_time: str
    car_seats: tuple[tuple[str, int], ...]
    http_status: int = 200


def _number(value: str) -> str:
    # The live API uses Cyrillic М in 751М; accept only this known homoglyph.
    return unicodedata.normalize("NFKC", value).strip().upper().replace("М", "M")


def _station(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", value).upper() if ch.isalnum())


def _count(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MonitorError("UNKNOWN", f"Invalid {field} seat count")
    return value


def _date_time(value, field: str) -> datetime:
    if not isinstance(value, str):
        raise MonitorError("UNKNOWN", f"Missing {field}")
    try:
        return datetime.strptime(value, "%d.%m.%Y %H:%M")
    except ValueError as exc:
        raise MonitorError("UNKNOWN", f"Unexpected {field} format") from exc


def interpret_response(data: dict) -> Availability:
    if not isinstance(data, dict) or "error" not in data or data.get("error") is not None:
        raise MonitorError("UNKNOWN", "API envelope or error field changed", data=data)
    try:
        trains = data["data"]["directions"]["forward"]["trains"]
    except (KeyError, TypeError) as exc:
        raise MonitorError("UNKNOWN", "API train list schema changed", data=data) from exc
    if not isinstance(trains, list) or not trains:
        raise MonitorError("UNKNOWN", "API train list is empty or invalid", data=data)

    candidates = []
    for train in trains:
        if not isinstance(train, dict):
            raise MonitorError("UNKNOWN", "Invalid train entry", data=data)
        number = train.get("number")
        brand = train.get("brand")
        if (isinstance(number, str) and _number(number) == "751M") or brand == "Jaloliddin Manguberdi":
            candidates.append(train)
    if len(candidates) != 1:
        raise MonitorError("UNKNOWN", "Target train not found or ambiguous", data=data)
    train = candidates[0]
    number = train.get("number")
    brand = train.get("brand")
    if not isinstance(number, str) or not isinstance(brand, str):
        raise MonitorError("UNKNOWN", "Target identity fields missing", data=data)
    if _number(number) != "751M" or brand != "Jaloliddin Manguberdi":
        raise MonitorError("UNKNOWN", "Target identity fields conflict", data=data)

    dep = _date_time(train.get("departureDate"), "departureDate")
    arv = _date_time(train.get("arrivalDate"), "arrivalDate")
    if dep.strftime("%Y-%m-%d %H:%M") != "2026-11-10 10:57" or arv.strftime("%Y-%m-%d %H:%M") != "2026-11-10 15:12":
        raise MonitorError("UNKNOWN", "Target date or time changed", data=data)
    route = train.get("subRoute")
    if not isinstance(route, dict):
        raise MonitorError("UNKNOWN", "Target route missing", data=data)
    if (
        str(route.get("depStationCode")) != DEP_CODE
        or str(route.get("arvStationCode")) != ARV_CODE
        or _station(str(route.get("depStationName"))) not in ("BUKHARA", "BUKHARA1")
        or _station(str(route.get("arvStationName"))) != "TASHKENT"
    ):
        raise MonitorError("UNKNOWN", "Target station or station code changed", data=data)

    cars = train.get("cars")
    if not isinstance(cars, list):
        raise MonitorError("UNKNOWN", "Target cars field missing", data=data)
    car_seats = []
    for car in cars:
        if not isinstance(car, dict) or not isinstance(car.get("type"), str) or not car["type"]:
            raise MonitorError("UNKNOWN", "Invalid car class entry", data=data)
        count = _count(car.get("freeSeats"), "car.freeSeats")
        detail = car.get("seatDetail")
        tariffs = car.get("tariffs")
        if not isinstance(detail, dict) or not isinstance(tariffs, list):
            raise MonitorError("UNKNOWN", "Car seat detail schema changed", data=data)
        for key in ("undef", "lateralDn", "lateralUp", "freeComp", "down", "up"):
            _count(detail.get(key), f"seatDetail.{key}")
        physical_seats = sum(detail[key] for key in ("undef", "lateralDn", "lateralUp", "down", "up"))
        if physical_seats != count:
            raise MonitorError("UNKNOWN", "Car freeSeats and seatDetail disagree", data=data)
        for tariff in tariffs:
            if not isinstance(tariff, dict):
                raise MonitorError("UNKNOWN", "Invalid tariff entry", data=data)
            _count(tariff.get("freeSeats"), "tariff.freeSeats")
        if sum(tariff["freeSeats"] for tariff in tariffs) > count:
            raise MonitorError("UNKNOWN", "Tariff count exceeds car seats", data=data)
        car_seats.append((car["type"], count))

    total = sum(count for _, count in car_seats)
    return Availability(
        result="AVAILABLE" if total >= 1 else "UNAVAILABLE",
        available_seats=total,
        train_number=number,
        departure_time=dep.strftime("%H:%M"),
        arrival_time=arv.strftime("%H:%M"),
        car_seats=tuple(car_seats),
    )


def fetch_availability(*, session=None) -> Availability:
    client = session or requests.Session()
    xsrf = str(uuid.uuid4())
    payload = {
        "directions": {
            "forward": {
                "date": TARGET_DATE,
                "depStationCode": DEP_CODE,
                "arvStationCode": ARV_CODE,
            }
        }
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Language": "en",
        "device-type": "BROWSER",
        "Origin": "https://eticket.railway.uz",
        "User-Agent": "UzbekistanTrainAvailabilityMonitor/1.0",
        "X-XSRF-TOKEN": xsrf,
        "Cookie": f"XSRF-TOKEN={xsrf}",
    }
    try:
        response = client.post(API_URL, json=payload, headers=headers, timeout=(5, 20))
    except requests.RequestException as exc:
        raise MonitorError("ERROR", "Network or timeout error") from exc
    status = response.status_code
    if status != 200:
        raise MonitorError("ERROR", f"API HTTP {status}", http_status=status)
    if "application/json" not in response.headers.get("Content-Type", "").lower():
        raise MonitorError("UNKNOWN", "API returned non-JSON content", http_status=status)
    try:
        data = response.json()
    except ValueError as exc:
        raise MonitorError("UNKNOWN", "API JSON parse error", http_status=status) from exc
    try:
        return interpret_response(data)
    except MonitorError as exc:
        exc.http_status = status
        try:
            trains = data["data"]["directions"]["forward"]["trains"]
            candidates = [train for train in trains if isinstance(train, dict) and (
                (isinstance(train.get("number"), str) and _number(train["number"]) == "751M")
                or train.get("brand") == "Jaloliddin Manguberdi"
            )]
            exc.target_found = "true" if candidates else "false"
            if len(candidates) == 1:
                train = candidates[0]
                exc.train_number = _number(train["number"]) if isinstance(train.get("number"), str) else "unknown"
                for source, destination in (("departureDate", "departure_time"), ("arrivalDate", "arrival_time")):
                    value = train.get(source)
                    if isinstance(value, str) and re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", value):
                        setattr(exc, destination, value[-5:])
        except (KeyError, TypeError, ValueError):
            pass
        raise


def write_schema_diagnostic(data) -> None:
    """Only field names/types; never values, response bodies, cookies, or headers."""
    if data is None:
        return
    def shape(value, depth=0):
        if depth >= 5:
            return type(value).__name__
        if isinstance(value, dict):
            return {str(key): shape(item, depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return {"type": "list", "length": len(value), "item": shape(value[0], depth + 1) if value else None}
        return type(value).__name__
    path = Path("work/api-schema.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(shape(data), ensure_ascii=False, indent=2), encoding="utf-8")


def run_once(*, fetcher=fetch_availability, store=None, notify=send_notification, now=None, test_mode=False) -> str:
    current = now or datetime.now(ZoneInfo("Asia/Tashkent"))
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    LOGGER.info("check_time=%s timezone=Asia/Tashkent", current.astimezone(ZoneInfo("Asia/Tashkent")).isoformat())
    if test_mode:
        title, message = test_message()
        notify(title, message)
        LOGGER.info("result=TEST_NOTIFICATION_SENT production_state=unchanged")
        return "TEST_NOTIFICATION_SENT"
    if current.astimezone(ZoneInfo("Asia/Tashkent")) >= DEPARTURE:
        LOGGER.info("result=EXPIRED target_departure=%s no_api_request=true", DEPARTURE.isoformat())
        return "EXPIRED"

    state_store = store or GitHubIssueStateStore()
    previous = state_store.load()
    try:
        availability = fetcher()
    except MonitorError as exc:
        LOGGER.warning(
            "http_status=%s target_train_found=%s train_number=%s departure_time=%s arrival_time=%s available_seats=unknown result=%s reason=%s",
            exc.http_status if exc.http_status is not None else "none", exc.target_found,
            exc.train_number, exc.departure_time, exc.arrival_time, exc.result, exc.reason,
        )
        if exc.result == "UNKNOWN":
            write_schema_diagnostic(exc.data)
        return exc.result
    LOGGER.info(
        "http_status=%s target_train_found=true train_number=%s departure_time=%s arrival_time=%s available_seats=%s car_seats=%s result=%s previous=%s",
        availability.http_status, _number(availability.train_number), availability.departure_time,
        availability.arrival_time, availability.available_seats, availability.car_seats,
        availability.result, previous or "NONE",
    )
    if availability.result == "AVAILABLE" and previous != "AVAILABLE":
        title, message = availability_message(availability.available_seats)
        notify(title, message)
        state_store.save("AVAILABLE")
        LOGGER.info("notification=sent state=AVAILABLE")
    elif availability.result == "UNAVAILABLE" and previous != "UNAVAILABLE":
        state_store.save("UNAVAILABLE")
        LOGGER.info("notification=none state=UNAVAILABLE")
    else:
        LOGGER.info("notification=none state=unchanged")
    return availability.result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    test_mode = os.environ.get("TEST_MODE", "false").lower() in ("1", "true", "yes")
    try:
        result = run_once(test_mode=test_mode)
    except (StateStoreError, NotificationError) as exc:
        # These errors contain no request objects, headers, or credentials.
        LOGGER.error("result=ERROR reason=%s", exc)
        return 1
    except Exception as exc:
        # Never log arbitrary exception text: it may contain credentials.
        LOGGER.error("result=ERROR reason=unexpected_failure type=%s", type(exc).__name__)
        return 1
    return 0 if result in ("AVAILABLE", "UNAVAILABLE", "TEST_NOTIFICATION_SENT", "EXPIRED") else 1


if __name__ == "__main__":
    sys.exit(main())

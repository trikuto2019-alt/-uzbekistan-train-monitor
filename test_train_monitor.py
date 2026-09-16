from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from train_monitor import MonitorError, fetch_availability, interpret_response, run_once

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=ZoneInfo("Asia/Tashkent"))


def api_data(seats=0):
    cars = [] if seats == 0 else [{
        "type": "Sitting",
        "freeSeats": seats,
        "tariffs": [{"classServiceType": "2E", "freeSeats": seats, "tariff": 100000}],
        "seatDetail": {
            "undef": seats, "lateralDn": 0, "lateralUp": 0,
            "freeComp": 0, "down": 0, "up": 0,
        },
    }]
    return {
        "data": {"directions": {"forward": {"trains": [{
            "number": "751М", "brand": "Jaloliddin Manguberdi",
            "departureDate": "10.11.2026 10:57",
            "arrivalDate": "10.11.2026 15:06",
            "subRoute": {
                "depStationName": "BUKHARA", "depStationCode": "2900800",
                "arvStationName": "TASHKENT", "arvStationCode": "2900000",
            },
            "cars": cars,
        }]}}},
        "error": None,
    }


class FakeStore:
    def __init__(self, state=None):
        self.state = state
        self.saves = []

    def load(self):
        return self.state

    def save(self, state):
        self.saves.append(state)
        self.state = state


class FakeResponse:
    status_code = 500
    headers = {"Content-Type": "application/json"}


class FakeSession:
    def post(self, *args, **kwargs):
        return FakeResponse()


def availability(seats):
    return interpret_response(api_data(seats))


def test_zero_seats_no_notification():
    store = FakeStore()
    sent = []
    assert run_once(fetcher=lambda: availability(0), store=store, notify=lambda *args: sent.append(args), now=NOW) == "UNAVAILABLE"
    assert sent == []
    assert store.state == "UNAVAILABLE"


def test_one_seat_available():
    result = availability(1)
    assert result.result == "AVAILABLE"
    assert result.available_seats == 1


def test_target_missing_unknown():
    data = api_data()
    data["data"]["directions"]["forward"]["trains"][0]["number"] = "752М"
    data["data"]["directions"]["forward"]["trains"][0]["brand"] = "Other"
    with pytest.raises(MonitorError, match="not found") as exc:
        interpret_response(data)
    assert exc.value.result == "UNKNOWN"


def test_http_500_error():
    with pytest.raises(MonitorError) as exc:
        fetch_availability(session=FakeSession())
    assert exc.value.result == "ERROR"
    assert exc.value.http_status == 500


def test_changed_schema_unknown():
    data = api_data(1)
    del data["data"]["directions"]
    with pytest.raises(MonitorError) as exc:
        interpret_response(data)
    assert exc.value.result == "UNKNOWN"


def test_unavailable_to_available_sends_once():
    store = FakeStore("UNAVAILABLE")
    sent = []
    assert run_once(fetcher=lambda: availability(1), store=store, notify=lambda *args: sent.append(args), now=NOW) == "AVAILABLE"
    assert len(sent) == 1
    assert store.state == "AVAILABLE"


def test_available_to_available_no_notification():
    store = FakeStore("AVAILABLE")
    sent = []
    run_once(fetcher=lambda: availability(1), store=store, notify=lambda *args: sent.append(args), now=NOW)
    assert sent == []
    assert store.saves == []


def test_available_unavailable_available_resends():
    store = FakeStore("AVAILABLE")
    sent = []
    notify = lambda *args: sent.append(args)
    run_once(fetcher=lambda: availability(0), store=store, notify=notify, now=NOW)
    run_once(fetcher=lambda: availability(1), store=store, notify=notify, now=NOW)
    assert len(sent) == 1
    assert store.saves == ["UNAVAILABLE", "AVAILABLE"]


def test_first_available_sends():
    store = FakeStore()
    sent = []
    run_once(fetcher=lambda: availability(1), store=store, notify=lambda *args: sent.append(args), now=NOW)
    assert len(sent) == 1


def test_error_does_not_change_last_known_state():
    store = FakeStore("AVAILABLE")
    sent = []
    def error():
        raise MonitorError("ERROR", "API HTTP 500", http_status=500)
    assert run_once(fetcher=error, store=store, notify=lambda *args: sent.append(args), now=NOW) == "ERROR"
    assert store.state == "AVAILABLE"
    run_once(fetcher=lambda: availability(1), store=store, notify=lambda *args: sent.append(args), now=NOW)
    assert sent == []


def test_test_mode_one_notification_no_api_or_state():
    sent = []
    def forbidden():
        raise AssertionError("TEST_MODE must not call the API")
    assert run_once(fetcher=forbidden, notify=lambda *args: sent.append(args), now=NOW, test_mode=True) == "TEST_NOTIFICATION_SENT"
    assert len(sent) == 1
    assert "TEST_MODE" in sent[0][1]


def test_after_departure_no_api():
    def forbidden():
        raise AssertionError("expired monitor must not call the API")
    now = datetime(2026, 11, 10, 10, 57, tzinfo=ZoneInfo("Asia/Tashkent"))
    assert run_once(fetcher=forbidden, now=now) == "EXPIRED"


def test_missing_car_count_is_unknown():
    data = api_data(1)
    del data["data"]["directions"]["forward"]["trains"][0]["cars"][0]["freeSeats"]
    with pytest.raises(MonitorError) as exc:
        interpret_response(data)
    assert exc.value.result == "UNKNOWN"


def test_multiple_classes_use_car_seats_even_when_sleeper_tariff_is_zero():
    data = api_data(1)
    sleeper = {
        "type": "Sleeper", "freeSeats": 2,
        "tariffs": [{"classServiceType": "3P", "freeSeats": 0, "tariff": 100000}],
        "seatDetail": {
            "undef": 0, "lateralDn": 0, "lateralUp": 0,
            "freeComp": 1, "down": 1, "up": 1,
        },
    }
    data["data"]["directions"]["forward"]["trains"][0]["cars"].append(sleeper)
    result = interpret_response(data)
    assert result.result == "AVAILABLE"
    assert result.available_seats == 3


def test_conflicting_seat_details_are_unknown():
    data = api_data(1)
    data["data"]["directions"]["forward"]["trains"][0]["cars"][0]["seatDetail"]["undef"] = 0
    with pytest.raises(MonitorError) as exc:
        interpret_response(data)
    assert exc.value.result == "UNKNOWN"

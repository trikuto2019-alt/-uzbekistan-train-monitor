"""Notification adapters. ntfy is the default, permanently free option."""

from __future__ import annotations

import os
import re
import requests

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
NTFY_URL = "https://ntfy.sh"
TICKET_URL = "https://eticket.railway.uz/"


class NotificationError(Exception):
    pass


def send_ntfy(title: str, message: str, *, session=None) -> None:
    topic = os.environ.get("NTFY_TOPIC", "")
    # ntfy.sh topics are public. Require an unguessable value and never log it.
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", topic):
        raise NotificationError("NTFY_TOPIC must be a random 32-64 character value")
    client = session or requests.Session()
    try:
        response = client.post(
            NTFY_URL,
            json={
                "topic": topic,
                "title": title,
                "message": message,
                "click": TICKET_URL,
                "tags": ["train"],
            },
            headers={"User-Agent": "UzbekistanTrainAvailabilityMonitor/1.0"},
            timeout=(5, 20),
        )
        if response.status_code != 200:
            raise NotificationError(f"ntfy HTTP {response.status_code}")
        result = response.json()
        if result.get("event") != "message" or result.get("topic") != topic:
            raise NotificationError("ntfy returned an unexpected response")
    except (requests.RequestException, ValueError) as exc:
        raise NotificationError("ntfy request failed") from exc


def send_pushover(title: str, message: str, *, session=None) -> None:
    user = os.environ.get("PUSHOVER_USER_KEY")
    token = os.environ.get("PUSHOVER_API_TOKEN")
    if not user or not token:
        raise NotificationError("Pushover secrets are missing")
    client = session or requests.Session()
    try:
        response = client.post(
            PUSHOVER_URL,
            data={
                "token": token,
                "user": user,
                "title": title,
                "message": message,
                "url": TICKET_URL,
                "url_title": "公式e-ticketサイトを開く",
            },
            timeout=(5, 20),
        )
        if response.status_code != 200:
            raise NotificationError(f"Pushover HTTP {response.status_code}")
        if response.json().get("status") != 1:
            raise NotificationError("Pushover rejected the message")
    except (requests.RequestException, ValueError) as exc:
        raise NotificationError("Pushover request failed") from exc


def send_notification(title: str, message: str) -> None:
    provider = os.environ.get("NOTIFIER", "ntfy").strip().lower()
    if provider == "ntfy":
        send_ntfy(title, message)
    elif provider == "pushover":
        send_pushover(title, message)
    else:
        raise NotificationError("NOTIFIER must be ntfy or pushover")


def availability_message(seats: int) -> tuple[str, str]:
    return (
        "🚨 Jaloliddin Manguberdi 空席発生",
        "2026/11/10\n"
        "Bukhara 10:57 → Tashkent 15:06\n\n"
        "Jaloliddin Manguberdi 751M\n\n"
        "購入可能な空席を確認しました。\n\n"
        f"現在の空席数：{seats}\n\n"
        "今すぐ公式サイトを確認してください。",
    )


def test_message() -> tuple[str, str]:
    return (
        "🧪 Jaloliddin Manguberdi 通知テスト",
        "これはTEST_MODEの通知です。実際の空席を意味しません。\n"
        "公式サイト: https://eticket.railway.uz/",
    )

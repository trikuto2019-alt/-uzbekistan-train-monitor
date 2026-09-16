from __future__ import annotations

import pytest

from notifier import NotificationError, send_ntfy


class Response:
    status_code = 200

    def __init__(self, topic):
        self.topic = topic

    def json(self):
        return {"event": "message", "topic": self.topic}


class Session:
    def __init__(self, topic):
        self.topic = topic
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.topic)


def test_ntfy_sends_clickable_notification_without_logging_topic(monkeypatch):
    topic = "0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("NTFY_TOPIC", topic)
    session = Session(topic)
    send_ntfy("title", "message", session=session)
    assert len(session.calls) == 1
    _, request = session.calls[0]
    assert request["json"]["topic"] == topic
    assert request["json"]["click"] == "https://eticket.railway.uz/"


@pytest.mark.parametrize("topic", ["", "short", "contains/slash", "a" * 65])
def test_ntfy_rejects_weak_or_invalid_topics(monkeypatch, topic):
    monkeypatch.setenv("NTFY_TOPIC", topic)
    with pytest.raises(NotificationError, match="32-64"):
        send_ntfy("title", "message", session=Session(topic))

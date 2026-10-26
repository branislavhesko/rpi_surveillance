import requests

from rpi_surveillance.backend.telegram_notifier import TelegramNotifier


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"ok": True}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.calls = []
        self.response = response or FakeResponse()
        self.exc = exc

    def post(self, url, data=None, files=None, timeout=None):
        self.calls.append((url, data, files))
        if self.exc:
            raise self.exc
        return self.response


def test_send_photo_to_each_chat():
    session = FakeSession()
    notifier = TelegramNotifier("TOKEN", ["1", "2"], session=session)
    assert notifier.send("hello", b"\xff\xd8jpeg")
    assert [c[0] for c in session.calls] == [
        "https://api.telegram.org/botTOKEN/sendPhoto"
    ] * 2
    assert [c[1]["chat_id"] for c in session.calls] == ["1", "2"]
    assert session.calls[0][1]["caption"] == "hello"
    assert session.calls[0][2]["photo"][1] == b"\xff\xd8jpeg"


def test_send_text_message():
    session = FakeSession()
    TelegramNotifier("TOKEN", ["1"], session=session).send("hi")
    url, data, files = session.calls[0]
    assert (
        url.endswith("/sendMessage")
        and data == {"chat_id": "1", "text": "hi"}
        and files is None
    )


def test_api_error_is_reported_not_raised():
    session = FakeSession(
        FakeResponse(400, {"ok": False, "description": "chat not found"})
    )
    assert TelegramNotifier("TOKEN", ["1"], session=session).send("hi") is False


def test_network_error_does_not_leak_token(caplog):
    session = FakeSession(
        exc=requests.ConnectionError("https://api.telegram.org/botSECRET/x")
    )
    assert TelegramNotifier("SECRET", ["1"], session=session).send("hi") is False
    assert "SECRET" not in caplog.text


def test_send_async():
    session = FakeSession()
    notifier = TelegramNotifier("TOKEN", ["1"], session=session)
    assert notifier.send_async("hi").result(timeout=5) is True
    notifier.close()


def test_from_env(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert TelegramNotifier.from_env() is None
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " 1, 2 ,")
    assert TelegramNotifier.from_env().chat_ids == ["1", "2"]

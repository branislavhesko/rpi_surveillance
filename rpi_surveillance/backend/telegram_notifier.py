"""Minimal Telegram Bot API client for sending alerts.

Configured from ``.env`` via ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID``
(comma-separated for several chats). Uses plain HTTPS calls so no extra SDK is
needed.
"""

import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor

import requests

from rpi_surveillance.config import load_env

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_ids: list[str],
        timeout: float = 15.0,
        session: requests.Session | None = None,
    ):
        if not token:
            raise ValueError("Telegram bot token is required")
        if not chat_ids:
            raise ValueError("At least one Telegram chat id is required")
        self._token = token
        self.chat_ids = list(chat_ids)
        self.timeout = timeout
        self._session = session or requests.Session()
        # One worker keeps alerts ordered and off the caller's thread.
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="telegram"
        )

    @classmethod
    def from_env(cls) -> "TelegramNotifier | None":
        """Build a notifier from the environment, or ``None`` if not configured."""
        load_env()
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        raw_ids = os.environ.get("TELEGRAM_CHAT_ID", "").split(",")
        chat_ids = [c.strip() for c in raw_ids if c.strip()]
        if not token or not chat_ids:
            logger.warning(
                "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset; Telegram alerts disabled"
            )
            return None
        return cls(token, chat_ids)

    def _call(self, method: str, data: dict, files: dict | None = None) -> None:
        url = API_URL.format(token=self._token, method=method)
        try:
            resp = self._session.post(url, data=data, files=files, timeout=self.timeout)
        except requests.RequestException as e:
            # The exception text contains the URL, i.e. the bot token.
            name = type(e).__name__
            raise RuntimeError(f"Telegram {method} request failed: {name}") from None
        if resp.status_code != 200:
            try:
                description = resp.json().get("description", resp.text)
            except ValueError:
                description = resp.text
            raise RuntimeError(
                f"Telegram {method} failed ({resp.status_code}): {description}"
            )

    def send(self, text: str, image_jpeg: bytes | None = None) -> bool:
        """Send ``text`` to every chat, as a photo caption if ``image_jpeg`` is set.

        Returns ``True`` if every chat received the message. Errors are logged,
        never raised, so a flaky network can't take down the caller.
        """
        ok = True
        for chat_id in self.chat_ids:
            try:
                if image_jpeg is not None:
                    self._call(
                        "sendPhoto",
                        data={"chat_id": chat_id, "caption": text[:1024]},
                        files={"photo": ("snapshot.jpg", image_jpeg, "image/jpeg")},
                    )
                else:
                    self._call(
                        "sendMessage", data={"chat_id": chat_id, "text": text[:4096]}
                    )
            except Exception as e:
                ok = False
                logger.error(f"Telegram notification to chat {chat_id} failed: {e}")
        return ok

    def send_async(self, text: str, image_jpeg: bytes | None = None) -> Future:
        """Queue :meth:`send` on a background thread."""
        return self._executor.submit(self.send, text, image_jpeg)

    def close(self) -> None:
        self._executor.shutdown(wait=False)

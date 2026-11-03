from typing import Protocol


class NotificationSender(Protocol):
    def send(self, content: str, idempotency_key: str) -> None: ...

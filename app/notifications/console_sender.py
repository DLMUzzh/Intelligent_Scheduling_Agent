import logging

logger = logging.getLogger('scheduling.notifications')


class ConsoleSender:
    def send(self, content: str, idempotency_key: str) -> None:
        logger.info('模拟通知 [%s]\n%s', idempotency_key, content)

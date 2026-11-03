from typing import Any


class BusinessError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, details: Any = None):
        self.code = code
        self.message = message
        self.status = status
        self.details = details
        super().__init__(message)

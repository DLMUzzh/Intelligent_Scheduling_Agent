from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def business_date() -> date:
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()

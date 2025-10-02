import datetime as dt
from typing import Optional, Tuple, cast

try:
    from dateutil import parser as dateutil_parser  # optional
except Exception:
    dateutil_parser = None


class TimeParseError(ValueError):
    pass


def parse_dt_flexible(s: str) -> dt.datetime:
    s = s.strip().replace("T", " ")
    # Try strict formats first
    fmts = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    )
    for fmt in fmts:
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            pass
    # Z suffix (UTC)
    if s.endswith("Z"):
        s2 = s[:-1]
        for fmt in fmts:
            try:
                return dt.datetime.strptime(s2, fmt).replace(tzinfo=dt.timezone.utc).astimezone(tz=None).replace(tzinfo=None)
            except ValueError:
                pass
    # Fallback: dateutil if available
    if dateutil_parser is not None:
        try:
            dv = dateutil_parser.parse(s)
            if dv.tzinfo:
                return cast(dt.datetime, dv.astimezone(tz=None).replace(tzinfo=None))
            return cast(dt.datetime, dv)
        except Exception:
            pass
    raise TimeParseError(f"Invalid datetime format: {s}. Use 'YYYY-MM-DD HH:MM:SS' or ISO-like.")


def parse_start_and_window(start_str: str, minutes: Optional[int], end_str: Optional[str]) -> Tuple[dt.datetime, dt.datetime]:
    if (minutes is None) == (end_str is None):
        raise TimeParseError("Provide either --minutes or --end, not both.")
    start = parse_dt_flexible(start_str)
    if end_str:
        end = parse_dt_flexible(end_str)
        if end.date() != start.date():
            raise TimeParseError("Window crosses midnight. Choose a window within a single calendar day.")
    else:
        assert minutes is not None
        mins = int(minutes)
        end = start + dt.timedelta(minutes=mins)
        # Clamp to end-of-day if duration crosses midnight
        if end.date() != start.date():
            end = dt.datetime.combine(start.date(), dt.time(23, 59, 59, 999999))
    return start, end

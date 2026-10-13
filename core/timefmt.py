"""Myanmar Standard Time, formatted the way it is actually spoken.

WHY THIS IS NOT JUST datetime.now()
    The app used to announce whatever the machine's clock said, in English, and
    leave the model to translate it into Burmese. Three things went wrong, and
    all three looked identical from the outside — "JARVIS said the wrong time":

      1. A machine set to the wrong timezone says the wrong hour, confidently.
      2. "Saturday, September 26, 2026 — 11:59 AM" has to be converted to
         Burmese numerals and month names by the model, and that conversion is
         not reliable.
      3. The clock was read once, when the session opened, and never again. An
         hour into a conversation the model still believes the time it was told
         at the start.

    So: the zone is pinned rather than trusted (1), the string is built here in
    Burmese rather than left to the model (2), and the model can ask again at
    any moment through the get_current_time tool (3).

WHY A FIXED OFFSET AND NOT zoneinfo("Asia/Yangon")
    Myanmar has never observed daylight saving; it has been UTC+6:30 without
    interruption. A constant cannot drift, and it does not depend on a tz
    database — which Windows does not ship, so zoneinfo would need the tzdata
    package installed to resolve the zone at all. A dependency that can silently
    fail is a poor foundation for the one thing that must never be wrong.
"""
from datetime import datetime, timedelta, timezone

MMT = timezone(timedelta(hours=6, minutes=30), name="MMT")

_MONTHS = (
    "ဇန်နဝါရီ", "ဖေဖော်ဝါရီ", "မတ်", "ဧပြီ", "မေ", "ဇွန်",
    "ဇူလိုင်", "ဩဂုတ်", "စက်တင်ဘာ", "အောက်တိုဘာ", "နိုဝင်ဘာ", "ဒီဇင်ဘာ",
)

# Indexed by datetime.weekday(): Monday is 0.
_WEEKDAYS = (
    "တနင်္လာ", "အင်္ဂါ", "ဗုဒ္ဓဟူး", "ကြာသပတေး", "သောကြာ", "စနေ", "တနင်္ဂနွေ",
)

_DIGITS = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")


def to_burmese_digits(value) -> str:
    """1234 -> ၁၂၃၄"""
    return str(value).translate(_DIGITS)


def now_mmt() -> datetime:
    """The current moment, in Myanmar Standard Time, whatever the PC thinks."""
    return datetime.now(MMT)


def burmese_date(dt: datetime) -> str:
    """'၂၀၂၆ ခုနှစ် စက်တင်ဘာ ၂၆ ရက် စနေနေ့'"""
    return (f"{to_burmese_digits(dt.year)} ခုနှစ် "
            f"{_MONTHS[dt.month - 1]} {to_burmese_digits(dt.day)} ရက် "
            f"{_WEEKDAYS[dt.weekday()]}နေ့")


def burmese_month_day(dt: datetime) -> str:
    """'စက်တင်ဘာ ၂၆ ရက်နေ့' — month and day only.

    The greeting says "ဒီနေ့ကတော့ စက်တင်ဘာ ၂၆ ရက်နေ့ပါ" — naming the year and
    the weekday there would be answering a question nobody asked, so this is a
    separate formatter rather than a flag on burmese_date().
    """
    return f"{_MONTHS[dt.month - 1]} {to_burmese_digits(dt.day)} ရက်နေ့"


def burmese_clock(dt: datetime) -> str:
    """'မွန်းတည့် ၁၂ နာရီ ၀၅ မိနစ်'

    The day is split the way Burmese splits it rather than by AM/PM: the
    Burmese words for morning, noon, afternoon, evening and night are what a
    listener needs, and 12-hour AM/PM has no natural Burmese equivalent.
    """
    hour, minute = dt.hour, dt.minute
    if hour < 12:
        period = "နံနက်"
    elif hour == 12:
        period = "မွန်းတည့်"
    elif hour < 16:
        period = "မွန်းလွဲ"
    elif hour < 19:
        period = "ညနေ"
    else:
        period = "ည"
    return (f"{period} {to_burmese_digits(hour % 12 or 12)} နာရီ "
            f"{to_burmese_digits(f'{minute:02d}')} မိနစ်")


def describe(dt: datetime | None = None) -> str:
    """Date and time as one spoken Burmese line."""
    dt = dt or now_mmt()
    return f"{burmese_date(dt)}၊ မြန်မာစံတော်ချိန် {burmese_clock(dt)}"


def machine_readable(dt: datetime | None = None) -> str:
    """The same moment as ISO, for the model to quote if it needs precision."""
    dt = dt or now_mmt()
    return dt.strftime("%Y-%m-%d %H:%M")

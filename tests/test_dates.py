from datetime import date

import pytest
from conftest import TODAY

from tcal.dates import parse_date, parse_jump

# TODAY is Wednesday 2026-11-18


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("today", TODAY),
        (" Today ", TODAY),
        ("tomorrow", date(2026, 11, 19)),
        ("yesterday", date(2026, 11, 17)),
        ("thu", date(2026, 11, 19)),
        ("fri", date(2026, 11, 20)),
        ("Friday", date(2026, 11, 20)),
        ("sun", date(2026, 11, 22)),
        ("mon", date(2026, 11, 23)),
        ("wed", date(2026, 11, 25)),  # the next one, not today
        ("tues", date(2026, 11, 24)),
        ("+3d", date(2026, 11, 21)),
        ("-1d", date(2026, 11, 17)),
        ("-1w", date(2026, 11, 11)),
        ("+2w", date(2026, 12, 2)),
        ("+2m", date(2027, 1, 18)),
        ("-11m", date(2025, 12, 18)),
        ("+1y", date(2027, 11, 18)),
        ("next week", date(2026, 11, 25)),
        ("Next  Month", date(2026, 12, 18)),
        ("last month", date(2026, 10, 18)),
        ("next year", date(2027, 11, 18)),
        ("next fri", date(2026, 11, 27)),  # Friday of next week (Wed 18 -> 27, not 20)
        ("next monday", date(2026, 11, 23)),
        ("last wed", date(2026, 11, 11)),
        ("in 2 days", date(2026, 11, 20)),
        ("in 1 week", date(2026, 11, 25)),
        ("in 3 months", date(2027, 2, 18)),
        ("2026-12-24", date(2026, 12, 24)),
        ("2027-1-5", date(2027, 1, 5)),
        ("24.12.", date(2026, 12, 24)),
        ("24.12", date(2026, 12, 24)),
        ("1.2.", date(2026, 2, 1)),
        ("24.12.2027", date(2027, 12, 24)),
        ("dec 24", date(2026, 12, 24)),
        ("December 24", date(2026, 12, 24)),
        ("dec 24 2027", date(2027, 12, 24)),
        ("dec 24, 2027", date(2027, 12, 24)),
        ("24 dec", date(2026, 12, 24)),
        ("24 Sept", date(2026, 9, 24)),
        ("24 dec 2027", date(2027, 12, 24)),
        ("tonight", TODAY),
    ],
)
def test_parse_date(text: str, expected: date) -> None:
    assert parse_date(text, TODAY) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "soon",
        "fr",
        "frx",
        "+3",
        "3d",
        "+3x",
        "2026-13-01",
        "2026-02-30",
        "31.11.",
        "30 feb",
        "dec",
        "dec 32",
        "24 de",
        "24 foo",
        "12/24",
    ],
)
def test_parse_date_rejects(text: str) -> None:
    assert parse_date(text, TODAY) is None


def test_relative_months_clamp() -> None:
    assert parse_date("+1m", date(2027, 1, 31)) == date(2027, 2, 28)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("fri", date(2026, 11, 20)),
        ("dec", date(2026, 12, 1)),
        ("January 2027", date(2027, 1, 1)),
        ("jan 2027", date(2027, 1, 1)),
        ("2027", date(2027, 1, 1)),
        ("12/24", date(2026, 12, 24)),
        ("24/12", date(2026, 12, 24)),
        ("1/5/2027", date(2027, 1, 5)),
    ],
)
def test_parse_jump_takes_months_years_and_slashes(text: str, expected: date) -> None:
    assert parse_jump(text, TODAY) == expected


@pytest.mark.parametrize("text", ["foo", "foo 2027", "13/13", "99999"])
def test_parse_jump_rejects(text: str) -> None:
    assert parse_jump(text, TODAY) is None

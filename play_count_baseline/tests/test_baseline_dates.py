"""baseline_map.local_to_unix: Music.app's wall-clock date parts as exact Unix seconds.

The parts are local wall-clock time, so the offset that applies is the one in force on
that date. Each expected value below is written as a literal, worked out from the UTC
wall clock (New York noon is 17:00 UTC in standard time and 16:00 UTC in daylight time),
so a wrong offset on either side of a transition fails rather than agreeing with itself.
A wall-clock time inside the spring-forward gap and one inside the fall-back fold are
pinned too, with the zone named and again with no zone and the process's ``TZ`` set to
the same zone, so the machine's own rules are held to the same literals.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import baseline_map as bm  # noqa: E402 - import follows the sys.path bootstrap above

#: A zone with both transitions, named rather than the machine's, so the test is fixed.
_NEW_YORK = ZoneInfo("America/New_York")
#: Noon, in seconds after midnight, the parts' last field.
_NOON = 43200
#: 02:30 on the spring-forward day, a wall-clock time New York skips, and the first
#: reading's Unix seconds: the offset before the gap, standard time, so 07:30 UTC.
_IN_THE_GAP = "2024/3/10/9000"
_IN_THE_GAP_AT = 1710055800
#: 01:30 on the fall-back day, a wall-clock time New York reads twice, and the first
#: reading's Unix seconds: the earlier, daylight-time one, so 05:30 UTC.
_IN_THE_FOLD = "2024/11/3/5400"
_IN_THE_FOLD_AT = 1730611800
#: POSIX's re-read of ``TZ``, looked up by name: Windows has none, and the type checker
#: may check for it, so the class that needs it skips there.
_TZSET: Callable[[], None] | None = getattr(time, "tzset", None)


class LocalToUnixTest(unittest.TestCase):
    """`local_to_unix` applies the offset in force on the parts' own date."""

    def _at_noon(self, date: str) -> int | None:
        return bm.local_to_unix(f"{date}/{_NOON}", zone=_NEW_YORK)

    def test_the_day_before_spring_forward_is_standard_time(self) -> None:
        self.assertEqual(self._at_noon("2024/3/9"), 1710003600)

    def test_the_day_after_spring_forward_is_daylight_time(self) -> None:
        self.assertEqual(self._at_noon("2024/3/11"), 1710172800)

    def test_the_day_before_fall_back_is_daylight_time(self) -> None:
        self.assertEqual(self._at_noon("2024/11/2"), 1730563200)

    def test_the_day_after_fall_back_is_standard_time(self) -> None:
        self.assertEqual(self._at_noon("2024/11/4"), 1730739600)

    def test_seconds_after_midnight_become_hours_minutes_and_seconds(self) -> None:
        # 12:34:56 on the day after spring forward, daylight time.
        self.assertEqual(
            bm.local_to_unix("2024/3/11/45296", zone=_NEW_YORK), 1710174896
        )

    def test_a_time_in_the_spring_forward_gap_reads_as_standard_time(self) -> None:
        self.assertEqual(bm.local_to_unix(_IN_THE_GAP, zone=_NEW_YORK), _IN_THE_GAP_AT)

    def test_a_time_in_the_fall_back_fold_reads_as_its_first_daylight_time(
        self,
    ) -> None:
        self.assertEqual(
            bm.local_to_unix(_IN_THE_FOLD, zone=_NEW_YORK), _IN_THE_FOLD_AT
        )

    def test_no_date_gives_none(self) -> None:
        self.assertIsNone(bm.local_to_unix("", zone=_NEW_YORK))

    def test_malformed_parts_give_none(self) -> None:
        for parts in (
            "2024/13/1/0",
            "x",
            "2024/1/1",
            "2024/2/30/0",
            "0/1/1/0",
            "2024/1/1/86400",
            "2024/1/1/0/0",
            "2024/1/1/0\n",
            # A fullwidth digit two, which a ``\d`` pattern would accept as a digit.
            "２024/1/1/0",
        ):
            with self.subTest(parts=parts):
                self.assertIsNone(bm.local_to_unix(parts, zone=_NEW_YORK))

    def test_the_last_second_of_a_day_is_accepted(self) -> None:
        self.assertEqual(bm.local_to_unix("2024/3/9/86399", zone=_NEW_YORK), 1710046799)


@unittest.skipIf(_TZSET is None, "time.tzset is POSIX-only")
class MachineZoneTest(unittest.TestCase):
    """With no zone, the process's own ``TZ`` decides, set here to New York."""

    def setUp(self) -> None:
        """Point the process at New York; restore its zone, and re-read it, after."""
        tzset = _TZSET
        assert tzset is not None  # the class skips where it is absent
        # Cleanups run last first: the patch is undone, then the zone is re-read.
        self.addCleanup(tzset)
        patcher = mock.patch.dict(os.environ, {"TZ": "America/New_York"})
        patcher.start()
        self.addCleanup(patcher.stop)
        tzset()

    def test_standard_and_daylight_time_follow_the_machine_s_zone(self) -> None:
        self.assertEqual(bm.local_to_unix(f"2024/3/9/{_NOON}"), 1710003600)
        self.assertEqual(bm.local_to_unix(f"2024/11/2/{_NOON}"), 1730563200)

    def test_the_gap_and_the_fold_read_as_they_do_with_a_named_zone(self) -> None:
        self.assertEqual(bm.local_to_unix(_IN_THE_GAP), _IN_THE_GAP_AT)
        self.assertEqual(bm.local_to_unix(_IN_THE_FOLD), _IN_THE_FOLD_AT)


if __name__ == "__main__":
    unittest.main()

"""Canonical calendar domain — WorldTick, CalendarDefinition, GameDate, CalendarService.

This module defines the Stage 4 calendar domain contracts.  It is a
domain-only module and must not import from:

    storage, models, retrieval, tools, application, cli, ollama

No filesystem access, YAML loading, campaign state persistence, or
current-world-state mutation.

Responsibility
──────────────
- WorldTick: canonical signed integer minute scalar.
- CalendarMonth / IntercalaryDay / CalendarHoliday: calendar component models.
- GameDate: display/calendar date value with regular and intercalary modes.
- CalendarDefinition: complete calendar configuration (months, intercalary
  days, holidays, hours/minutes per day).
- CalendarService: deterministic, stateless Protocol for world_tick ↔ date
  conversion and time arithmetic.

S4-01 — implemented in DeterministicCalendarService
────────────────────────────────────────────────────
- date_to_tick / tick_to_date.

S4-02 — implemented in DeterministicCalendarService
────────────────────────────────────────────────────
- advance_world_time / time_until.
- Signed elapsed-minute arithmetic on canonical WorldTick.
- No date round-trip in production arithmetic.
- No mutable current-world-time ownership.

Deferred to S4-03
─────────────────
- TimelineEvent query APIs (events_between, events_near, upcoming,
  overdue_events, time_until_event).

    TimelineEvent supports exact, approximate, range and unknown temporal
    certainty.  Event query semantics must explicitly define how interval
    overlap and unknown dates behave.  That decision belongs to S4-03.

    Do NOT casually treat every TimelineEvent as a single exact tick.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, BeforeValidator, Field, model_validator

# ── WorldTick ────────────────────────────────────────────────────────────────


def _validate_world_tick(value: object) -> int:
    """Validate a WorldTick value.

    WorldTick is a strict integer number of game minutes relative to the
    campaign epoch.  Negative values allow representation of dates before
    the campaign epoch.

    - negative, zero and positive ``int`` accepted
    - ``bool`` rejected
    - ``str`` rejected
    - ``float`` rejected
    """
    if isinstance(value, bool):
        raise ValueError("WorldTick must not be a bool")
    if not isinstance(value, int):
        raise ValueError(f"WorldTick must be an int, got {type(value).__name__}")
    return value


WorldTick = Annotated[
    int,
    BeforeValidator(_validate_world_tick),
    Field(
        strict=True,
        description="Canonical game-time value: integer minutes relative to campaign epoch",
    ),
]
"""Canonical game-time value.

``WorldTick`` is a strict signed integer representing the number of game
minutes relative to the campaign epoch.

- negative, zero and positive ``int`` accepted
- ``bool`` rejected
- ``str`` rejected
- ``float`` rejected
"""


# ── CalendarMonth ────────────────────────────────────────────────────────────


class CalendarMonth(BaseModel):
    """One named month in a calendar definition.

    Examples:
        ``CalendarMonth(name="Hammer", days=30)``
        ``CalendarMonth(name="Eleasis", days=31)``
        ``CalendarMonth(name="Первый Туман", days=29)``
    """

    name: str
    """Month name (non-empty, no surrounding whitespace, printable Unicode)."""

    days: int
    """Number of days in this month (integer >= 1)."""

    # ── Field validation ────────────────────────────────────────────────

    @model_validator(mode="before")
    @classmethod
    def _validate_name(cls, data: object) -> object:
        if isinstance(data, dict) and "name" in data:
            name = data["name"]
            if isinstance(name, bool):
                raise ValueError("CalendarMonth name must not be a bool")
            if not isinstance(name, str):
                raise ValueError(f"CalendarMonth name must be a string, got {type(name).__name__}")
            if not name:
                raise ValueError("CalendarMonth name must not be empty")
            if name.strip() != name:
                raise ValueError("CalendarMonth name must not have leading or trailing whitespace")
            if not name.isprintable():
                raise ValueError("CalendarMonth name must not contain non-printable characters")
        return data

    @model_validator(mode="before")
    @classmethod
    def _validate_days(cls, data: object) -> object:
        if isinstance(data, dict) and "days" in data:
            days = data["days"]
            if isinstance(days, bool):
                raise ValueError("CalendarMonth days must not be a bool")
            if not isinstance(days, int):
                raise ValueError(f"CalendarMonth days must be an int, got {type(days).__name__}")
            if days < 1:
                raise ValueError(f"CalendarMonth days must be >= 1, got {days}")
        return data

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }


# ── IntercalaryDay ───────────────────────────────────────────────────────────


class IntercalaryDay(BaseModel):
    """One named intercalary day inserted after a declared month.

    An intercalary day represents one named day that occurs once per
    calendar year, outside that month's numbered days.

    Examples:
        ``IntercalaryDay(name="Midwinter", after_month="Hammer")``
        ``IntercalaryDay(name="Shieldmeet", after_month="Eleasis")``
    """

    name: str
    """Intercalary day name (non-empty, no surrounding whitespace, printable)."""

    after_month: str
    """The month after which this intercalary day occurs (must match a declared month)."""

    # ── Field validation ────────────────────────────────────────────────

    @model_validator(mode="before")
    @classmethod
    def _validate_name(cls, data: object) -> object:
        if isinstance(data, dict) and "name" in data:
            name = data["name"]
            if isinstance(name, bool):
                raise ValueError("IntercalaryDay name must not be a bool")
            if not isinstance(name, str):
                raise ValueError(f"IntercalaryDay name must be a string, got {type(name).__name__}")
            if not name:
                raise ValueError("IntercalaryDay name must not be empty")
            if name.strip() != name:
                raise ValueError("IntercalaryDay name must not have leading or trailing whitespace")
            if not name.isprintable():
                raise ValueError("IntercalaryDay name must not contain non-printable characters")
        return data

    @model_validator(mode="before")
    @classmethod
    def _validate_after_month(cls, data: object) -> object:
        if isinstance(data, dict) and "after_month" in data:
            after = data["after_month"]
            if isinstance(after, bool):
                raise ValueError("IntercalaryDay after_month must not be a bool")
            if not isinstance(after, str):
                raise ValueError(
                    f"IntercalaryDay after_month must be a string, got {type(after).__name__}"
                )
            if not after:
                raise ValueError("IntercalaryDay after_month must not be empty")
            if after.strip() != after:
                raise ValueError(
                    "IntercalaryDay after_month must not have leading or trailing whitespace"
                )
            if not after.isprintable():
                raise ValueError(
                    "IntercalaryDay after_month must not contain non-printable characters"
                )
        return data

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }


# ── CalendarHoliday ─────────────────────────────────────────────────────────


class CalendarHoliday(BaseModel):
    """An annual holiday label associated with a calendar date.

    Holidays are labels — they MUST NOT affect elapsed-time arithmetic
    unless that date is separately represented as an intercalary day.

    Exactly one target form must be valid:
    - Regular holiday: ``month`` + ``day``
    - Intercalary holiday: ``intercalary_day``

    No year field: holidays recur annually in the v0.1 schema.

    Examples:
        ``CalendarHoliday(name="Midwinter Holiday", month="Hammer", day=1)``
        ``CalendarHoliday(name="Shieldmeet", intercalary_day="Shieldmeet")``
    """

    name: str
    """Holiday name (non-empty, no surrounding whitespace, printable)."""

    month: str | None = None
    """Month name for a regular holiday."""

    day: int | None = None
    """Day of month for a regular holiday."""

    intercalary_day: str | None = None
    """Intercalary day name for an intercalary holiday."""

    # ── Target-shape validation ─────────────────────────────────────────

    @model_validator(mode="after")
    def _validate_target_shape(self) -> CalendarHoliday:
        """Validate that exactly one target form (month+day or intercalary) is set."""
        has_regular = self.month is not None or self.day is not None
        has_intercalary = self.intercalary_day is not None

        if self.month is not None and self.day is None:
            raise ValueError("day is required when month is set")

        if self.day is not None and self.month is None:
            raise ValueError("month is required when day is set")

        if has_regular and has_intercalary:
            raise ValueError(
                "month+day and intercalary_day must not both be set; use exactly one target form"
            )

        if not has_regular and not has_intercalary:
            raise ValueError("exactly one target form required: month+day or intercalary_day")

        return self

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }


# ── GameDate ─────────────────────────────────────────────────────────────────


class GameDate(BaseModel):
    """Display/calendar date value.

    Supports two mutually exclusive modes:

    Regular date mode::
        ``month`` is set, ``day`` is set and >= 1, ``intercalary_day`` is None

    Intercalary date mode::
        ``intercalary_day`` is set, ``month`` is None, ``day`` is None

    ``GameDate`` itself cannot know which month names exist or how long a
    month is.  Those definition-dependent checks belong to
    ``CalendarDefinition`` / future ``CalendarService`` validation.

    Examples:
        ``GameDate(year=1492, month="Hammer", day=1, hour=0, minute=0)``

        ``GameDate(year=1492, intercalary_day="Midwinter", hour=12, minute=30)``
    """

    year: int
    """Campaign year (strict integer, negative/zero/positive accepted)."""

    month: str | None = None
    """Month name for a regular date."""

    day: int | None = None
    """Day of month for a regular date (>= 1 when set)."""

    intercalary_day: str | None = None
    """Intercalary day name for an intercalary date."""

    hour: int = 0
    """Hour of day (>= 0)."""

    minute: int = 0
    """Minute of hour (>= 0)."""

    # ── Field-level validation ──────────────────────────────────────────

    @model_validator(mode="before")
    @classmethod
    def _validate_year(cls, data: object) -> object:
        if isinstance(data, dict) and "year" in data:
            year = data["year"]
            if isinstance(year, bool):
                raise ValueError("GameDate year must not be a bool")
            if not isinstance(year, int):
                raise ValueError(f"GameDate year must be an int, got {type(year).__name__}")
        return data

    @model_validator(mode="before")
    @classmethod
    def _validate_hour_minute_primitives(cls, data: object) -> object:
        if isinstance(data, dict):
            for field, label in [("hour", "hour"), ("minute", "minute")]:
                if field in data:
                    val = data[field]
                    if isinstance(val, bool):
                        raise ValueError(f"GameDate {label} must not be a bool")
                    if not isinstance(val, int):
                        raise ValueError(
                            f"GameDate {label} must be an int, got {type(val).__name__}"
                        )
                    if val < 0:
                        raise ValueError(f"GameDate {label} must be >= 0, got {val}")
        return data

    @model_validator(mode="after")
    def _validate_date_shape(self) -> GameDate:
        """Validate that the date shape is either regular or intercalary, not mixed."""
        has_month = self.month is not None
        has_day = self.day is not None
        has_intercalary = self.intercalary_day is not None

        if has_intercalary:
            if has_month or has_day:
                raise ValueError("intercalary_day must not be combined with month or day")
            return self

        # Regular date mode
        if not has_month and not has_day:
            raise ValueError("either month+day or intercalary_day is required")
        if has_month and not has_day:
            raise ValueError("day is required when month is set")
        if has_day and not has_month:
            raise ValueError("month is required when day is set")

        # day >= 1 validation
        if self.day is not None and self.day < 1:
            raise ValueError(f"GameDate day must be >= 1, got {self.day}")

        return self

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }


# ── CalendarDefinition ───────────────────────────────────────────────────────


def _validate_printable_nonempty(value: object, label: str = "value") -> str:
    """Validate a non-empty printable string."""
    if isinstance(value, bool):
        raise ValueError(f"{label} must not be a bool")
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{label} must not be empty")
    if value.strip() != value:
        raise ValueError(f"{label} must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError(f"{label} must not contain non-printable characters")
    return value


def _validate_hours_or_minutes(value: object, label: str) -> int:
    """Validate hours_per_day or minutes_per_hour."""
    if isinstance(value, bool):
        raise ValueError(f"{label} must not be a bool")
    if not isinstance(value, int):
        raise ValueError(f"{label} must be an int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{label} must be >= 1, got {value}")
    return value


class CalendarDefinition(BaseModel):
    """Complete definition of a campaign calendar.

    ``CalendarDefinition`` is generic and Gregorian-independent.  Month
    names, lengths, intercalary days, holidays, hours per day and minutes
    per hour are all configurable.

    Validation checks:
    - At least one month required.
    - Month names unique (case-insensitive).
    - Intercalary names unique (case-insensitive).
    - Month and intercalary names must not collide (case-insensitive).
    - ``IntercalaryDay.after_month`` must reference an existing month exactly.
    - ``hours_per_day`` >= 1, ``minutes_per_hour`` >= 1.
    - Epoch validated against definition.
    - Holiday references validated against definition.
    """

    schema_version: Literal[1] = 1
    """Schema version for migration detection.  Currently always 1."""

    calendar_id: str
    """Unique calendar identifier (non-empty, printable, no surrounding whitespace)."""

    epoch: GameDate
    """The campaign epoch date (tick 0)."""

    months: tuple[CalendarMonth, ...]
    """Ordered tuple of months in this calendar (at least one required)."""

    intercalary_days: tuple[IntercalaryDay, ...] = ()
    """Intercalary days inserted after specific months."""

    holidays: tuple[CalendarHoliday, ...] = ()
    """Annual holiday labels (do NOT affect elapsed-time arithmetic)."""

    hours_per_day: int = 24
    """Number of hours in a day (>= 1)."""

    minutes_per_hour: int = 60
    """Number of minutes in an hour (>= 1)."""

    # ── Pre-construction validators ─────────────────────────────────────

    @model_validator(mode="before")
    @classmethod
    def _validate_primitives(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        if "calendar_id" in data:
            _validate_printable_nonempty(data["calendar_id"], label="calendar_id")

        if "hours_per_day" in data:
            _validate_hours_or_minutes(data["hours_per_day"], label="hours_per_day")

        if "minutes_per_hour" in data:
            _validate_hours_or_minutes(data["minutes_per_hour"], label="minutes_per_hour")

        return data

    @model_validator(mode="after")
    def _validate_structure(self) -> CalendarDefinition:
        """Validate structural constraints that require full model access."""
        # At least one month
        if not self.months:
            raise ValueError("CalendarDefinition must have at least one month")

        # Unique month names (case-insensitive)
        month_names_lower = [m.name.casefold() for m in self.months]
        if len(month_names_lower) != len(set(month_names_lower)):
            raise ValueError("CalendarDefinition month names must be unique (case-insensitive)")

        # Unique intercalary names (case-insensitive)
        intercalary_names_lower = [d.name.casefold() for d in self.intercalary_days]
        if len(intercalary_names_lower) != len(set(intercalary_names_lower)):
            raise ValueError(
                "CalendarDefinition intercalary day names must be unique (case-insensitive)"
            )

        # Month and intercalary names must not collide
        if set(month_names_lower) & set(intercalary_names_lower):
            raise ValueError("CalendarDefinition month and intercalary day names must not collide")

        # Build lookup maps
        month_map = {m.name: m for m in self.months}
        intercalary_names = {d.name for d in self.intercalary_days}

        # IntercalaryDay.after_month must reference an existing month exactly
        for ic in self.intercalary_days:
            if ic.after_month not in month_map:
                raise ValueError(
                    f"IntercalaryDay after_month '{ic.after_month}' "
                    f"does not match any declared month"
                )

        # Validate epoch
        self._validate_date_against_definition(
            self.epoch,
            month_map,
            intercalary_names=intercalary_names,
            hours_per_day=self.hours_per_day,
            minutes_per_hour=self.minutes_per_hour,
            label="epoch",
        )

        # Validate holidays
        for h in self.holidays:
            if h.intercalary_day is not None:
                intercalary_names = {d.name for d in self.intercalary_days}
                if h.intercalary_day not in intercalary_names:
                    raise ValueError(
                        f"Holiday intercalary_day '{h.intercalary_day}' "
                        f"does not match any declared intercalary day"
                    )
            else:
                assert h.month is not None and h.day is not None
                if h.month not in month_map:
                    raise ValueError(f"Holiday month '{h.month}' does not match any declared month")
                if h.day < 1 or h.day > month_map[h.month].days:
                    raise ValueError(
                        f"Holiday day {h.day} is out of range for month "
                        f"'{h.month}' (1-{month_map[h.month].days})"
                    )

        return self

    @staticmethod
    def _validate_date_against_definition(
        date: GameDate,
        month_map: dict[str, CalendarMonth],
        *,
        intercalary_names: set[str] | None = None,
        hours_per_day: int = 24,
        minutes_per_hour: int = 60,
        label: str,
    ) -> None:
        """Validate a GameDate against this calendar definition.

        Validates month/day (regular dates), intercalary day name
        (intercalary dates), and time-of-day components.
        """
        if date.intercalary_day is not None:
            if intercalary_names is not None and date.intercalary_day not in intercalary_names:
                raise ValueError(
                    f"{label} intercalary_day '{date.intercalary_day}' "
                    f"does not match any declared intercalary day"
                )
        else:
            assert date.month is not None
            if date.month not in month_map:
                raise ValueError(f"{label} month '{date.month}' does not match any declared month")
            month = month_map[date.month]
            if date.day is None or date.day < 1:
                raise ValueError(f"{label} day must be >= 1")
            if date.day > month.days:
                raise ValueError(
                    f"{label} day {date.day} exceeds month '{date.month}' length ({month.days})"
                )

        # Time-of-day validation
        if date.hour >= hours_per_day:
            raise ValueError(f"{label} hour {date.hour} must be < hours_per_day ({hours_per_day})")
        if date.minute >= minutes_per_hour:
            raise ValueError(
                f"{label} minute {date.minute} must be < minutes_per_hour ({minutes_per_hour})"
            )

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }


# ── CalendarService Protocol ─────────────────────────────────────────────────


@runtime_checkable
class CalendarService(Protocol):
    """Deterministic, stateless calendar arithmetic protocol.

    ``CalendarService`` owns world_tick ↔ date conversion and time
    arithmetic.  It does NOT own campaign current-time persistence.

    S4-00 defines these signatures.  S4-01 implements
    ``date_to_tick`` / ``tick_to_date`` in ``DeterministicCalendarService``.
    S4-02 implements ``advance_world_time`` / ``time_until``.

    Deferred to S4-03:
    - TimelineEvent query APIs
    """

    @property
    def definition(self) -> CalendarDefinition:
        """Return the calendar definition this service is configured with."""
        ...

    def date_to_tick(self, date: GameDate) -> WorldTick:
        """Convert a ``GameDate`` to its canonical ``WorldTick``.

        Implemented in ``DeterministicCalendarService`` (S4-01).
        """
        ...

    def tick_to_date(self, tick: WorldTick) -> GameDate:
        """Convert a ``WorldTick`` to its canonical ``GameDate``.

        Implemented in ``DeterministicCalendarService`` (S4-01).
        """
        ...

    def advance_world_time(
        self,
        current_tick: WorldTick,
        *,
        minutes: int,
    ) -> WorldTick:
        """Advance from ``current_tick`` by ``minutes``.

        Implemented in S4-02.
        """
        ...

    def time_until(
        self,
        start_tick: WorldTick,
        end_tick: WorldTick,
    ) -> int:
        """Return the number of minutes between two ticks.

        Implemented in S4-02.
        """
        ...


# ── DeterministicCalendarService ────────────────────────────────────────────


class _CalendarLayout:
    """Immutable precomputed layout derived from a CalendarDefinition.

    Computed once at construction time.  All fields are derived from the
    definition and do not represent mutable campaign state.
    """

    __slots__ = (
        "minutes_per_day",
        "days_per_year",
        "_hours_per_day",
        "_minutes_per_hour",
        "_month_offsets",
        "_intercalary_offsets",
        "_day_index",
        "_month_map",
        "_intercalary_set",
        "_month_names_ordered",
        "_ic_names_ordered",
    )

    def __init__(self, definition: CalendarDefinition) -> None:
        self.minutes_per_day: int = definition.hours_per_day * definition.minutes_per_hour
        self.days_per_year: int = sum(m.days for m in definition.months) + len(
            definition.intercalary_days
        )
        self._hours_per_day: int = definition.hours_per_day
        self._minutes_per_hour: int = definition.minutes_per_hour

        # Build month map and intercalary set for validation
        self._month_map: dict[str, CalendarMonth] = {m.name: m for m in definition.months}
        self._intercalary_set: set[str] = {d.name for d in definition.intercalary_days}
        self._month_names_ordered: tuple[str, ...] = tuple(m.name for m in definition.months)
        self._ic_names_ordered: tuple[str, ...] = tuple(d.name for d in definition.intercalary_days)

        # Build the chronological day index for one year.
        # For each month in order: emit its numbered days, then emit any
        # intercalary days declared after that month (in declaration order).
        # This correctly handles multiple intercalary days after the same month.
        lookup: list[tuple[bool, str, int]] = []
        month_offsets: list[int] = []
        ic_offsets: list[int] = []
        for m in definition.months:
            month_offsets.append(len(lookup))
            for d in range(m.days):
                lookup.append((False, m.name, d + 1))
            # Emit intercalary days declared after this month
            for ic in definition.intercalary_days:
                if ic.after_month == m.name:
                    ic_offsets.append(len(lookup))
                    lookup.append((True, ic.name, 1))

        self._month_offsets: tuple[int, ...] = tuple(month_offsets)
        self._intercalary_offsets: tuple[int, ...] = tuple(ic_offsets)
        self._day_index: tuple[tuple[bool, str, int], ...] = tuple(lookup)

    def validate_date(self, date: GameDate, label: str = "date") -> None:
        """Validate a GameDate against the calendar definition."""
        if date.intercalary_day is not None:
            if date.intercalary_day not in self._intercalary_set:
                raise ValueError(
                    f"{label} intercalary_day '{date.intercalary_day}' "
                    f"does not match any declared intercalary day"
                )
        else:
            assert date.month is not None
            if date.month not in self._month_map:
                raise ValueError(f"{label} month '{date.month}' does not match any declared month")
            month = self._month_map[date.month]
            if date.day is None or date.day < 1:
                raise ValueError(f"{label} day must be >= 1")
            if date.day > month.days:
                raise ValueError(
                    f"{label} day {date.day} exceeds month '{date.month}' length ({month.days})"
                )

        # Time-of-day validation
        if date.hour < 0:
            raise ValueError(f"{label} hour must be >= 0")
        if date.hour >= self._hours_per_day:
            raise ValueError(
                f"{label} hour {date.hour} must be < hours_per_day ({self._hours_per_day})"
            )
        if date.minute < 0:
            raise ValueError(f"{label} minute must be >= 0")
        if date.minute >= self._minutes_per_hour:
            raise ValueError(
                f"{label} minute {date.minute} must be < minutes_per_hour ({self._minutes_per_hour})"
            )

    def _day_index_offset(self, date: GameDate) -> int:
        """Return zero-based day offset of date within its year."""
        if date.intercalary_day is not None:
            ic_idx = self._ic_names_ordered.index(date.intercalary_day)
            return self._intercalary_offsets[ic_idx]
        # Regular date
        month_idx = self._month_names_ordered.index(date.month)  # type: ignore[arg-type]
        return self._month_offsets[month_idx] + (date.day - 1)  # type: ignore[operator]


class DeterministicCalendarService:
    """Deterministic, stateless calendar conversion and arithmetic service.

    Converts between ``GameDate`` and ``WorldTick`` using direct ordinal
    arithmetic (S4-01).  Provides elapsed-minute arithmetic via
    ``advance_world_time`` and ``time_until`` (S4-02).

    Complexity depends only on calendar-definition size, not on year or
    tick magnitude.

    The service is stateless with respect to campaign current time.
    Mutable world-tick persistence belongs to the application layer.
    """

    def __init__(self, definition: CalendarDefinition) -> None:
        self._definition = definition
        self._layout = _CalendarLayout(definition)
        self._minutes_per_day = self._layout.minutes_per_day
        self._days_per_year = self._layout.days_per_year

        # Precompute epoch reference
        self._epoch_year = definition.epoch.year
        self._epoch_day_offset = self._layout._day_index_offset(definition.epoch)
        self._epoch_minute_of_day = (
            definition.epoch.hour * definition.minutes_per_hour + definition.epoch.minute
        )

    @property
    def definition(self) -> CalendarDefinition:
        """Return the calendar definition this service is configured with."""
        return self._definition

    @staticmethod
    def _validate_minutes(value: object) -> int:
        """Validate a signed integer minute amount.

        - negative, zero and positive ``int`` accepted
        - ``bool`` rejected
        - ``str`` rejected
        - ``float`` rejected
        """
        if isinstance(value, bool):
            raise ValueError("minutes must not be a bool")
        if not isinstance(value, int):
            raise ValueError(f"minutes must be an int, got {type(value).__name__}")
        return value

    def date_to_tick(self, date: GameDate) -> WorldTick:
        """Convert a ``GameDate`` to its canonical ``WorldTick``.

        Uses direct ordinal arithmetic: computes the absolute minute
        for the given date and subtracts the epoch absolute minute.

        Complexity: O(number of months + number of intercalary days),
        not O(abs(year)) or O(abs(tick)).
        """
        self._layout.validate_date(date, label="date")

        day_offset = self._layout._day_index_offset(date)
        minute_of_day = date.hour * self._definition.minutes_per_hour + date.minute

        # Absolute minute = year * days_per_year * minutes_per_day
        #                 + day_offset * minutes_per_day
        #                 + minute_of_day
        abs_minute = (
            date.year * self._days_per_year * self._minutes_per_day
            + day_offset * self._minutes_per_day
            + minute_of_day
        )

        epoch_abs_minute = (
            self._epoch_year * self._days_per_year * self._minutes_per_day
            + self._epoch_day_offset * self._minutes_per_day
            + self._epoch_minute_of_day
        )

        return WorldTick(abs_minute - epoch_abs_minute)

    def tick_to_date(self, tick: WorldTick) -> GameDate:
        """Convert a ``WorldTick`` to its canonical ``GameDate``.

        Uses divmod-based inverse ordinal arithmetic.

        Complexity: O(number of months + number of intercalary days),
        not O(abs(year)) or O(abs(tick)).
        """
        _validate_world_tick(tick)

        # Absolute minute = epoch absolute minute + tick
        epoch_abs_minute = (
            self._epoch_year * self._days_per_year * self._minutes_per_day
            + self._epoch_day_offset * self._minutes_per_day
            + self._epoch_minute_of_day
        )
        abs_minute = epoch_abs_minute + tick

        # Floor-divide to get year and remainder
        minutes_per_year = self._days_per_year * self._minutes_per_day
        year, remainder = divmod(abs_minute, minutes_per_year)

        # remainder is minutes within the year
        day_offset, minute_of_day = divmod(remainder, self._minutes_per_day)

        # Look up day in the day index
        is_intercalary, name, day = self._layout._day_index[day_offset]

        hour, minute = divmod(minute_of_day, self._definition.minutes_per_hour)

        if is_intercalary:
            return GameDate(
                year=year,
                intercalary_day=name,
                hour=hour,
                minute=minute,
            )
        else:
            return GameDate(
                year=year,
                month=name,
                day=day,
                hour=hour,
                minute=minute,
            )

    def advance_world_time(
        self,
        current_tick: WorldTick,
        *,
        minutes: int,
    ) -> WorldTick:
        """Advance from ``current_tick`` by ``minutes``.

        Elapsed-minute arithmetic on the canonical ``WorldTick`` scalar.
        The result is ``current_tick + minutes`` with no clamping, no
        date round-trip, and no calendar-boundary awareness — those
        boundaries are already encoded in the tick scalar.

        Parameters
        ----------
        current_tick:
            The current world tick (signed integer minutes).
        minutes:
            Signed integer number of game minutes to advance (negative
            for backward, zero for no change, positive for forward).

        Returns
        -------
        The new ``WorldTick`` after advancing by ``minutes``.
        """
        # Validate inputs using existing strict-integer helpers
        _validate_world_tick(current_tick)
        self._validate_minutes(minutes)

        return WorldTick(current_tick + minutes)

    def time_until(
        self,
        start_tick: WorldTick,
        end_tick: WorldTick,
    ) -> int:
        """Return the signed number of minutes between two ticks.

        ``end_tick - start_tick``.  A positive result means ``end_tick``
        is after ``start_tick``; a negative result means ``end_tick`` is
        before ``start_tick``; zero means they are the same tick.

        Parameters
        ----------
        start_tick:
            The starting world tick.
        end_tick:
            The ending world tick.

        Returns
        -------
        Signed integer difference in minutes.
        """
        _validate_world_tick(start_tick)
        _validate_world_tick(end_tick)

        return int(end_tick - start_tick)

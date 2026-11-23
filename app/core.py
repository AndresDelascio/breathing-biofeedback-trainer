"""Pure timing, protocol and pulse calculations; no GUI or serial dependency."""

from collections import deque
from dataclasses import dataclass
import json
import math
import statistics


@dataclass(frozen=True)
class Sample:
    t_ms: int
    ir: int
    red: int
    finger: bool
    beat: bool
    ibi_ms: int | None
    spo2: int | None = None
    resp_raw: int | None = None


def parse_sample(line: str) -> Sample | None:
    """Parse protocol v1. Ignore boot/info messages, reject malformed samples."""
    try:
        data = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("type") != "sample":
        return None
    if type(data.get("v")) is not int or data["v"] != 1:
        raise ValueError("Unsupported sample protocol version")
    for key, maximum in (("t_ms", 0xFFFFFFFF), ("ir", 262143), ("red", 262143)):
        value = data.get(key)
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError(f"Invalid {key}")
    if type(data.get("finger")) is not bool or type(data.get("beat")) is not bool:
        raise ValueError("finger and beat must be booleans")
    ibi = data.get("ibi_ms")
    if data["beat"]:
        if not data["finger"] or type(ibi) is not int or not 300 <= ibi <= 2000:
            raise ValueError("Beat requires contact and a 300–2000 ms interval")
    elif ibi is not None:
        raise ValueError("Non-beat samples must have a null interval")
    spo2 = data.get("spo2")
    if spo2 is not None and (type(spo2) is not int or not 70 <= spo2 <= 100 or not data["finger"]):
        raise ValueError("SpO2 requires contact and a 70–100% value, or null")
    resp = data.get("resp_raw")
    if resp is not None and (type(resp) is not int or not 0 <= resp <= 4095):
        raise ValueError("resp_raw must be a 12-bit ADC value or null")
    return Sample(data["t_ms"], data["ir"], data["red"], data["finger"], data["beat"], ibi, spo2, resp)


def parse_error(line: str) -> str | None:
    """Return the readable message of a firmware error packet, else None."""
    try:
        data = json.loads(line)
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict) and data.get("type") == "error":
        return str(data.get("message") or "Sensor error")[:200]
    return None


class DeviceClock:
    """Map the device's t_ms onto host monotonic seconds.

    USB delivers lines in bursts, so receipt time is jittery. The device clock is
    not. Anchor on the least-delayed packet seen so far: a packet that would map
    after its own receipt is faster than the anchor, so it becomes the anchor.
    A lag over 1 s means a device reset, a t_ms wrap or a long stall: re-anchor.
    ponytail: no drift model; at ~50 ppm crystal error the 1 s re-anchor fires every ~5 h.
    """

    def __init__(self):
        self.offset: float | None = None

    def clear(self):
        self.offset = None

    def to_host(self, t_ms: int, received_at: float) -> float:
        t = t_ms / 1000
        if self.offset is None or not 0 <= received_at - (t + self.offset) <= 1:
            self.offset = received_at - t
        return t + self.offset


@dataclass(frozen=True)
class Settings:
    inhale: float = 4.0
    exhale: float = 6.0
    minutes: float = 5.0

    def __post_init__(self):
        for name, low, high in (("inhale", 2, 10), ("exhale", 2, 10), ("minutes", 0.5, 30)):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name.capitalize()} must be between {low} and {high}.")

    @property
    def breaths_per_minute(self) -> float:
        return 60 / (self.inhale + self.exhale)

    def phase(self, elapsed: float) -> tuple[str, float, float]:
        """Return phase, smooth circle expansion [0,1], seconds left in phase."""
        position = max(0.0, elapsed) % (self.inhale + self.exhale)
        if position < self.inhale:
            progress = position / self.inhale
            return "Inhale", (1 - math.cos(math.pi * progress)) / 2, self.inhale - position
        progress = (position - self.inhale) / self.exhale
        return "Exhale", (1 + math.cos(math.pi * progress)) / 2, self.exhale * (1 - progress)


class Session:
    """Monotonic clock: paused time is excluded and completion is bounded."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.accumulated = 0.0
        self.started_at: float | None = None

    @property
    def running(self) -> bool:
        return self.started_at is not None

    def elapsed(self, now: float) -> float:
        active = max(0.0, now - self.started_at) if self.running else 0.0
        return min(self.settings.minutes * 60, self.accumulated + active)

    def complete(self, now: float) -> bool:
        return self.elapsed(now) >= self.settings.minutes * 60

    def start(self, now: float):
        if not self.running and not self.complete(now):
            self.started_at = now

    def pause(self, now: float):
        self.accumulated = self.elapsed(now)
        self.started_at = None


class PulseTracker:
    """Average eight recent accepted pulse intervals; clear on contact/data loss.

    Bounds remove impossible-for-this-prototype readings, not motion artifacts.
    This is a PPG pulse estimate, not an ECG/HRV or signal-quality classifier.
    """

    def __init__(self):
        self.intervals: deque[int] = deque(maxlen=8)
        self.last_beat: float | None = None

    def clear(self):
        self.intervals.clear()
        self.last_beat = None

    def update(self, sample: Sample, now: float):
        if not sample.finger:
            self.clear()
            return
        if self.last_beat is not None and now - self.last_beat > 3:
            self.clear()
        if sample.beat and sample.ibi_ms is not None:
            self.intervals.append(sample.ibi_ms)
            self.last_beat = now

    def bpm(self, now: float) -> float | None:
        if self.last_beat is None or now - self.last_beat > 3:
            self.clear()
        if len(self.intervals) < 3:
            return None
        return 60000 * len(self.intervals) / sum(self.intervals)


def hr_swing(beats: list[tuple[float, float]], period_s: float) -> float | None:
    """Heart-rate swing per guided breath (max − min bpm), the size of RSA.

    Respiratory sinus arrhythmia: heart rate rises on the inhale and falls on the
    exhale, most strongly near 6 breaths/min, so this is the number paced breathing
    can change. beats: (session_s, bpm) per beat. Median over the last 5 completed
    guide cycles with at least 3 beats each; None until there are 2 such cycles.
    """
    cycles: dict[int, list[float]] = {}
    for elapsed, bpm in beats:
        cycles.setdefault(int(elapsed // period_s), []).append(bpm)
    if not cycles:
        return None
    current = max(cycles)  # still in progress, so not a full breath yet
    swings = [max(v) - min(v) for k, v in sorted(cycles.items()) if k != current and len(v) >= 3]
    return statistics.median(swings[-5:]) if len(swings) >= 2 else None


class BreathTracker:
    """Find each breath's own peak and trough in the belt signal, independently of pacing.

    A peak is confirmed once the smoothed signal falls back from its running maximum
    by a swing threshold (a trough likewise, rising from its minimum). The threshold
    is a fraction of the median recent peak-to-trough swing, so it follows the user's
    breath size, and slow baseline drift, which never reverses by a breath's size,
    is ignored. Rate = 60 / median of recent peak-to-peak and trough-to-trough intervals.
    Movement can still look like breathing: this is not an apnea detector.
    """

    # Tuned on the synthetic stress cases in tests/test_breathing_stress.py.
    SMOOTH_TAU_S = 0.25        # EMA time constant; removes ADC noise, keeps 40/min breaths
    WARMUP_S = 20              # no rate shown for the first 20 s of belt data
    MIN_SWING = 30             # ADC counts; smaller reversals are noise, not breaths
    SWING_FRACTION = 0.3       # of the median recent swing
    MIN_INTERVAL_S = 1.4       # 40/min with tolerance for 40 ms sampling
    MAX_INTERVAL_S = 15.3      # 4/min with tolerance
    VARIABLE_CV = 0.25         # interval spread above this is flagged, not hidden

    def __init__(self):
        self.clear()

    def clear(self):
        self.smoothed = None
        self.last_sample_time = None
        self.started = None
        self.direction = 0              # +1 rising toward a peak, -1 falling toward a trough
        self.high = self.low = None     # (time_s, value) running extremes since the last turn
        self.last_turn = None           # (time_s, value) of the last confirmed peak or trough
        self.peaks = deque(maxlen=6)    # times; 5 intervals each from peaks and troughs
        self.troughs = deque(maxlen=6)
        self.swings = deque(maxlen=6)   # recent peak-to-trough sizes, ADC counts
        self.status = "Waiting for breathing belt"

    def update(self, raw: int | None, now: float):
        if raw is None or raw < 100 or raw > 4000:
            self.clear()
            self.status = "Check belt wiring / fit"
            return
        if self.last_sample_time is not None and now - self.last_sample_time > 1:
            self.clear()
        dt = 0.04 if self.last_sample_time is None else max(0, now - self.last_sample_time)
        self.last_sample_time = now
        if self.started is None:
            self.started = now
        alpha = 1 - math.exp(-dt / self.SMOOTH_TAU_S)
        s = raw if self.smoothed is None else self.smoothed + alpha * (raw - self.smoothed)
        self.smoothed = s
        if self.high is None:
            self.high = self.low = (now, s)
        threshold = max(self.MIN_SWING, self.SWING_FRACTION * statistics.median(self.swings)) \
            if self.swings else self.MIN_SWING
        if self.direction >= 0 and s >= self.high[1]:
            self.high = (now, s)
        if self.direction <= 0 and s <= self.low[1]:
            self.low = (now, s)
        if self.direction >= 0 and self.high[1] - s > threshold:
            self._turn(self.peaks, self.high[1], now)
            self.direction, self.low = -1, (now, s)
        elif self.direction <= 0 and s - self.low[1] > threshold:
            self._turn(self.troughs, self.low[1], now)
            self.direction, self.high = 1, (now, s)
        self.status = self._status(now)

    def _turn(self, turns: deque, value: float, now: float):
        # Time the turn when it is confirmed, on the steep slope, not at the flat
        # extreme, where noise moves the peak by ~0.3 s on slow breaths.
        if self.last_turn is not None:
            self.swings.append(abs(value - self.last_turn[1]))
        self.last_turn = (now, value)
        if turns and now - turns[-1] > self.MAX_INTERVAL_S:
            turns.clear()  # too long to be one breath: start counting afresh
        turns.append(now)

    def _intervals(self) -> list[float]:
        intervals = [b - a for turns in (self.peaks, self.troughs)
                     for a, b in zip(turns, list(turns)[1:])]
        return [i for i in intervals if self.MIN_INTERVAL_S <= i <= self.MAX_INTERVAL_S]

    def _median_interval(self, now: float) -> float | None:
        """Median breath interval in s, or None while warming up or without recent breaths."""
        if self.started is None or now - self.started < self.WARMUP_S:
            return None
        intervals = self._intervals()
        if len(intervals) < 3:
            return None
        median = statistics.median(intervals)
        if now - self.last_turn[0] > min(15.5, 1.6 * median):
            return None
        return median

    def _status(self, now: float) -> str:
        if now - self.started < self.WARMUP_S:
            return f"Calibrating belt · {math.ceil(self.WARMUP_S - (now - self.started))} s"
        if self._median_interval(now) is None:
            return "No clear breathing movement" if self.last_turn is None else "Collecting breathing cycles"
        intervals = self._intervals()
        if statistics.pstdev(intervals) > self.VARIABLE_CV * statistics.median(intervals):
            return "Variable breathing · showing the median"
        return "Belt movement detected"

    def rate(self, now: float) -> float | None:
        """Breaths/min from recent cycles; None if stale, warming up or no clear breaths. No side effects."""
        if self.last_sample_time is None or now - self.last_sample_time > 1:
            return None
        median = self._median_interval(now)
        return None if median is None else 60 / median

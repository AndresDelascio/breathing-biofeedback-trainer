"""Clearly labelled simulated data and a bounded, background USB reader."""

from dataclasses import dataclass
import math
from queue import Empty, Full, Queue
import random
import threading
import time

from core import Sample, parse_error, parse_sample


@dataclass(frozen=True)
class Event:
    received_at: float
    sample: Sample | None = None
    message: str | None = None
    fatal: bool = False
    reset: bool = False  # the device reported a break in its data; clear pulse history


class DemoSource:
    name = "DEMO • simulated pulse"

    def __init__(self, now: float):
        self.started = now
        self.last_emit = now - 1
        self.last_beat = now
        self.next_beat = now + 0.86
        self.interval = 860
        self.random = random.Random(42)

    def poll(self, now: float) -> list[Event]:
        if now - self.last_emit < 0.039:
            return []
        self.last_emit = now
        t = now - self.started
        beat = now >= self.next_beat
        emitted_interval = self.interval if beat else None
        if beat:
            self.last_beat = now
            # Synthetic RSA: beats speed up as the demo belt rises (inhale), ~65-75 bpm.
            # It follows the demo's own 12/min breathing, not the guide.
            self.interval = round(860 - 65 * math.sin(2 * math.pi * t / 5))
            self.next_beat = now + self.interval / 1000
        phase = (now - self.last_beat) / (self.interval / 1000)
        wave = 3600 * math.exp(-((phase - 0.12) / 0.1) ** 2)
        ir = int(90000 + wave + 180 * math.sin(t) + self.random.uniform(-70, 70))
        # Demo breathing is 12/min, independent of the guide (default 6/min).
        resp = round(2000 + 280 * math.sin(2 * math.pi * t / 5) + self.random.uniform(-3, 3))
        sample = Sample(int(t * 1000) & 0xFFFFFFFF, ir, int(ir * 0.8), True, beat,
                        emitted_interval, 97 + round(math.sin(t / 20)), resp)
        return [Event(now, sample)]

    def close(self):
        pass


def list_ports() -> list[str]:
    try:
        from serial.tools import list_ports as serial_ports
    except ImportError:
        return []
    return [port.device for port in serial_ports.comports()]


class SerialSource:
    def __init__(self, port: str):
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("Install pyserial: python -m pip install -r app/requirements.txt") from exc
        try:
            # serial_for_url opens "COM3" or "/dev/ttyUSB0" like Serial(), and also "loop://" for tests.
            self.connection = serial.serial_for_url(port, 115200, timeout=0.1)
        except (serial.SerialException, OSError) as exc:
            raise RuntimeError(f"Cannot open {port}: {exc}") from exc
        self.name = f"LIVE • {port}"
        self.events: Queue[Event] = Queue(maxsize=512)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._read, name="pulse-serial", daemon=True)
        self.thread.start()

    def _put(self, event: Event):
        try:
            self.events.put_nowait(event)
        except Full:
            # Keep memory bounded. A stalled UI must not replay old biofeedback.
            try:
                self.events.get_nowait()
            except Empty:
                pass
            try:
                self.events.put_nowait(Event(time.monotonic(), message="Reader backlog: some samples were dropped."))
            except Full:
                pass

    def _read(self):
        pending = bytearray()
        discarding = False
        try:
            while not self.stop.is_set():
                chunk = self.connection.read(min(4096, self.connection.in_waiting or 1))
                for byte in chunk:
                    if byte == 10:
                        if not discarding:
                            line = pending.decode("utf-8", errors="replace").strip()
                            try:
                                sample = parse_sample(line)
                                if sample:
                                    self._put(Event(time.monotonic(), sample))
                                elif (error := parse_error(line)):
                                    # Firmware errors mean the optical stream broke: reset pulse history.
                                    self._put(Event(time.monotonic(), message=error, reset=True))
                            except ValueError as exc:
                                self._put(Event(time.monotonic(), message=f"Skipped invalid sample: {exc}"))
                        pending.clear()
                        discarding = False
                    elif not discarding:
                        pending.append(byte)
                        if len(pending) > 2048:
                            pending.clear()
                            discarding = True
                            self._put(Event(time.monotonic(), message="Skipped oversized serial line."))
        except Exception as exc:
            if not self.stop.is_set():
                self._put(Event(time.monotonic(), message=f"USB disconnected: {exc}", fatal=True))

    def poll(self, now: float) -> list[Event]:
        result = []
        for _ in range(512):
            try:
                result.append(self.events.get_nowait())
            except Empty:
                break
        return result

    def close(self):
        self.stop.set()
        self.thread.join(timeout=0.5)
        self.connection.close()

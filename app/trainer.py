"""Run with `python app/trainer.py`; demo works without third-party packages."""

import argparse
from collections import deque
import csv
from datetime import datetime, timezone
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core import BreathTracker, DeviceClock, PulseTracker, Session, Settings, hr_swing
from sources import DemoSource, SerialSource, list_ports

ROOT = Path(__file__).resolve().parents[1]
BG = "#10232c"
CARD = "#19343e"
INK = "#f0f7f5"
MUTED = "#a8c3c8"
MINT = "#80dfc2"
AMBER = "#f4ce8a"
FONT = "Arial"  # Portable scalable fallback on Windows, macOS and Linux Tk.


class Trainer:
    def __init__(self, root: tk.Tk, port: str | None = None):
        self.root = root
        root.title("Breathing Biofeedback Trainer")
        root.geometry("1000x850")
        root.minsize(940, 760)
        root.configure(bg=BG)
        self.source = DemoSource(time.monotonic())
        self.tracker = PulseTracker()
        self.breath_tracker = BreathTracker()
        self.clock = DeviceClock()
        self.session = Session(Settings())
        self.belt = deque(maxlen=1600)  # (time_s, resp_raw), ~64 s at 25 Hz
        self.beats = deque(maxlen=200)  # (time_s, heart rate bpm), one per beat
        self.session_beats = []         # (session_s, bpm) while guiding, for the swing
        self.last_sample = None
        self.last_received = None
        self.source_started = time.monotonic()
        self.source_failed = False
        self.record_file = None
        self.record_writer = None
        self.record_path = None
        self.last_flush = 0.0
        self.closed = False
        self.after_id = None
        self._build()
        self.refresh_ports()
        if port:
            self.port.set(port)
            self.connect()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()

    def label(self, parent, text="", size=11, color=INK, **kwargs):
        return tk.Label(parent, text=text, font=(FONT, size), fg=color,
                        bg=parent.cget("bg"), **kwargs)

    def _build(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=(FONT, 10), padding=(12, 8))
        style.configure("TEntry", padding=5)
        style.configure("TCombobox", padding=5)
        style.configure("Horizontal.TProgressbar", background=MINT, troughcolor=CARD)
        shell = tk.Frame(self.root, bg=BG, padx=28, pady=16)
        shell.pack(fill="both", expand=True)
        header = tk.Frame(shell, bg=BG)
        header.pack(fill="x")
        self.label(header, "Breathe at your own pace", 24).pack(side="left")
        self.mode = self.label(header, "DEMO · SIMULATED", 10, AMBER)
        self.mode.pack(side="right")
        self.label(shell, "Guided breathing · belly-belt breathing rate · heart-rate response to each breath.",
                   11, MUTED).pack(anchor="w", pady=(5, 16))

        connection = tk.Frame(shell, bg=BG)
        connection.pack(fill="x")
        self.label(connection, "Sensor port", color=MUTED).pack(side="left", padx=(0, 10))
        self.port = tk.StringVar()
        self.port_box = ttk.Combobox(connection, textvariable=self.port, width=20)
        self.port_box.pack(side="left", padx=(0, 8))
        ttk.Button(connection, text="Refresh", command=self.refresh_ports).pack(side="left", padx=4)
        ttk.Button(connection, text="Connect USB", command=self.connect).pack(side="left", padx=4)
        ttk.Button(connection, text="Use demo", command=self.use_demo).pack(side="left", padx=4)
        self.note = self.label(shell, "Demo is synthetic. Connect an ESP32 for your own pulse.", 10, AMBER,
                               anchor="w", wraplength=900)
        self.note.pack(fill="x", pady=(8, 14))

        # Pack the bottom block first: Tk's pack shrinks the last-packed widget first,
        # so this keeps the controls and footer whole and lets the cards shrink instead.
        bottom = tk.Frame(shell, bg=BG)
        bottom.pack(side="bottom", fill="x")
        content = tk.Frame(shell, bg=BG)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)
        guide = tk.Frame(content, bg=CARD, padx=16, pady=12)
        guide.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.label(guide, "BREATHING GUIDE", 10, MUTED).pack(anchor="w")
        self.pacer = tk.Canvas(guide, bg=CARD, highlightthickness=0, height=206, width=440)
        self.pacer.pack(fill="both", expand=True)
        self.elapsed_label = self.label(guide, "Ready · 05:00 session", 11, MUTED)
        self.elapsed_label.pack(pady=(0, 8))
        self.progress = ttk.Progressbar(guide, maximum=100)
        self.progress.pack(fill="x", pady=(0, 6))

        feedback = tk.Frame(content, bg=CARD, padx=20, pady=12)
        feedback.grid(row=0, column=1, sticky="nsew")
        self.label(feedback, "HEART RATE FEEDBACK", 10, MUTED).pack(anchor="w")
        self.pulse_label = self.label(feedback, "—", 40, MINT)
        self.pulse_label.pack(pady=(6, 0))
        self.label(feedback, "bpm · pulse estimate", 11, MUTED).pack()
        self.contact_label = self.label(feedback, "Waiting for pulse...", 10, AMBER, wraplength=310)
        self.contact_label.pack(pady=(6, 3))
        self.interval_label = self.label(feedback, "Last pulse interval: —", 10, MUTED)
        self.interval_label.pack()
        oxygen = tk.Frame(feedback, bg=CARD)
        oxygen.pack()
        self.label(oxygen, "Experimental SpO₂ (uncalibrated):", 9, MUTED).pack(side="left")
        self.oxygen_label = self.label(oxygen, "— %", 9, MUTED)
        self.oxygen_label.pack(side="left", padx=(4, 0))
        # Caption packed first at the bottom so a short window shrinks the chart, not the caption.
        self.label(feedback, "60 s · heart rate (mint) · belt (grey) · inhale (band)", 9, MUTED).pack(side="bottom")
        self.chart = tk.Canvas(feedback, bg=CARD, highlightthickness=0, width=300, height=80)
        self.chart.pack(fill="both", expand=True, pady=(8, 0))

        measurements = tk.Frame(bottom, bg=BG)
        measurements.pack(fill="x", pady=(12, 0))
        measurements.columnconfigure(0, weight=1, uniform="metric")
        measurements.columnconfigure(1, weight=1, uniform="metric")
        breath = tk.Frame(measurements, bg=CARD, padx=14, pady=8)
        breath.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.label(breath, "BREATHING RATE · CHEST BELT", 10, MUTED).pack(anchor="w")
        self.breath_label = self.label(breath, "— breaths/min", 22, MINT)
        self.breath_label.pack(anchor="w")
        self.breath_status = self.label(breath, "Waiting for breathing belt", 9, MUTED)
        self.breath_status.pack(anchor="w")
        swing = tk.Frame(measurements, bg=CARD, padx=14, pady=8)
        swing.grid(row=0, column=1, sticky="nsew")
        self.label(swing, "HEART-RATE SWING PER BREATH · RSA", 10, MUTED).pack(anchor="w")
        self.swing_label = self.label(swing, "— bpm", 22, MINT)
        self.swing_label.pack(anchor="w")
        self.swing_status = self.label(swing, "Start the guide to measure", 9, MUTED)
        self.swing_status.pack(anchor="w")

        settings = tk.Frame(bottom, bg=BG)
        settings.pack(fill="x", pady=(12, 10))
        self.setting_vars = []
        self.setting_inputs = []
        for caption, default, lower, upper in (("Inhale (s)", 4, 2, 10),
                                                ("Exhale (s)", 6, 2, 10),
                                                ("Session (min)", 5, 0.5, 30)):
            self.label(settings, caption, 10, MUTED).pack(side="left", padx=(0, 7))
            value = tk.StringVar(value=str(default))
            entry = ttk.Spinbox(settings, from_=lower, to=upper, increment=0.5,
                                textvariable=value, width=5)
            entry.pack(side="left", padx=(0, 18))
            self.setting_vars.append(value)
            self.setting_inputs.append(entry)
        self.rate_label = self.label(settings, "6.0 breaths/min", 10, MINT)
        self.rate_label.pack(side="right")
        actions = tk.Frame(bottom, bg=BG)
        actions.pack(fill="x")
        self.start_button = ttk.Button(actions, text="Start breathing", command=self.toggle_session)
        self.start_button.pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Reset session", command=self.reset_session).pack(side="left")
        self.record_button = ttk.Button(actions, text="Record CSV...", command=self.toggle_recording)
        self.record_button.pack(side="right")
        self.record_label = self.label(bottom, "Recording off · files stay on your computer", 9, MUTED)
        self.record_label.pack(anchor="w", pady=(10, 0))
        self.label(bottom, "Breathe comfortably; stop if you feel dizzy. This is an educational prototype, not a medical device.",
                   9, MUTED, wraplength=900, justify="left").pack(anchor="w", pady=(10, 0))

    def refresh_ports(self):
        ports = list_ports()
        self.port_box["values"] = ports
        if ports and not self.port.get():
            self.port.set(ports[0])

    def switch_source(self, source):
        self.stop_recording()
        self.source.close()
        self.source = source
        self.tracker.clear()
        self.breath_tracker.clear()
        self.clock.clear()
        self.belt.clear()
        self.beats.clear()
        self.last_sample = None
        self.last_received = None
        self.source_started = time.monotonic()
        self.source_failed = False
        demo = isinstance(source, DemoSource)
        self.mode.config(text="DEMO · SIMULATED" if demo else "LIVE · USB SENSOR", fg=AMBER if demo else MINT)
        self.note.config(text="Demo is synthetic. Connect an ESP32 for your own pulse." if demo else
                         "Connected. Allow the ESP32 to restart, then rest a finger lightly on the sensor.")

    def connect(self):
        port = self.port.get().strip()
        if not port:
            messagebox.showinfo("Select a port", "Choose or enter a serial port, such as COM3.")
            return
        # Release an existing connection before reconnecting the same port.
        if isinstance(self.source, SerialSource):
            self.switch_source(DemoSource(time.monotonic()))
        try:
            source = SerialSource(port)
        except RuntimeError as exc:
            messagebox.showerror("Connection failed", str(exc))
            return
        self.switch_source(source)

    def use_demo(self):
        self.switch_source(DemoSource(time.monotonic()))

    def _settings(self) -> Settings:
        try:
            return Settings(*(float(value.get()) for value in self.setting_vars))
        except ValueError as exc:
            raise ValueError("Use numbers: inhale/exhale 2–10 seconds; session 0.5–30 minutes.") from exc

    def toggle_session(self):
        now = time.monotonic()
        if self.session.running:
            self.session.pause(now)
            self.start_button.config(text="Resume breathing")
        else:
            if self.session.accumulated == 0 or self.session.complete(now):
                try:
                    self.session = Session(self._settings())
                except ValueError as exc:
                    messagebox.showerror("Check the timing", str(exc))
                    return
                self.session_beats.clear()
            self.session.start(now)
            self.start_button.config(text="Pause breathing")
            for entry in self.setting_inputs:
                entry.config(state="disabled")
            self.rate_label.config(text=f"{self.session.settings.breaths_per_minute:.1f} breaths/min")

    def reset_session(self):
        self.session = Session(self.session.settings)
        self.session_beats.clear()
        self.start_button.config(text="Start breathing")
        for entry in self.setting_inputs:
            entry.config(state="normal")

    def toggle_recording(self):
        if self.record_file:
            self.stop_recording()
            return
        directory = ROOT / "sessions"
        try:
            directory.mkdir(exist_ok=True)
        except OSError:
            directory = Path.home()
        prefix = "demo" if isinstance(self.source, DemoSource) else "live"
        filename = filedialog.asksaveasfilename(
            title="Record pulse samples", initialdir=str(directory),
            initialfile=f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.csv",
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not filename:
            return
        try:
            self.record_file = open(filename, "w", newline="", encoding="utf-8")
            self.record_writer = csv.writer(self.record_file)
            self.record_writer.writerow([
                "utc_received", "source", "device_ms", "session_s", "session_state", "phase",
                "inhale_s", "exhale_s", "session_minutes", "ir", "red", "finger", "beat", "ibi_ms", "pulse_bpm",
                "spo2_pct_experimental", "resp_raw", "breathing_rate_bpm"])
        except OSError as exc:
            self.stop_recording()
            messagebox.showerror("Cannot record", str(exc))
            return
        self.record_path = filename
        self.last_flush = time.monotonic()
        self.record_button.config(text="Stop recording")
        self.record_label.config(text=f"Recording {prefix.upper()} → {Path(filename).name}", fg=AMBER)

    def stop_recording(self):
        if self.record_file:
            try:
                self.record_file.close()
                self.record_label.config(text=f"Saved {self.record_path}", fg=MUTED)
            except OSError as exc:
                self.record_label.config(text=f"Recording could not be fully saved: {exc}", fg=AMBER)
        self.record_file = None
        self.record_writer = None
        self.record_button.config(text="Record CSV...")

    def _record(self, sample, acquired_at, received_at):
        if not self.record_writer:
            return
        elapsed = self.session.elapsed(acquired_at)
        state = ("complete" if self.session.complete(acquired_at) else
                 "running" if self.session.running else "paused" if elapsed else "idle")
        phase = self.session.settings.phase(elapsed)[0].lower() if state == "running" else ""
        bpm = self.tracker.bpm(acquired_at)
        breathing_rate = self.breath_tracker.rate(acquired_at)
        settings = self.session.settings
        try:
            # UTC describes host receipt, not the acquisition time of buffered USB data.
            received_utc = datetime.fromtimestamp(
                time.time() - max(0, time.monotonic() - received_at), timezone.utc).isoformat()
            self.record_writer.writerow([
                received_utc, "demo" if isinstance(self.source, DemoSource) else "live",
                sample.t_ms, f"{elapsed:.3f}", state, phase, settings.inhale, settings.exhale,
                settings.minutes, sample.ir, sample.red, int(sample.finger), int(sample.beat),
                sample.ibi_ms if sample.ibi_ms is not None else "", f"{bpm:.1f}" if bpm is not None else "",
                sample.spo2 if sample.spo2 is not None else "",
                sample.resp_raw if sample.resp_raw is not None else "",
                f"{breathing_rate:.1f}" if breathing_rate is not None else ""])
            if received_at - self.last_flush >= 1:
                self.record_file.flush()
                self.last_flush = received_at
        except OSError as exc:
            self.stop_recording()
            self.record_label.config(text=f"Recording stopped: {exc}", fg=AMBER)

    def _draw_pacer(self, now):
        canvas = self.pacer
        canvas.delete("all")
        w, h = max(canvas.winfo_width(), 200), max(canvas.winfo_height(), 200)
        elapsed = self.session.elapsed(now)
        phase, expansion, remaining = self.session.settings.phase(elapsed)
        if not self.session.running:
            phase = "Complete" if self.session.complete(now) else "Paused" if elapsed else "Ready"
        radius = min(w * 0.32, h * 0.42) * (0.58 + 0.42 * expansion)
        x, y = w / 2, h / 2
        outer = min(w * 0.32, h * 0.42)
        canvas.create_oval(x-outer, y-outer, x+outer, y+outer, outline="#365963", width=1)
        canvas.create_oval(x-radius, y-radius, x+radius, y+radius, fill="#28594f", outline=MINT, width=2)
        canvas.create_text(x, y-10, text=phase, fill=INK, font=(FONT, 24))
        detail = f"{remaining:.1f} seconds" if self.session.running else "Keep it comfortable"
        canvas.create_text(x, y+24, text=detail, fill=MUTED, font=(FONT, 10))
        left = max(0, round(self.session.settings.minutes * 60 - elapsed))
        self.elapsed_label.config(text=f"{left // 60:02d}:{left % 60:02d} remaining · {self.session.settings.breaths_per_minute:.1f} breaths/min")
        self.progress["value"] = elapsed / (self.session.settings.minutes * 60) * 100

    def _draw_chart(self, now, window_s=60):
        """Heart rate per beat over the belt and the guide, so RSA is visible by eye."""
        canvas = self.chart
        canvas.delete("all")
        w, h = max(canvas.winfo_width(), 100), max(canvas.winfo_height(), 60)
        x = lambda t: w * (1 - (now - t) / window_s)
        if self.session.running:
            settings = self.session.settings
            period = settings.inhale + settings.exhale
            # ponytail: maps the guide back assuming no pause inside the window.
            start = now - self.session.elapsed(now)
            first = int((now - window_s - start) // period)
            for k in range(max(0, first), int((now - start) // period) + 1):
                left, right = start + k * period, start + k * period + settings.inhale
                canvas.create_rectangle(max(0, x(left)), 0, min(w, x(right)), h, fill="#1f3c44", width=0)
        belt = [(t, v) for t, v in self.belt if now - t <= window_s and v is not None]
        if len(belt) >= 2:
            low, high = min(v for _, v in belt), max(v for _, v in belt)
            span = max(20, high - low)
            canvas.create_line(*[c for t, v in belt for c in (x(t), h - 6 - (v - low) / span * (h - 12))],
                               fill="#56707a", width=1)
        beats = [(t, bpm) for t, bpm in self.beats if now - t <= window_s]
        if len(beats) < 3:
            canvas.create_text(w / 2, h / 2, text="Waiting for heartbeats", fill=MUTED, font=(FONT, 10))
            return
        low, high = min(b for _, b in beats), max(b for _, b in beats)
        mid, span = (low + high) / 2, max(10, high - low)  # at least 10 bpm tall, so noise stays flat
        y = lambda bpm: h / 2 - (bpm - mid) / span * (h - 16)
        segment, previous = [], None
        for t, bpm in beats:
            if previous is not None and t - previous > 3:  # missed beats: break the line
                if len(segment) >= 4:
                    canvas.create_line(*segment, fill=MINT, width=2)
                segment = []
            segment.extend((x(t), y(bpm)))
            previous = t
        if len(segment) >= 4:
            canvas.create_line(*segment, fill=MINT, width=2)
        canvas.create_text(4, 2, text=f"{high:.0f}", fill=MUTED, font=(FONT, 8), anchor="nw")
        canvas.create_text(4, h - 2, text=f"{low:.0f} bpm", fill=MUTED, font=(FONT, 8), anchor="sw")

    def tick(self):
        if self.closed:
            return
        now = time.monotonic()
        for event in self.source.poll(now):
            if event.message:
                self.note.config(text=event.message)
            # One skipped line must not blank the pulse; IBIs are measured on the device.
            if event.reset:
                self.tracker.clear()
            if event.fatal:
                self.source_failed = True
                self.stop_recording()
                self.last_received = None
                self.last_sample = None
            if event.sample and not self.source_failed:
                # Do not show a burst of old samples as current pulse feedback.
                if now - event.received_at > 1:
                    self.tracker.clear()
                    self.breath_tracker.clear()
                    continue
                if (self.last_sample is not None and event.sample.t_ms < self.last_sample.t_ms
                        and self.last_sample.t_ms - event.sample.t_ms < 0x80000000):
                    self.tracker.clear()
                    self.breath_tracker.clear()
                    self.belt.clear()
                    self.beats.clear()
                self.last_sample = event.sample
                self.last_received = event.received_at
                # Algorithms run on device time (even 40 ms steps), not bursty USB receipt time.
                acquired = self.clock.to_host(event.sample.t_ms, event.received_at)
                self.tracker.update(event.sample, acquired)
                self.breath_tracker.update(event.sample.resp_raw, acquired)
                self.belt.append((acquired, event.sample.resp_raw))
                if event.sample.beat:
                    bpm_now = 60000 / event.sample.ibi_ms
                    self.beats.append((acquired, bpm_now))
                    if self.session.running:
                        self.session_beats.append((self.session.elapsed(acquired), bpm_now))
                self._record(event.sample, acquired, event.received_at)
        stale = self.last_received is None or now - self.last_received > 1
        if stale:
            self.tracker.clear()
            self.breath_tracker.clear()
        bpm = self.tracker.bpm(now)
        self.pulse_label.config(text=f"{bpm:.0f}" if bpm is not None else "—")
        interval = self.tracker.intervals[-1] if self.tracker.intervals else None
        self.interval_label.config(text=f"Last pulse interval: {interval} ms" if interval else "Last pulse interval: —")
        if self.source_failed:
            status = "Disconnected · reconnect USB"
        elif stale:
            status = "No fresh data · check USB / firmware" if now - self.source_started > 5 else "Waiting for sensor..."
        elif not self.last_sample.finger:
            status = "Rest a finger lightly on the sensor"
        elif bpm is None:
            status = "Collecting pulses · hold still"
        else:
            status = "Simulated signal" if isinstance(self.source, DemoSource) else "Finger detected · hold still"
        self.contact_label.config(text=status)
        breathing_rate = self.breath_tracker.rate(now)
        self.breath_label.config(text=f"{breathing_rate:.1f} breaths/min" if breathing_rate is not None else "— breaths/min")
        self.breath_status.config(text=self.breath_tracker.status)
        oxygen = self.last_sample.spo2 if self.last_sample is not None and not stale else None
        self.oxygen_label.config(text=f"{oxygen} %" if oxygen is not None else "— %")
        settings = self.session.settings
        # Only show the swing while the pulse itself is valid, never a stale number.
        swing = hr_swing(self.session_beats, settings.inhale + settings.exhale) if bpm is not None else None
        self.swing_label.config(text=f"{swing:.1f} bpm" if swing is not None else "— bpm")
        self.swing_status.config(
            text="Max − min heart rate in each guided breath · median of 5" if swing is not None else
            "Start the guide to measure" if not self.session_beats else "Follow the guide for 2 full breaths")
        if self.session.running and self.session.complete(now):
            self.session.pause(now)
            self.start_button.config(text="Start again")
            for entry in self.setting_inputs:
                entry.config(state="normal")
            self.stop_recording()
        if not self.session.running and self.session.accumulated == 0:
            try:
                self.session = Session(self._settings())
                self.rate_label.config(text=f"{self.session.settings.breaths_per_minute:.1f} breaths/min")
            except ValueError:
                self.rate_label.config(text="Check timing values")
        self._draw_pacer(now)
        self._draw_chart(now)
        self.after_id = self.root.after(40, self.tick)

    def close(self):
        self.closed = True
        if self.after_id:
            self.root.after_cancel(self.after_id)
        self.stop_recording()
        self.source.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Connect directly to an ESP32 port (e.g. COM3)")
    parser.add_argument("--list-ports", action="store_true", help="List USB serial ports and exit")
    args = parser.parse_args()
    if args.list_ports:
        print("\n".join(list_ports()) or "No serial ports found. Check pyserial, the USB cable and driver.")
        return
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        parser.exit(1, f"Cannot open a desktop window: {exc}\nRun on a desktop with Python's Tk support installed.\n")
    Trainer(root, args.port)
    root.mainloop()


if __name__ == "__main__":
    main()

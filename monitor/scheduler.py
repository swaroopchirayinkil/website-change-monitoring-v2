# -*- coding: utf-8 -*-
"""
monitor/scheduler.py
--------------------
Background schedule coordinator and persistence manager for WebGlancer.
Supports specific daily times (with AM/PM and Timezone selection) or periodic intervals.
"""

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
try:
    import zoneinfo
except ImportError:
    zoneinfo = None

from monitor.config import CACHE_DIR, ensure_dirs, REPORT_FILE
from monitor.scan_manager import scan_manager, build_combined_report_results
from monitor.screenshot_engine import trim_memory

SCHEDULE_CONFIG_FILE = CACHE_DIR / "schedule_config.json"


DEFAULT_SCHEDULE = {
    "enabled": False,
    "frequency": "daily",  # 'daily', '1h', '6h', '12h'
    "hour": 9,             # 1-12
    "minute": 0,           # 0, 15, 30, 45
    "ampm": "AM",          # 'AM' or 'PM'
    "timezone": "UTC",     # e.g., 'UTC', 'Asia/Kolkata', 'America/New_York'
    "speed": "low",
    "last_run": None,
}


def parse_24h(hour_12: int, minute: int, ampm: str) -> tuple[int, int]:
    """Convert 12-hour format with AM/PM to 24-hour hour and minute."""
    h = int(hour_12) % 12
    if str(ampm).upper() == "PM":
        h += 12
    return h, int(minute)


def get_tz_object(tz_name: str):
    """Get ZoneInfo object or None if invalid/unavailable."""
    if zoneinfo and tz_name:
        try:
            return zoneinfo.ZoneInfo(tz_name)
        except Exception:
            pass
    return None


class SchedulerManager:
    """Background thread scheduler manager."""

    def __init__(self):
        self.lock = threading.Lock()
        self.config = dict(DEFAULT_SCHEDULE)
        self.thread = None
        self.running = False

    def load_config(self):
        """Load schedule configuration from disk."""
        ensure_dirs()
        with self.lock:
            if SCHEDULE_CONFIG_FILE.exists():
                try:
                    data = json.loads(SCHEDULE_CONFIG_FILE.read_text(encoding="utf-8"))
                    self.config.update(data)
                except Exception:
                    pass

    def save_config(self, new_config: dict):
        """Save schedule configuration to disk and reload schedule state."""
        ensure_dirs()
        with self.lock:
            self.config.update(new_config)
            SCHEDULE_CONFIG_FILE.write_text(json.dumps(self.config, indent=2), encoding="utf-8")

    def get_status(self) -> dict:
        """Get current scheduler configuration and calculated next execution timestamp."""
        with self.lock:
            cfg = dict(self.config)

        next_run_dt = self._calculate_next_run(cfg)
        cfg["next_run"] = next_run_dt.strftime("%Y-%m-%d %I:%M:%S %p (%Z)") if next_run_dt else "N/A"
        cfg["next_run_iso"] = next_run_dt.isoformat() if next_run_dt else None
        return cfg

    def _get_current_now(self, tz_name: str) -> datetime:
        tz_obj = get_tz_object(tz_name)
        return datetime.now(tz_obj) if tz_obj else datetime.now()

    def _calculate_next_run(self, cfg: dict) -> datetime | None:
        """Calculate next upcoming datetime for display."""
        if not cfg.get("enabled"):
            return None

        freq = cfg.get("frequency", "daily")
        tz_name = cfg.get("timezone", "UTC")
        now = self._get_current_now(tz_name)

        if freq == "daily":
            target_h, target_m = parse_24h(cfg.get("hour", 9), cfg.get("minute", 0), cfg.get("ampm", "AM"))
            target_dt = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
            if target_dt <= now:
                target_dt += timedelta(days=1)
            return target_dt
        else:
            hours_map = {"1h": 1, "6h": 6, "12h": 12}
            interval_hours = hours_map.get(freq, 1)

            last_run_str = cfg.get("last_run")
            if last_run_str:
                try:
                    last_run_dt = datetime.fromisoformat(last_run_str)
                    if tz_obj := get_tz_object(tz_name):
                        if last_run_dt.tzinfo is None:
                            last_run_dt = last_run_dt.replace(tzinfo=tz_obj)
                    next_dt = last_run_dt + timedelta(hours=interval_hours)
                    if next_dt > now:
                        return next_dt
                except Exception:
                    pass
            return now + timedelta(hours=interval_hours)

    def _is_due(self, cfg: dict) -> bool:
        """Check if scheduled scan is due to be executed now."""
        if not cfg.get("enabled"):
            return False

        freq = cfg.get("frequency", "daily")
        tz_name = cfg.get("timezone", "UTC")
        now = self._get_current_now(tz_name)

        last_run_dt = None
        if cfg.get("last_run"):
            try:
                last_run_dt = datetime.fromisoformat(cfg["last_run"])
                if tz_obj := get_tz_object(tz_name):
                    if last_run_dt.tzinfo is None:
                        last_run_dt = last_run_dt.replace(tzinfo=tz_obj)
            except Exception:
                pass

        if freq == "daily":
            target_h, target_m = parse_24h(cfg.get("hour", 9), cfg.get("minute", 0), cfg.get("ampm", "AM"))
            target_today = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
            
            # If current time is past today's target execution time
            if now >= target_today:
                # Due if we haven't run today since the target execution time
                if last_run_dt is None or last_run_dt < target_today:
                    return True
            return False
        else:
            hours_map = {"1h": 1, "6h": 6, "12h": 12}
            interval_hours = hours_map.get(freq, 1)
            if last_run_dt is None:
                return True
            return (now - last_run_dt) >= timedelta(hours=interval_hours)

    def start(self, report_generator=None):
        """Start the background scheduler daemon thread."""
        self.load_config()
        self.running = True
        self.thread = threading.Thread(target=self._loop, args=(report_generator,), daemon=True)
        self.thread.start()

    def _loop(self, report_generator=None):
        """Main background scheduler polling loop."""
        idle_ticks = 0
        while self.running:
            try:
                time.sleep(5)
                idle_ticks += 1
                if idle_ticks % 12 == 0:  # Every ~60 seconds when idle
                    trim_memory()

                with self.lock:
                    cfg = dict(self.config)

                if not cfg.get("enabled"):
                    continue

                if scan_manager.is_running:
                    continue

                if self._is_due(cfg):
                    tz_name = cfg.get("timezone", "UTC")
                    now = self._get_current_now(tz_name)
                    
                    with self.lock:
                        self.config["last_run"] = now.isoformat()
                        SCHEDULE_CONFIG_FILE.write_text(json.dumps(self.config, indent=2), encoding="utf-8")

                    print(f"⏰ [Scheduler] Triggering scheduled live visual check pass at {now.strftime('%Y-%m-%d %I:%M:%S %p %Z')}...")

                    def _wrapper(results):
                        if report_generator:
                            report_generator(results)
                        else:
                            from monitor.server import generate_html_report
                            generate_html_report(results, REPORT_FILE)

                    scan_manager.start_scan(
                        action="check",
                        speed=cfg.get("speed", "low"),
                        report_generator=_wrapper
                    )
            except Exception as e:
                time.sleep(5)



scheduler_manager = SchedulerManager()

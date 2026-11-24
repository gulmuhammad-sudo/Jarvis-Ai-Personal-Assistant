"""Location, weather, prayer times, news, alarms and the background scheduler.

Everything here uses free services that need no key:
  - wttr.in        weather (and a best-guess location from your internet connection)
  - aladhan.com    prayer times
  - Google News    headlines (RSS)
Alarms, your city and settings are saved in data/ so they survive restarts.
"""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Callable

from .config import DATA_DIR, DATA_LOCK, read_json, write_json

ALARMS_FILE = DATA_DIR / "alarms.json"
LOCATION_FILE = DATA_DIR / "location.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
PRAYERS = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
REPEATS = ("once", "daily", "weekdays", "weekends", "days")
CATCH_UP = timedelta(minutes=5)     # an alarm missed by up to 5 min (PC asleep, busy) still rings


def _get_json(url: str, timeout: int = 20, ua: dict | None = None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=ua or UA), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------------- #
# Settings (language, chosen mic, prayer reminders...)
# --------------------------------------------------------------------------- #

def get_setting(key: str, default=None):
    data = read_json(SETTINGS_FILE, {})
    return data.get(key, default) if isinstance(data, dict) else default


def set_setting(key: str, value) -> None:
    with DATA_LOCK:
        data = read_json(SETTINGS_FILE, {})
        data = data if isinstance(data, dict) else {}
        data[key] = value
        write_json(SETTINGS_FILE, data)


# --- personalisation: what the assistant is called, and the look of the Command Center ---
DEFAULT_NAME = os.environ.get("JARVIS_NAME", "Jarvis")
THEMES = ("dark", "light", "system")


def clean_name(name: str) -> str:
    """A tidy assistant name (letters in any language, digits, spaces, . - '), or ValueError."""
    name = re.sub(r"\s+", " ", str(name or "")).strip().strip(".")
    if not 1 <= len(name) <= 24 or not re.fullmatch(r"[^\W_](?:[\w .'-]*[^\W_])?", name):
        raise ValueError("A name needs 1-24 letters or digits (spaces, dots, dashes and apostrophes are fine).")
    return name


def agent_name() -> str:
    try:
        return clean_name(get_setting("assistant_name") or DEFAULT_NAME)
    except ValueError:
        return "Jarvis"


def set_agent_name(name: str) -> str:
    name = clean_name(name)
    set_setting("assistant_name", name)
    return name


def theme() -> str:
    t = get_setting("theme") or os.environ.get("JARVIS_THEME", "dark")
    return t if t in THEMES else "dark"


# --------------------------------------------------------------------------- #
# Location
# --------------------------------------------------------------------------- #

_loc_cache: dict | None = None


def get_location() -> dict:
    """{'city', 'country', 'lat', 'lon', 'source'}: from .env, the saved city, or a best guess."""
    global _loc_cache
    if os.environ.get("JARVIS_CITY"):
        return {"city": os.environ["JARVIS_CITY"], "country": os.environ.get("JARVIS_COUNTRY", ""),
                "lat": None, "lon": None, "source": ".env"}
    saved = read_json(LOCATION_FILE, None)
    if saved:
        return saved
    if _loc_cache:
        return _loc_cache
    try:  # wttr.in reports the area nearest to this internet connection (only a rough guess)
        a = _get_json("https://wttr.in/?format=j1", ua={"User-Agent": "curl/8"})["nearest_area"][0]
        _loc_cache = {"city": a["region"][0]["value"] or a["areaName"][0]["value"],
                      "country": a["country"][0]["value"],
                      "lat": float(a["latitude"]), "lon": float(a["longitude"]), "source": "auto"}
    except Exception:
        _loc_cache = {"city": "Islamabad", "country": "Pakistan", "lat": 33.6844, "lon": 73.0479, "source": "default"}
    return _loc_cache


# what the page asks for all the time must never wait for the internet (20 seconds and more on a bad line): what is known is
# given at once, and the rest is fetched in the background
_BACK: dict[str, float] = {}
_BACK_LOCK = threading.Lock()


def _later(key: str, fetch) -> None:
    """Fetch in the background: once at a time, and not again within a minute."""
    with _BACK_LOCK:
        if time.monotonic() < _BACK.get(key, 0.0):
            return
        _BACK[key] = time.monotonic() + 60

    def go() -> None:
        try:
            fetch()
        except Exception as e:
            print(f"[schedule] {key}: {type(e).__name__}")
    threading.Thread(target=go, name=f"fetch-{key}", daemon=True).start()


def known_location() -> dict:
    """The location as far as known ({} while it is being looked up)."""
    if os.environ.get("JARVIS_CITY") or read_json(LOCATION_FILE, None) or _loc_cache:
        return get_location()
    _later("location", get_location)
    return {}


def known_prayers(day: date) -> dict[str, str] | None:
    """The prayer times as far as known (None while they are being fetched)."""
    loc = known_location()
    if not loc:
        return None
    key = (day.isoformat(), _where(loc), os.environ.get("JARVIS_PRAYER_METHOD", "1"), os.environ.get("JARVIS_PRAYER_SCHOOL", "1"))
    if key in _prayer_cache:
        return _prayer_cache[key]
    _later(f"prayers {day.isoformat()}", lambda: prayer_times(day))
    return None


def set_location(city: str, country: str = "") -> dict:
    """Save the user's city (looked up on the map so prayer times and weather are exact)."""
    q = urllib.parse.quote(f"{city} {country}".strip())
    lat = lon = None
    try:
        hits = _get_json(f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1",
                         ua={"User-Agent": "Jarvis-personal-assistant/1.0"})
        if hits:
            lat, lon = float(hits[0]["lat"]), float(hits[0]["lon"])
            country = country or hits[0].get("display_name", "").split(",")[-1].strip()
    except Exception:
        pass
    loc = {"city": city.strip().title(), "country": country, "lat": lat, "lon": lon, "source": "saved"}
    with DATA_LOCK:
        write_json(LOCATION_FILE, loc)
    _prayer_cache.clear()
    _weather_cache.clear()
    _BACK.clear()
    return loc


def _where(loc: dict) -> str:
    if loc.get("lat") is not None:
        return f"{loc['lat']},{loc['lon']}"
    return urllib.parse.quote(f"{loc['city']} {loc.get('country', '')}".strip())


# --------------------------------------------------------------------------- #
# Weather
# --------------------------------------------------------------------------- #

_weather_cache: dict = {}


def weather(city: str | None = None) -> dict:
    loc = {"city": city, "country": "", "lat": None, "lon": None} if city else get_location()
    key = _where(loc)
    hit = _weather_cache.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    d = _get_json(f"https://wttr.in/{key}?format=j1", ua={"User-Agent": "curl/8"})
    cur, today = d["current_condition"][0], d["weather"][0]
    out = {"place": loc["city"], "temp_c": int(cur["temp_C"]), "feels_c": int(cur["FeelsLikeC"]),
           "condition": cur["weatherDesc"][0]["value"].strip(), "humidity": int(cur["humidity"]),
           "wind_kmh": int(cur["windspeedKmph"]), "max_c": int(today["maxtempC"]), "min_c": int(today["mintempC"]),
           "rain_chance": max(int(h.get("chanceofrain", 0)) for h in today["hourly"])}
    _weather_cache[key] = (time.time(), out)
    return out


def weather_text(city: str | None = None) -> str:
    w = weather(city)
    return (f"{w['place']}: {w['condition']}, {w['temp_c']}°C (feels like {w['feels_c']}°C). "
            f"Today {w['min_c']}–{w['max_c']}°C, humidity {w['humidity']}%, wind {w['wind_kmh']} km/h, "
            f"chance of rain up to {w['rain_chance']}%.")


# --------------------------------------------------------------------------- #
# Prayer times (Aladhan; Karachi method + Hanafi Asr by default, as used in Pakistan)
# --------------------------------------------------------------------------- #

_prayer_cache: dict = {}


def prayer_times(day: date | None = None, city: str | None = None) -> dict[str, str]:
    day = day or date.today()
    loc = {"city": city, "country": "", "lat": None, "lon": None} if city else get_location()
    method = os.environ.get("JARVIS_PRAYER_METHOD", "1")   # 1 = University of Islamic Sciences, Karachi
    school = os.environ.get("JARVIS_PRAYER_SCHOOL", "1")   # 1 = Hanafi Asr, 0 = Shafi'i
    key = (day.isoformat(), _where(loc), method, school)
    if key in _prayer_cache:
        return _prayer_cache[key]
    stamp = day.strftime("%d-%m-%Y")
    if loc.get("lat") is not None:
        url = (f"https://api.aladhan.com/v1/timings/{stamp}?latitude={loc['lat']}&longitude={loc['lon']}"
               f"&method={method}&school={school}")
    else:
        url = (f"https://api.aladhan.com/v1/timingsByCity/{stamp}?city={urllib.parse.quote(loc['city'])}"
               f"&country={urllib.parse.quote(loc.get('country') or 'Pakistan')}&method={method}&school={school}")
    t = _get_json(url)["data"]["timings"]
    times = {p: t[p][:5] for p in PRAYERS}
    times["Sunrise"] = t["Sunrise"][:5]
    if len(_prayer_cache) > 20:
        _prayer_cache.clear()
    _prayer_cache[key] = times
    return times


def _at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())


def next_prayer(now: datetime | None = None) -> tuple[str, datetime] | None:
    now = now or datetime.now()
    for offset in (0, 1):
        day = (now + timedelta(days=offset)).date()
        try:
            times = prayer_times(day)
        except Exception:
            return None
        for p in PRAYERS:
            if _at(day, times[p]) > now:
                return p, _at(day, times[p])
    return None


def prayer_text(city: str | None = None) -> str:
    times = prayer_times(city=city)
    here = get_location()
    loc = city or here["city"]
    approx = "" if city or here.get("source") in ("saved", ".env") else (
        " NOTE: location was guessed from the internet connection, so times may be off; "
        "ask the user for their city and call set_location.")
    text = (f"Prayer times today in {loc}{approx}: " + ", ".join(f"{p} {times[p]}" for p in PRAYERS)
            + f" (sunrise {times['Sunrise']}).")
    if not city:
        nxt = next_prayer()
        if nxt:
            mins = int((nxt[1] - datetime.now()).total_seconds() // 60)
            text += f" Next: {nxt[0]} at {nxt[1]:%H:%M}, in {mins // 60}h {mins % 60}m."
    return text


# --------------------------------------------------------------------------- #
# News
# --------------------------------------------------------------------------- #

def headlines(n: int = 5) -> list[str]:
    region = os.environ.get("JARVIS_NEWS_REGION", "PK")
    url = f"https://news.google.com/rss?hl=en-{region}&gl={region}&ceid={region}:en"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        rss = r.read().decode("utf-8", "replace")
    return [html.unescape(t) for t in re.findall(r"<item>.*?<title>(.*?)</title>", rss, re.S)][:n]


# --------------------------------------------------------------------------- #
# Alarms (saved; can repeat daily, on weekdays, weekends or chosen days)
# --------------------------------------------------------------------------- #

def _parse_time(text: str) -> str:
    """Accepts '7', '7:30', '07:30', '7:30 pm', '19:30', '7.30' -> 'HH:MM'."""
    t = str(text).strip().lower().replace(".", ":")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", t)
    if not m:
        raise ValueError(f"Couldn't understand the time '{text}'. Use e.g. 07:30 or 7:30 pm.")
    h, mnt, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap and not 1 <= h <= 12:
        raise ValueError(f"'{text}' isn't a valid time.")
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if not (0 <= h < 24 and 0 <= mnt < 60):
        raise ValueError(f"'{text}' isn't a valid time.")
    return f"{h:02d}:{mnt:02d}"


def _days_for(repeat: str, days: list[str] | None) -> list[int]:
    if repeat == "daily":
        return list(range(7))
    if repeat == "weekdays":
        return [0, 1, 2, 3, 4]
    if repeat == "weekends":
        return [5, 6]
    if repeat == "days":
        picked = sorted({DAY_NAMES.index(d.lower()[:3]) for d in (days or []) if d.lower()[:3] in DAY_NAMES})
        if not picked:
            raise ValueError("Choose at least one day (mon, tue, wed, thu, fri, sat, sun).")
        return picked
    return []


def list_alarms() -> list[dict]:
    data = read_json(ALARMS_FILE, [])
    return data if isinstance(data, list) else []


def _alarm(at: str, label: str, repeat: str, days: list[str] | None) -> dict:
    repeat = (repeat or "once").lower()
    if repeat not in REPEATS:
        repeat = "once"
    return _switch_on({"time": _parse_time(at), "label": " ".join(str(label or "").split())[:120] or "Alarm", "repeat": repeat,
                       "days": _days_for(repeat, days)})


def _switch_on(alarm: dict) -> dict:
    alarm.update(enabled=True, last_fired=None, since=datetime.now().isoformat(timespec="seconds"))
    alarm.pop("date", None)
    if alarm["repeat"] == "once":  # today if still ahead, otherwise tomorrow
        when = _at(date.today(), alarm["time"])
        alarm["date"] = (when if when > datetime.now() else when + timedelta(days=1)).date().isoformat()
    return alarm


def add_alarm(at: str, label: str = "", repeat: str = "once", days: list[str] | None = None) -> dict:
    alarm = _alarm(at, label, repeat, days)
    with DATA_LOCK:
        alarms = list_alarms()
        alarm["id"] = max((a["id"] for a in alarms), default=0) + 1
        alarms.append(alarm)
        write_json(ALARMS_FILE, alarms)
    return alarm


def update_alarm(alarm_id: int, at: str, label: str = "", repeat: str = "once", days: list[str] | None = None) -> dict:
    """Change it; it's on again afterwards, and may still ring today."""
    alarm = _alarm(at, label, repeat, days)
    with DATA_LOCK:
        alarms = list_alarms()
        if not any(a["id"] == alarm_id for a in alarms):
            raise ValueError("That alarm is gone.")
        alarm["id"] = alarm_id
        write_json(ALARMS_FILE, [alarm if a["id"] == alarm_id else a for a in alarms])
    return alarm


def enable_alarm(alarm_id: int, on: bool) -> dict:
    with DATA_LOCK:
        alarms = list_alarms()
        a = next((a for a in alarms if a["id"] == alarm_id), None)
        if not a:
            raise ValueError("That alarm is gone.")
        if on and not a.get("enabled", True):
            _switch_on(a)
        elif not on:
            a["enabled"] = False
        write_json(ALARMS_FILE, alarms)
    return a


def delete_alarm(alarm_id: int) -> bool:
    with DATA_LOCK:
        alarms = list_alarms()
        kept = [a for a in alarms if a["id"] != alarm_id]
        if len(kept) != len(alarms):
            write_json(ALARMS_FILE, kept)
    return len(kept) != len(alarms)


def next_fire(alarm: dict, now: datetime | None = None) -> datetime | None:
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    if not alarm.get("enabled", True):
        return None
    if alarm["repeat"] == "once":
        when = _at(date.fromisoformat(alarm["date"]), alarm["time"])
        return when if when >= now else None
    for offset in range(8):
        day = (now + timedelta(days=offset)).date()
        when = _at(day, alarm["time"])
        if day.weekday() in alarm["days"] and when >= now and alarm.get("last_fired") != day.isoformat():
            return when
    return None


def describe_alarm(a: dict) -> str:
    rep = {"once": "once", "daily": "every day", "weekdays": "on weekdays", "weekends": "on weekends"}.get(
        a["repeat"], "on " + ", ".join(DAY_NAMES[d].title() for d in a["days"]))
    nf = next_fire(a)
    return f"#{a['id']} {a['time']} {a['label']} ({rep})" + (f", next {nf:%a %d %b %H:%M}" if nf else "" if a.get("enabled", True) else ", switched off")


# --------------------------------------------------------------------------- #
# The scheduler thread
# --------------------------------------------------------------------------- #

class Scheduler:
    """Fires alarms, prayer reminders, battery warnings and the morning briefing while Jarvis runs."""

    def __init__(self, notify: Callable[[str, str], None], run_prompt: Callable[[str], None] | None = None,
                 start: bool = True):
        self.notify = notify            # notify(message, kind)
        self.run_prompt = run_prompt    # ask Jarvis something (used for the morning briefing)
        self.fired: set[str] = set()    # "<date>|<event>" keys already announced today
        self.battery_warned: set[int] = set()
        self.battery_full_said = False
        self.on_tick: Callable[[datetime], object] | None = None     # automations (hud.py)
        if start:
            threading.Thread(target=self._loop, name="scheduler", daemon=True).start()

    @staticmethod
    def prayer_lead() -> int:
        return int(os.environ.get("JARVIS_PRAYER_REMINDER_MINUTES", "10"))

    @staticmethod
    def prayers_on() -> bool:
        default = os.environ.get("JARVIS_PRAYER_REMINDERS", "on") != "off"
        return get_setting("prayer_reminders", default) is not False

    @staticmethod
    def briefing_time() -> str | None:
        t = os.environ.get("JARVIS_BRIEFING_TIME", "08:00").strip()
        return None if t.lower() in ("", "off", "none") else _parse_time(t)

    def _once(self, key: str) -> bool:
        if key in self.fired:
            return False
        self.fired.add(key)
        return True

    def _loop(self) -> None:
        while True:
            try:
                self.tick(datetime.now())
            except Exception as e:  # never let a bad network call kill the scheduler
                print(f"[scheduler] {type(e).__name__}: {e}")
            try:
                if self.on_tick:
                    self.on_tick(datetime.now())
            except Exception as e:
                print(f"[automations] {type(e).__name__}: {e}")
            time.sleep(15)

    def tick(self, now: datetime) -> None:
        today = now.date().isoformat()
        self.fired = {k for k in self.fired if k.startswith(today)}   # forget yesterday's
        due = lambda when: timedelta(0) <= now - when <= CATCH_UP     # noqa: E731
        self._alarms(now, today, due)
        self._prayers(now, today, due)
        self.check_battery()
        bt = self.briefing_time()
        if bt and self.run_prompt and timedelta(0) <= now - _at(now.date(), bt) <= timedelta(minutes=10) \
                and self._once(f"{today}|briefing"):
            self.run_prompt("Give me my daily briefing.")

    def _alarms(self, now: datetime, today: str, due) -> None:
        with DATA_LOCK:
            alarms, changed, done = list_alarms(), False, set()
            for a in alarms:
                if not a.get("enabled", True) or a.get("last_fired") == today:
                    continue
                if a["repeat"] == "once" and (a.get("date") or "9999") > today:
                    continue
                if a["repeat"] != "once" and now.weekday() not in a["days"]:
                    continue
                at = _at(date.fromisoformat(a["date"]) if a["repeat"] == "once" else now.date(), a["time"])
                if at > now:
                    continue
                if due(at):
                    self.notify(f"Alarm: {a['label']} ({a['time']})", "alarm")
                elif now - at < timedelta(hours=24) and a.get("since", "9999") < at.isoformat():      # the PC or the app was off
                    self.notify(f"You missed the alarm \"{a['label']}\" ({at:%a} {a['time']}): the app or the PC was off.", "info")
                a["last_fired"] = today
                changed = True
                if a["repeat"] == "once":
                    done.add(a["id"])
            if changed:   # finished one-off alarms are removed (switched-off ones stay)
                write_json(ALARMS_FILE, [a for a in alarms if a["id"] not in done])

    def _prayers(self, now: datetime, today: str, due) -> None:
        try:
            times = prayer_times(now.date()) if self.prayers_on() else None
        except Exception:   # offline: skip prayers this round; alarms/battery/briefing keep working
            return
        if not times:
            return
        lead = self.prayer_lead()
        for p in PRAYERS:
            at = _at(now.date(), times[p])
            if lead and now < at and due(at - timedelta(minutes=lead)) and self._once(f"{today}|{p}|pre"):
                self.notify(f"{p} prayer in {lead} minutes ({times[p]}).", "prayer")
            if due(at) and self._once(f"{today}|{p}|now"):
                self.notify(f"It's time for {p} prayer ({times[p]}).", "prayer")

    def check_battery(self, percent: float | None = None, plugged: bool | None = None) -> None:
        """Warn once at each level (20/10/5 %) while unplugged; say when it's fully charged."""
        if percent is None:
            try:
                import psutil
                bat = psutil.sensors_battery()
            except Exception:
                bat = None
            if not bat:
                return
            percent, plugged = bat.percent, bat.power_plugged
        warn_at = int(os.environ.get("JARVIS_BATTERY_WARN", "20"))
        levels = sorted({warn_at, 10, 5}, reverse=True)
        if plugged:
            self.battery_warned.clear()
            if percent >= 100 and not self.battery_full_said \
                    and os.environ.get("JARVIS_BATTERY_FULL_NOTICE", "on") != "off":
                self.battery_full_said = True
                self.notify("Battery is fully charged. You can unplug the charger.", "battery")
            return
        self.battery_full_said = False
        for lvl in levels:
            if percent <= lvl and lvl not in self.battery_warned:
                self.battery_warned.update(x for x in levels if x >= lvl)
                urgent = " Please plug in the charger now." if lvl <= 10 else " Please plug in the charger."
                self.notify(f"Battery low: {percent:.0f}% left.{urgent}", "battery")
                break

    def upcoming(self, limit: int = 8) -> list[dict]:
        """Next alarms and today's remaining prayers, for the HUD timeline."""
        now = datetime.now()
        items = []
        for a in list_alarms():
            nf = next_fire(a, now)
            if nf and nf - now < timedelta(days=2):
                items.append({"at": nf, "label": a["label"], "kind": "alarm",
                              "repeat": a["repeat"] if a["repeat"] != "once" else ""})
        if self.prayers_on():
            try:
                times = known_prayers(now.date()) or {}
                items += [{"at": _at(now.date(), times[p]), "label": f"{p} prayer", "kind": "prayer", "repeat": ""}
                          for p in PRAYERS if p in times and _at(now.date(), times[p]) > now]
            except Exception:
                pass
        items.sort(key=lambda i: i["at"])
        return [{"due": i["at"].strftime("%H:%M"), "message": i["label"], "kind": i["kind"], "repeat": i["repeat"],
                 "left": max(0, int((i["at"] - now).total_seconds()))} for i in items[:limit]]

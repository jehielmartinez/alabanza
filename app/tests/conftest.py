"""Shared test doubles.

The appliance's logic is pure — a state machine over a player, a Bluetooth
backend and a clock — so almost everything is testable without a Pi, without
libmpv and without sleeping. See docs/TESTING.md.
"""

import sys

import pytest

from alabanza.app import App
from alabanza.bible import Bible
from alabanza.books import BOOKS
from alabanza.bt_fake import FakeBackend
from alabanza.events import Event, Kind
from alabanza.library import Hymn, Library
from alabanza.settings import Settings, save


class FakeClock:
    """Time only moves when a test says so, so a 30 s timeout costs nothing."""

    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakePlayer:
    """libmpv's contract, without libmpv: no media, no audio device, no window."""

    def __init__(self):
        self.active = False
        self.paused = False
        self.volume = 80
        self.speed = 1.0
        self.position = 0.0
        self.duration = 0.0
        self.audio_device = "auto"
        self.audio_devices: list[tuple[str, str]] = []
        self.played: list = []
        self.seeks: list[float] = []
        self.showing_idle = False
        self.images: list = []       # stills put on HDMI (verse slides)

    def play(self, path):
        self.played.append(path)
        self.active = True
        self.paused = False
        self.showing_idle = False
        self.speed = 1.0        # spec: speed resets per hymn

    def show_idle(self):
        self.showing_idle = True

    def show_image(self, path):
        self.images.append(path)
        self.showing_idle = False

    def toggle_pause(self):
        if self.active:
            self.paused = not self.paused

    def stop(self):
        self.active = False
        self.paused = False
        self.showing_idle = True

    def finish(self):
        """The hymn reaches its end on its own, as distinct from being
        stopped. The real player unloads the file and app.tick() notices."""
        self.active = False
        self.paused = False

    def seek(self, seconds):
        if self.active:
            self.seeks.append(seconds)

    def nudge_speed(self, direction):
        self.speed = round(min(1.25, max(0.75, self.speed + direction * 0.05)), 2)
        return self.speed

    def nudge_volume(self, direction):
        self.volume = min(100, max(0, self.volume + direction))    # 1% per click, like the real one
        return self.volume

    def shutdown(self):
        pass


class FakeSlides:
    """The slide worker's contract: show(ref) and cancel()."""

    def __init__(self):
        self.shown: list = []
        self.cancelled = 0

    def show(self, ref):
        self.shown.append(ref)

    def cancel(self):
        self.cancelled += 1


def make_bible(verses_per_chapter: int = 5) -> Bible:
    """Every book and chapter of the canon, with placeholder verses, so
    navigation can be exercised across every boundary without the text."""
    data = {
        i: [[f"{name} {c}:{v} palabra " * 4 for v in range(1, verses_per_chapter + 1)]
            for c in range(1, chapters + 1)]
        for i, (name, _, chapters) in enumerate(BOOKS)
    }
    return Bible(data=data)


def make_library(numbers=((5, "Al Cielo Voy"), (14, "Bienvenida da Jesús"),
                          (279, "¡Santo! ¡Santo! ¡Santo!"))) -> Library:
    return Library({n: Hymn(n, t, f"/nonexistent/{n:03d}.mp4") for n, t in numbers}, [])


class Harness:
    """An app plus the doubles it runs on, driven the way __main__ drives it."""

    def __init__(self, app, player, bt, clock):
        self.app, self.player, self.bt, self.clock = app, player, bt, clock

    def press(self, *keys):
        """Send events; a bare Kind, or (Kind, value) for digits."""
        for key in keys:
            kind, value = key if isinstance(key, tuple) else (key, 0)
            self.app.handle(Event(kind, value))
        return self.app.tick()

    def type_number(self, number: int):
        return self.press(*[(Kind.DIGIT, int(d)) for d in str(number)])

    def advance(self, seconds: float, step: float = 0.05):
        """Let time pass the way the 50 ms loop would, ticking as it goes."""
        remaining = seconds
        vm = self.app.tick()
        while remaining > 0:
            self.clock.advance(min(step, remaining))
            remaining -= step
            vm = self.app.tick()
        return vm

    def advance_until(self, predicate, limit: float = 120.0, step: float = 0.05):
        """Run until something is true, rather than guessing how long it takes.

        Timing-sensitive assertions ("is it paused 22 s in?") are how these
        tests turn flaky; wait for the state instead.
        """
        vm = self.app.tick()
        waited = 0.0
        while not predicate(self) and waited < limit:
            self.clock.advance(step)
            waited += step
            vm = self.app.tick()
        assert predicate(self), f"never became true within {limit}s"
        return vm

    def tick(self):
        return self.app.tick()

    @property
    def message(self):
        return self.app.message

    def rows(self, vm=None):
        """The list rows currently on screen, cursor marker included."""
        return (vm or self.app.tick()).lines

    def cursor_row(self, vm=None):
        return next((r for r in self.rows(vm) if r.startswith("> ")), None)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def player():
    return FakePlayer()


@pytest.fixture
def harness(clock, player, tmp_path):
    """The default rig: three hymns, a jack output, a fake Bluetooth adapter."""

    def build(*, settings=None, paired=(), bt=None, library=None, bible=None):
        backend = bt if bt is not None else FakeBackend(paired=paired, clock=clock)
        # settings go through a real file, so construction exercises the actual
        # boot path — including the auto-reconnect that only fires when the
        # saved output is Bluetooth
        path = tmp_path / "settings.json"
        save(settings or Settings(), path)
        slides = FakeSlides()
        app = App(tmp_path / "library", player, path, backend, clock=clock,
                  bible=bible, slides=slides)
        app.library = library if library is not None else make_library()
        rig = Harness(app, player, backend, clock)
        rig.slides = slides
        return rig

    return build


def pytest_collection_modifyitems(config, items):
    """`device` tests need real hardware; skip them anywhere that isn't a Pi."""
    if sys.platform.startswith("linux"):
        try:
            model = open("/proc/device-tree/model").read()
            if "Raspberry Pi" in model:
                return
        except OSError:
            pass
    skip = pytest.mark.skip(reason="needs real hardware; run on the Pi")
    for item in items:
        if "device" in item.keywords:
            item.add_marker(skip)

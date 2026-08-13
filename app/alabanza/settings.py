"""Persisted device settings.

Spec: the selected audio output and the per-output volume levels survive
reboots (decisions 5 & 6). On the device these live on the small writable
partition; writes must be rare and atomic (decision 10) — so saves are
debounced by the app and written via tmp-file + rename.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

OUTPUTS = ("jack", "bluetooth", "hdmi")
OUTPUT_LABELS = {"jack": "Jack", "bluetooth": "Bluetooth", "hdmi": "HDMI"}
DEFAULT_VOLUMES = {"jack": 80, "bluetooth": 60, "hdmi": 80}


@dataclass
class Settings:
    output: str = "jack"
    volumes: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_VOLUMES))
    last_bt_device: str = ""      # MAC of the speaker to reconnect to at boot
    # MAC -> friendly name, so the OLED can show real names before the adapter
    # answers. BlueZ stays the source of truth for what is actually paired.
    bt_names: dict[str, str] = field(default_factory=dict)

    @property
    def volume(self) -> int:
        return self.volumes.get(self.output, 80)

    @volume.setter
    def volume(self, value: int) -> None:
        self.volumes[self.output] = value

    def next_output(self) -> str:
        i = OUTPUTS.index(self.output) if self.output in OUTPUTS else 0
        self.output = OUTPUTS[(i + 1) % len(OUTPUTS)]
        return self.output


def load(path: Path) -> Settings:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return Settings()
    s = Settings()
    if data.get("output") in OUTPUTS:
        s.output = data["output"]
    for name, vol in (data.get("volumes") or {}).items():
        if name in OUTPUTS and isinstance(vol, int):
            s.volumes[name] = max(0, min(100, vol))
    s.last_bt_device = str(data.get("last_bt_device", ""))
    for mac, name in (data.get("bt_names") or {}).items():
        s.bt_names[str(mac)] = str(name)
    return s


def save(settings: Settings, path: Path) -> None:
    """Atomic write: tmp file + rename, so a power yank mid-save can never
    leave a corrupt settings file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=1))
    os.replace(tmp, path)

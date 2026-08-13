"""Settings survive power yanks (decision 10) and hold per-output volume.

The device is unplugged mid-service as a matter of course, so a half-written
settings file must never be possible and a corrupt one must never stop it
booting.
"""

import json

from alabanza.settings import DEFAULT_VOLUMES, Settings, load, save


def test_a_save_is_atomic_and_leaves_no_temp_behind(tmp_path):
    path = tmp_path / "settings.json"
    save(Settings(output="bluetooth"), path)
    assert json.loads(path.read_text())["output"] == "bluetooth"
    assert list(tmp_path.iterdir()) == [path]     # the tmp file was renamed away


def test_it_creates_the_directory_on_first_save(tmp_path):
    path = tmp_path / "writable" / "settings.json"
    save(Settings(), path)
    assert path.exists()


def test_a_corrupt_file_falls_back_to_defaults_instead_of_crashing(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json")
    assert load(path).output == "jack"


def test_a_missing_file_falls_back_to_defaults(tmp_path):
    assert load(tmp_path / "never-written.json").output == "jack"


def test_a_garbage_output_is_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"output": "telepathy"}))
    assert load(path).output == "jack"


def test_out_of_range_volumes_are_clamped(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"volumes": {"jack": 500, "hdmi": -20}}))
    settings = load(path)
    assert settings.volumes["jack"] == 100
    assert settings.volumes["hdmi"] == 0


def test_a_round_trip_keeps_everything(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(output="bluetooth", last_bt_device="AA:BB:CC:00:00:01",
                        bt_names={"AA:BB:CC:00:00:01": "JBL Flip 5"})
    original.volumes["bluetooth"] = 42
    save(original, path)
    restored = load(path)
    assert restored.output == "bluetooth"
    assert restored.volumes["bluetooth"] == 42
    assert restored.last_bt_device == "AA:BB:CC:00:00:01"
    assert restored.bt_names == {"AA:BB:CC:00:00:01": "JBL Flip 5"}


def test_an_old_settings_file_without_bt_names_still_loads(tmp_path):
    """Forward compatibility: the Bluetooth work added a field."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"output": "hdmi", "volumes": {"hdmi": 70}}))
    settings = load(path)
    assert settings.output == "hdmi"
    assert settings.bt_names == {}


class TestPerOutputVolume:
    def test_volume_follows_the_selected_output(self):
        settings = Settings()
        assert settings.volume == DEFAULT_VOLUMES["jack"]
        settings.output = "bluetooth"
        assert settings.volume == DEFAULT_VOLUMES["bluetooth"]

    def test_setting_it_only_touches_the_current_output(self):
        settings = Settings(output="bluetooth")
        settings.volume = 30
        assert settings.volumes["bluetooth"] == 30
        assert settings.volumes["jack"] == DEFAULT_VOLUMES["jack"]

    def test_outputs_cycle_and_come_back_round(self):
        settings = Settings()
        assert [settings.next_output() for _ in range(3)] == [
            "bluetooth", "hdmi", "jack"]

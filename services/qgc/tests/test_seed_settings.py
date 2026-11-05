import configparser
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "seed_settings", Path(__file__).resolve().parents[1] / "seed_settings.py"
)
seed_settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_settings)


def read(path):
    cp = configparser.ConfigParser(interpolation=None, delimiters=("=",))
    cp.optionxform = str
    cp.read(path)
    return cp


def test_fresh_file_has_version_router_link_and_no_udp(tmp_path):
    f = tmp_path / "QGroundControl.ini"
    assert seed_settings.seed(f)
    cp = read(f)
    assert cp["General"]["SettingsVersion"] == "9"
    assert cp["General"]["gcsMavlinkSystemID"] == "254", (
        "distinct from Lyrebird dashboard/ROS (255)"
    )
    assert cp["General"]["sendGCSHeartbeat"] == "true"
    assert cp["General"]["preferredFirmwareClass"] == "12", "PX4 (Lyrebird)"
    assert cp["General"]["preferredVehicleClass"] == "2", "Multi-Rotor"
    assert cp["General"]["firstRunPromptIdsShown"] == "3", "no first-run dialog"
    assert cp["AutoConnect"]["autoConnectUDP"] == "false"
    links = cp["LinkConfigurations"]
    assert links["count"] == "1"
    assert links["Link0\\type"] == "2"
    assert links["Link0\\host"] == "127.0.0.1"
    assert links["Link0\\port"] == "5760"
    assert links["Link0\\auto"] == "true"
    assert "Link0\\name=" in f.read_text()  # QSettings format: no spaces around '='


def test_idempotent(tmp_path):
    f = tmp_path / "QGroundControl.ini"
    seed_settings.seed(f)
    assert not seed_settings.seed(f)


def test_user_links_and_settings_are_kept_udp_is_enforced(tmp_path):
    f = tmp_path / "QGroundControl.ini"
    f.write_text(
        "[General]\nSettingsVersion=9\nUserKey=keep\n\n[AutoConnect]\nautoConnectUDP=true\n\n"
        "[LinkConfigurations]\ncount=1\nLink0\\name=Feld-Laptop\nLink0\\type=1\n"
    )
    assert seed_settings.seed(f, port=5761)
    cp = read(f)
    assert cp["General"]["UserKey"] == "keep"
    assert cp["AutoConnect"]["autoConnectUDP"] == "false"
    links = cp["LinkConfigurations"]
    assert links["Link0\\name"] == "Feld-Laptop"
    assert links["Link1\\name"] == seed_settings.ROUTER_LINK_NAME
    assert links["Link1\\port"] == "5761"
    assert links["count"] == "2"


def test_router_link_is_updated_in_place(tmp_path):
    f = tmp_path / "QGroundControl.ini"
    seed_settings.seed(f, port=5760)
    seed_settings.seed(f, port=5770)
    links = read(f)["LinkConfigurations"]
    assert links["count"] == "1"
    assert links["Link0\\port"] == "5770"


def test_user_system_id_is_kept_and_range_checked(tmp_path):
    import pytest

    f = tmp_path / "QGroundControl.ini"
    f.write_text(
        "[General]\nSettingsVersion=9\ngcsMavlinkSystemID=200\nsendGCSHeartbeat=false\n"
    )
    seed_settings.seed(f)
    general = read(f)["General"]
    assert general["gcsMavlinkSystemID"] == "200"
    assert general["sendGCSHeartbeat"] == "true"
    with pytest.raises(ValueError):
        seed_settings.seed(tmp_path / "x.ini", system_id=0)


def test_user_vehicle_preferences_are_kept(tmp_path):
    f = tmp_path / "QGroundControl.ini"
    f.write_text(
        "[General]\nSettingsVersion=9\npreferredFirmwareClass=3\nfirstRunPromptIdsShown=3,7\n"
    )
    seed_settings.seed(f)
    general = read(f)["General"]
    assert general["preferredFirmwareClass"] == "3"
    assert general["firstRunPromptIdsShown"] == "3,7"

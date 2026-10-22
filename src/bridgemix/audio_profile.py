"""Manage saved audio-rate preferences and Windows-style PipeWire endpoints."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

from bridgemix.paths import config_dir

RATE = 96_000
HARDWARE_RATE = 48_000
CHANNEL_MAP = "[ FL FR ]"
SERVICE_NAME = "bridgemix-audio-profile.service"
_LOGGER = logging.getLogger(__name__)

OUTPUT_ENDPOINTS = (
    ("chat", "CHAT", 1),
    ("game", "GAME", 2),
    ("music", "MUSIC", 3),
    ("system", "SYSTEM", 4),
)
INPUT_ENDPOINTS = (
    ("stream", "STREAM", 5),
    ("mic", "MIC", 6),
    ("sub_mix", "SUB MIX", 7),
)


class ProfileError(RuntimeError):
    pass


def _state_paths() -> tuple[Path, Path]:
    state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    directory = state_home / "bridgecast-linux"
    return directory, directory / "pipewire-96.json"


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ProfileError(f"command failed ({result.returncode}): {command[0]}: {detail}")
    return result


def _require_tools() -> tuple[str, str]:
    if sys.platform != "linux" or not Path("/proc").is_dir():
        raise ProfileError("this profile must run on Linux")
    pactl = shutil.which("pactl")
    pw_loopback = shutil.which("pw-loopback")
    if not pactl:
        raise ProfileError("pactl is required to find the PipeWire UCM endpoints")
    if not pw_loopback:
        raise ProfileError("pw-loopback is required (PipeWire 0.3.60 or newer)")
    _run([pactl, "info"])
    return pactl, pw_loopback


def _objects(pactl: str, kind: str) -> dict[str, str]:
    result = _run([pactl, "list", "short", kind])
    found: dict[str, str] = {}
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) >= 4:
            found[fields[1]] = fields[3]
    return found


def _hardware_node(pactl: str, kind: str, line: int, direction: str) -> str:
    pattern = re.compile(rf"Roland_BRIDGE_CAST_V2.*HiFi__Line{line}__{direction}$")
    matches = [name for name in _objects(pactl, kind) if pattern.search(name)]
    if len(matches) != 1:
        raise ProfileError(
            f"expected one BRIDGE CAST V2 Line{line} {direction}, found {len(matches)}; "
            "check that the ALSA UCM HiFi profile is active"
        )
    return matches[0]


def _info_defaults(pactl: str) -> tuple[str, str]:
    result = _run([pactl, "info"])
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.startswith("Default Sink:"):
            values["sink"] = line.split(":", 1)[1].strip()
        elif line.startswith("Default Source:"):
            values["source"] = line.split(":", 1)[1].strip()
    return values.get("sink", ""), values.get("source", "")


def _settings_path() -> Path:
    return config_dir() / "audio-profile.json"


def get_sample_rate() -> int:
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return HARDWARE_RATE
    rate = data.get("sample_rate") if isinstance(data, dict) else None
    return rate if rate in (HARDWARE_RATE, RATE) else HARDWARE_RATE


def _save_sample_rate(rate: int) -> None:
    if rate not in (HARDWARE_RATE, RATE):
        raise ProfileError("sample rate must be 48000 or 96000")
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump({"sample_rate": rate}, stream, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def is_available() -> bool:
    if sys.platform != "linux" or not all(shutil.which(name) for name in ("pactl", "pw-loopback", "systemctl")):
        return False
    return (
        subprocess.run(["systemctl", "--user", "show-environment"], check=False, capture_output=True).returncode == 0
        and subprocess.run(["pactl", "info"], check=False, capture_output=True).returncode == 0
    )


def _systemd_config_dir() -> Path:
    return config_dir().parent / "systemd" / "user"


def _systemd_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


def _service_unit_text() -> str:
    config_home = config_dir().parent
    raw_state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    state_home = Path(raw_state_home) if raw_state_home and Path(raw_state_home).is_absolute() else Path.home() / ".local" / "state"
    python = _systemd_quote(sys.executable)
    return "\n".join(
        (
            "[Unit]",
            "Description=BridgeMix Windows-style PipeWire audio endpoints",
            "Wants=pipewire.service pipewire-pulse.service wireplumber.service",
            "After=pipewire.service pipewire-pulse.service wireplumber.service",
            "",
            "[Service]",
            "Type=oneshot",
            "RemainAfterExit=yes",
            f"Environment={_systemd_quote('XDG_CONFIG_HOME=' + str(config_home))}",
            f"Environment={_systemd_quote('XDG_STATE_HOME=' + str(state_home))}",
            f"ExecStart={python} -m bridgemix.audio_profile service-start",
            f"ExecStop={python} -m bridgemix.audio_profile service-stop",
            "TimeoutStartSec=20",
            "TimeoutStopSec=20",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        )
    )


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise ProfileError("systemctl is required for persistent per-login audio endpoints")
    return _run([systemctl, "--user", *args], check=check)


def _service_enabled() -> bool:
    return _systemctl("is-enabled", SERVICE_NAME, check=False).returncode == 0


def _service_active() -> bool:
    return _systemctl("is-active", SERVICE_NAME, check=False).returncode == 0


def service_state() -> tuple[bool, bool]:
    """Return (enabled-at-login, active-now) without raising on missing systemd."""
    if not shutil.which("systemctl"):
        return False, False
    try:
        return _service_enabled(), _service_active()
    except ProfileError:
        return False, False


def install_service() -> Path:
    """Install/reload the disabled user unit; enabling follows the user's rate choice."""
    _systemctl("show-environment")
    unit_path = _systemd_config_dir() / SERVICE_NAME
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=unit_path.parent, delete=False) as stream:
        stream.write(_service_unit_text())
        temporary = Path(stream.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, unit_path)
    _systemctl("daemon-reload")
    return unit_path


def _reconcile_service(rate: int) -> None:
    if rate == RATE:
        install_service()
        if not _service_enabled():
            _systemctl("enable", SERVICE_NAME)
        if _service_active():
            _systemctl("restart", SERVICE_NAME)
        else:
            _systemctl("start", SERVICE_NAME)
        return

    if _service_enabled() or _service_active():
        _systemctl("disable", "--now", SERVICE_NAME)
    else:
        _stop_profile()


def apply_sample_rate(rate: int) -> str:
    """Persist the UI choice and apply it now plus on subsequent logins."""
    if rate not in (HARDWARE_RATE, RATE):
        raise ProfileError("sample rate must be 48000 or 96000")
    old_rate = get_sample_rate()
    _save_sample_rate(rate)
    try:
        if rate == RATE:
            _reconcile_service(RATE)
            return "96 kHz endpoints active and enabled for user login."
        _reconcile_service(HARDWARE_RATE)
        return "96 kHz endpoints stopped; using the native 48 kHz USB profile."
    except (ProfileError, OSError, subprocess.SubprocessError):
        _save_sample_rate(old_rate)
        try:
            _reconcile_service(old_rate)
        except (ProfileError, OSError, subprocess.SubprocessError) as rollback_error:
            _LOGGER.warning("could not restore the previous audio profile: %s", rollback_error)
        raise


def remove_service() -> None:
    """Disable and remove the user unit; leave the rate preference intact."""
    if shutil.which("systemctl"):
        _systemctl("disable", "--now", SERVICE_NAME, check=False)
    _stop_profile()
    unit_path = _systemd_config_dir() / SERVICE_NAME
    unit_path.unlink(missing_ok=True)
    if shutil.which("systemctl"):
        _systemctl("daemon-reload", check=False)


def _loopback_command(
    pw_loopback: str,
    direction: str,
    slug: str,
    label: str,
    hardware_node: str,
) -> tuple[str, list[str]]:
    virtual_name = f"bridgecast_v2_{slug}_96"
    process_name = f"bridgecast_v2_{slug}_loop"
    common = [
        pw_loopback,
        "--name",
        process_name,
        "--channels",
        "2",
        "--channel-map",
        CHANNEL_MAP,
    ]
    description = f'"{label} (BRIDGE CAST V2) 96 kHz"'

    if direction == "sink":
        capture_props = (
            f"node.name={virtual_name} media.class=Audio/Sink "
            f"node.description={description} audio.rate={RATE} audio.channels=2 "
            f"audio.position={CHANNEL_MAP}"
        )
        playback_props = (
            f"node.name={process_name}_hardware node.description={description} "
            f"audio.rate={HARDWARE_RATE} audio.channels=2 "
            f"audio.position={CHANNEL_MAP} node.passive=true stream.dont-remix=true"
        )
        command = common + [
            "--playback",
            hardware_node,
            "--capture-props",
            capture_props,
            "--playback-props",
            playback_props,
        ]
    else:
        capture_props = (
            f"node.name={process_name}_hardware node.description={description} "
            f"audio.rate={HARDWARE_RATE} audio.channels=2 "
            f"audio.position={CHANNEL_MAP} node.passive=true stream.dont-remix=true"
        )
        playback_props = (
            f"node.name={virtual_name} media.class=Audio/Source "
            f"node.description={description} audio.rate={RATE} audio.channels=2 "
            f"audio.position={CHANNEL_MAP} stream.dont-remix=true"
        )
        command = common + [
            "--capture",
            hardware_node,
            "--capture-props",
            capture_props,
            "--playback-props",
            playback_props,
        ]
    return process_name, command


def _write_state(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump({"version": 1, "processes": records}, stream)
        stream.write("\n")
        temporary = Path(stream.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _read_state(path: Path) -> list[dict[str, object]]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"cannot read profile state {path}: {exc}") from exc
    if state.get("version") != 1 or not isinstance(state.get("processes"), list):
        raise ProfileError(f"unsupported profile state format: {path}")
    return state["processes"]


def _process_matches(record: dict[str, object]) -> bool:
    try:
        pid = int(record["pid"])
        expected_name = str(record["process_name"])
        raw = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (KeyError, ValueError, OSError):
        return False
    arguments = [os.fsdecode(item) for item in raw if item]
    has_pw_loopback = any(Path(argument).name == "pw-loopback" for argument in arguments)
    return has_pw_loopback and expected_name in arguments


def _stop_processes(records: list[dict[str, object]], timeout: float = 4.0) -> list[dict[str, object]]:
    remaining: list[dict[str, object]] = []
    for record in reversed(records):
        if not _process_matches(record):
            continue
        pid = int(record["pid"])
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and _process_matches(record):
            time.sleep(0.1)
        if _process_matches(record):
            remaining.append(record)
    return list(reversed(remaining))


def _live_nodes(pactl: str) -> tuple[dict[str, str], dict[str, str]]:
    return _objects(pactl, "sinks"), _objects(pactl, "sources")


def _expected_nodes() -> tuple[set[str], set[str]]:
    return (
        {f"bridgecast_v2_{slug}_96" for slug, _, _ in OUTPUT_ENDPOINTS},
        {f"bridgecast_v2_{slug}_96" for slug, _, _ in INPUT_ENDPOINTS},
    )


def _nodes_ready(pactl: str) -> tuple[bool, list[str]]:
    sinks, sources = _live_nodes(pactl)
    expected_sinks, expected_sources = _expected_nodes()
    missing: list[str] = []
    for name in sorted(expected_sinks):
        if name not in sinks or "96000Hz" not in sinks[name]:
            missing.append(name)
    for name in sorted(expected_sources):
        if name not in sources or "96000Hz" not in sources[name]:
            missing.append(name)
    return not missing, missing


def _profile_active(pactl: str, records: list[dict[str, object]]) -> bool:
    expected_sinks, expected_sources = _expected_nodes()
    if len(records) != len(expected_sinks) + len(expected_sources):
        return False
    return all(_process_matches(record) for record in records) and _nodes_ready(pactl)[0]


def _start_profile(pactl: str, pw_loopback: str, state_path: Path) -> None:
    if state_path.exists():
        previous = _read_state(state_path)
        if _profile_active(pactl, previous):
            print("BRIDGE CAST Windows-style 96 kHz endpoints are already active.")
            return
        remaining = _stop_processes(previous)
        if remaining:
            raise ProfileError("stale loopback processes did not stop; inspect profile state before retrying")
        state_path.unlink(missing_ok=True)

    # Resolve every physical endpoint before starting any child process.
    hardware: list[tuple[str, str, str, str]] = []
    for slug, label, line in OUTPUT_ENDPOINTS:
        hardware.append(("sink", slug, label, _hardware_node(pactl, "sinks", line, "sink")))
    for slug, label, line in INPUT_ENDPOINTS:
        hardware.append(("source", slug, label, _hardware_node(pactl, "sources", line, "source")))

    expected_sinks, expected_sources = _expected_nodes()
    sinks, sources = _live_nodes(pactl)
    collisions = sorted((expected_sinks & sinks.keys()) | (expected_sources & sources.keys()))
    if collisions:
        raise ProfileError("virtual endpoint names already exist outside this profile: " + ", ".join(collisions))

    defaults_before = _info_defaults(pactl)
    records: list[dict[str, object]] = []
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(state_path.parent, 0o700)

    try:
        with ExitStack() as logs:
            for direction, slug, label, hardware_node in hardware:
                process_name, command = _loopback_command(pw_loopback, direction, slug, label, hardware_node)
                log = logs.enter_context(tempfile.TemporaryFile(mode="w+b"))
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    start_new_session=True,
                )
                records.append({"pid": process.pid, "process_name": process_name})
                _write_state(state_path, records)

            deadline = time.monotonic() + 8.0
            ready = False
            missing: list[str] = []
            while time.monotonic() < deadline:
                dead = [record for record in records if not _process_matches(record)]
                if dead:
                    names = ", ".join(str(record["process_name"]) for record in dead)
                    raise ProfileError(f"pw-loopback exited during startup: {names}")
                ready, missing = _nodes_ready(pactl)
                if ready:
                    break
                time.sleep(0.1)
            if not ready:
                raise ProfileError("96 kHz PipeWire nodes did not appear: " + ", ".join(missing))

            defaults_after = _info_defaults(pactl)
            if defaults_after != defaults_before:
                raise ProfileError("the default audio devices changed during startup; profile rolled back")
    except (ProfileError, OSError, subprocess.SubprocessError):
        remaining = _stop_processes(records)
        if not remaining:
            state_path.unlink(missing_ok=True)
        raise

    print("Loaded four 96 kHz playback sinks and three 96 kHz capture sources.")
    print("PipeWire converts to/from the matching 48 kHz UCM lines; defaults were unchanged.")


def _stop_profile(state_path: Path) -> None:
    if not state_path.exists():
        print("BRIDGE CAST Windows-style 96 kHz endpoints are not managed by this profile.")
        return
    records = _read_state(state_path)
    remaining = _stop_processes(records)
    if remaining:
        _write_state(state_path, remaining)
        names = ", ".join(str(record["process_name"]) for record in remaining)
        raise ProfileError("some pw-loopback processes did not stop: " + names)
    state_path.unlink(missing_ok=True)
    print("Unloaded the optional BRIDGE CAST 96 kHz endpoints.")


def _status(pactl: str, state_path: Path) -> None:
    if not state_path.exists():
        print("BRIDGE CAST Windows-style 96 kHz endpoints are not loaded.")
        return
    records = _read_state(state_path)
    sinks, sources = _live_nodes(pactl)
    expected_sinks, expected_sources = _expected_nodes()
    print("Sinks:")
    for name in sorted(expected_sinks):
        print(f"  {name}: {sinks.get(name, 'missing')}")
    print("Sources:")
    for name in sorted(expected_sources):
        print(f"  {name}: {sources.get(name, 'missing')}")
    print(f"pw-loopback processes: {sum(_process_matches(record) for record in records)}/{len(records)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("start", "stop", "status", "apply-rate", "service-start", "service-stop", "install-service", "remove-service"),
    )
    parser.add_argument("rate", nargs="?")
    args = parser.parse_args()
    _, state_path = _state_paths()
    try:
        if args.action == "stop" or args.action == "service-stop":
            _stop_profile(state_path)
        elif args.action == "install-service":
            print(install_service())
        elif args.action == "remove-service":
            remove_service()
        elif args.action == "apply-rate":
            if args.rate is None:
                raise ProfileError("apply-rate requires 48000 or 96000")
            print(apply_sample_rate(int(args.rate)))
        elif args.action == "service-start":
            if get_sample_rate() == RATE:
                pactl, pw_loopback = _require_tools()
                _start_profile(pactl, pw_loopback, state_path)
            else:
                _stop_profile(state_path)
        elif args.action == "start":
            pactl, pw_loopback = _require_tools()
            _start_profile(pactl, pw_loopback, state_path)
        else:
            pactl, _ = _require_tools()
            _status(pactl, state_path)
    except (ProfileError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"bridgecast-96: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

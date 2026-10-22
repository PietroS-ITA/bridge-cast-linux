import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from bridgemix import audio_profile


class LoopbackCommandTests(unittest.TestCase):
    def test_playback_sink_exposes_96_and_targets_48_line(self):
        name, command = audio_profile._loopback_command(
            "/usr/bin/pw-loopback",
            "sink",
            "game",
            "GAME",
            "alsa_output.usb-Roland_BRIDGE_CAST_V2-test.HiFi__Line2__sink",
        )

        self.assertEqual(name, "bridgecast_v2_game_loop")
        self.assertEqual(
            command[command.index("--playback") + 1],
            "alsa_output.usb-Roland_BRIDGE_CAST_V2-test.HiFi__Line2__sink",
        )
        capture = command[command.index("--capture-props") + 1]
        playback = command[command.index("--playback-props") + 1]
        self.assertIn("media.class=Audio/Sink", capture)
        self.assertIn("audio.rate=96000", capture)
        self.assertIn("audio.rate=48000", playback)

    def test_capture_source_exposes_96_from_48_line(self):
        name, command = audio_profile._loopback_command(
            "/usr/bin/pw-loopback",
            "source",
            "stream",
            "STREAM",
            "alsa_input.usb-Roland_BRIDGE_CAST_V2-test.HiFi__Line5__source",
        )

        self.assertEqual(name, "bridgecast_v2_stream_loop")
        self.assertEqual(
            command[command.index("--capture") + 1],
            "alsa_input.usb-Roland_BRIDGE_CAST_V2-test.HiFi__Line5__source",
        )
        capture = command[command.index("--capture-props") + 1]
        playback = command[command.index("--playback-props") + 1]
        self.assertIn("audio.rate=48000", capture)
        self.assertIn("media.class=Audio/Source", playback)
        self.assertIn("audio.rate=96000", playback)

    def test_endpoint_map_matches_windows_channel_splits(self):
        self.assertEqual(
            audio_profile.OUTPUT_ENDPOINTS,
            (("chat", "CHAT", 1), ("game", "GAME", 2), ("music", "MUSIC", 3), ("system", "SYSTEM", 4)),
        )
        self.assertEqual(
            audio_profile.INPUT_ENDPOINTS,
            (("stream", "STREAM", 5), ("mic", "MIC", 6), ("sub_mix", "SUB MIX", 7)),
        )

    def test_hardware_node_selects_only_matching_v2_ucm_line(self):
        devices = {
            "alsa_output.usb-Roland_BRIDGE_CAST_V2-test.HiFi__Line2__sink": "float32le 2ch 48000Hz",
            "alsa_output.usb-Roland_BRIDGE_CAST_V2-test.HiFi__Line3__sink": "float32le 2ch 48000Hz",
        }
        with patch.object(audio_profile, "_objects", return_value=devices):
            node = audio_profile._hardware_node("pactl", "sinks", 2, "sink")
        self.assertTrue(node.endswith("HiFi__Line2__sink"))

    def test_nodes_ready_requires_96_khz_on_all_expected_nodes(self):
        sinks = {name: "float32le 2ch 96000Hz" for name in audio_profile._expected_nodes()[0]}
        sources = {name: "float32le 2ch 96000Hz" for name in audio_profile._expected_nodes()[1]}
        with patch.object(audio_profile, "_live_nodes", return_value=(sinks, sources)):
            self.assertEqual(audio_profile._nodes_ready("pactl"), (True, []))

        sources[next(iter(sources))] = "float32le 2ch 48000Hz"
        with patch.object(audio_profile, "_live_nodes", return_value=(sinks, sources)):
            ready, missing = audio_profile._nodes_ready("pactl")
        self.assertFalse(ready)
        self.assertEqual(len(missing), 1)


class PersistentRateSettingsTests(unittest.TestCase):
    def test_sample_rate_defaults_to_usb_rate_and_persists(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": directory}
        ):
            self.assertEqual(audio_profile.get_sample_rate(), 48_000)
            audio_profile._save_sample_rate(96_000)
            self.assertEqual(audio_profile.get_sample_rate(), 96_000)
            saved = json.loads((Path(directory) / "bridgemix" / "audio-profile.json").read_text())
            self.assertEqual(saved, {"sample_rate": 96_000})

    def test_invalid_sample_rate_is_rejected(self):
        with self.assertRaises(audio_profile.ProfileError):
            audio_profile._save_sample_rate(88_200)

    def test_user_service_unit_waits_for_pipewire_and_runs_saved_profile(self):
        unit = audio_profile._service_unit_text()
        self.assertIn("Type=oneshot", unit)
        self.assertIn("RemainAfterExit=yes", unit)
        self.assertIn("After=pipewire.service pipewire-pulse.service", unit)
        self.assertIn("bridgemix.audio_profile service-start", unit)
        self.assertIn("WantedBy=default.target", unit)
        self.assertNotIn("ExecStartPre=", unit)

    def test_install_service_writes_user_unit_without_enabling_it(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": directory}
        ), patch.object(audio_profile, "_systemctl") as systemctl:
            unit_path = audio_profile.install_service()
            unit_text = unit_path.read_text(encoding="utf-8")
            self.assertTrue(unit_path.exists())
            self.assertIn("ExecStart=", unit_text)
            self.assertIn("ExecStop=", unit_text)
            self.assertIn("WantedBy=default.target", unit_text)
            self.assertIn(call("daemon-reload"), systemctl.call_args_list)
            self.assertFalse(any("enable" in args for args, _ in systemctl.call_args_list))

    def test_setting_96_enables_and_starts_login_service(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": directory}
        ), patch.object(audio_profile, "install_service"), patch.object(
            audio_profile, "_service_enabled", return_value=False
        ), patch.object(audio_profile, "_service_active", return_value=False), patch.object(
            audio_profile, "_systemctl"
        ) as systemctl:
            message = audio_profile.apply_sample_rate(96_000)
            self.assertEqual(audio_profile.get_sample_rate(), 96_000)
            self.assertIn(call("enable", audio_profile.SERVICE_NAME), systemctl.call_args_list)
            self.assertIn(call("start", audio_profile.SERVICE_NAME), systemctl.call_args_list)
            self.assertIn("login", message)

    def test_setting_48_disables_and_stops_login_service(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": directory}
        ), patch.object(audio_profile, "_service_enabled", return_value=True), patch.object(
            audio_profile, "_service_active", return_value=True
        ), patch.object(audio_profile, "_systemctl") as systemctl:
            audio_profile._save_sample_rate(96_000)
            message = audio_profile.apply_sample_rate(48_000)
            self.assertEqual(audio_profile.get_sample_rate(), 48_000)
            self.assertIn(
                call("disable", "--now", audio_profile.SERVICE_NAME),
                systemctl.call_args_list,
            )
            self.assertIn("stopped", message)


if __name__ == "__main__":
    unittest.main()

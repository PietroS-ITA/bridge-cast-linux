# BRIDGE CAST Linux: session handoff

## Goal and decision

The goal is to replicate the Windows-facing 96 kHz BRIDGE CAST V2 endpoints on
Linux. The user now accepts the same host-side rate conversion as Windows: apps
see 96 kHz stereo endpoints while the USB device remains at 48 kHz. Do not
describe this as native 96 kHz hardware transport.

## Repository

- Repository: https://github.com/PietroS-ITA/bridge-cast-linux
- Branch: `master`
- Public source project retained as remote `upstream`: Ex0danify/BridgeMix
- Continue from the latest commit on `master`; the persistent audio-profile work follows the WASAPI probe.
- The Windows capture helper is `tools/capture-bridgecast-usb.ps1`.
- The detailed investigation is `doc/LINUX_96KHZ.md`.

## What already works

- The Linux kernel binds the device (`0582:031e`) to `snd-usb-audio`.
- ALSA exposes the V2's 14-channel playback and 6-channel capture streams at
  48,000 Hz, with 24-bit samples in 32-bit subframes.
- BridgeMix already provides the Linux control application. A real MIDI/SysEx
  handshake succeeded with the connected V2, firmware `3.00 (130)`.
- Full suite passed: 253 passed, 2 skipped.

## Windows USB capture findings

The supplied 45.8-second USBPcap capture was not copied into this repository.
It contains about 3.31 MB of isochronous payload, potentially audio; the payload
was not decoded or saved.

The device was enumerated while the user reported Windows Driver Settings was
set to 96 kHz. The 221-byte USB configuration still advertised only 48,000 Hz:

- Playback: 14 channels, maximum packet size 392 bytes at endpoint `0x0d`.
- Capture: 6 channels, maximum packet size 168 bytes at endpoint `0x8e`.
- Observed isochronous packet payloads were 336 bytes for playback and 144 bytes
  for capture. These exactly match `14 x 4 x 48,000` and `6 x 4 x 48,000` bytes
  per second over 8,000 high-speed USB intervals.
- The same packet sizes appeared in both stream-restart windows. No 96,000 Hz
  audio alternate format or vendor-specific USB control/bulk rate command was
  observed. The control traffic included HID setup and standard
  `SET_INTERFACE` changes between alternate settings 0 and 1.
- Full 14-channel playback and 6-channel capture at 96 kHz would require 672
  and 288 bytes per USB interval, exceeding endpoint maxima of 392 and 168.
  A narrower channel map could fit in theory, but none is advertised.

Conclusion: the capture provides no 96 kHz USB mode to port. The Windows-facing
96 kHz endpoint must be reproduced as a host-side format/conversion path; do not
add an ALSA hardware rate override.

## Windows WASAPI probe

The Roland Windows driver `2.0.0.0` was queried using WASAPI. The probe called
`GetMixFormat` and `IsFormatSupported` only; it did not initialize or start audio
streams. Every active BRIDGE CAST V2 endpoint reported a 96,000 Hz, 2-channel
WAVEFORMATEXTENSIBLE float32 mix format with a stereo channel mask. Exclusive
mode accepted PCM16 and 24-valid-bit PCM in a 32-bit container at 96,000 Hz.
Shared mode used 96,000 Hz as the exact mix format and returned it as the
closest format for 44.1 and 48 kHz queries.

This is the format exposed to Windows applications, not evidence of 96 kHz USB
transport. The WASAPI endpoints are stereo, while USB remains 14-channel
playback and 6-channel capture at 48 kHz. The user requests replicating this
application-facing Windows behavior on Linux using explicit host-side
conversion.

If USBPcap is needed again, run `tools/capture-bridgecast-usb.ps1` from an
elevated PowerShell console. Keep capture files outside Git; they can contain
USB identifiers and audio payload.

The read-only WASAPI probe is `tools/probe-wasapi-formats.ps1`; run it from
PowerShell with `-ExecutionPolicy Bypass` if the local policy blocks unsigned
scripts. It does not require Administrator privileges.

`tools/bridgecast-96.py` now provides reversible PipeWire `pw-loopback` nodes
that map UCM Lines 1-7 to 96 kHz stereo endpoints and resample to/from 48 kHz.
On Linux with PipeWire 1.6.9, all seven nodes reported 96 kHz and the default
sink/source remained unchanged. The selected 96 kHz profile is currently active
and enabled for the user's next login.

Run `python3 -m unittest discover -s tests -p test_bridgecast_96.py` for the
profile, settings, and service tests. A live endpoint test confirmed the rate
formats; no audio was played or captured samples inspected.

## Persistent application setting

The Linux sidebar now has an `AUDIO` page with a 48/96 kHz selector. The
preference is saved to `~/.config/bridgemix/audio-profile.json`. Choosing 96 kHz
enables and starts the per-user `bridgemix-audio-profile.service`; choosing
48 kHz stops and disables it. The user service is installed disabled by
`setup.sh --install` and removed by `setup.sh --uninstall`.

The user's current preference is 96 kHz and the systemd user service is enabled
and active. It was intentionally left running so the user can select the new
endpoints in applications. The USB transport remains 48 kHz; this is the same
application-facing conversion model as Windows.

The interface was kept in the existing Python/PyQt6 application. A full Rust
rewrite was rejected because it would duplicate the MIDI/control/plugin stack
without improving this audio-profile feature.

## Prompt for the Linux validation session

```text
Read doc/SESSION_HANDOFF.md and doc/LINUX_96KHZ.md. The app now exposes 48/96
kHz in its Linux AUDIO page and persists the choice through a systemd user
service. Keep default sinks/sources unchanged and do not claim native 96 kHz
USB transport. The active user preference is 96 kHz.
```

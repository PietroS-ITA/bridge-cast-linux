# BRIDGE CAST V2 on Linux: 96 kHz investigation

## Goal

Replicate the Windows-facing 96 kHz BRIDGE CAST V2 endpoints on Linux while
leaving the physical 48 kHz USB transport unchanged. Windows exposes stereo
96 kHz formats to applications and maps them onto the device's existing
multichannel USB streams. Do not describe this as native 96 kHz USB transport,
modify the kernel driver, or send undocumented control commands to the mixer.

## Verified on this machine

- The device enumerates as `Roland Corp. BRIDGE CAST V2` on USB bus 003, device
  008, at High Speed.
- The kernel binds the device to `snd-usb-audio`; ALSA creates card `V2`.
- `/proc/asound/card2/stream0` reports 14 playback channels and 6 capture
  channels, both at 48,000 Hz, 24-bit samples in 32-bit containers.
- The active USB audio alternate settings advertise 48,000 Hz. Their isochronous
  endpoints have maximum packet sizes of 392 bytes (playback) and 168 bytes
  (capture).
- ALSA exposes two MIDI ports named `BRIDGE CAST V2 MIDI 1` and
  `BRIDGE CAST V2 MIDI 2`.
- BridgeMix successfully opened the first MIDI port, completed the SysEx
  handshake, identified `Bridge Cast V2` firmware `3.00 (130)`, and started
  state synchronization. The app then disconnected cleanly.
- The existing BridgeMix application supports the original BRIDGE CAST and V2
  and controls the mixer over MIDI SysEx. It does not implement or replace the
  USB audio driver and does not select the audio sample rate.

Device serial numbers are intentionally not recorded here.

## Roland's documented Windows behavior

Roland states that BRIDGE CAST supports 44.1, 48, and 96 kHz and documents
changing the rate through the Windows `BRIDGE CAST Driver Settings` utility,
after closing applications using the device:

- [Windows 10 instructions](https://support.roland.com/hc/en-us/articles/12263418911259-BRIDGE-CAST-How-do-I-change-the-sample-rate-of-BRIDGE-CAST-in-Windows-10)
- [Windows 11 instructions](https://support.roland.com/hc/en-us/articles/17006825878811-BRIDGE-CAST-How-do-I-change-the-sample-rate-of-BRIDGE-CAST-in-Windows-11)

Roland's product specifications explicitly distinguish the operating systems:
Windows supports 44.1/48/96 kHz, while macOS, iOS, and "Other" are specified at
48 kHz. Linux's current 48 kHz limit is therefore consistent with Roland's
published support matrix, not evidence of a broken ALSA configuration:

- [BRIDGE CAST specifications](https://www.roland.com/us/products/bridge_cast/specifications/)

The user confirms that Windows was already set to 96 kHz while Linux reports
48 kHz. This supports an OS/driver-specific path, but does not reveal whether
Windows changes the device mode, sends a vendor request, or exposes a driver-side
format that is not present in the USB descriptors.

The current Linux descriptor snapshot only proves that the device advertises
48 kHz in its present state. It does not establish whether selecting 96 kHz on
Windows changes the device's descriptors, its firmware state, the driver's
stream format, or some combination of these.

## Windows-to-Linux endpoint mapping

The public ALSA UCM profile already splits the V2's multichannel ALSA streams
into the stereo endpoints used by Windows:

- Playback: `CHAT` -> `Line1` (hardware channels 0-1), `GAME` -> `Line2` (2-3),
  `MUSIC` -> `Line3` (12-13), `SYSTEM` -> `Line4` (10-11).
- Capture: `STREAM` -> `Line5` (hardware channels 0-1), `MIC` -> `Line6` (2-3),
  `SUB MIX` -> `Line7` (4-5).

These channel splits are defined in the
[upstream BridgeCastV2 UCM profile](https://github.com/alsa-project/alsa-ucm-conf/blob/master/ucm2/USB-Audio/Roland/BridgeCastV2-Hifi.conf).

### Capturing the Windows transition

Use Wireshark with USBPcap installed on the physical Windows boot. The
[Wireshark USB capture guide](https://wiki.wireshark.org/CaptureSetup/USB) and
[USBPcap tour](https://desowin.org/usbpcap/tour.html) describe the setup.

The repository includes [`tools/capture-bridgecast-usb.ps1`](../tools/capture-bridgecast-usb.ps1),
which locates USBPcapCMD, selects the root hub containing the BRIDGE CAST, and
starts/stops a capture. Run PowerShell as Administrator from a checkout of this
repository:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\capture-bridgecast-usb.ps1
```

The script writes a `.pcap` file to the system drive root by default. It
automates USBPcap detection and capture; reconnecting the device and changing
96/48 kHz in Roland's settings utility remain manual because no supported
command-line interface for that utility is documented. The script also accepts
`-RootHub` and `-OutputPath` overrides.

1. Close applications that use the BRIDGE CAST as an audio device.
2. In Wireshark, identify the USBPcap root hub that lists the BRIDGE CAST under
   its attached devices. Enable capture of newly connected devices.
3. Start capture, then unplug and reconnect the BRIDGE CAST so enumeration and
   descriptors are included.
4. Open `BRIDGE CAST Driver Settings` and change 96 kHz to 48 kHz, then back to
   96 kHz. Keep DAWs, browsers, games, and other audio clients closed.
5. Stop capture and keep the original `.pcap` or `.pcapng`. Do not filter or
   export only decoded packets; the raw capture is needed to compare control
   transfers and endpoint descriptors.

Do not play or record audio during capture. Save the trace outside the source
repository and share it privately; USB captures can contain the unit's USB
serial number and host/device identifiers. A capture with no active audio stream
should contain configuration/control traffic rather than user audio.

### First Windows capture analysis

The first supplied USBPcap capture lasted 45.8 seconds and contained 2,554
records. The user reported that Windows was set to 96 kHz before capture. On
re-enumeration, the BRIDGE CAST V2 still advertised only 48,000 Hz:

- Playback: 14 channels, 24-bit samples in 32-bit subframes, one 48,000 Hz
  format, endpoint `0x0d`, maximum packet size 392 bytes.
- Capture: 6 channels, 24-bit samples in 32-bit subframes, one 48,000 Hz format,
  endpoint `0x8e`, maximum packet size 168 bytes.
- The configuration descriptor was 221 bytes. No 96,000 Hz alternate audio
  format was present.
- The trace contained no vendor-specific USB control or bulk data requests
  associated with sample-rate selection. The observed control traffic was
  descriptor/HID setup plus standard `SET_INTERFACE` changes between alternate
  settings 0 and 1 on the audio interfaces.
- Stream restarts appeared in two later time windows, but the descriptor did not
  change and the isochronous transfer sizes were effectively identical.
- The isochronous payloads were 336 bytes per playback interval and 144 bytes per
  capture interval in both windows. With 8,000 high-speed USB intervals per
  second, these match `14 x 4 x 48,000` and `6 x 4 x 48,000` bytes per second.
  Full 14-channel playback and 6-channel capture at 96 kHz would require 672 and
  288 bytes per interval, exceeding the advertised endpoint limits of 392 and
  168 bytes. A narrower channel map could fit in theory, but none is advertised
  by this configuration.

This is evidence that Windows' 96 kHz setting is a host-driver format or
conversion path, not a USB mode exposed by the device. It is not sufficient to
claim that Linux can enable native 96 kHz on the hardware. A Linux virtual
96 kHz endpoint could resample to the device's 48 kHz transport, but that would
not provide 96 kHz hardware capture/playback or add fidelity.

The capture also contained about 3.31 MB of isochronous payload across the
playback and capture endpoints. The payload was not decoded or saved in this
repository; treat the supplied capture as potentially containing audio and keep
it private.

### Windows WASAPI probe

On Windows with the Roland driver `2.0.0.0`, a read-only WASAPI probe examined
all active BRIDGE CAST V2 playback and capture endpoints. It called
`IAudioClient::GetMixFormat` and `IsFormatSupported`; it did not initialize or
start an audio stream.

- Every active V2 endpoint reported a 96,000 Hz, 2-channel WAVEFORMATEXTENSIBLE
  float32 mix format with a stereo channel mask.
- In exclusive mode, every V2 endpoint accepted PCM16 and 24-valid-bit PCM in a
  32-bit container at 96,000 Hz. It did not report 44.1 or 48 kHz for these
  exclusive endpoint formats while the selected driver rate was 96 kHz.
- In shared mode, 96 kHz was the exact engine format. Queries at 44.1 and 48 kHz
  returned 96 kHz as the closest shared format.

This establishes that the Windows driver exposes a 2-channel 96 kHz format to
WASAPI applications. It does not establish 96 kHz USB transport: the same unit's
USB descriptors and isochronous payloads remain 48 kHz and expose 14 playback
and 6 capture channels. The Windows driver/device path therefore performs
conversion or channel mapping somewhere between the 2-channel WASAPI format and
the multichannel USB transport. The Linux implementation mirrors the
application-facing format, not a native 96 kHz USB stream.

The repeatable read-only probe is `tools/probe-wasapi-formats.ps1`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\probe-wasapi-formats.ps1
```

## Persistent Windows-style profile

On Linux, BridgeMix adds an `AUDIO` page to the sidebar. Choose 48 or 96 kHz and
press Apply. 48 kHz is the default. Selecting 96 saves the preference under
`~/.config/bridgemix/audio-profile.json`, creates/enables the user systemd
service, and starts the endpoints immediately. It restores them on each login;
selecting 48 stops and disables them.

`setup.sh --install` prepares the user unit without enabling it; enabling is
controlled by the Audio page. `setup.sh --uninstall` stops and removes the unit.
The Rust rewrite was deliberately declined: the existing Python/PyQt6
application and PipeWire integration meet the requirement without a second
implementation of the MIDI/control stack.

The optional profile creates four stereo 96 kHz playback sinks and three stereo
96 kHz capture sources using native PipeWire `pw-loopback` nodes. Each virtual
endpoint is backed by its corresponding UCM `Line1`-`Line7` endpoint at the
hardware's 48 kHz rate; PipeWire resamples between the two sides. The nodes use
stereo float32, matching the Windows mix format. Default sinks and sources are
left unchanged. The installer prepares the disabled user service; selecting 96
in the app enables it. `setup.sh --uninstall` stops and removes the service.

For manual diagnostics in a Linux user session:

```sh
python3 -m bridgemix.audio_profile status
python3 -m bridgemix.audio_profile start
python3 -m bridgemix.audio_profile stop
```

The `pw-loopback` processes are reversible and managed using a private state
file under `${XDG_STATE_HOME:-~/.local/state}/bridgecast-linux/`. Startup fails
safely if any physical UCM line is missing and cleans up partial launches. No
root privileges or persistent PipeWire configuration files are required. Stop
the profile before removing an endpoint that an application is using.

The audio-profile tests run without PipeWire hardware:

```sh
python3 -m unittest discover -s tests -p test_bridgecast_96.py
```

They verify endpoint mappings, persisted preferences, systemd unit generation,
and the independent 96/48 kHz loopback parameters. The live profile was loaded
on PipeWire 1.6.9: all seven virtual endpoints reported 96 kHz while the UCM
hardware endpoints remained at 48 kHz. The default sink and source were
unchanged. No test audio was played or microphone samples inspected.

This gives applications the same 96 kHz endpoint choices as Windows, while the
BRIDGE CAST USB transport remains at 48 kHz. It does not increase the mixer's
hardware sample rate or add fidelity.

## Upstream project

This repository started from [Ex0danify/BridgeMix](https://github.com/Ex0danify/BridgeMix),
licensed under GPL-3.0-or-later. The upstream remote is retained as `upstream`.

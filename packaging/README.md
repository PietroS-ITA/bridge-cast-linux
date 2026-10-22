# Package Installation

## pipx and uv

Install the public GitHub source into an isolated Python environment:

```sh
pipx install 'git+https://github.com/PietroS-ITA/bridge-cast-linux.git'
uv tool install --from 'git+https://github.com/PietroS-ITA/bridge-cast-linux.git' bridgemix
```

After the first PyPI release, use `pipx install bridgemix` or
`uv tool install bridgemix`. The Release workflow builds wheel and source
distributions; PyPI upload is optional and uses Trusted Publishing when enabled.

## Arch Linux

The `bridgemix-git` AUR recipe is in `packaging/arch/PKGBUILD`. To build it from
this repository checkout:

```sh
cd packaging/arch
makepkg -si
```

The recipe uses Arch Python packages. `python-sounddevice` is an AUR dependency.
PipeWire, `pipewire-pulse`, and `alsa-ucm-conf` are optional for the Windows-style
96 kHz endpoint profile; it requires all three to expose the split device lines.

## Linux, macOS, and Windows source installer

`setup.sh` remains the supported conda/venv installer on Linux and macOS;
`setup.bat` handles Windows. The 96 kHz PipeWire service is installed per-user
and is enabled only when selected in BridgeMix's AUDIO settings.

## Registry submission status

The repository contains installable build metadata and an Arch package recipe.
Submitting the recipe to AUR and publishing the first release to PyPI require
maintainer accounts. Configure this repository as a PyPI Trusted Publisher, then
dispatch the Release workflow with its `publish_pypi` option enabled to publish
the wheel and source distribution.

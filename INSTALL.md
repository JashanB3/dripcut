# Installing DripCut

DripCut runs entirely on your machine. Once installed it needs no network, except
to download a Whisper model the first time you transcribe.

**Requirements:** Python 3.10 or newer, FFmpeg, roughly 1 GB of disk for the app and
its dependencies, plus space for whatever you render. Ollama and Faster-Whisper are
optional — every video tool works without them.

---

## macOS

Tuned for Apple Silicon: DripCut uses VideoToolbox hardware encoding when the
FFmpeg build provides it.

```bash
# 1. Homebrew, if you do not have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Python and FFmpeg
brew install python@3.12 ffmpeg

# 3. DripCut
git clone <repo> dripcut && cd dripcut
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 4. Check it
dripcut doctor
dripcut
```

The Homebrew FFmpeg build includes VideoToolbox. If `dripcut doctor` reports
VideoToolbox missing, run `brew reinstall ffmpeg`.

On first launch macOS may ask for permission to read the folder your videos live
in. Grant it, or move your footage under `~/Movies`.

## Linux

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y python3 python3-venv python3-pip ffmpeg

# Fedora
sudo dnf install -y python3 python3-pip ffmpeg

# Arch
sudo pacman -S python python-pip ffmpeg
```

Then:

```bash
git clone <repo> dripcut && cd dripcut
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
dripcut doctor
dripcut
```

On Debian and Ubuntu, `ffmpeg` from the default repositories is fine. There is no
hardware encoding path on Linux in this release; exports use libx264 and are
correspondingly slower.

## Windows

Use PowerShell.

```powershell
# 1. Python from python.org or the Store; tick "Add python.exe to PATH"
python --version

# 2. FFmpeg
winget install Gyan.FFmpeg
#    or: choco install ffmpeg
#    or download from https://www.gyan.dev/ffmpeg/builds/ and add bin\ to PATH

# 3. DripCut
git clone <repo> dripcut
cd dripcut
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

# 4. Check it
dripcut doctor
dripcut
```

If PowerShell refuses to run the activation script:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Windows paths are handled throughout, but note that DripCut is developed and tested
primarily on macOS. Report anything that looks wrong.

---

## FFmpeg

DripCut needs both `ffmpeg` and `ffprobe` on `PATH`. Verify:

```bash
ffmpeg -version
ffprobe -version
```

If they live somewhere unusual, point DripCut at them instead of changing `PATH`:

```bash
dripcut config --set ffmpeg_path=/opt/ffmpeg/bin/ffmpeg
dripcut config --set ffprobe_path=/opt/ffmpeg/bin/ffprobe
```

## Faster-Whisper (transcription)

Installed automatically with DripCut. The *model weights* are not — they download
on first use:

| Model | Download | Notes |
|---|---|---|
| `tiny` | ~75 MB | Fast, rough |
| `base` | ~145 MB | |
| `small` | ~480 MB | **Default.** Good balance on an M1 |
| `medium` | ~1.5 GB | Noticeably slower |
| `large-v3` | ~3 GB | Not recommended on 8 GB |

Trigger the download once while you have a connection:

```bash
dripcut transcribe /path/to/any-short-clip.mp4
```

Change the model with `dripcut config --set ai.whisper_model=base` or on the
Settings page.

## Ollama (analysis)

Only needed for highlights, hooks, titles, summaries and chapters.

```bash
# macOS
brew install ollama        # or download from https://ollama.com

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows: installer from https://ollama.com
```

Then pull the default model and start the server:

```bash
ollama pull qwen2.5:3b
ollama serve
```

DripCut can start the server itself — that is `ai.auto_start_ollama`, on by
default. Use a different model with `dripcut config --set ai.ollama_model=llama3.2`.

---

## Verifying the install

`dripcut doctor` is the single source of truth. It checks Python, FFmpeg, FFprobe,
hardware encoding, Faster-Whisper, the Whisper model, Ollama, the application
folders, write permissions and free space — and every problem it reports comes with
the command that fixes it.

```
✔ OK    Python              3.12.3 (CPython)
✔ OK    FFmpeg              ffmpeg version 6.1.1
✔ OK    Core encoders       224 encoders available (libx264, aac present)
▲ WARN  Ollama server       not reachable at http://127.0.0.1:11434
✔ OK    Free space          41.2 GB available on the output volume
```

A `WARN` means a feature is unavailable, not that DripCut is broken.

## Troubleshooting

**`dripcut: command not found`**
The virtualenv is not active. `source .venv/bin/activate`, or use the full path
`.venv/bin/dripcut`.

**`FFmpeg not found on PATH`**
Install it, or set `ffmpeg_path` as above. Restart your shell after installing.

**Port 7999 already in use**
`dripcut up --port 8080`, or make it permanent with
`dripcut config --set server.port=8080`.

**The browser does not open**
The server is still running — open `http://127.0.0.1:7999` yourself. Disable the
attempt with `dripcut up --no-browser`.

**Exports are very slow on macOS**
Check `dripcut doctor` for VideoToolbox. If it is available but disabled, run
`dripcut config --set video.hardware_accel=true`.

**Everything is slow and the fans are loud**
Lower the worker count: `dripcut config --set video.max_workers=1`. Two is the
default and suits 8 GB; more will thrash.

**Transcription fails with a download error**
The model needs a connection on first use. Check you can reach the internet, then
retry. Once cached it works offline forever.

**"AI unavailable" on the AI Studio page**
Run `dripcut doctor`. It will tell you which of Whisper, the Ollama server or the
model is missing, and how to get it.

**A render failed part-way**
Check free space first — video output is large. The Exports page shows the error
and its hint; full detail is in `<DRIPCUT_HOME>/logs/dripcut.log`.

**Reset everything**
`dripcut config --reset` restores factory settings. To start completely fresh,
delete the DripCut folder under your platform's application-data directory
(`dripcut info` prints the path).

## Where things live

`dripcut info` prints all of these. Defaults:

| | macOS | Linux | Windows |
|---|---|---|---|
| Config and data | `~/Library/Application Support/DripCut` | `~/.local/share/DripCut` | `%LOCALAPPDATA%\DripCut` |
| Cache | `~/Library/Caches/DripCut` | `~/.cache/DripCut` | `%LOCALAPPDATA%\DripCut\cache` |
| Output | `~/Movies/DripCut` | `~/Videos/DripCut` | `%USERPROFILE%\Videos\DripCut` |

Override with `DRIPCUT_HOME` and `DRIPCUT_OUTPUT`.

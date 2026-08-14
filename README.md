# Stem Mashup Pro

**AI-Powered Music Mashup & Mixing Studio**

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Web_Interface-success?style=flat-square)

A modern web-based tool for creating mashups by loading and mixing 2 songs with independent control over vocals, beats, bass, pitch, reverb, speed, EQ, and automatic beatmatching. Includes AI-powered stem separation and support for key/BPM matching to prepare stems for professional DAW mixing.

---

## Features

- **Load & mix 2 songs** with automatic BPM and key detection
- **AI Stem Separation** — isolate vocals, beats, bass, and other instruments using Demucs
- **Key & BPM Matching** — override detected keys and tempo to match your mashup
- **Independent stem controls** — precise volume control for each element
- **Per-song effects** — pitch shift, reverb, speed adjustment, 3-band EQ (Low/Mid/High)
- **Automatic beatmatching** — align multiple tracks to a common tempo with beat-phase sync
- **Crossfader** — seamlessly blend between songs
- **Live preview** — render 60-second samples without autoplay
- **Full remix rendering** — generate complete mixdowns with slider automation baked in
- **Adjusted stems export** — download stems pitch/tempo-matched to your settings for DAW use
- **Timestamped outputs** — all renders and stems include date-time stamps with BPM/key info in filenames
- **Preset system** — save and load mixer configurations as JSON
- **Web interface** — modern Gradio-based interface with real-time status updates
- **One-audio-at-a-time playback** — only one audio player can play simultaneously

---

## Output Organization

All audio files are automatically saved to an `Audio/` folder with clear naming:

```
Audio/
├── stems_export_original_2026-08-14_143022.zip      # Original stems (unchanged)
├── final_remix_original_C-G_120bpm_2026-08-14_110822.mp3    # Final mix if no changes
├── final_remix_C-G_140bpm_2026-08-14_143022.mp3             # Final mix with adjustments
├── render_output_C-G_140bpm_2026-08-14_143022.zip           # Full package (remix + stems)
└── stems_bpm-key-adjusted/
    ├── Song1_track_vocals_C_140bpm.wav              # Adjusted stem (for DAW)
    └── ...
```

**Filename format:**
- `stems_export_original_TIMESTAMP.zip` — Original stems at detected BPM/key
- `final_remix_KEY1-KEY2_BPMVALUE_TIMESTAMP.mp3` — Final remix
  - Shows `original` if no pitch/BPM changes were made
- `render_output_KEY1-KEY2_BPMVALUE_TIMESTAMP.zip` — Complete render package
- Individual stems: `Song#_name_stemtype_KEY_BPMVALUE.wav`

---

## Tech Stack

- **Python 3.10+**
- **Gradio** – web interface with real-time updates
- **FFmpeg** – audio mixing and effects processing
- **Demucs** – AI stem separation
- **Librosa** – BPM detection, beat analysis, and key detection

---

## Installation

1. Clone the repository:

```bash
git clone https://github.com/laudaniels/Stem-Mashup-Pro.git
cd Stem-Mashup-Pro
```

2. Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate    # macOS/Linux
venv\Scripts\activate       # Windows
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Ensure FFmpeg is installed:
   - **Windows**: [ffmpeg.org](https://ffmpeg.org/download.html)
   - **macOS**: `brew install ffmpeg`
   - **Linux**: `sudo apt-get install ffmpeg`

---

## Quick Start

```bash
python3 gradio_app.py
```

Opens at `http://localhost:7860`

### Basic Workflow

1. **Load 2 songs** — automatic BPM/key detection starts immediately
2. **Wait for analysis** — you'll see a progress animation during detection and stem separation
3. **Download stems** (optional) — get the original separated stems as a ZIP
4. **Override keys/BPM** (optional) — select different keys or target BPM if desired
5. **Adjust mixing** — control stem volumes, effects, crossfader, and beatmatching
6. **Live preview** — click **LIVE PREVIEW** to hear a 60-second sample
7. **Render** — click **RENDER FULL REMIX AND STEMS** to:
   - Generate the full-length final remix with all your settings
   - Create adjusted stems (pitch/tempo-matched) for importing into your DAW
   - Download both as a single ZIP package

### For DAW Workflows

After rendering, you'll get adjusted stems with your BPM/key settings baked in. Import these into your favorite DAW (Ableton, Logic, etc.) for professional mixing with:
- Full automation capabilities
- More advanced effects and processing
- Multi-track editing flexibility

---

## UI Guide

### Status of Detecting and Separating the Tracks
- Shows real-time progress during song loading, BPM/key analysis, and stem separation
- Displays completion message with tips for next steps
- Animated indicator shows when processing is active

### Per-Song Controls
- **Stem Levels**: Independent volume control for Vocals, Beats, Bass, Other
- **Pitch Shift**: Select a target key from the dropdown (auto-calculates semitone shift)
- **Effects**: Reverb, Speed, 3-band EQ
- **Key Override**: Override detected key (affects pitch shift suggestions)
- **BPM Override**: Set a custom target BPM for tempo matching

### Mixing Section
- **Crossfader**: Blend between Song 1 and Song 2
- **Target Tempo**: Set the BPM you want the final mix to be
- **Beatmatch**: Align beat grids for seamless mixing
- **Pitch Shift Suggestion**: Shows recommended pitch adjustments for key matching

### Download Widgets
- **Download Stems (ZIP)**: Original separated stems (original BPM/key)
- **Download Render + Stems (ZIP)**: Final remix + adjusted stems ready for DAW

---

## Disclaimer

This tool is for educational and creative purposes. Only use audio files you own or have permission to use. The developer is not responsible for copyright violations.

---

## Credits

**Based on:** [Neon Mashup Studio](https://github.com/codewithpb11/neon-mashup-studio) by Pramit Baksi

---

## License

MIT License. See [LICENSE](LICENSE) for details.

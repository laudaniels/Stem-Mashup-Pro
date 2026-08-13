# Stem Mashup Pro

**AI-Powered Music Mashup & Mixing Studio**

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Web_Interface-success?style=flat-square)

A modern web-based tool for creating mashups by loading and mixing 2 songs with independent control over vocals, beats, bass, pitch, reverb, speed, EQ, and automatic beatmatching.

---

## Features

- **Load & mix 2 songs** with automatic BPM detection
- **AI Stem Separation** — isolate vocals, beats, bass, and other instruments using Demucs
- **Independent stem controls** — precise volume and mute control for each element
- **Per-song effects** — pitch shift, reverb, speed adjustment, 3-band EQ (Low/Mid/High)
- **Automatic beatmatching** — align multiple tracks to a common tempo
- **Crossfader** — seamlessly blend between songs
- **Live preview** — render 60-second samples in real-time
- **Preset system** — save and load mixer configurations as JSON
- **Web interface** — modern Gradio-based interface, no installation of heavy dependencies needed

---

## Screenshots

![Main Interface](Prieview1.png)

![Mixer Controls](Preview3.png)

---

## Tech Stack

- **Python 3.10+**
- **Gradio** – web interface
- **FFmpeg** – audio mixing and effects
- **Demucs** – AI stem separation
- **Librosa** – BPM detection and beat analysis

---

## Installation

1. Clone the repository:

```bash
git clone https://github.com/laudaniels/Stem-Mashup-Pro.git
cd Stem-Mashup-Pro
```

2. Create and activate a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # macOS/Linux
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

**Basic workflow:**
1. Load 2 songs using the Load buttons or just drop them into the box
2. Wait for automatic BPM detection
3. Wait for the Stem separation
4. Download the all the (unchanged) Stems as a ZIP
5. Adjust volumes, effects, and beatmatching
6. Click **LIVE PREVIEW** to hear a 60-second sample after every adjustment
7. Click **RENDER REMIX** to generate the full-length output

---

## Disclaimer

This tool is for educational and creative purposes. Only use audio files you own or have permission to use. The developer is not responsible for copyright violations.

---

## Credits

**Based on:** [Neon Mashup Studio](https://github.com/codewithpb11/neon-mashup-studio) by Pramit Baksi

---

## License

MIT License. See [LICENSE](LICENSE) for details.

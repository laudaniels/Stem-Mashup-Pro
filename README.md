# Stem Mashup Pro

**AI-Powered Dual-Song Real-Time Audio Mixer**

![React](https://img.shields.io/badge/React-18-blue?style=flat-square)
![Flask](https://img.shields.io/badge/Flask-Web_API-orange?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Web_Interface-success?style=flat-square)

A modern hybrid React + Flask web application for creating mashups by loading and mixing 2 songs side-by-side with real-time stem controls, synchronized playback, automatic beatmatching, and key transposition. Includes AI-powered stem separation and professional download options.

---

## ✨ Features

### Real-Time Mixing
- **Dual-song mixer** — load two MP3s into independent slots with synchronized playback
- **HTML5 audio synchronization** — first song's timeline controls both songs for seamless beatmatching
- **Independent stem volumes** — control Vocals, Drums, Bass, and Other separately for each song
- **Crossfader** — blend between Song 1 and Song 2 in real-time

### Audio Analysis & Processing
- **AI Stem Separation** — isolate vocals, drums, bass, and other instruments using Demucs
- **Intelligent BPM Detection** — auto-detect tempo with optional override (librosa-based)
- **Smart Key Detection** — identify song key with optional override (Essentia + librosa fallback)
- **Beatmatching** — align Song 2 to Song 1, or both to a target BPM
- **Key Transposition** — pitch-shift tracks to match target key with recommendation button
- **Recommended Key** — algorithm finds best compromise key between both songs to minimize total transposition

### Downloads & Exports
- **9 downloadable files:**
  - Original stems for Song 1 (4 stems)
  - Original stems for Song 2 (4 stems)
  - Processed stems (beatmatched + transposed)
  - Final mix WAV (all stems combined with volume settings + crossfader)
- **ZIP archives** — organized downloads with clear naming and metadata

### User Experience
- **Auto-loop playback** — automatically restart at track end during playback
- **Real-time status** — visual feedback during stem separation and processing
- **Drag-and-drop upload** — intuitive file loading with visual feedback
- **Responsive design** — works on desktop browsers

---

## Architecture

### Frontend
- **React 18** — interactive UI for real-time mixing
- **Vite** — fast development server and bundler
- **HTML5 Audio API** — synchronous playback of dual songs
- **Responsive CSS** — dark theme with modern gradient styling

### Backend
- **Flask** — REST API for audio processing
- **Demucs** — AI-powered stem separation
- **Librosa** — BPM detection and tempo-stretching
- **Essentia** — key detection (with librosa fallback)
- **FFmpeg** — final mix rendering and WAV encoding

### File Structure
```
stem-mashup-pro/
├── frontend/                 # React app
│   ├── src/
│   │   ├── components/       # React components (DualMixer, StemLoader, etc.)
│   │   ├── styles/           # CSS for mixing interface
│   │   └── App.jsx
│   ├── vite.config.js
│   └── package.json
├── api.py                    # Flask REST API endpoints
├── mashup_engine.py          # Audio processing core
├── requirements.txt
└── Audio/                    # Generated stems and mixes (git-ignored)
```

### API Endpoints
- `POST /api/separate-stems` — upload file, return stems + metadata (BPM, key)
- `POST /api/process-stems` — beatmatch + transpose stems
- `POST /api/render-final-mix` — mix all stems into final WAV
- `POST /api/download-stems-zip` — download original/processed stems as ZIP
- `GET /api/download-file/<filename>` — download single audio file

---

## Tech Stack

- **React 18** + Vite
- **Flask** + Flask-CORS
- **Python 3.10+**
- **Demucs** – AI stem separation
- **Librosa** – BPM detection and tempo-stretching
- **Essentia** – key detection
- **FFmpeg** – final mix rendering

---

## Installation

### Prerequisites
- **Python 3.10+**
- **Node.js 16+** (for React frontend)
- **FFmpeg** (for audio mixing)

### Setup

1. **Clone the repository:**
```bash
git clone https://github.com/laudaniels/Stem-Mashup-Pro.git
cd Stem-Mashup-Pro
```

2. **Create and activate a Python virtual environment:**
```bash
python3 -m venv .venv
source venv/bin/activate    # macOS/Linux
venv\Scripts\activate       # Windows
```

3. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

4. **Install Node dependencies for React:**
```bash
cd frontend
npm install
cd ..
```

5. **Ensure FFmpeg is installed:**
   - **macOS**: `brew install ffmpeg`
   - **Linux**: `sudo apt-get install ffmpeg`
   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) or `choco install ffmpeg`

### Troubleshooting Installation

**Missing Demucs model:**
On first run, Demucs downloads a ~500MB model. This happens automatically but requires internet connection.

**FFmpeg not found:**
Ensure FFmpeg is in your PATH. Test with: `ffmpeg -version`

**Port already in use:**
- Flask (5000): Change `port=5000` in `api.py`
- React (5173): Vite uses first available port or change in `frontend/vite.config.js`

---

## Quick Start

### 1. Start the Flask Backend
```bash
source .venv/bin/activate
python3 api.py
```
Runs at `http://localhost:5000`

### 2. Start the React Frontend (in another terminal)
```bash
cd frontend
npm install      # First time only
npm run dev
```
Opens at `http://localhost:5173`

### Basic Workflow

1. **Upload Song 1** — drag-and-drop or click upload area
   - Automatic stem separation starts (4 stems: vocals, drums, bass, other)
   - BPM and key are detected automatically
2. **Upload Song 2** — same as Song 1, processed in parallel
3. **Review metadata** — see detected BPM/key for each song
4. **Override (optional)** — change Target BPM or Target Key if desired
5. **Mix in real-time:**
   - Adjust stem volumes (0-100%) for each song independently
   - Use crossfader to blend between songs
   - Listen with Play/Pause button
6. **Click "Recommend" button** — gets best compromise key between both songs
7. **Download files:**
   - **Original Stems ZIP** — Song 1 + Song 2 stems at detected settings
   - **Processed Stems ZIP** — beatmatched + transposed stems
   - **Final Mix WAV** — all stems combined with your volume settings + crossfader

### Key Features Explained

**Beatmatching Logic:**
- If **Target BPM** is set: both songs align to that BPM
- If **Target BPM** is empty: Song 2 aligns to Song 1's BPM

**Key Recommendation:**
- Algorithm finds the single key that minimizes total transposition needed
- Shows best compromise between both songs' detected keys
- Example: if Song 1 is in C and Song 2 is in F, recommendation might be Eb or D

**Auto-Loop:**
- When playback reaches end of track, automatically restarts from beginning
- Useful for testing beatmatching and mix timing

---

## UI Guide

### Song Slots (Left & Right)
Each slot has:
- **Upload area** — drag-and-drop MP3 files (purple gradient box)
- **Metadata display** — shows filename, detected BPM, detected Key
- **Stem sliders** — four vertical faders for Vocals, Drums, Bass, Other (0-100%)
- **Target Key dropdown** — select key for transposition
- **Processing status** — shows "separating...", "processing...", or ✓ complete

### Playback Controls (Center)
- **Play/Pause button** — toggle audio playback
- **Progress bar** — scrub through current track
- **Time display** — current time and duration

### Mixing Controls (Bottom)
- **Crossfader** — blend between Song 1 (left) and Song 2 (right)
- **Target BPM input** — set tempo for beatmatching (empty = Song 2 matches Song 1)
- **Target Key dropdown** — select key for both songs
- **"💡 Recommend" button** — auto-select best compromise key
- **Download buttons** — original stems, processed stems, final mix WAV

### Processing Indicators
- Purple spinner shows when stems are separating or being processed
- ✓ Check mark shows when ready
- Error messages show in red if something fails

---

## Output Files

All generated files are stored in `Audio/` folder with timestamps:

```
Audio/
├── stems/
│   ├── [timestamp]/
│   │   ├── Song1_vocals.wav
│   │   ├── Song1_drums.wav
│   │   ├── Song1_bass.wav
│   │   ├── Song1_other.wav
│   │   ├── Song2_vocals.wav
│   │   └── ... (Song 2 stems)
│   └── ...
├── processed/
│   ├── [timestamp]/
│   │   ├── vocals_beatmatched_transposed.wav
│   │   ├── drums_beatmatched_transposed.wav
│   │   └── ...
│   └── ...
└── [timestamp]_final_mix.wav         # Final stereo mix
```

---

---

## Project Status

- **Active:** React + Flask real-time dual-song mixer
- **Archived:** Original Gradio-based interface (see `archive/` for legacy code)

The Gradio interface was replaced with a modern hybrid React + Flask architecture for real-time audio processing and better UX.

---

## Disclaimer

This tool is for educational and creative purposes. Only use audio files you own or have permission to use. The developer is not responsible for copyright violations.

Stem separation is AI-powered and may not perfectly separate all instruments. Use downloaded stems as a starting point, not as final product stems.

---

## Credits

- **AI Stem Separation:** [Demucs](https://github.com/facebookresearch/demucs) (Meta)
- **Audio Analysis:** [Librosa](https://librosa.org/) and [Essentia](https://essentia.upf.edu/)
- **Original Inspiration:** [Neon Mashup Studio](https://github.com/codewithpb11/neon-mashup-studio) by Pramit Baksi

---

## License

MIT License. See [LICENSE](LICENSE) for details.

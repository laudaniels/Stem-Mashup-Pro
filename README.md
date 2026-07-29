# Neon Mashup Studio

**Multi-Track AI-Powered Song Mashup Studio**

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?style=flat-square)

A desktop application that allows users to load 2–3 songs and creatively mash them up with independent control over vocals, beats, bass, pitch, reverb, speed, EQ, and more.

---

## Features

- Load up to **3 songs**
- Independent volume controls (Vocals / Beats / Bass)
- Pitch shifting, Reverb, and Speed control
- 3-band EQ (Low, Mid, High)
- **Live Preview** (60 seconds)
- Global **Crossfader**
- Preset Save / Load system
- Progress bar during rendering
- Dark Bluish-Neon modern UI
- Basic waveform visualization

---

## Screenshots

![Main Interface](Prieview1.png)

![Mixer Controls](Preview3.png)

---

## Tech Stack

- **Python 3.10+**
- **Tkinter** – GUI
- **FFmpeg** – Audio processing
- **Demucs** – AI stem separation (optional)
- **Matplotlib + NumPy** – Waveform display

---

## Installation

1. Clone the repository:

```bash
git clone https://github.com/codewithpb11/neon-mashup-studio.git
cd neon-mashup-studio

Install dependencies:

Bashpip install -r requirements.txt

Make sure FFmpeg is installed and added to your system PATH.
Run the application:

Bashpython app_gui.py

How to Use

Click + Song 1, + Song 2 (and optionally + Song 3) to load tracks.
Adjust the sliders for Vocals, Beats, Bass, Pitch, Reverb, Speed, and EQ.
Use the Crossfader to balance between songs.
Click Live Preview to hear a 60-second sample.
Click Render Remix to generate the final output.
Save your favorite settings using Save Preset.


Disclaimer
This tool is created for educational and creative purposes only.
Please only use audio files that you own or have proper rights to use.
The developer is not responsible for any copyright violations by users.

Future Plans

Real waveform extraction from audio files
Better AI stem separation integration
Ability to export individual stems
Possible web version in the future


Author
Pramit Baksi
2nd Year B.Tech Student, Computer Science & Engineering
Kolkata, West Bengal, India

License
This project is licensed under the MIT License.

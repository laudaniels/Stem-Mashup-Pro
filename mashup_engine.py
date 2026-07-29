import shutil
import subprocess
import sys
from pathlib import Path


class MashupEngine:
    """Build FFmpeg mixes and optionally prepare Demucs source stems."""

    STEM_NAMES = ("vocals", "drums", "bass", "other")

    def __init__(self):
        self.ffmpeg = "ffmpeg"
        self.ffplay = "ffplay"
        self.stems_dir = Path("separated_stems")

    def separate_stems(self, songs):
        """Run Demucs once for each source and return its produced stem paths."""
        if not shutil.which("demucs"):
            # `python -m demucs` is the supported fallback when its Scripts
            # directory is not included in PATH.
            probe = subprocess.run([sys.executable, "-m", "demucs", "--help"],
                                   capture_output=True, text=True)
            if probe.returncode != 0:
                raise RuntimeError(
                    "Stem separation needs Demucs. Install it in Command Prompt with:\n\n"
                    "python -m pip install -U demucs\n\n"
                    "Then click SEPARATE STEMS again. The first run also downloads its audio model.")

        self.stems_dir.mkdir(exist_ok=True)
        results = []
        for song in songs:
            command = [sys.executable, "-m", "demucs", "--out", str(self.stems_dir), song]
            result = subprocess.run(command, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "Demucs failed without an error message."
                raise RuntimeError(f"Demucs could not separate {Path(song).name}:\n{detail[-1200:]}")

            # Demucs writes: separated_stems/<model>/<original filename>/<stem>.wav
            song_folder = Path(song).stem
            candidates = list(self.stems_dir.glob(f"*/{song_folder}"))
            if not candidates:
                raise RuntimeError(f"Demucs finished, but no stem folder was found for {Path(song).name}.")
            folder = candidates[0]
            stems = {name: str(folder / f"{name}.wav") for name in self.STEM_NAMES}
            missing = [name for name, path in stems.items() if not Path(path).is_file()]
            if missing:
                raise RuntimeError(f"Demucs did not create all expected stems for {Path(song).name}: {', '.join(missing)}")
            results.append(stems)
        return results

    @staticmethod
    def _effects(chain, sliders, slot):
        """Apply the track-wide controls after its stems have been balanced."""
        pitch = float(sliders.get(f"s{slot}_pitch_shift", 0.0))
        speed = float(sliders.get(f"s{slot}_speed", 1.0))
        reverb = float(sliders.get(f"s{slot}_reverb", 0.0))
        eq_low = float(sliders.get(f"s{slot}_eq_low", 0.0))
        eq_mid = float(sliders.get(f"s{slot}_eq_mid", 0.0))
        eq_high = float(sliders.get(f"s{slot}_eq_high", 0.0))

        if abs(pitch) > 0.05:
            chain += f",asetrate=44100*{2 ** (pitch / 12)},aresample=44100"
        if abs(speed - 1.0) > 0.05:
            chain += f",atempo={speed}"
        if reverb > 0.05:
            chain += f",aecho=0.8:0.9:{int(reverb * 60)}:{reverb * 0.4}"
        if abs(eq_low) > 0.05:
            chain += f",equalizer=f=100:width_type=o:width=2:g={eq_low * 6}"
        if abs(eq_mid) > 0.05:
            chain += f",equalizer=f=1000:width_type=o:width=2:g={eq_mid * 4}"
        if abs(eq_high) > 0.05:
            chain += f",equalizer=f=8000:width_type=o:width=2:g={eq_high * 5}"
        return chain

    def render(self, params, preview=False, preview_duration=15):
        slots = params["songs"]
        stems_by_slot = params.get("stems", [None] * len(slots))
        sliders = params["sliders"]
        if len(slots) < 2 or not slots[0] or not slots[1]:
            raise ValueError("Load Song 1 and Song 2 before mixing. Song 3 is optional.")

        crossfade = float(params.get("crossfader", 50)) / 100.0
        fades = {0: min(1.0, 2 * (1 - crossfade)), 1: min(1.0, 2 * crossfade)}
        inputs, filters, mixed_tracks = [], [], []
        input_number = 0

        for slot, song in enumerate(slots):
            if not song:
                continue
            fade = fades.get(slot, 1.0)
            stem_set = stems_by_slot[slot] if slot < len(stems_by_slot) else None
            valid_stems = (isinstance(stem_set, dict) and
                           all(name in stem_set and Path(stem_set[name]).is_file() for name in self.STEM_NAMES))

            if valid_stems:
                volumes = {
                    "vocals": float(sliders.get(f"s{slot}_vocals_vol", 1.0)),
                    "drums": float(sliders.get(f"s{slot}_beats_vol", 1.0)),
                    "bass": float(sliders.get(f"s{slot}_bass_vol", 1.0)),
                    "other": 1.0,
                }
                labels = []
                for stem in self.STEM_NAMES:
                    inputs.extend(["-i", stem_set[stem]])
                    label = f"stem_{slot}_{stem}"
                    filters.append(f"[{input_number}:a]volume={volumes[stem] * fade}[{label}]")
                    labels.append(f"[{label}]")
                    input_number += 1
                chain = "".join(labels) + f"amix=inputs=4:normalize=0"
            else:
                inputs.extend(["-i", song])
                total_volume = (
                    float(sliders.get(f"s{slot}_vocals_vol", 1.0)) +
                    float(sliders.get(f"s{slot}_beats_vol", 1.0)) +
                    float(sliders.get(f"s{slot}_bass_vol", 1.0))
                ) / 3 * fade
                chain = f"[{input_number}:a]volume={total_volume}"
                input_number += 1

            chain = self._effects(chain, sliders, slot)
            filters.append(f"{chain}[track_{slot}]")
            mixed_tracks.append(f"[track_{slot}]")

        filter_complex = ";".join(filters)
        filter_complex += ";" + "".join(mixed_tracks)
        filter_complex += f"amix=inputs={len(mixed_tracks)}:duration=longest:normalize=0,alimiter=limit=0.95[final]"

        output = "preview_temp.mp3" if preview else "final_remix.mp3"
        command = [self.ffmpeg, "-y", *inputs, "-filter_complex", filter_complex, "-map", "[final]"]
        if preview:
            command += ["-t", str(preview_duration)]
        command += ["-c:a", "libmp3lame", "-q:a", "2", output]

        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        except FileNotFoundError as error:
            raise RuntimeError("FFmpeg is not installed or is not in PATH. Install FFmpeg before previewing or rendering.") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or "FFmpeg failed without an error message."
            raise RuntimeError(f"FFmpeg could not make the mix:\n{detail[-1200:]}")

        if preview:
            try:
                subprocess.Popen([self.ffplay, "-nodisp", "-autoexit", "-t", str(preview_duration), output],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                pass  # The preview file was made; only automatic playback is unavailable.
        return output

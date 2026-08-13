import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class MashupEngine:
    """Build FFmpeg mixes and optionally prepare Demucs source stems."""

    STEM_NAMES = ("vocals", "drums", "bass", "other")
    TARGET_SAMPLE_RATE = 44100

    # Class-level, not per-instance: the GUI creates a fresh MashupEngine()
    # for every button click, but "is a preview currently playing" and "kill
    # everything this app has spawned" both need to survive across those
    # short-lived instances.
    _preview_process = None
    _active_encode_processes = []

    @classmethod
    def is_previewing(cls):
        return cls._preview_process is not None and cls._preview_process.poll() is None

    @classmethod
    def stop_preview(cls):
        """Kill the currently playing preview, if any."""
        if cls._preview_process and cls._preview_process.poll() is None:
            cls._preview_process.terminate()
        cls._preview_process = None

    @classmethod
    def stop_all(cls):
        """Kill every ffmpeg/ffplay process this app has spawned. Call this
        before the GUI exits -- ffmpeg/ffplay are independent OS processes
        and are not tied to the Python process's lifetime, so closing the
        window does not stop them on its own."""
        cls.stop_preview()
        for proc in cls._active_encode_processes:
            if proc.poll() is None:
                proc.terminate()
        cls._active_encode_processes = []

    def __init__(self):
        self.ffmpeg = "ffmpeg"
        self.ffplay = "ffplay"
        self.stems_dir = BASE_DIR / "separated_stems"

    def separate_stems(self, songs):
        """Run Demucs once for each source and return its produced stem paths."""
        if not shutil.which("demucs"):
            # `python -m demucs` is the supported fallback when its Scripts
            # directory is not included in PATH.
            probe = subprocess.run([sys.executable, "-m", "demucs", "--help"],
                                   capture_output=True, text=True, timeout=30)
            if probe.returncode != 0:
                raise RuntimeError(
                    "Stem separation needs Demucs. Install it in Command Prompt with:\n\n"
                    "python -m pip install -U demucs\n\n"
                    "Then click SEPARATE STEMS again. The first run also downloads its audio model.")

        self.stems_dir.mkdir(exist_ok=True)
        results = []
        for song in songs:
            # Each song gets its own output folder keyed by its full resolved
            # path, so two different songs that happen to share a base
            # filename (e.g. "track.mp3" from different folders) never
            # collide or overwrite each other's stems.
            song_hash = hashlib.sha1(str(Path(song).resolve()).encode("utf-8")).hexdigest()[:16]
            song_out_dir = self.stems_dir / song_hash
            command = [sys.executable, "-m", "demucs", "--out", str(song_out_dir), song]
            result = subprocess.run(command, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "Demucs failed without an error message."
                raise RuntimeError(f"Demucs could not separate {Path(song).name}:\n{detail[-1200:]}")

            # Demucs writes: <song_out_dir>/<model>/<original filename>/<stem>.wav
            song_folder = Path(song).stem
            candidates = list(song_out_dir.glob(f"*/{song_folder}"))
            if not candidates:
                raise RuntimeError(f"Demucs finished, but no stem folder was found for {Path(song).name}.")
            folder = candidates[0]
            stems = {name: str(folder / f"{name}.wav") for name in self.STEM_NAMES}
            missing = [name for name, path in stems.items() if not Path(path).is_file()]
            if missing:
                raise RuntimeError(f"Demucs did not create all expected stems for {Path(song).name}: {', '.join(missing)}")
            results.append(stems)
        return results

    def analyze_track(self, song_path):
        """Estimate a track's tempo (BPM) and a reference beat position
        (`beat_anchor`, in seconds, absolute within the original file).

        Analyzes a 60s window starting 15s in rather than the whole file --
        intros/outros (silence, spoken intros, sparse arrangement) throw off
        autocorrelation-based tempo estimation more than a track's main
        groove does, and skipping most of the file keeps this fast on long
        tracks. Falls back to the whole file for anything shorter than that.

        beat_anchor feeds beatmatching (see render()): once two tracks are
        both stretched to the same target tempo, aligning this one timestamp
        modulo a beat period locks their beat grids together for the rest
        of the track, not just at the instant it was measured.
        """
        import librosa
        import numpy as np

        try:
            total_duration = librosa.get_duration(path=song_path)
        except TypeError:
            # Older librosa releases use the `filename` kwarg instead of `path`.
            total_duration = librosa.get_duration(filename=song_path)

        offset = 15.0 if total_duration > 90.0 else 0.0
        window = min(60.0, max(total_duration - offset, 1.0))

        y, sr = librosa.load(song_path, sr=None, mono=True, offset=offset, duration=window)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        tempo = float(np.asarray(tempo).reshape(-1)[0])

        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        beat_anchor = float(beat_times[0]) + offset if len(beat_times) else offset
        return tempo, beat_anchor

    @staticmethod
    def _atempo_chain(ratio):
        """ffmpeg's atempo filter only accepts a 0.5-2.0 ratio per instance.
        Decompose an arbitrary ratio into a chain of atempo filters that are
        each within that range and multiply out to the requested ratio."""
        factors = []
        remaining = ratio
        while remaining < 0.5 or remaining > 2.0:
            step = 2.0 if remaining > 2.0 else 0.5
            factors.append(step)
            remaining /= step
        factors.append(remaining)
        return ",".join(f"atempo={f}" for f in factors)

    @classmethod
    def _effects(cls, chain, sliders, slot, tempo_ratio=1.0):
        """Apply the track-wide controls after its stems have been balanced.

        Every chain reaching this point has already been normalized to
        TARGET_SAMPLE_RATE (see render()), so the asetrate trick below is
        always relative to the stream's actual sample rate, not a guess.

        tempo_ratio folds in BPM-matching (target_bpm / detected_bpm, from
        render()) on top of the manual Speed slider -- atempo changes tempo
        without touching pitch, so it's the right tool for BPM matching,
        unlike the asetrate-based pitch shift below.

        Returns (chain, duration_scale): duration_scale is how much this
        chain compresses (>1) or stretches (<1) the track's timeline overall
        -- render() uses it to project a beat position measured on the
        original file forward through these effects, for beatmatching.
        """
        pitch = float(sliders.get(f"s{slot}_pitch_shift", 0.0))
        speed = float(sliders.get(f"s{slot}_speed", 1.0)) * tempo_ratio
        reverb = float(sliders.get(f"s{slot}_reverb", 0.0))
        eq_low = float(sliders.get(f"s{slot}_eq_low", 0.0))
        eq_mid = float(sliders.get(f"s{slot}_eq_mid", 0.0))
        eq_high = float(sliders.get(f"s{slot}_eq_high", 0.0))

        duration_scale = 1.0
        if abs(pitch) > 0.05:
            rate = cls.TARGET_SAMPLE_RATE
            pitch_ratio = 2 ** (pitch / 12)
            chain += f",asetrate={rate}*{pitch_ratio},aresample={rate}"
            duration_scale *= pitch_ratio
        if abs(speed - 1.0) > 0.05:
            chain += "," + cls._atempo_chain(speed)
            duration_scale *= speed
        if reverb > 0.05:
            chain += f",aecho=0.8:0.9:{int(reverb * 60)}:{reverb * 0.4}"
        if abs(eq_low) > 0.05:
            chain += f",equalizer=f=100:width_type=o:width=2:g={eq_low * 6}"
        if abs(eq_mid) > 0.05:
            chain += f",equalizer=f=1000:width_type=o:width=2:g={eq_mid * 4}"
        if abs(eq_high) > 0.05:
            chain += f",equalizer=f=8000:width_type=o:width=2:g={eq_high * 5}"
        return chain, duration_scale

    def render(self, params, preview=False, preview_duration=15):
        slots = params["songs"]
        stems_by_slot = params.get("stems", [None] * len(slots))
        bpms = params.get("bpms", [None] * len(slots))
        beat_anchors = params.get("beat_anchors", [None] * len(slots))
        beat_offsets = params.get("beat_offsets", [0.0] * len(slots))
        target_bpm = params.get("target_bpm")
        # Beatmatching only makes sense once every aligned track shares the
        # same tempo -- without a target BPM their beat grids would just
        # drift apart again over the length of the track.
        beatmatch = bool(params.get("beatmatch")) and bool(target_bpm)
        sliders = params["sliders"]
        if len(slots) < 2 or not slots[0] or not slots[1]:
            raise ValueError("Load Song 1 and Song 2 before mixing. Song 3 is optional.")

        # Pre-pass for beatmatching: project each track's measured beat
        # position through the timeline-scaling effects (pitch + tempo
        # match + manual speed) it will actually get, so we know where that
        # beat lands in the *rendered* output, not the original file. Only
        # tracks that are themselves being tempo-matched to target_bpm are
        # eligible -- an unmatched track's tempo (and therefore beat period)
        # differs from the rest, so aligning it once would just drift out of
        # phase again a few beats later.
        final_anchors = {}
        if beatmatch:
            for slot, song in enumerate(slots):
                if not song:
                    continue
                detected_bpm = bpms[slot] if slot < len(bpms) else None
                anchor = beat_anchors[slot] if slot < len(beat_anchors) else None
                if not detected_bpm or anchor is None:
                    continue
                # Song 1 (slot 0) is always the fixed beatmatch reference --
                # adelay can only push a track later, never earlier, so one
                # track has to be everyone else's zero point. It never takes
                # a phase offset either, since nudging the reference's own
                # anchor would just be a roundabout way of shifting every
                # other track by the same amount -- same result, more
                # confusing knob. Expressed in each other song's own native
                # tempo. Alignment below is modulo one beat_period, so only
                # the fractional part shifts anything audible -- whole-beat
                # offsets land on an equivalent beat and cancel out. This is
                # beat-level phase correction, not bar/downbeat selection.
                offset_beats = 0.0 if slot == 0 else (beat_offsets[slot] if slot < len(beat_offsets) else 0.0)
                anchor = anchor + offset_beats * (60.0 / detected_bpm)
                tempo_ratio = target_bpm / detected_bpm
                pitch = float(sliders.get(f"s{slot}_pitch_shift", 0.0))
                speed = float(sliders.get(f"s{slot}_speed", 1.0)) * tempo_ratio
                duration_scale = 1.0
                if abs(pitch) > 0.05:
                    duration_scale *= 2 ** (pitch / 12)
                if abs(speed - 1.0) > 0.05:
                    duration_scale *= speed
                final_anchors[slot] = anchor / duration_scale
        # Song 1 is always the reference. If it has no usable BPM (analysis
        # failed and no override was set), beatmatching does nothing at all
        # this render rather than silently falling back to another track.
        reference_slot = 0 if 0 in final_anchors else None
        beat_period = 60.0 / target_bpm if beatmatch else None

        crossfade = float(params.get("crossfader", 50)) / 100.0
        fades = {0: min(1.0, 2 * (1 - crossfade)), 1: min(1.0, 2 * crossfade)}
        inputs, filters, mixed_tracks = [], [], []
        input_number = 0
        # Every track is normalized to the same sample rate/channel layout
        # before mixing or effects, so amix never has to guess how to
        # reconcile mismatched inputs, and asetrate-based pitch shifting can
        # rely on a known, fixed source rate.
        normalize = f"aformat=sample_rates={self.TARGET_SAMPLE_RATE}:channel_layouts=stereo"

        for slot, song in enumerate(slots):
            if not song:
                continue
            # Crossfader balance (song 1/2 only) — stem volumes now handle all level control
            fade = fades.get(slot, 1.0)
            stem_set = stems_by_slot[slot] if slot < len(stems_by_slot) else None
            valid_stems = (isinstance(stem_set, dict) and
                           all(name in stem_set and Path(stem_set[name]).is_file() for name in self.STEM_NAMES))

            if valid_stems:
                volumes = {
                    "vocals": float(sliders.get(f"s{slot}_vocals_vol", 1.0)),
                    "drums": float(sliders.get(f"s{slot}_beats_vol", 1.0)),
                    "bass": float(sliders.get(f"s{slot}_bass_vol", 1.0)),
                    "other": float(sliders.get(f"s{slot}_other_vol", 1.0)),
                }
                labels = []
                for stem in self.STEM_NAMES:
                    inputs.extend(["-i", stem_set[stem]])
                    label = f"stem_{slot}_{stem}"
                    filters.append(f"[{input_number}:a]volume={volumes[stem] * fade}[{label}]")
                    labels.append(f"[{label}]")
                    input_number += 1
                chain = "".join(labels) + f"amix=inputs=4:normalize=0,{normalize}"
            else:
                inputs.extend(["-i", song])
                total_volume = (
                    float(sliders.get(f"s{slot}_vocals_vol", 1.0)) +
                    float(sliders.get(f"s{slot}_beats_vol", 1.0)) +
                    float(sliders.get(f"s{slot}_bass_vol", 1.0))
                ) / 3 * fade
                chain = f"[{input_number}:a]volume={total_volume},{normalize}"
                input_number += 1

            # BPM-match this track to the user's target tempo, if both a
            # target and a detected BPM are available. Falsy detected_bpm
            # covers "not analyzed yet" (None) and "analysis failed" (False).
            detected_bpm = bpms[slot] if slot < len(bpms) else None
            tempo_ratio = (target_bpm / detected_bpm) if (target_bpm and detected_bpm) else 1.0

            chain, _duration_scale = self._effects(chain, sliders, slot, tempo_ratio)

            # Nudge this track's start later (never earlier -- delaying is
            # the only direction adelay can go) so its beat anchor lines up
            # with the reference track's, modulo one beat period.
            if beatmatch and reference_slot is not None and slot != reference_slot and slot in final_anchors:
                delta = (final_anchors[reference_slot] - final_anchors[slot]) % beat_period
                if delta > 0.005:
                    chain += f",adelay={int(round(delta * 1000))}:all=1"

            filters.append(f"{chain}[track_{slot}]")
            mixed_tracks.append(f"[track_{slot}]")

        filter_complex = ";".join(filters)
        filter_complex += ";" + "".join(mixed_tracks)
        filter_complex += f"amix=inputs={len(mixed_tracks)}:duration=longest:normalize=0,alimiter=limit=0.95[final]"

        output = str(BASE_DIR / ("preview_temp.mp3" if preview else "final_remix.mp3"))
        command = [self.ffmpeg, "-y", *inputs, "-filter_complex", filter_complex, "-map", "[final]"]
        if preview:
            command += ["-t", str(preview_duration)]
        command += ["-c:a", "libmp3lame", "-q:a", "2", output]

        # Run via Popen (not subprocess.run) and track the process so
        # stop_all() can kill it if the GUI is closed mid-encode.
        try:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except FileNotFoundError as error:
            raise RuntimeError("FFmpeg is not installed or is not in PATH. Install FFmpeg before previewing or rendering.") from error

        MashupEngine._active_encode_processes.append(proc)
        try:
            stdout, stderr = proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        finally:
            if proc in MashupEngine._active_encode_processes:
                MashupEngine._active_encode_processes.remove(proc)

        if proc.returncode != 0:
            detail = (stderr or "").strip() or "FFmpeg failed without an error message."
            raise RuntimeError(f"FFmpeg could not make the mix:\n{detail[-1200:]}")

        if preview:
            # A new preview always replaces whatever is currently playing --
            # otherwise every click of LIVE PREVIEW stacks another ffplay on
            # top of the last one, with no way to stop them from the GUI.
            MashupEngine.stop_preview()
            try:
                MashupEngine._preview_process = subprocess.Popen(
                    [self.ffplay, "-nodisp", "-autoexit", "-t", str(preview_duration), output],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                pass  # The preview file was made; only automatic playback is unavailable.
        return output

#!/usr/bin/env python3
import sys
from pathlib import Path

def _running_in_venv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)

if not _running_in_venv():
    sys.exit(
        "Stem Mashup Pro must be run from inside a virtual environment.\n\n"
        "Create one and install dependencies first:\n\n"
        "    python3 -m venv venv\n"
        "    source venv/bin/activate    (macOS/Linux)\n"
        "    .\\venv\\Scripts\\activate      (Windows)\n"
        "    pip install -r requirements.txt\n"
        "    python3 gradio_app.py\n"
    )

import gradio as gr
import json
import threading
from threading import Lock
from mashup_engine import MashupEngine

BASE_DIR = Path(__file__).resolve().parent

presets_dir = BASE_DIR / "presets"
presets_dir.mkdir(exist_ok=True)

KEY_NAMES = [
    "C major", "C#/Db major", "D major", "D#/Eb major", "E major", "F major",
    "F#/Gb major", "G major", "G#/Ab major", "A major", "A#/Bb major", "B major",
    "C minor", "C#/Db minor", "D minor", "D#/Eb minor", "E minor", "F minor",
    "F#/Gb minor", "G minor", "G#/Ab minor", "A minor", "A#/Bb minor", "B minor"
]

class StudioState:
    """Manages the entire studio state: songs, stems, BPMs, sliders, etc."""
    def __init__(self):
        self.engine = MashupEngine()
        self.song_paths = [None, None]
        self.stem_paths = [None, None]
        self.song_bpms = [None, None]
        self.song_beat_anchors = [None, None]
        self.song_keys = [None, None]
        self.bpm_overrides = [0.0, 0.0]
        self.key_overrides = [-1, -1]
        self.beat_offsets = [0.0, 0.0]
        self._sep_lock = Lock()
        self._analysis_events = [threading.Event(), threading.Event()]
        self.status_messages = []
        self._status_lock = Lock()
        self.sep_in_progress = False
        self.animation_frame = 0

        # Per-song sliders: [vocals, beats, bass, other, pitch, reverb, speed, eq_low, eq_mid, eq_high]
        self.sliders = {
            f"s{i}_{name}": val
            for i in range(2)
            for name, val in [
                ("vocals_vol", 1.0),
                ("beats_vol", 1.0),
                ("bass_vol", 1.0),
                ("other_vol", 1.0),
                ("pitch_shift", 0.0),
                ("reverb", 0.0),
                ("speed", 1.0),
                ("eq_low", 0.0),
                ("eq_mid", 0.0),
                ("eq_high", 0.0),
            ]
        }
        self.crossfader = 50
        self.target_bpm = 0
        self.beatmatch = False

    def both_songs_loaded(self):
        """Check if both songs are loaded."""
        return self.song_paths[0] is not None and self.song_paths[1] is not None

    def stems_ready(self):
        """Check if stems are separated for both songs."""
        return (self.both_songs_loaded() and
                self.stem_paths[0] is not None and
                self.stem_paths[1] is not None)

    def add_status(self, message):
        """Add a status message (visible in UI)."""
        with self._status_lock:
            self.status_messages.append(message)
            if len(self.status_messages) > 6:
                self.status_messages.pop(0)
        print(message)

    def get_status_text(self):
        """Return all status messages as a single text block."""
        with self._status_lock:
            return "\n".join(self.status_messages)

    def load_song(self, file_obj, slot):
        """Load a song and kick off BPM and key analysis in background."""
        if file_obj is None:
            return f"Song {slot+1}: no file", "", ""

        self.song_paths[slot] = file_obj.name
        self.stem_paths[slot] = None
        self.song_bpms[slot] = None
        self.song_beat_anchors[slot] = None
        self.song_keys[slot] = None
        self._analysis_events[slot].clear()

        self.add_status(f"📁 Song {slot+1} loaded: {Path(file_obj.name).name}")

        def analyze():
            try:
                self.add_status(f"🎵 Song {slot+1}: Analyzing BPM...")
                bpm, anchor = self.engine.analyze_track(file_obj.name)
                self.song_bpms[slot] = bpm
                self.song_beat_anchors[slot] = anchor
                self.add_status(f"✓ Song {slot+1}: BPM = {bpm:.0f}")

                self.add_status(f"🎼 Song {slot+1}: Analyzing key...")
                key = self.engine.analyze_key(file_obj.name)
                self.song_keys[slot] = key
                key_name = self.engine._key_to_note(key) if key >= 0 else "?"
                self.add_status(f"✓ Song {slot+1}: Key = {key_name}")

                # Start stem separation for this song immediately after analysis
                if not self.stem_paths[slot]:
                    self.add_status(f"🔄 Song {slot+1}: Starting stem separation...")
                    try:
                        stem_set = self.engine.separate_stems([file_obj.name])
                        self.stem_paths[slot] = stem_set[0]
                        self.add_status(f"✓ Song {slot+1}: Stems ready (Vocals, Beats, Bass, Other)")
                    except Exception as sep_e:
                        self.add_status(f"❌ Song {slot+1}: Stem separation error: {sep_e}")

            except Exception as e:
                self.add_status(f"❌ Song {slot+1}: Analysis error: {e}")
                self.song_bpms[slot] = False
                self.song_keys[slot] = -1
            finally:
                self._analysis_events[slot].set()

        # Start analysis in background without waiting
        thread = threading.Thread(target=analyze, daemon=True)
        thread.start()

        if not self.both_songs_loaded():
            other = 2 - slot
            self.add_status(f"⏳ Waiting for Song {other}...")

        # Return immediately with audio file - don't wait for analysis!
        return f"Song {slot+1}: {Path(file_obj.name).name} (analyzing…)", file_obj.name, ""

    def update_key_override(self, slot, value):
        self.key_overrides[slot] = int(value) if value else -1

    def get_effective_keys(self):
        """Return keys with overrides applied (-1 means not detected/available)."""
        result = []
        for i in range(2):
            if self.key_overrides[i] >= 0:
                result.append(self.key_overrides[i])
            else:
                result.append(self.song_keys[i] if self.song_keys[i] is not None else -1)
        return result

    def get_key_display(self, slot):
        """Get display text for a song's key."""
        if self.song_keys[slot] is None:
            return "detecting…"
        elif self.song_keys[slot] == -1:
            return "error"
        else:
            return self.engine._key_to_note(self.song_keys[slot])

    def get_pitch_shift_suggestion(self):
        """Get suggested pitch shift in semitones to match Song 1's key."""
        keys = self.get_effective_keys()
        if keys[0] < 0 or keys[1] < 0:
            return 0
        return self.engine._semitones_between(keys[1], keys[0])

    def separate_stems(self):
        """Separate stems for any loaded songs that don't have them yet."""
        selected = [(i, p) for i, p in enumerate(self.song_paths) if p and not self.stem_paths[i]]
        if not selected:
            print("[Stems] No new songs to separate.")
            return "No new songs to separate."

        self.sep_in_progress = True
        self.add_status("🔄 Starting stem separation (2-5 min per song)...")

        def task():
            try:
                song_paths_list = [p for _, p in selected]
                print(f"[Stems] Running Demucs on: {[Path(p).name for p in song_paths_list]}")
                self.add_status(f"⚙️ Running Demucs on {len(selected)} song(s)...")
                created = self.engine.separate_stems(song_paths_list)
                for (slot, _), stem_set in zip(selected, created):
                    self.stem_paths[slot] = stem_set
                    print(f"[Stems] Song {slot+1} stems ready: {list(stem_set.keys())}")
                    self.add_status(f"✓ Song {slot+1} stems ready: Vocals, Beats, Bass, Other")

                # Auto-create ZIP file when all stems are ready
                if self.stems_ready():
                    self._create_stems_zip()

            except Exception as e:
                print(f"[Stems] Error: {type(e).__name__}: {e}")
                self.add_status(f"❌ Stem separation error: {e}")
            finally:
                self.sep_in_progress = False

        threading.Thread(target=task, daemon=True).start()
        return "Separating stems — this may take several minutes…"

    def _create_stems_zip(self):
        """Create ZIP file of stems (called automatically after separation)."""
        import zipfile
        try:
            zip_path = BASE_DIR / "stems_export.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for slot, stem_dict in enumerate(self.stem_paths):
                    if stem_dict:
                        song_name = Path(self.song_paths[slot]).stem
                        for stem_name, stem_path in stem_dict.items():
                            arcname = f"Song_{slot+1}_{song_name}/{stem_name}.wav"
                            zf.write(stem_path, arcname=arcname)
            self.add_status(f"📦 ZIP ready: stems_export.zip")
            print(f"[Stems] ZIP auto-created: {zip_path}")
        except Exception as e:
            print(f"[Stems] ZIP creation error: {e}")
            self.add_status(f"❌ ZIP creation error: {e}")

    def get_animated_status(self):
        """Return status with animated spinner if stem separation is running."""
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        status = self.get_status_text()

        if self.sep_in_progress:
            frame = frames[self.animation_frame % len(frames)]
            self.animation_frame += 1
            if "Running Demucs" in status:
                return f"{status} {frame}"

        return status

    def update_slider(self, key, value):
        self.sliders[key] = value
        print(f"[Slider] {key} = {value}")

    def update_crossfader(self, value):
        self.crossfader = value
        print(f"[Crossfader] {value}% (Song 1 ← → Song 2)")

    def update_target_bpm(self, value):
        self.target_bpm = value or 0
        print(f"[Target BPM] {self.target_bpm}")

    def update_beatmatch(self, value):
        self.beatmatch = value
        print(f"[Beatmatch] {'enabled' if value else 'disabled'}")

    def update_bpm_override(self, slot, value):
        self.bpm_overrides[slot] = value or 0.0
        print(f"[BPM Override] Song {slot+1} = {self.bpm_overrides[slot]} (0=auto)")

    def update_beat_offset(self, slot, value):
        self.beat_offsets[slot] = value or 0.0
        print(f"[Beat Offset] Song {slot+1} = {self.beat_offsets[slot]}s")

    def update_key_override(self, slot, value):
        """Update key override from dropdown selection."""
        if value and value in KEY_NAMES:
            self.key_overrides[slot] = KEY_NAMES.index(value)
            print(f"[Key Override] Song {slot+1} = {value}")
            self.add_status(f"🎹 Song {slot+1} key override: {value}")
        else:
            self.key_overrides[slot] = -1
            print(f"[Key Override] Song {slot+1} = auto-detect")
            self.add_status(f"🎹 Song {slot+1} key override: auto-detect")

    def _key_to_note(self, key):
        """Convert key number to note name."""
        notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        return notes[key] if 0 <= key < 12 else "?"

    def get_effective_bpms(self):
        """Return BPMs with overrides applied."""
        result = []
        for i in range(2):
            if self.bpm_overrides[i] > 0:
                result.append(self.bpm_overrides[i])
            elif self.song_bpms[i] is None or self.song_bpms[i] is False:
                result.append(None)
            else:
                result.append(self.song_bpms[i])
        return result

    def get_bpm_display(self, slot):
        """Get display text for a song's BPM."""
        if self.song_bpms[slot] is None:
            return "detecting…"
        elif self.song_bpms[slot] is False:
            return "error"
        else:
            return f"{self.song_bpms[slot]:.1f}"

    def build_params(self):
        """Build the params dict for engine.render()."""
        return {
            "songs": self.song_paths,
            "stems": self.stem_paths,
            "bpms": self.get_effective_bpms(),
            "beat_anchors": self.song_beat_anchors,
            "beat_offsets": self.beat_offsets,
            "target_bpm": self.target_bpm or None,
            "beatmatch": self.beatmatch,
            "sliders": self.sliders.copy(),
            "crossfader": self.crossfader,
        }

    def preview(self):
        """Render a 60-second preview."""
        try:
            params = self.build_params()
            if not params["songs"][0] or not params["songs"][1]:
                return None, "Load Song 1 and Song 2 before previewing."
            output = self.engine.render(params, preview=True, preview_duration=60)
            return output, "Preview generated and playing…"
        except Exception as e:
            return None, f"Preview error: {str(e)[:100]}"

    def render(self):
        """Render the full remix."""
        try:
            params = self.build_params()
            if not params["songs"][0] or not params["songs"][1]:
                return None, "Load Song 1 and Song 2 before rendering."
            output = self.engine.render(params, preview=False)
            return output, f"Remix saved as: {output}"
        except Exception as e:
            return None, f"Render error: {str(e)[:100]}"

    def download_stems(self):
        """Create a ZIP file of all separated stems."""
        import zipfile

        if not self.both_songs_loaded():
            return None, "Load both songs first."
        if not self.stem_paths[0] or not self.stem_paths[1]:
            return None, "Separate stems first."

        try:
            zip_path = BASE_DIR / "stems_export.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for slot, stem_dict in enumerate(self.stem_paths):
                    if stem_dict:
                        song_name = Path(self.song_paths[slot]).stem
                        for stem_name, stem_path in stem_dict.items():
                            arcname = f"Song_{slot+1}_{song_name}/{stem_name}.wav"
                            zf.write(stem_path, arcname=arcname)
            self.add_status(f"📦 Stems exported: {zip_path.name}")
            print(f"[Stems] ZIP created: {zip_path}")
            return str(zip_path), f"Stems downloaded: stems_export.zip"
        except Exception as e:
            self.add_status(f"❌ Stem export error: {e}")
            print(f"[Stems] Export error: {e}")
            return None, f"Export error: {str(e)[:100]}"

    def save_preset(self, name):
        """Save current settings to a JSON preset file."""
        try:
            data = {
                "sliders": self.sliders,
                "crossfader": self.crossfader,
                "target_bpm": self.target_bpm,
                "beatmatch": self.beatmatch,
                "bpm_overrides": self.bpm_overrides,
                "beat_offsets": self.beat_offsets,
            }
            path = presets_dir / f"{name}.json" if not name.endswith(".json") else presets_dir / name
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            return f"Preset saved: {path.name}"
        except Exception as e:
            return f"Save error: {str(e)[:100]}"

    def load_preset(self, name):
        """Load settings from a JSON preset file."""
        try:
            path = presets_dir / name if (presets_dir / name).exists() else presets_dir / f"{name}.json"
            with open(path) as f:
                data = json.load(f)
            loaded_sliders = data.get("sliders", {})
            self.sliders.update(loaded_sliders)
            self.crossfader = data.get("crossfader", 50)
            self.target_bpm = data.get("target_bpm", 0)
            self.beatmatch = data.get("beatmatch", False)
            self.bpm_overrides = data.get("bpm_overrides", [0, 0])
            self.beat_offsets = data.get("beat_offsets", [0, 0])
            return f"Preset loaded: {path.name}"
        except Exception as e:
            return f"Load error: {str(e)[:100]}"

def create_app():
    state = StudioState()

    with gr.Blocks(
        title="Stem Mashup Pro - AI-Powered Music Mashup & Mixing Studio"
    ) as app:
        gr.Markdown("# Stem Mashup Pro — AI-Powered Music Mashup & Mixing")

        # ===== Load & Analyze =====
        gr.Markdown("### Load Songs & Auto-Detect BPM")

        file_inputs = []
        bpm_displays = []
        key_displays = []
        bpm_overrides_ui = []
        key_overrides_ui = []
        beat_offsets_ui = []
        audio_players = []

        with gr.Row():
            for i in range(2):
                with gr.Column():
                    gr.Markdown(f"**Song {i+1}**")
                    file_input = gr.File(
                        label=f"Load",
                        file_count="single",
                        type="filepath"
                    )
                    file_inputs.append(file_input)

                    audio_player = gr.Audio(label="Preview", type="filepath", interactive=False)
                    audio_players.append(audio_player)

                    with gr.Row():
                        bpm_display = gr.Textbox(label="BPM", value="—", interactive=False, scale=1)
                        bpm_displays.append(bpm_display)
                        key_display = gr.Textbox(label="Key", value="—", interactive=False, scale=1)
                        key_displays.append(key_display)

                    with gr.Row():
                        bpm_override = gr.Number(label="Override BPM", value=0, minimum=0, maximum=200, scale=1)
                        bpm_overrides_ui.append(bpm_override)
                        key_override = gr.Dropdown(
                            label="Override Key",
                            choices=["Auto-detect"] + KEY_NAMES,
                            value="Auto-detect",
                            scale=1
                        )
                        key_overrides_ui.append(key_override)


        # System status display with auto-refresh
        with gr.Row():
            separate_status = gr.Textbox(
                label="System Status",
                value="",
                interactive=False,
                lines=6,
                max_lines=6
            )
            status_refresh_timer = gr.Timer(value=0.5, active=True)

            def update_status_display():
                status_text = state.get_status_text()
                # Add progress bar if stems are being processed
                if not state.stems_ready() and (state.sep_in_progress or any(state.song_bpms)):
                    fill = int((state.animation_frame % 20) * 5)  # Animated fill
                    bar = "█" * fill + "░" * (20 - fill)
                    status_text += f"\n\n⚙️ Processing... [{bar}]"
                # Show completion message when stems are ready
                elif state.stems_ready():
                    status_text += "\n\n✨ Files analyzed and stems created, have fun Mixing!"
                return gr.update(value=status_text)

            status_refresh_timer.tick(
                update_status_display,
                outputs=[separate_status]
            )

        with gr.Row():
            stems_download = gr.File(label="📥 Download Stems (ZIP)", type="filepath", interactive=False, scale=1, container=False)

            def get_stems_zip():
                zip_path = BASE_DIR / "stems_export.zip"
                if zip_path.exists():
                    return str(zip_path)
                return None

            # Update download file when stems are ready
            def update_download():
                if state.stems_ready():
                    return gr.update(interactive=True, value=get_stems_zip())
                return gr.update(interactive=False, value=None)

            status_refresh_timer.tick(
                update_download,
                outputs=[stems_download]
            )

        def make_load_callback(slot):
            def load_and_update(f):
                if f is None:
                    state.song_paths[slot] = None
                    state.stem_paths[slot] = None
                    state.song_bpms[slot] = None
                    state.song_keys[slot] = None
                    state.add_status(f"🗑️ Song {slot+1} removed")
                    status_text = state.get_status_text()
                    return None, "—", "—", status_text
                else:
                    msg, audio_path, _ = state.load_song(f, slot)
                    bpm_text = state.get_bpm_display(slot)
                    key_text = state.get_key_display(slot)
                    status_text = state.get_status_text()
                    return audio_path, bpm_text, key_text, status_text
            return load_and_update

        for i, file_input in enumerate(file_inputs):
            if i == 0:
                file_input.change(
                    make_load_callback(i),
                    inputs=[file_input],
                    outputs=[audio_players[i], bpm_displays[i], key_displays[i], separate_status]
                )
            else:
                def make_song2_callback(slot):
                    def load_song2(f):
                        if f is None:
                            state.song_paths[slot] = None
                            state.stem_paths[slot] = None
                            state.song_bpms[slot] = None
                            state.song_keys[slot] = None
                            state.add_status(f"🗑️ Song {slot+1} removed")
                            return None, "—", "—", state.get_status_text()

                        msg, audio_path, _ = state.load_song(f, slot)
                        bpm_text = state.get_bpm_display(slot)
                        key_text = state.get_key_display(slot)
                        status_text = state.get_status_text()
                        return audio_path, bpm_text, key_text, status_text
                    return load_song2

                file_input.change(
                    make_song2_callback(i),
                    inputs=[file_input],
                    outputs=[audio_players[i], bpm_displays[i], key_displays[i], separate_status]
                )

        # Song 2 is kept enabled (always loadable)

        # BPM override callbacks
        for i, bpm_override in enumerate(bpm_overrides_ui):
            bpm_override.change(
                lambda val, slot=i: state.update_bpm_override(slot, val),
                inputs=[bpm_override]
            )

        # Key override callbacks
        for i, key_override in enumerate(key_overrides_ui):
            key_override.change(
                lambda val, slot=i: state.update_key_override(slot, val),
                inputs=[key_override]
            )

        # Beat offset callbacks
        for slot, offset_ui in beat_offsets_ui:
            offset_ui.change(
                lambda v, s=slot: state.update_beat_offset(s, v),
                inputs=[offset_ui]
            )

        # ===== Per-Song Controls =====
        gr.Markdown("### Per-Song Levels & Effects")

        slider_refs = {}
        pitch_dropdowns = []
        with gr.Row():
            for i in range(2):
                with gr.Column():
                    gr.Markdown(f"**Song {i+1}**")
                    gr.Markdown("*Stem Levels*")
                    for name, label in [("vocals_vol", "Vocals"), ("beats_vol", "Beats"), ("bass_vol", "Bass"), ("other_vol", "Other")]:
                        sl = gr.Slider(0, 1, value=1, step=0.1, label=label, interactive=False)
                        sl.change(lambda v, s=i, n=name: state.update_slider(f"s{s}_{n}", v), inputs=[sl])
                        slider_refs[f"s{i}_{name}"] = sl

                    gr.Markdown("*Effects*")

                    # Pitch shift as key selector dropdown - shows detected key by default
                    pitch_dropdown = gr.Dropdown(
                        label="Pitch Shift (Select Key)",
                        choices=KEY_NAMES,
                        value=KEY_NAMES[0],
                        interactive=False
                    )
                    pitch_dropdowns.append(pitch_dropdown)

                    def make_pitch_callback(slot):
                        def on_pitch_change(key_name):
                            if key_name in KEY_NAMES:
                                key_idx = KEY_NAMES.index(key_name)
                                detected_idx = state.song_keys[slot] if state.song_keys[slot] is not None else 0
                                semitone_shift = (key_idx - detected_idx) % 12
                                if semitone_shift > 6:
                                    semitone_shift -= 12
                                state.update_slider(f"s{slot}_pitch_shift", semitone_shift)
                                state.add_status(f"🎵 Song {slot+1} pitch: {key_name} ({semitone_shift:+d} semitones)")
                        return on_pitch_change

                    pitch_dropdown.change(
                        make_pitch_callback(i),
                        inputs=[pitch_dropdown]
                    )
                    slider_refs[f"s{i}_pitch_shift"] = pitch_dropdown

                    # Other effects
                    for name, label, min_v, max_v, default in [
                        ("reverb", "Reverb", 0, 1, 0),
                        ("speed", "Speed", 0.5, 1.5, 1),
                        ("eq_low", "EQ Low", -1.5, 1.5, 0),
                        ("eq_mid", "EQ Mid", -1.5, 1.5, 0),
                        ("eq_high", "EQ High", -1.5, 1.5, 0),
                    ]:
                        sl = gr.Slider(min_v, max_v, value=default, step=0.1, label=label, interactive=False)
                        sl.change(lambda v, s=i, n=name: state.update_slider(f"s{s}_{n}", v), inputs=[sl])
                        slider_refs[f"s{i}_{name}"] = sl

        # ===== Mixing Controls =====
        gr.Markdown("### Mixing")

        pitch_suggestion = gr.Textbox(label="Pitch Shift Suggestion", value="—", interactive=False)

        def update_pitch_suggestion():
            keys = state.get_effective_keys()
            if keys[0] < 0 or keys[1] < 0:
                return "Detect both keys first."

            song1_key_name = state.engine._key_to_note(keys[0])
            song2_key_name = state.engine._key_to_note(keys[1])

            if keys[0] == keys[1]:
                return f"Keys match! Both are {song1_key_name}"
            else:
                # Calculate semitone difference
                diff = state.engine._semitones_between(keys[1], keys[0])
                abs_diff = abs(diff)

                # Calculate balanced approach: meet in the middle
                mid_shift_s1 = -diff / 2 if diff > 0 else diff / 2
                mid_shift_s2 = diff / 2 if diff > 0 else -diff / 2
                mid_shift_s1 = round(mid_shift_s1 * 2) / 2
                mid_shift_s2 = round(mid_shift_s2 * 2) / 2

                mid_key_idx = (keys[0] + keys[1]) // 2
                mid_key_name = state.engine._key_to_note(mid_key_idx)

                return (f"{abs_diff} steps: Shift Song 2 {diff:+d} semitones to {song1_key_name}, "
                        f"or meet in middle ({mid_key_name}): S1 {mid_shift_s1:+.1f}, S2 {mid_shift_s2:+.1f}")

        for key_override in key_overrides_ui:
            key_override.change(
                lambda: update_pitch_suggestion(),
                outputs=[pitch_suggestion]
            )

        with gr.Row():
            crossfader = gr.Slider(0, 100, value=50, step=1, label="Crossfader (Song 1 ← → Song 2)")
            crossfader.change(lambda v: state.update_crossfader(v), inputs=[crossfader])

        with gr.Row():
            target_bpm = gr.Number(label="Target Tempo (BPM, 0 = off)", value=0, minimum=0, maximum=200)
            beatmatch = gr.Checkbox(label="Beatmatch (align beat grids)", value=False)
            beat_phase_offset = gr.Slider(0, 4, value=0, step=0.1, label="Song 2 Beat Phase (0-4 beats)")

            target_bpm.change(lambda v: state.update_target_bpm(v), inputs=[target_bpm])
            beatmatch.change(lambda v: state.update_beatmatch(v), inputs=[beatmatch])
            beat_phase_offset.change(
                lambda v: state.update_beat_offset(1, v),
                inputs=[beat_phase_offset]
            )

        # ===== Presets =====
        gr.Markdown("### Presets")
        with gr.Row():
            preset_name = gr.Textbox(label="Preset Name", placeholder="my_mashup")
            save_btn = gr.Button("Save Preset")
            load_btn = gr.Button("Load Preset")
            preset_status = gr.Textbox(value="Ready", interactive=False, scale=2)

        save_btn.click(
            lambda name: state.save_preset(name),
            inputs=[preset_name],
            outputs=[preset_status]
        )

        load_btn.click(
            lambda name: state.load_preset(name),
            inputs=[preset_name],
            outputs=[preset_status]
        )

        # ===== Render =====
        gr.Markdown("### Render")

        with gr.Row():
            preview_btn = gr.Button("▶ LIVE PREVIEW", size="lg", scale=1, interactive=False)
            render_btn = gr.Button("🎛️ RENDER REMIX", size="lg", scale=1, interactive=False)

        with gr.Row():
            output_audio = gr.Audio(label="Output", type="filepath")
            render_status = gr.Textbox(label="Status", value="Ready", interactive=False, scale=2)

        preview_btn.click(
            lambda: state.preview(),
            outputs=[output_audio, render_status]
        )

        render_btn.click(
            lambda: state.render(),
            outputs=[output_audio, render_status]
        )

        # Enable controls when stems are ready + animated status + pitch suggestion + BPM/Key displays + pitch dropdowns
        def refresh_status_and_controls():
            status_text = state.get_animated_status()
            stems_ready = state.stems_ready()

            # Get BPM and Key displays for both songs
            bpm1_text = state.get_bpm_display(0)
            key1_text = state.get_key_display(0)
            bpm2_text = state.get_bpm_display(1)
            key2_text = state.get_key_display(1)

            # Get detected keys for pitch dropdowns
            keys = state.get_effective_keys()
            pitch1_value = KEY_NAMES[keys[0]] if keys[0] >= 0 and keys[0] < len(KEY_NAMES) else KEY_NAMES[0]
            pitch2_value = KEY_NAMES[keys[1]] if keys[1] >= 0 and keys[1] < len(KEY_NAMES) else KEY_NAMES[0]

            # Get pitch shift suggestion (key names + options)
            if keys[0] < 0 or keys[1] < 0:
                pitch_text = "Detect both keys first."
            elif keys[0] == keys[1]:
                key_name = state.engine._key_to_note(keys[0])
                pitch_text = f"Keys match! Both are {key_name}"
            else:
                song1_key = state.engine._key_to_note(keys[0])
                song2_key = state.engine._key_to_note(keys[1])
                diff = state.engine._semitones_between(keys[1], keys[0])
                abs_diff = abs(diff)

                mid_shift_s1 = -diff / 2 if diff > 0 else diff / 2
                mid_shift_s2 = diff / 2 if diff > 0 else -diff / 2
                mid_shift_s1 = round(mid_shift_s1 * 2) / 2
                mid_shift_s2 = round(mid_shift_s2 * 2) / 2

                mid_key_idx = (keys[0] + keys[1]) // 2
                mid_key = state.engine._key_to_note(mid_key_idx)

                pitch_text = (f"{abs_diff} steps: Shift S2 {diff:+d} semitones to {song1_key}, "
                             f"or middle ({mid_key}): S1 {mid_shift_s1:+.1f}, S2 {mid_shift_s2:+.1f}")

            updates = [status_text, gr.update(interactive=stems_ready), gr.update(interactive=stems_ready), pitch_text,
                      gr.update(value=bpm1_text), gr.update(value=key1_text), gr.update(value=bpm2_text), gr.update(value=key2_text),
                      gr.update(value=pitch1_value), gr.update(value=pitch2_value)]
            # Update all sliders
            for slider in slider_refs.values():
                updates.append(gr.update(interactive=stems_ready))
            return updates

        slider_outputs = list(slider_refs.values())
        status_refresh_timer.tick(
            refresh_status_and_controls,
            outputs=[separate_status, preview_btn, render_btn, pitch_suggestion, bpm_displays[0], key_displays[0], bpm_displays[1], key_displays[1], pitch_dropdowns[0], pitch_dropdowns[1]] + slider_outputs
        )

    return app

if __name__ == "__main__":
    app = create_app()
    app.launch(share=False, theme=gr.themes.Base(primary_hue="purple"))

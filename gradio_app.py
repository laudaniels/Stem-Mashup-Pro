#!/usr/bin/env python3
import sys
from pathlib import Path

def _running_in_venv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)

if not _running_in_venv():
    sys.exit(
        "Kolkata Studio must be run from inside a virtual environment.\n\n"
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
        self.auto_sep_triggered = False
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
        """Load a song and kick off BPM and key analysis."""
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
            except Exception as e:
                self.add_status(f"❌ Song {slot+1}: Analysis error: {e}")
                self.song_bpms[slot] = False
                self.song_keys[slot] = -1
            finally:
                self._analysis_events[slot].set()

        thread = threading.Thread(target=analyze, daemon=True)
        thread.start()

        if not self.both_songs_loaded():
            other = 2 - slot
            self.add_status(f"⏳ Waiting for Song {other}...")

        self._analysis_events[slot].wait(timeout=120)
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
            except Exception as e:
                print(f"[Stems] Error: {type(e).__name__}: {e}")
                self.add_status(f"❌ Stem separation error: {e}")
            finally:
                self.sep_in_progress = False

        threading.Thread(target=task, daemon=True).start()
        return "Separating stems — this may take several minutes…"

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
        title="Kolkata Studio v7.4 - Waveform + Crossfader + Beatmatch"
    ) as app:
        gr.Markdown("# Kolkata Studio v7.4 — Waveform + Crossfader + Beatmatch")

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

                    if i == 0:
                        gr.Textbox(label="Beat Phase Offset", value="— (Reference)", interactive=False)
                    else:
                        beat_offset = gr.Number(label="Beat Phase Offset", value=0, step=0.1)
                        beat_offsets_ui.append((i, beat_offset))

        # System status display with auto-refresh
        with gr.Row():
            separate_status = gr.Textbox(
                label="System Status",
                value="",
                interactive=False,
                lines=6,
                max_lines=6
            )
            status_refresh_timer = gr.Timer(value=1.0, active=True)

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

                    with state._sep_lock:
                        if state.both_songs_loaded() and not state.auto_sep_triggered:
                            state.auto_sep_triggered = True
                            state.separate_stems()

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

                        with state._sep_lock:
                            if state.both_songs_loaded() and not state.auto_sep_triggered:
                                state.auto_sep_triggered = True
                                state.separate_stems()

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
                    for name, label, min_v, max_v, default in [
                        ("pitch_shift", "Pitch Shift", -1.5, 1.5, 0),
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
            suggestion = state.get_pitch_shift_suggestion()
            if suggestion == 0:
                return "Keys match! No pitch shift needed."
            else:
                direction = "up" if suggestion > 0 else "down"
                return f"Shift Song 2 {abs(suggestion)} semitones {direction} to match Song 1"

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

            target_bpm.change(lambda v: state.update_target_bpm(v), inputs=[target_bpm])
            beatmatch.change(lambda v: state.update_beatmatch(v), inputs=[beatmatch])

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

        # Enable controls when stems are ready + animated status
        def refresh_status_and_controls():
            status_text = state.get_animated_status()
            stems_ready = state.stems_ready()
            return status_text, gr.update(interactive=stems_ready), gr.update(interactive=stems_ready)

        status_refresh_timer.tick(
            refresh_status_and_controls,
            outputs=[separate_status, preview_btn, render_btn]
        )

    return app

if __name__ == "__main__":
    app = create_app()
    app.launch(share=False, theme=gr.themes.Base(primary_hue="purple"))

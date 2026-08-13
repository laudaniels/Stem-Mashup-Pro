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

    def load_song(self, file_obj, slot):
        """Load a song and kick off BPM and key analysis."""
        if file_obj is None:
            return f"Song {slot+1}: no file", "", ""
        self.song_paths[slot] = file_obj.name
        self.stem_paths[slot] = None
        self.song_bpms[slot] = None
        self.song_beat_anchors[slot] = None
        self.song_keys[slot] = None

        def analyze():
            try:
                bpm, anchor = self.engine.analyze_track(file_obj.name)
                self.song_bpms[slot] = bpm
                self.song_beat_anchors[slot] = anchor
                key = self.engine.analyze_key(file_obj.name)
                self.song_keys[slot] = key
            except Exception as e:
                self.song_bpms[slot] = False

        threading.Thread(target=analyze, daemon=True).start()
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
            return "No new songs to separate."

        def task():
            try:
                song_paths_list = [p for _, p in selected]
                created = self.engine.separate_stems(song_paths_list)
                for (slot, _), stem_set in zip(selected, created):
                    self.stem_paths[slot] = stem_set
            except Exception:
                pass

        threading.Thread(target=task, daemon=True).start()
        return "Separating stems — this may take several minutes…"

    def update_slider(self, key, value):
        self.sliders[key] = value

    def update_crossfader(self, value):
        self.crossfader = value

    def update_target_bpm(self, value):
        self.target_bpm = value or 0

    def update_beatmatch(self, value):
        self.beatmatch = value

    def update_bpm_override(self, slot, value):
        self.bpm_overrides[slot] = value or 0.0

    def update_beat_offset(self, slot, value):
        self.beat_offsets[slot] = value or 0.0

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
        title="Kolkata Studio v7.4 - Waveform + Crossfader + Beatmatch",
        theme=gr.themes.Base(primary_hue="purple")
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
                    file_input = gr.File(label=f"Load", file_count="single", type="filepath")
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
                        key_override = gr.Number(label="Override Key (0-11)", value=-1, minimum=-1, maximum=11, scale=1)
                        key_overrides_ui.append(key_override)

                    if i == 0:
                        gr.Textbox(label="Beat Phase Offset", value="— (Reference)", interactive=False)
                    else:
                        beat_offset = gr.Number(label="Beat Phase Offset", value=0, step=0.1)
                        beat_offsets_ui.append((i, beat_offset))

        # Setup load callbacks with proper closures
        separate_status = gr.Textbox(value="Ready", interactive=False, scale=2)

        def make_load_callback(slot):
            def load_and_update(f):
                msg, audio_path, _ = state.load_song(f, slot)
                bpm_text = state.get_bpm_display(slot)
                key_text = state.get_key_display(slot)
                sep_status = "Ready"

                with state._sep_lock:
                    if state.both_songs_loaded() and not state.auto_sep_triggered:
                        state.auto_sep_triggered = True
                        sep_status = state.separate_stems()

                return audio_path, bpm_text, key_text, sep_status
            return load_and_update

        for i, file_input in enumerate(file_inputs):
            file_input.change(
                make_load_callback(i),
                inputs=[file_input],
                outputs=[audio_players[i], bpm_displays[i], key_displays[i], separate_status]
            )

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
                        sl = gr.Slider(0, 1, value=1, step=0.1, label=label)
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
                        sl = gr.Slider(min_v, max_v, value=default, step=0.1, label=label)
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
            preview_btn = gr.Button("▶ LIVE PREVIEW", size="lg", scale=1)
            render_btn = gr.Button("🎛️ RENDER REMIX", size="lg", scale=1)

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

    return app

if __name__ == "__main__":
    app = create_app()
    app.launch(share=False)

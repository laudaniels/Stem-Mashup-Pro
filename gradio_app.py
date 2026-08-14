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
from datetime import datetime
from mashup_engine import MashupEngine

BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / "Audio"
AUDIO_DIR.mkdir(exist_ok=True)
# Ensure Audio directory has proper permissions
import os as _os
_os.chmod(str(AUDIO_DIR), 0o755)

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
        self.pitch_manually_changed = [False, False]  # Track if user has manually changed pitch
        self.selected_pitch_keys = [None, None]  # Track selected keys from pitch dropdown for filename
        self._sep_lock = Lock()
        self._analysis_locks = [Lock(), Lock()]  # Prevent race conditions on analysis/separation
        self._analysis_events = [threading.Event(), threading.Event()]
        self.status_messages = []
        self._status_lock = Lock()
        self.sep_in_progress = False
        self.render_in_progress = False
        self.render_counter = 0  # Counter for unique filenames
        self.last_render_path = None  # Track the last render for display
        self.animation_frame = 0  # For progress bar animation

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
            if len(self.status_messages) > 30:
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

        # Handle both File object (from gr.File) and string path (from gr.Audio)
        file_path = file_obj.name if hasattr(file_obj, 'name') else file_obj
        self.song_paths[slot] = file_path
        self.stem_paths[slot] = None
        self.song_bpms[slot] = None
        self.song_beat_anchors[slot] = None
        self.song_keys[slot] = None
        self._analysis_events[slot].clear()

        self.add_status(f"📁 Song {slot+1} loaded: {Path(file_path).name}")

        def analyze():
            # Use lock to prevent multiple concurrent analyses for this slot
            with self._analysis_locks[slot]:
                self.sep_in_progress = True
                try:
                    self.add_status(f"🎵 Song {slot+1}: Analyzing BPM...")
                    bpm, anchor = self.engine.analyze_track(file_path)
                    self.song_bpms[slot] = bpm
                    self.song_beat_anchors[slot] = anchor
                    self.add_status(f"✓ Song {slot+1}: BPM = {bpm:.0f}")

                    self.add_status(f"🎼 Song {slot+1}: Analyzing key...")
                    key = self.engine.analyze_key(file_path)
                    self.song_keys[slot] = key
                    key_name = self.engine._key_to_note(key) if key >= 0 else "?"
                    self.add_status(f"✓ Song {slot+1}: Key = {key_name}")

                    # Start stem separation for this song immediately after analysis
                    if not self.stem_paths[slot]:
                        self.add_status(f"🔄 Song {slot+1}: Starting stem separation...")
                        try:
                            stem_set = self.engine.separate_stems([file_path])
                            self.stem_paths[slot] = stem_set[0]
                            self.add_status(f"✓ Song {slot+1}: Stems ready (Vocals, Beats, Bass, Other)")

                            # Create ZIP when both songs' stems are ready
                            if self.stems_ready():
                                self._create_stems_zip()
                        except Exception as sep_e:
                            self.add_status(f"❌ Song {slot+1}: Stem separation error: {sep_e}")

                except Exception as e:
                    self.add_status(f"❌ Song {slot+1}: Analysis error: {e}")
                    self.song_bpms[slot] = False
                    self.song_keys[slot] = -1
                finally:
                    self.sep_in_progress = False
                    self._analysis_events[slot].set()

        # Start analysis in background without waiting
        thread = threading.Thread(target=analyze, daemon=True)
        thread.start()

        if not self.both_songs_loaded():
            other = 2 - slot
            self.add_status(f"⏳ Waiting for Song {other}...")

        # Return immediately with audio file - don't wait for analysis!
        return f"Song {slot+1}: {Path(file_path).name} (analyzing…)", file_path, ""

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

                # Auto-create ZIP file and preview when all stems are ready
                if self.stems_ready():
                    self._create_stems_zip()
                    self._auto_generate_preview()

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
        import os
        import subprocess
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            zip_filename = f"stems_export_original_{timestamp}.zip"
            zip_path = AUDIO_DIR / zip_filename
            temp_dir = AUDIO_DIR / f"temp_stems_{timestamp}"
            temp_dir.mkdir(exist_ok=True)

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for slot, stem_dict in enumerate(self.stem_paths):
                    if stem_dict:
                        song_name = Path(self.song_paths[slot]).stem
                        for stem_name, stem_path in stem_dict.items():
                            # Convert to 16-bit WAV
                            temp_wav = temp_dir / f"{stem_name}_{slot}.wav"
                            subprocess.run(
                                ["ffmpeg", "-i", stem_path, "-acodec", "pcm_s16le", str(temp_wav), "-y"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                check=True
                            )
                            arcname = f"Song_{slot+1}_{song_name}/{stem_name}.wav"
                            zf.write(str(temp_wav), arcname=arcname)

            # Clean up temp directory
            import shutil
            shutil.rmtree(temp_dir)

            # Ensure ZIP file is readable
            os.chmod(str(zip_path), 0o644)
            self.add_status(f"📦 ZIP ready: {zip_filename}")
            print(f"[Stems] ZIP auto-created: {zip_path}")
        except Exception as e:
            print(f"[Stems] ZIP creation error: {e}")
            self.add_status(f"❌ ZIP creation error: {e}")

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
            self.pitch_manually_changed[slot] = False  # Reset so pitch dropdown updates
            print(f"[Key Override] Song {slot+1} = {value}")
            self.add_status(f"🎹 Song {slot+1} key override: {value}")
        else:
            self.key_overrides[slot] = -1
            self.pitch_manually_changed[slot] = False  # Reset so pitch dropdown updates
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

    def _auto_generate_preview(self):
        """Auto-generate preview when stems are ready. Stores in last_render_path."""
        try:
            if not self.stems_ready():
                return

            self.add_status("🎵 Auto-generating preview mix with current settings...")
            audio_path, msg = self.preview()

            if audio_path:
                self.last_render_path = audio_path
                self.add_status("✨ Preview ready! Click play to listen.")
                print(f"[Auto-Preview] Generated: {Path(audio_path).name}")
            else:
                self.add_status(f"Preview not ready: {msg}")
        except Exception as e:
            self.add_status(f"❌ Auto-preview error: {str(e)[:100]}")
            print(f"[Auto-Preview] Error: {e}")

    def render(self):
        """Render the full remix and adjusted stems."""
        try:
            params = self.build_params()
            if not params["songs"][0] or not params["songs"][1]:
                return None, "Load Song 1 and Song 2 before rendering."

            self.render_in_progress = True

            # Get the actual settings used
            keys = self.get_effective_keys()
            bpms = self.get_effective_bpms()
            target_bpm = params.get("target_bpm") or 0
            bpm_overridden = target_bpm > 0

            # Check if pitch has been shifted (using the sliders, not just key overrides)
            pitch_shift_1 = abs(self.sliders.get("s0_pitch_shift", 0.0)) > 0.05
            pitch_shift_2 = abs(self.sliders.get("s1_pitch_shift", 0.0)) > 0.05
            pitch_changed = pitch_shift_1 or pitch_shift_2

            # Get key and BPM display values
            # Use selected pitch keys if manually changed, otherwise use detected keys
            key1_name = self.selected_pitch_keys[0].split()[0] if self.selected_pitch_keys[0] else (self.engine._key_to_note(keys[0]) if keys[0] >= 0 else "?")
            key2_name = self.selected_pitch_keys[1].split()[0] if self.selected_pitch_keys[1] else (self.engine._key_to_note(keys[1]) if keys[1] >= 0 else "?")
            detected_bpm = int(bpms[0]) if bpms[0] else 0  # Use Song 1's BPM as reference

            # Build filename with actual settings or "original" if nothing changed
            if not (pitch_changed or bpm_overridden):
                # No changes - show "original" with the original detected values
                output_name_base = f"final_remix_original_{key1_name}-{key2_name}_{detected_bpm}bpm"
            else:
                # Show what was changed
                bpm_str = f"{int(target_bpm)}bpm" if bpm_overridden else f"{detected_bpm}bpm"
                output_name_base = f"final_remix_{key1_name}-{key2_name}_{bpm_str}"

            # Render the final remix with all slider settings to Audio folder
            temp_output = self.engine.render(params, preview=False)

            # Use MP3 directly with unique counter
            self.render_counter += 1
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            output_name = f"{output_name_base}_{timestamp}_{self.render_counter}.mp3"
            output = str(AUDIO_DIR / output_name)

            import shutil
            import os
            # Move the temp MP3 to the final location
            shutil.move(temp_output, output)
            # Ensure file is readable
            os.chmod(output, 0o644)

            # Clean up old render files (keep only 3 most recent)
            try:
                render_files = sorted(AUDIO_DIR.glob("final_remix_*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
                for old_file in render_files[3:]:  # Keep 3 most recent
                    old_file.unlink()

                # Also clean up old render ZIPs (keep only 3 most recent)
                render_zips = sorted(AUDIO_DIR.glob("render_output_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
                for old_zip in render_zips[3:]:  # Keep 3 most recent
                    old_zip.unlink()
            except Exception as e:
                print(f"[Render] Cleanup warning: {e}")

            # Create adjusted stems (pitch/tempo only, no mixing)
            self._render_adjusted_stems_silent(params, key1_name, key2_name, detected_bpm, target_bpm, bpm_overridden, pitch_changed)

            # Create ZIP file with all outputs
            zip_path = self._create_render_zip(output, output_name_base, timestamp)
            self.last_render_path = zip_path  # Track for display

            self.render_in_progress = False
            return output, f"✨ Render complete! Remix: {output_name}\n📦 Download package ready in Audio/ folder"
        except Exception as e:
            self.render_in_progress = False
            return None, f"❌ Render error: {str(e)[:100]}"

    def _render_adjusted_stems_silent(self, params, key1_name, key2_name, detected_bpm, target_bpm, bpm_overridden, pitch_changed):
        """Render individual stems solo with all effects applied."""
        try:
            stems_adjusted_dir = AUDIO_DIR / "stems_bpm-key-adjusted"
            # Clear old stems before creating new ones
            if stems_adjusted_dir.exists():
                import shutil
                shutil.rmtree(stems_adjusted_dir)
            stems_adjusted_dir.mkdir(exist_ok=True)

            stem_types = ["vocals", "beats", "bass", "other"]
            bpm_value = int(target_bpm) if target_bpm and target_bpm > 0 else int(detected_bpm) if detected_bpm else 0

            for slot in range(2):
                if not self.stem_paths[slot]:
                    continue

                song_name = Path(self.song_paths[slot]).stem
                current_key = key1_name if slot == 0 else key2_name

                # Render each stem solo (mute others, apply all effects)
                for stem_type in stem_types:
                    # Create params copy with all stem volumes set to 0 except this one
                    solo_params = params.copy()
                    solo_params["sliders"] = params["sliders"].copy()

                    # Mute all stems except the current one
                    for s in range(2):
                        for st in stem_types:
                            solo_params["sliders"][f"s{s}_{st}_vol"] = 0.0

                    # Unmute only this stem
                    solo_params["sliders"][f"s{slot}_{stem_type}_vol"] = 1.0

                    # Render the solo stem with all effects applied
                    temp_output = self.engine.render(solo_params, preview=False)

                    # Save as high-quality, uncompressed WAV
                    suffix = f"{current_key}_{bpm_value}bpm"
                    output_path = stems_adjusted_dir / f"Song{slot+1}_{song_name}_{stem_type}_{suffix}.wav"

                    # Convert to 16-bit PCM WAV
                    import subprocess
                    subprocess.run(
                        ["ffmpeg", "-i", temp_output, "-acodec", "pcm_s16le", str(output_path), "-y"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True
                    )

                    # Clean up temp file
                    Path(temp_output).unlink()

        except Exception as e:
            print(f"[Render] Stem adjustment error: {e}")

    def _render_adjusted_stems(self, params):
        """Render individual stems with pitch/tempo adjustments (no mixing)."""
        try:
            stems_adjusted_dir = AUDIO_DIR / "stems_bpm-key-adjusted"
            stems_adjusted_dir.mkdir(exist_ok=True)

            # Process each song's stems
            bpms = self.get_effective_bpms()
            for slot in range(2):
                if not self.stem_paths[slot]:
                    continue

                song_name = Path(self.song_paths[slot]).stem
                stem_dict = self.stem_paths[slot]
                song_bpm = bpms[slot]

                # Only process if we have a valid BPM
                if not song_bpm:
                    self.add_status(f"⚠️ Skipping Song {slot+1} stems: no BPM detected")
                    continue

                pitch_shift = self.sliders.get(f"s{slot}_pitch_shift", 0.0)
                speed_factor = self.sliders.get(f"s{slot}_speed", 1.0)

                # Process each stem type
                for stem_name, stem_path in stem_dict.items():
                    output_path = stems_adjusted_dir / f"Song{slot+1}_{song_name}_{stem_name}_bpm-key-adjusted.wav"

                    # Use engine to apply pitch and tempo adjustments
                    self.engine.process_stem(
                        stem_path,
                        str(output_path),
                        pitch_shift=pitch_shift,
                        speed=speed_factor,
                        target_bpm=params.get("target_bpm"),
                        song_bpm=song_bpm
                    )
                    self.add_status(f"✓ Stem: {output_path.name}")

            self.add_status(f"✓ All stems processed and ready")
        except Exception as e:
            self.add_status(f"❌ Stem processing error: {e}")
            print(f"[Stems] Adjustment error: {e}")

    def _create_render_zip(self, remix_path, output_name_base, timestamp):
        """Create ZIP file with remix and adjusted stems."""
        import zipfile
        import os
        try:
            zip_filename = f"render_output_{output_name_base}_{timestamp}.zip"
            zip_path = AUDIO_DIR / zip_filename
            stems_adjusted_dir = AUDIO_DIR / "stems_bpm-key-adjusted"

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # Add the final remix
                if Path(remix_path).exists():
                    remix_filename = f"01_final_remix_{output_name_base}_{timestamp}.mp3"
                    zf.write(remix_path, arcname=remix_filename)

                # Add all adjusted stems
                if stems_adjusted_dir.exists():
                    for stem_file in sorted(stems_adjusted_dir.glob("*.wav")):
                        zf.write(stem_file, arcname=f"02_stems/{stem_file.name}")

            # Ensure ZIP file is readable
            os.chmod(str(zip_path), 0o644)
            self.add_status(f"✓ Download package ready: {zip_filename}")
            print(f"[Render] ZIP created: {zip_path}")
            return str(zip_path)
        except Exception as e:
            print(f"[Render] ZIP creation error: {e}")
            self.add_status(f"⚠️ ZIP creation: {e}")
            return None

    def download_stems(self):
        """Create a ZIP file of all separated stems."""
        import zipfile
        import os
        import subprocess

        if not self.both_songs_loaded():
            return None, "Load both songs first."
        if not self.stem_paths[0] or not self.stem_paths[1]:
            return None, "Separate stems first."

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            zip_filename = f"stems_export_original_{timestamp}.zip"
            zip_path = AUDIO_DIR / zip_filename
            temp_dir = AUDIO_DIR / f"temp_stems_{timestamp}"
            temp_dir.mkdir(exist_ok=True)

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for slot, stem_dict in enumerate(self.stem_paths):
                    if stem_dict:
                        song_name = Path(self.song_paths[slot]).stem
                        for stem_name, stem_path in stem_dict.items():
                            # Convert to 16-bit WAV
                            temp_wav = temp_dir / f"{stem_name}_{slot}.wav"
                            subprocess.run(
                                ["ffmpeg", "-i", stem_path, "-acodec", "pcm_s16le", str(temp_wav), "-y"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                check=True
                            )
                            arcname = f"Song_{slot+1}_{song_name}/{stem_name}.wav"
                            zf.write(str(temp_wav), arcname=arcname)

            # Clean up temp directory
            import shutil
            shutil.rmtree(temp_dir)

            # Ensure ZIP file is readable
            os.chmod(str(zip_path), 0o644)
            self.add_status(f"📦 Stems exported: {zip_filename}")
            print(f"[Stems] ZIP created: {zip_path}")
            return str(zip_path), f"Stems downloaded: {zip_filename}"
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

    def count_audio_files(self):
        """Count files/folders in Audio directory."""
        count = 0
        if AUDIO_DIR.exists():
            for file in AUDIO_DIR.glob("*"):
                count += 1
        return count

    def cleanup_audio_files(self):
        """Delete all generated audio files."""
        try:
            import shutil
            deleted_count = 0

            # Delete files in Audio folder
            if AUDIO_DIR.exists():
                for file in AUDIO_DIR.glob("*"):
                    if file.is_file():
                        file.unlink()
                        deleted_count += 1
                    elif file.is_dir():
                        shutil.rmtree(file)
                        deleted_count += 1

            self.add_status(f"🗑️ Cleanup complete: {deleted_count} files/folders deleted")
            remaining = self.count_audio_files()
            return f"✓ Cleanup complete! Deleted {deleted_count} files and folders.", gr.update(value=f"🗑️ Cleanup Audio Files ({remaining})")
        except Exception as e:
            self.add_status(f"❌ Cleanup error: {e}")
            return f"Cleanup error: {str(e)[:100]}", gr.update()

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
        audio_players = []

        with gr.Row():
            for i in range(2):
                with gr.Column():
                    gr.Markdown(f"**Song {i+1}**")
                    audio_player = gr.Audio(label="Load & Preview", type="filepath", interactive=True)
                    audio_players.append(audio_player)
                    file_inputs.append(audio_player)

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
            gr.HTML('<div style="width: 100%; height: 1px; background: linear-gradient(90deg, #6366f1, #8b5cf6, transparent);"></div>')
        with gr.Row():
            separate_status = gr.Textbox(
                label="Status of Detecting and Separating the Tracks",
                value="",
                interactive=False,
                lines=6,
                elem_id="system_status_box"
            )

            status_refresh_timer = gr.Timer(value=0.5, active=True)


        with gr.Row():
            stems_download = gr.File(label="📥 Download Stems (ZIP)", type="filepath", scale=1, file_count="single", file_types=[".zip"], elem_id="stems_download_file")

            # Update download file when stems are ready
            def update_stems_download():
                if state.stems_ready():
                    # Find the most recent stems ZIP file by modification time
                    stem_files = list(AUDIO_DIR.glob("stems_export_original_*.zip"))
                    if stem_files:
                        # Sort by modification time (newest first)
                        newest = max(stem_files, key=lambda p: p.stat().st_mtime)
                        return gr.update(value=str(newest), interactive=False)
                return gr.update(value=None, interactive=False)


        def make_load_callback(slot):
            def load_and_update(f):
                if f is None:
                    state.song_paths[slot] = None
                    state.stem_paths[slot] = None
                    state.song_bpms[slot] = None
                    state.song_keys[slot] = None
                    state.pitch_manually_changed[slot] = False
                    state.add_status(f"🗑️ Song {slot+1} removed")
                    status_text = state.get_status_text()
                    return gr.update(), "—", "—", status_text
                else:
                    msg, audio_path, _ = state.load_song(f, slot)
                    bpm_text = state.get_bpm_display(slot)
                    key_text = state.get_key_display(slot)
                    status_text = state.get_status_text()
                    return gr.update(), bpm_text, key_text, status_text
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
                            state.pitch_manually_changed[slot] = False
                            state.add_status(f"🗑️ Song {slot+1} removed")
                            return gr.update(), "—", "—", state.get_status_text()

                        msg, audio_path, _ = state.load_song(f, slot)
                        bpm_text = state.get_bpm_display(slot)
                        key_text = state.get_key_display(slot)
                        status_text = state.get_status_text()
                        return gr.update(), bpm_text, key_text, status_text
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

        # ===== Per-Song Controls =====
        with gr.Row():
            gr.HTML('<div style="width: 100%; height: 1px; background: linear-gradient(90deg, #6366f1, #8b5cf6, transparent);"></div>')
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
                                state.pitch_manually_changed[slot] = True
                                state.selected_pitch_keys[slot] = key_name
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
        with gr.Row():
            gr.HTML('<div style="width: 100%; height: 1px; background: linear-gradient(90deg, #6366f1, #8b5cf6, transparent);"></div>')
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
        with gr.Row():
            gr.HTML('<div style="width: 100%; height: 1px; background: linear-gradient(90deg, #6366f1, #8b5cf6, transparent);"></div>')
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
        with gr.Row():
            gr.HTML('<div style="width: 100%; height: 1px; background: linear-gradient(90deg, #6366f1, #8b5cf6, transparent);"></div>')
        gr.Markdown("### Render")

        with gr.Row():
            preview_btn = gr.Button("▶ LIVE PREVIEW", size="lg", scale=1, interactive=False)
            render_btn = gr.Button("🎛️ RENDER FULL REMIX AND STEMS", size="lg", scale=1, interactive=False)

        with gr.Row():
            output_audio = gr.Audio(label="Output", type="filepath", elem_id="output_audio_player", scale=2)
            render_status = gr.Textbox(label="Status", value="Ready", interactive=False, scale=1)

        with gr.Row():
            render_files_zip = gr.File(label="📥 Download Render + Stems (ZIP)", type="filepath", scale=1, file_count="single", file_types=[".zip"], elem_id="render_files_zip")

            # Update download when files are ready
            def update_render_download():
                # Only show the current render, not old files from previous sessions
                if state.last_render_path and Path(state.last_render_path).exists():
                    return gr.update(value=state.last_render_path, interactive=False)
                return gr.update(value=None, interactive=False)

            def update_output_audio():
                # Display auto-generated preview or render in the audio player
                if state.last_render_path and Path(state.last_render_path).exists():
                    return gr.update(value=state.last_render_path)
                return gr.update(value=None)

        preview_btn.click(
            lambda: state.preview(),
            outputs=[output_audio, render_status]
        )

        render_btn.click(
            lambda: state.render(),
            outputs=[output_audio, render_status]
        )

        # ===== Cleanup =====
        with gr.Row():
            gr.HTML('<div style="width: 100%; height: 1px; background: linear-gradient(90deg, #6366f1, #8b5cf6, transparent);"></div>')
        gr.Markdown("### Utilities")
        with gr.Row():
            file_count = state.count_audio_files()
            cleanup_btn = gr.Button(f"🗑️ Cleanup Audio Files ({file_count})", size="lg", scale=1)
            cleanup_status = gr.Textbox(value="Ready", interactive=False, scale=2, label="Status")

        cleanup_btn.click(
            lambda: state.cleanup_audio_files(),
            outputs=[cleanup_status, cleanup_btn]
        )

        # Enable controls when stems are ready + animated status + pitch suggestion + BPM/Key displays + pitch dropdowns
        def refresh_status_and_controls():
            status_text = state.get_status_text()  # Get status without animation
            stems_ready = state.stems_ready()

            # Show completion message when stems are ready
            if stems_ready:
                status_text += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ Files analyzed and stems created, have fun Mixing! ✨\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

            # Animate status with spinner when processing
            if state.sep_in_progress:
                spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
                spinner = spinners[state.animation_frame % len(spinners)]
                state.animation_frame += 1
                # Add spinner at the end of status text
                status_text += f"\n{spinner} Processing..."

            # Update status textbox
            status_update = gr.update(value=status_text)

            # Get BPM and Key displays for both songs
            bpm1_text = state.get_bpm_display(0)
            key1_text = state.get_key_display(0)
            bpm2_text = state.get_bpm_display(1)
            key2_text = state.get_key_display(1)

            # Get detected keys for pitch suggestion and dropdowns
            keys = state.get_effective_keys()

            # Prepare pitch dropdown updates (only if user hasn't manually changed them)
            pitch1_update = gr.update()
            pitch2_update = gr.update()
            if not state.pitch_manually_changed[0] and keys[0] >= 0:
                pitch1_update = gr.update(value=KEY_NAMES[keys[0]])
            if not state.pitch_manually_changed[1] and keys[1] >= 0:
                pitch2_update = gr.update(value=KEY_NAMES[keys[1]])

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

                pitch_text = (f"{abs_diff} steps: Shift Song 2 {diff:+d} semitones to {song1_key}, "
                             f"or middle ({mid_key}): Song 1 {mid_shift_s1:+.1f}, Song 2 {mid_shift_s2:+.1f}")

            updates = [status_update, gr.update(interactive=stems_ready), gr.update(interactive=stems_ready), gr.update(value=pitch_text),
                      gr.update(value=bpm1_text), gr.update(value=key1_text), gr.update(value=bpm2_text), gr.update(value=key2_text),
                      pitch1_update, pitch2_update]
            # Update all sliders
            for slider in slider_refs.values():
                updates.append(gr.update(interactive=stems_ready))
            return updates

        slider_outputs = list(slider_refs.values())

        # Single timer callback with all outputs (stems, render, status, controls)
        def update_all():
            # Call all update functions
            status_result = refresh_status_and_controls()
            stems_result = update_stems_download()
            render_result = update_render_download()
            audio_result = update_output_audio()

            # Combine all results: status outputs + stems download + render download + audio player
            return status_result + [stems_result, render_result, audio_result]

        status_refresh_timer.tick(
            update_all,
            outputs=[separate_status, preview_btn, render_btn, pitch_suggestion, bpm_displays[0], key_displays[0], bpm_displays[1], key_displays[1], pitch_dropdowns[0], pitch_dropdowns[1]] + slider_outputs + [stems_download, render_files_zip, output_audio]
        )

        # CSS for styling (script is now in head parameter)
        gr.HTML("""
        <style>
        #stems_download_file {
            min-height: 120px !important;
            height: 120px !important;
        }
        #stems_download_file .block {
            height: 100% !important;
        }
        #system_status_box {
            max-height: 180px !important;
        }
        #system_status_box textarea {
            height: 140px !important;
            max-height: 140px !important;
            overflow-y: auto !important;
            scroll-behavior: smooth !important;
            resize: none !important;
        }
        [data-testid="timer"] {
            display: none !important;
        }
        .gradio-timer {
            display: none !important;
        }
        @keyframes progress-walk {
            0% { background-position: 0% center; }
            100% { background-position: 200% center; }
        }
        </style>
        """)

    return app

if __name__ == "__main__":
    app = create_app()
    try:
        app.launch(share=False, theme=gr.themes.Base(primary_hue="purple"), head='<script>let lastScrollValue = "";function scrollStatusBoxToBottom(){const statusBox=document.getElementById("system_status_box");if(statusBox){const textarea=statusBox.querySelector("textarea");if(textarea){textarea.scrollTop=textarea.scrollHeight;setTimeout(()=>textarea.scrollTop=textarea.scrollHeight,10);setTimeout(()=>textarea.scrollTop=textarea.scrollHeight,50);setTimeout(()=>textarea.scrollTop=textarea.scrollHeight,100)}}}document.addEventListener("DOMContentLoaded",scrollStatusBoxToBottom);const statusObserver=new MutationObserver(()=>{setTimeout(scrollStatusBoxToBottom,50)});document.addEventListener("DOMContentLoaded",()=>{const statusBox=document.getElementById("system_status_box");if(statusBox){const textarea=statusBox.querySelector("textarea");if(textarea){textarea.addEventListener("input",scrollStatusBoxToBottom,true);textarea.addEventListener("change",scrollStatusBoxToBottom,true);statusObserver.observe(statusBox,{characterData:true,subtree:true,childList:true,attributes:true,attributeOldValue:true,characterDataOldValue:true})}}});setInterval(()=>{const statusBox=document.getElementById("system_status_box");if(statusBox){const textarea=statusBox.querySelector("textarea");if(textarea&&textarea.value!==lastScrollValue){lastScrollValue=textarea.value;scrollStatusBoxToBottom();setTimeout(scrollStatusBoxToBottom,10)}}},50);let currentlyPlaying=null;function setupAudioControls(){const allAudioPlayers=document.querySelectorAll("audio");allAudioPlayers.forEach(player=>{player.autoplay=false;player.removeAttribute("autoplay");player.pause();if(player._audioControlsInitialized){return;}player._audioControlsInitialized=true;player.addEventListener("play",()=>{if(currentlyPlaying&&currentlyPlaying!==player){currentlyPlaying.pause();}currentlyPlaying=player;},true);player.addEventListener("pause",()=>{if(currentlyPlaying===player){currentlyPlaying=null;}});player.addEventListener("ended",()=>{if(currentlyPlaying===player){currentlyPlaying=null;}})});}document.addEventListener("DOMContentLoaded",setupAudioControls);const audioObserver=new MutationObserver(()=>{setTimeout(setupAudioControls,50);});audioObserver.observe(document.body,{childList:true,subtree:true});setInterval(setupAudioControls,300);</script>')
    except KeyboardInterrupt:
        pass

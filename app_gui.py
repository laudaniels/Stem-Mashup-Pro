import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import json
import sys
import threading
from pathlib import Path
import hashlib
import math


def _running_in_venv():
    """True when running inside a virtual environment (venv/virtualenv).

    This app writes generated audio, stems, and presets straight into its
    own project folder and shells out to specific pip-installed tools
    (demucs) via sys.executable -- it's meant to run against a project-local
    interpreter, not a shared system/user Python install.
    """
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)

class KolkataStudio:
    def __init__(self, root):
        self.root = root
        self.root.title("Kolkata Studio v7.4 - Waveform + Crossfader")
        self.root.geometry("1580x980")
        self.root.configure(bg="#060612")

        self.song_paths = [None, None, None]
        self.stem_paths = [None, None, None]
        # None = not analyzed yet, False = analysis failed, float = detected BPM.
        self.song_bpms = [None, None, None]
        # Seconds into the original file where a reference beat falls, used
        # for beatmatching (see MashupEngine.render()). No manual override
        # for this -- unlike BPM, there's no simple value a user can type in
        # its place, so beatmatching only works for slots that were analyzed.
        self.song_beat_anchors = [None, None, None]
        # User-typed BPM per slot; blank means "trust the auto-detected value".
        self.bpm_override_vars = [tk.StringVar(value="") for _ in range(3)]
        # Nudges the detected beat anchor by N beats (in that song's own
        # native tempo). Alignment is computed modulo one beat, so only the
        # fractional part has any audible effect -- see build_song_slots().
        self.beat_offset_vars = [tk.StringVar(value="0") for _ in range(3)]
        self.sliders = {}
        self.waveform_canvases = {}
        self.song_frames = [None, None, None]
        self.waveform_containers = [None, None, None]
        self.presets_dir = Path(__file__).resolve().parent / "presets"
        self.presets_dir.mkdir(exist_ok=True)

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("Neon.Horizontal.TProgressbar",
                             troughcolor="#0f0a1f",
                             background="#a78bfa",
                             thickness=14)

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self):
        # Top bar
        top = tk.Frame(self.root, bg="#0d0a1a", height=58)
        top.pack(fill="x", pady=6)

        for i, text in enumerate(["+ Song 1", "+ Song 2", "+ Song 3"]):
            tk.Button(top, text=text, bg="#1a1330", fg="#c4b5fd",
                      font=("Segoe UI", 10, "bold"), bd=0, relief="flat",
                      activebackground="#2e1b4d",
                      command=lambda idx=i: self.load_song(idx)).pack(side="left", padx=9, pady=11)

        tk.Button(top, text="💾 Save Preset", bg="#1a1330", fg="#a5b4fc",
                  font=("Segoe UI", 10, "bold"), bd=0, relief="flat",
                  command=self.save_preset).pack(side="right", padx=9, pady=11)
        tk.Button(top, text="📂 Load Preset", bg="#1a1330", fg="#a5b4fc",
                  font=("Segoe UI", 10, "bold"), bd=0, relief="flat",
                  command=self.load_preset).pack(side="right", padx=9, pady=11)

        # The editor scrolls independently from the fixed playback controls.
        # This prevents the footer from covering long horizontal sliders.
        footer = tk.Frame(self.root, bg="#060612")
        footer.pack(side="bottom", fill="x")
        editor = tk.Frame(self.root, bg="#060612")
        editor.pack(fill="both", expand=True)

        # Scrollable editor area
        self.canvas = tk.Canvas(editor, bg="#060612", highlightthickness=0)
        scrollbar = tk.Scrollbar(editor, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg="#060612")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.main = self.scrollable_frame
        self.build_song_slots()

        # Fixed playback controls below the editor.
        cross_frame = tk.Frame(footer, bg="#0d0a1a")
        cross_frame.pack(fill="x", pady=6)

        tk.Label(cross_frame, text="CROSSFADER  (Song 1 ← → Song 2)",
                 bg="#0d0a1a", fg="#c4b5fd", font=("Segoe UI", 10, "bold")).pack()

        self.crossfader = tk.Scale(cross_frame, from_=0, to=100, resolution=1,
                                   orient="horizontal", length=700,
                                   bg="#1e1b4b", fg="#e879f9",
                                   troughcolor="#060612",
                                   highlightthickness=0, bd=0,
                                   sliderrelief="raised",
                                   activebackground="white",
                                   width=16, sliderlength=28)
        self.crossfader.set(50)
        self.crossfader.pack(pady=6)

        # Song volumes -- an independent overall level per song, on top of
        # the crossfader. Set Song 3 to 0 to hear just the Song 1/2
        # crossfade, or zero out two of them to audition a single song's
        # own Vocals/Beats/Bass/Other stem balance in isolation. Stored in
        # self.sliders like every other fader, so save/load preset picks
        # these up automatically with no extra plumbing.
        volumes_frame = tk.Frame(footer, bg="#0d0a1a")
        volumes_frame.pack(pady=(0, 6))

        tk.Label(volumes_frame, text="SONG VOLUMES  (mix all 3, or isolate one)",
                 bg="#0d0a1a", fg="#c4b5fd", font=("Segoe UI", 10, "bold")).pack()

        volumes_row = tk.Frame(volumes_frame, bg="#0d0a1a")
        volumes_row.pack(pady=4)

        song_volume_colors = [("#1e1b4b", "#818cf8"), ("#0f766e", "#2dd4bf"), ("#5b21b6", "#c4b5fd")]
        for i in range(3):
            bg_color, accent = song_volume_colors[i]
            col = tk.Frame(volumes_row, bg=bg_color, padx=10, pady=6)
            col.pack(side="left", padx=14)

            tk.Label(col, text=f"Song {i+1}", bg=bg_color, fg=accent,
                     font=("Segoe UI", 9, "bold")).pack()

            s = tk.Scale(col, from_=1.0, to=0.0, resolution=0.05,
                         orient="vertical", length=90,
                         bg=bg_color, fg="white",
                         troughcolor="#1e1b4b",
                         highlightthickness=0, bd=0,
                         sliderrelief="raised",
                         activebackground="white",
                         width=16, sliderlength=24)
            s.set(1.0)
            s.pack()
            self.sliders[f"s{i}_master_vol"] = s

        # Target tempo -- when set (non-zero), every track is time-stretched
        # via atempo to this BPM before the manual Speed slider is applied,
        # using each song's auto-detected BPM (see detect_bpm_async).
        tempo_frame = tk.Frame(footer, bg="#0d0a1a")
        tempo_frame.pack(pady=(0, 6))

        tk.Label(tempo_frame, text="TARGET TEMPO  (BPM, 0 = off):",
                 bg="#0d0a1a", fg="#c4b5fd", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))

        self.target_bpm_var = tk.IntVar(value=0)
        tk.Spinbox(tempo_frame, from_=0, to=200, increment=1, width=6,
                   textvariable=self.target_bpm_var,
                   bg="#1e1b4b", fg="#e879f9", buttonbackground="#312e81",
                   insertbackground="white", relief="flat",
                   font=("Segoe UI", 10, "bold")).pack(side="left")

        # Beatmatch only has an effect once a target tempo is set -- with no
        # common tempo, aligned tracks would just drift back out of phase.
        self.beatmatch_var = tk.BooleanVar(value=False)
        tk.Checkbutton(tempo_frame, text="Beatmatch (align beat grids)",
                        variable=self.beatmatch_var,
                        bg="#0d0a1a", fg="#c4b5fd", selectcolor="#1e1b4b",
                        activebackground="#0d0a1a", activeforeground="#c4b5fd",
                        font=("Segoe UI", 9, "bold")).pack(side="left", padx=(14, 0))

        # Bottom bar
        bottom = tk.Frame(footer, bg="#0d0a1a")
        bottom.pack(fill="x", pady=6)

        self.progress = ttk.Progressbar(bottom, style="Neon.Horizontal.TProgressbar",
                                        mode="indeterminate", length=460)
        self.progress.pack(pady=8)

        btn_frame = tk.Frame(bottom, bg="#0d0a1a")
        btn_frame.pack(pady=4)

        # Kept as instance attributes so _set_action_buttons() can drive them
        # while a preview/render/separation job is running -- without this,
        # clicking an action button twice launches overlapping ffmpeg/Demucs
        # jobs that write to the same output file.
        self.live_btn = tk.Button(btn_frame, text="▶  LIVE PREVIEW", bg="#4f46e5", fg="white",
                  font=("Segoe UI", 12, "bold"), width=18, height=2, bd=0,
                  activebackground="#6366f1", command=self.live_preview)
        self.live_btn.pack(side="left", padx=12)

        self.separate_btn = tk.Button(btn_frame, text="SEPARATE STEMS", bg="#0f766e", fg="white",
                  font=("Segoe UI", 10, "bold"), width=16, height=2, bd=0,
                  activebackground="#14b8a6", command=self.separate_stems)
        self.separate_btn.pack(side="left", padx=12)

        self.render_btn = tk.Button(btn_frame, text="🎛️  RENDER REMIX", bg="#7c3aed", fg="white",
                  font=("Segoe UI", 12, "bold"), width=18, height=2, bd=0,
                  activebackground="#8b5cf6", command=self.render)
        self.render_btn.pack(side="left", padx=12)

        self.status = tk.Label(footer, text="Ready • Waveform + Crossfader Edition",
                               bg="#060612", fg="#c4b5fd", font=("Segoe UI", 10))
        self.status.pack(fill="x", pady=3)

    def _set_action_buttons(self, mode):
        """mode is one of:
        - "busy": a render/preview/separation job is encoding -- everything locked.
        - "previewing": preview audio is playing -- only STOP PREVIEW is live.
        - "idle": nothing running.
        """
        if mode == "busy":
            for btn in (self.live_btn, self.separate_btn, self.render_btn):
                btn.config(state="disabled")
        elif mode == "previewing":
            self.live_btn.config(text="■  STOP PREVIEW", state="normal", command=self.stop_preview)
            self.separate_btn.config(state="disabled")
            self.render_btn.config(state="disabled")
        else:
            self.live_btn.config(text="▶  LIVE PREVIEW", state="normal", command=self.live_preview)
            self.separate_btn.config(state="normal")
            self.render_btn.config(state="normal")

    def _safe_after(self, func):
        """Like root.after(0, func), but tolerates the window already being
        destroyed -- background threads can still be finishing up after the
        user closes the app."""
        try:
            self.root.after(0, func)
        except tk.TclError:
            pass

    def stop_preview(self):
        from mashup_engine import MashupEngine
        MashupEngine.stop_preview()
        self._set_action_buttons("idle")
        self.status.config(text="Preview stopped")

    def _watch_preview(self):
        """Polls the playing preview and flips the button back to LIVE
        PREVIEW once ffplay exits on its own (preview_duration elapsed)."""
        from mashup_engine import MashupEngine
        if MashupEngine.is_previewing():
            self.root.after(500, self._watch_preview)
        else:
            self._set_action_buttons("idle")
            self.status.config(text="Ready • Waveform + Crossfader Edition")

    def on_close(self):
        """ffmpeg/ffplay are independent OS processes, not child threads --
        closing the window doesn't stop them unless we do it explicitly."""
        from mashup_engine import MashupEngine
        MashupEngine.stop_all()
        self.root.destroy()

    def load_song(self, index):
        file = filedialog.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav")])
        if file:
            self.song_paths[index] = file
            self.stem_paths[index] = None
            self.song_bpms[index] = None
            self.song_beat_anchors[index] = None
            self.bpm_override_vars[index].set("")
            self.beat_offset_vars[index].set("0")
            self.refresh_song_slot(index)
            self.detect_bpm_async(index)

    def detect_bpm_async(self, index):
        """Estimates the loaded song's tempo and a reference beat position
        in the background, updating the slot's title once known -- this
        analysis takes a few seconds and must not block the UI thread."""
        path = self.song_paths[index]

        def task():
            try:
                from mashup_engine import MashupEngine
                bpm, anchor = MashupEngine().analyze_track(path)
            except Exception:
                bpm, anchor = False, None

            # The user may have loaded a different song into this slot while
            # detection was running -- only apply a stale result if it's
            # still for the same song.
            if self.song_paths[index] == path:
                self.song_bpms[index] = bpm
                self.song_beat_anchors[index] = anchor
                self._safe_after(lambda: self.song_frames[index].config(text=self._song_title(index)))

        threading.Thread(target=task, daemon=True).start()

    def build_song_slots(self):
        """Builds all 3 song panels ONCE, at startup. Sliders live for the
        lifetime of the app -- loading a song never destroys or recreates
        them, so nothing you've dialed in gets reset."""
        color_map = {
            "Vocals":   ("#0e7490", "#22d3ee"),
            "Beats":    ("#4c1d95", "#a78bfa"),
            "Bass":     ("#701a75", "#e879f9"),
            "Other":    ("#78350f", "#fbbf24"),
            "Pitch":    ("#1e3a8a", "#60a5fa"),
            "Reverb":   ("#5b21b6", "#c4b5fd"),
            "Speed":    ("#312e81", "#818cf8"),
            "EQ Low":   ("#115e59", "#2dd4bf"),
            "EQ Mid":   ("#1e40af", "#93c5fd"),
            "EQ High":  ("#9d174d", "#f9a8d4"),
        }

        for i in range(3):
            text = f"SONG {i+1}  •  Empty"
            frame = tk.LabelFrame(self.main, text=text, bg="#0f0a1c", fg="#c4b5fd",
                                  font=("Segoe UI", 11, "bold"), padx=16, pady=10,
                                  bd=1, relief="solid",
                                  highlightbackground="#312e81", highlightthickness=1)
            frame.pack(fill="x", pady=12, padx=14)
            self.song_frames[i] = frame

            # Dedicated small container for the waveform -- loading a song
            # only ever clears/redraws this, never anything else in the frame
            wf_container = tk.Frame(frame, bg="#0f0a1c")
            wf_container.pack(fill="x")
            self.waveform_containers[i] = wf_container

            # Manual BPM override -- auto-detection isn't always right
            # (octave errors, syncopated tracks, etc.), so this always wins
            # over the detected value when it's non-blank. Bound with a
            # trace so the slot's title reflects it as you type, even though
            # the actual audio isn't touched until the next preview/render.
            bpm_row = tk.Frame(frame, bg="#0f0a1c")
            bpm_row.pack(fill="x", pady=(0, 8))
            tk.Label(bpm_row, text="Override BPM (blank = auto-detected):",
                     bg="#0f0a1c", fg="#818cf8", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
            tk.Entry(bpm_row, textvariable=self.bpm_override_vars[i], width=6,
                     bg="#1e1b4b", fg="#e879f9", insertbackground="white",
                     relief="flat", font=("Segoe UI", 9, "bold")).pack(side="left")
            self.bpm_override_vars[i].trace_add(
                "write", lambda *_args, idx=i: self.song_frames[idx].config(text=self._song_title(idx)))

            # Beat phase offset -- beatmatching aligns tracks modulo one
            # BEAT, not one bar, so only the fractional part of this value
            # matters (e.g. 0.5 nudges half a beat for fine-phase
            # correction); whole-number shifts (1, 2, ...) land back on an
            # equivalent beat and have no audible effect. This does NOT let
            # you pick which beat is bar 1 in a 4/4 track -- that would need
            # bar-level (mod 4-beat) alignment, which this app doesn't do.
            # Only affects anything when Beatmatch is on.
            #
            # Song 1 is always the fixed beatmatch reference (see
            # MashupEngine.render()) -- it's never delayed and never takes a
            # phase offset, so its field is disabled rather than left as a
            # control that would silently do nothing.
            offset_row = tk.Frame(frame, bg="#0f0a1c")
            offset_row.pack(fill="x", pady=(0, 8))
            if i == 0:
                tk.Label(offset_row, text="Beat Phase Offset: — (Song 1 is always the beatmatch reference)",
                         bg="#0f0a1c", fg="#6b7280", font=("Segoe UI", 9)).pack(side="left")
            else:
                tk.Label(offset_row, text="Beat Phase Offset (beats, for Beatmatch):",
                         bg="#0f0a1c", fg="#818cf8", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
                tk.Entry(offset_row, textvariable=self.beat_offset_vars[i], width=6,
                         bg="#1e1b4b", fg="#e879f9", insertbackground="white",
                         relief="flat", font=("Segoe UI", 9, "bold")).pack(side="left")
                self.beat_offset_vars[i].trace_add(
                    "write", lambda *_args, idx=i: self.song_frames[idx].config(text=self._song_title(idx)))

            # Vertical Faders
            vol_frame = tk.Frame(frame, bg="#0f0a1c")
            vol_frame.pack(fill="x", pady=8)

            for name in ["Vocals", "Beats", "Bass", "Other"]:
                bg_color, accent = color_map[name]
                col = tk.Frame(vol_frame, bg=bg_color, padx=8, pady=6)
                col.pack(side="left", padx=10)

                tk.Label(col, text=name, bg=bg_color, fg=accent,
                         font=("Segoe UI", 9, "bold")).pack()

                s = tk.Scale(col, from_=1.0, to=0.0, resolution=0.1,
                             orient="vertical", length=140,
                             bg=bg_color, fg="white",
                             troughcolor="#1e1b4b",
                             highlightthickness=0, bd=0,
                             sliderrelief="raised",
                             activebackground="white",
                             width=18, sliderlength=26)
                s.set(1.0)
                s.pack()
                self.sliders[f"s{i}_{name.lower()}_vol"] = s

            # Horizontal controls -- each row now states its own true
            # "neutral" value explicitly instead of a blanket 1.0 default
            for display_name, color_key, rng_from, rng_to, neutral in [
                ("Pitch Shift", "Pitch", -1.5, 1.5, 0.0),
                ("Reverb", "Reverb", 0.0, 1.0, 0.0),
                ("Speed", "Speed", 0.5, 1.5, 1.0),
                ("EQ Low", "EQ Low", -1.5, 1.5, 0.0),
                ("EQ Mid", "EQ Mid", -1.5, 1.5, 0.0),
                ("EQ High", "EQ High", -1.5, 1.5, 0.0),
            ]:
                bg_color, accent = color_map[color_key]
                key = f"s{i}_{display_name.lower().replace(' ', '_')}"

                row = tk.Frame(frame, bg="#0f0a1c")
                row.pack(fill="x", pady=3)

                label_frame = tk.Frame(row, bg=bg_color, padx=6, pady=2)
                label_frame.pack(side="left")
                tk.Label(label_frame, text=display_name, bg=bg_color, fg=accent,
                         font=("Segoe UI", 9, "bold"), width=11, anchor="w").pack()

                s = tk.Scale(row, from_=rng_from, to=rng_to, resolution=0.1,
                             orient="horizontal", length=720,
                             bg=bg_color, fg="white",
                             troughcolor="#1e1b4b",
                             highlightthickness=0, bd=0,
                             sliderrelief="raised",
                             activebackground="white",
                             width=14, sliderlength=28)
                s.set(neutral)
                s.pack(side="left", padx=8)
                self.sliders[key] = s

    def _effective_bpm(self, index):
        """The BPM value that will actually be used for this slot: a valid
        manual override always wins, otherwise the auto-detected value (or
        None/False if it's unknown/failed)."""
        override = self.bpm_override_vars[index].get().strip()
        if override:
            try:
                value = float(override)
                if value > 0:
                    return value
            except ValueError:
                pass
        return self.song_bpms[index]

    def _effective_beat_offset(self, index):
        """Beats to nudge this slot's detected beat anchor by (0.0 if the
        field is blank or unparsable). Song 1 is always the fixed beatmatch
        reference and never takes an offset -- forced here too, in case an
        older preset still has a stale non-zero value saved for slot 0."""
        if index == 0:
            return 0.0
        try:
            return float(self.beat_offset_vars[index].get().strip())
        except ValueError:
            return 0.0

    def _song_title(self, index):
        path = self.song_paths[index]
        if not path:
            return f"SONG {index+1}  •  Empty"
        override = self.bpm_override_vars[index].get().strip()
        bpm = self.song_bpms[index]
        if override:
            bpm_text = f"{override} BPM (override)"
        elif bpm is None:
            bpm_text = "detecting BPM…"
        elif bpm is False:
            bpm_text = "BPM unavailable"
        else:
            bpm_text = f"{bpm:.0f} BPM"
        offset = self._effective_beat_offset(index)
        if offset:
            bpm_text += f", phase offset {offset:+g}"
        return f"SONG {index+1}  •  {os.path.basename(path)}  •  {bpm_text}"

    def refresh_song_slot(self, index):
        """Called after loading a file into `index`. Only updates that
        slot's title text and waveform preview -- deliberately never
        touches any Scale widget, on this slot or any other."""
        path = self.song_paths[index]
        self.song_frames[index].config(text=self._song_title(index))

        wf_container = self.waveform_containers[index]
        for widget in wf_container.winfo_children():
            widget.destroy()

        if path:
            try:
                self.draw_waveform(wf_container, path, index)
            except Exception as e:
                tk.Label(wf_container, text=f"Waveform unavailable: {e}", bg="#0f0a1c", fg="#f87171").pack()

    def draw_waveform(self, parent, filepath, index):
        """Draw a lightweight waveform-style preview with Tkinter only.

        Matplotlib requires a native DLL which may be blocked by Windows
        Application Control.  This canvas has no compiled dependency, so it
        lets the application start on restricted Windows installations.
        """
        width, height = 920, 86
        canvas = tk.Canvas(parent, width=width, height=height,
                           bg="#090716", highlightthickness=1,
                           highlightbackground="#312e81")
        canvas.pack(fill="x", pady=(2, 8))

        midline = height // 2
        canvas.create_line(0, midline, width, midline, fill="#272047")

        # Use the file name to make a stable, distinct preview for each song.
        # It is intentionally a visual cue rather than a decoded audio graph;
        # MP3 decoding remains the job of FFmpeg during preview/rendering.
        seed = int(hashlib.sha256(filepath.encode("utf-8")).hexdigest()[:8], 16)
        phase_a = (seed % 628) / 100
        phase_b = ((seed >> 9) % 628) / 100
        points = []
        for x in range(0, width + 1, 3):
            t = x / width
            envelope = 0.24 + 0.76 * abs(math.sin(math.pi * (t + 0.08)))
            sample = (math.sin(t * 42 + phase_a) +
                      0.48 * math.sin(t * 103 + phase_b)) / 1.48
            points.extend((x, midline - sample * envelope * 33))
        canvas.create_line(*points, fill="#a78bfa", width=2, smooth=True)
        canvas.create_text(10, 10, anchor="nw", text="TRACK PREVIEW",
                           fill="#c4b5fd", font=("Segoe UI", 8, "bold"))
        self.waveform_canvases[index] = canvas

    def get_params(self):
        return {
            "songs": self.song_paths.copy(),
            "stems": self.stem_paths.copy(),
            "bpms": [self._effective_bpm(i) for i in range(len(self.song_paths))],
            "beat_anchors": self.song_beat_anchors.copy(),
            "beat_offsets": [self._effective_beat_offset(i) for i in range(len(self.song_paths))],
            "target_bpm": self.target_bpm_var.get() or None,
            "beatmatch": self.beatmatch_var.get(),
            "sliders": {k: v.get() for k, v in self.sliders.items()},
            "crossfader": self.crossfader.get()
        }

    def validate_mix(self, params):
        """Song 1 and Song 2 are the tracks governed by the crossfader."""
        if not params["songs"][0] or not params["songs"][1]:
            messagebox.showwarning(
                "Load Song 1 and Song 2",
                "Load audio into Song 1 and Song 2 before previewing or rendering. Song 3 is optional.")
            return False
        return True

    def live_preview(self):
        params = self.get_params()
        if not self.validate_mix(params):
            return
        self.status.config(text="Generating 60s preview...")
        self.progress.start(12)
        self._set_action_buttons("busy")
        self.root.update()

        def task():
            try:
                from mashup_engine import MashupEngine
                engine = MashupEngine()
                engine.render(params, preview=True, preview_duration=60)
                self._safe_after(lambda: self.status.config(text="Preview playing..."))
                self._safe_after(lambda: self._set_action_buttons("previewing"))
                self._safe_after(self._watch_preview)
            except Exception as e:
                self._safe_after(lambda err=e: messagebox.showerror("Preview Error", str(err)))
                self._safe_after(lambda: self._set_action_buttons("idle"))
                self._safe_after(lambda: self.status.config(text="Ready • Waveform + Crossfader Edition"))
            finally:
                self._safe_after(self.progress.stop)

        threading.Thread(target=task, daemon=True).start()

    def render(self):
        params = self.get_params()
        if not self.validate_mix(params):
            return
        self.status.config(text="Rendering full remix...")
        self.progress.start(12)
        self._set_action_buttons("busy")
        self.root.update()

        def task():
            try:
                from mashup_engine import MashupEngine
                engine = MashupEngine()
                output = engine.render(params, preview=False)
                self._safe_after(lambda out=output: messagebox.showinfo("Success", f"Remix saved as:\n{out}"))
                self._safe_after(lambda out=output: self.status.config(text=f"Done → {out}"))
            except Exception as e:
                self._safe_after(lambda err=e: messagebox.showerror("Render Error", str(err)))
                self._safe_after(lambda: self.status.config(text="Render failed"))
            finally:
                self._safe_after(self.progress.stop)
                self._safe_after(lambda: self._set_action_buttons("idle"))

        threading.Thread(target=task, daemon=True).start()

    def separate_stems(self):
        """Create vocal, drum, bass, and other stems for the loaded songs.

        Skips slots that already have stems for their currently loaded song
        -- load_song() clears stem_paths[index] whenever a new file is
        dropped into that slot, so a leftover entry here is always still
        valid and doesn't need to be re-computed by Demucs.
        """
        selected = [(slot, path) for slot, path in enumerate(self.song_paths)
                    if path and not self.stem_paths[slot]]
        if not selected:
            if any(self.song_paths):
                messagebox.showinfo("Already separated", "All loaded songs already have stems ready.")
            else:
                messagebox.showwarning("No songs", "Load at least one song before separating stems.")
            return

        self.status.config(text="Separating stems — this may take several minutes...")
        self.progress.start(12)
        self._set_action_buttons("busy")

        def task():
            try:
                from mashup_engine import MashupEngine
                created = MashupEngine().separate_stems([path for _, path in selected])
                for (slot, _), stem_set in zip(selected, created):
                    self.stem_paths[slot] = stem_set
                self._safe_after(lambda: messagebox.showinfo(
                    "Stems ready",
                    "Vocals, drums, bass, and other stems are ready. The vertical faders now control vocals, drums/beats, bass, and other separately."))
                self._safe_after(lambda: self.status.config(
                    text="Stems ready — precise vocal, beat, bass, and other control enabled"))
            except Exception as e:
                self._safe_after(lambda err=e: messagebox.showerror("Stem Separation", str(err)))
                self._safe_after(lambda: self.status.config(
                    text="Stem separation unavailable — full-track controls remain active"))
            finally:
                self._safe_after(self.progress.stop)
                self._safe_after(lambda: self._set_action_buttons("idle"))

        threading.Thread(target=task, daemon=True).start()

    def save_preset(self):
        name = filedialog.asksaveasfilename(initialdir=self.presets_dir,
                                            defaultextension=".json",
                                            filetypes=[("Preset", "*.json")])
        if name:
            data = {k: v.get() for k, v in self.sliders.items()}
            data["crossfader"] = self.crossfader.get()
            data["target_bpm"] = self.target_bpm_var.get()
            data["beatmatch"] = self.beatmatch_var.get()
            data["bpm_overrides"] = [v.get() for v in self.bpm_override_vars]
            data["beat_offsets"] = [v.get() for v in self.beat_offset_vars]
            with open(name, "w") as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo("Saved", "Preset saved")

    def load_preset(self):
        name = filedialog.askopenfilename(initialdir=self.presets_dir,
                                          filetypes=[("Preset", "*.json")])
        if name:
            with open(name, "r") as f:
                data = json.load(f)
            for key, value in data.items():
                if key in self.sliders:
                    self.sliders[key].set(value)
                if key == "crossfader":
                    self.crossfader.set(value)
                if key == "target_bpm":
                    self.target_bpm_var.set(value)
                if key == "beatmatch":
                    self.beatmatch_var.set(value)
                if key == "bpm_overrides":
                    for i, override in enumerate(value):
                        if i < len(self.bpm_override_vars):
                            self.bpm_override_vars[i].set(override)
                if key == "beat_offsets":
                    for i, offset in enumerate(value):
                        if i < len(self.beat_offset_vars):
                            self.beat_offset_vars[i].set(offset)
            messagebox.showinfo("Loaded", "Preset loaded")


if __name__ == "__main__":
    if not _running_in_venv():
        sys.exit(
            "Kolkata Studio must be run from inside a virtual environment.\n\n"
            "Create one and install dependencies first:\n\n"
            "    python -m venv .venv\n"
            "    .venv\\Scripts\\activate      (Windows)\n"
            "    source .venv/bin/activate    (macOS/Linux)\n"
            "    pip install -r requirements.txt\n"
            "    python app_gui.py\n"
        )
    root = tk.Tk()
    app = KolkataStudio(root)
    root.mainloop()

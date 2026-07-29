import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import json
import threading
from pathlib import Path
import hashlib
import math

class KolkataStudio:
    def __init__(self, root):
        self.root = root
        self.root.title("Kolkata Studio v7.4 - Waveform + Crossfader")
        self.root.geometry("1580x980")
        self.root.configure(bg="#060612")

        self.song_paths = [None, None, None]
        self.stem_paths = [None, None, None]
        self.sliders = {}
        self.waveform_canvases = {}
        self.song_frames = [None, None, None]
        self.waveform_containers = [None, None, None]
        self.presets_dir = Path("presets")
        self.presets_dir.mkdir(exist_ok=True)

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("Neon.Horizontal.TProgressbar",
                             troughcolor="#0f0a1f",
                             background="#a78bfa",
                             thickness=14)

        self.build_ui()

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

        # Bottom bar
        bottom = tk.Frame(footer, bg="#0d0a1a")
        bottom.pack(fill="x", pady=6)

        self.progress = ttk.Progressbar(bottom, style="Neon.Horizontal.TProgressbar",
                                        mode="indeterminate", length=460)
        self.progress.pack(pady=8)

        btn_frame = tk.Frame(bottom, bg="#0d0a1a")
        btn_frame.pack(pady=4)

        tk.Button(btn_frame, text="▶  LIVE PREVIEW", bg="#4f46e5", fg="white",
                  font=("Segoe UI", 12, "bold"), width=18, height=2, bd=0,
                  activebackground="#6366f1", command=self.live_preview).pack(side="left", padx=12)

        tk.Button(btn_frame, text="SEPARATE STEMS", bg="#0f766e", fg="white",
                  font=("Segoe UI", 10, "bold"), width=16, height=2, bd=0,
                  activebackground="#14b8a6", command=self.separate_stems).pack(side="left", padx=12)

        tk.Button(btn_frame, text="🎛️  RENDER REMIX", bg="#7c3aed", fg="white",
                  font=("Segoe UI", 12, "bold"), width=18, height=2, bd=0,
                  activebackground="#8b5cf6", command=self.render).pack(side="left", padx=12)

        self.status = tk.Label(footer, text="Ready • Waveform + Crossfader Edition",
                               bg="#060612", fg="#c4b5fd", font=("Segoe UI", 10))
        self.status.pack(fill="x", pady=3)

    def load_song(self, index):
        file = filedialog.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav")])
        if file:
            self.song_paths[index] = file
            self.stem_paths[index] = None
            self.refresh_song_slot(index)

    def build_song_slots(self):
        """Builds all 3 song panels ONCE, at startup. Sliders live for the
        lifetime of the app -- loading a song never destroys or recreates
        them, so nothing you've dialed in gets reset."""
        color_map = {
            "Vocals":   ("#0e7490", "#22d3ee"),
            "Beats":    ("#4c1d95", "#a78bfa"),
            "Bass":     ("#701a75", "#e879f9"),
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

            # Vertical Faders
            vol_frame = tk.Frame(frame, bg="#0f0a1c")
            vol_frame.pack(fill="x", pady=8)

            for name in ["Vocals", "Beats", "Bass"]:
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

    def refresh_song_slot(self, index):
        """Called after loading a file into `index`. Only updates that
        slot's title text and waveform preview -- deliberately never
        touches any Scale widget, on this slot or any other."""
        path = self.song_paths[index]
        text = f"SONG {index+1}  •  {os.path.basename(path)}" if path else f"SONG {index+1}  •  Empty"
        self.song_frames[index].config(text=text)

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
        self.root.update()

        def task():
            try:
                from mashup_engine import MashupEngine
                engine = MashupEngine()
                engine.render(params, preview=True, preview_duration=60)
                self.root.after(0, lambda: self.status.config(text="Preview playing..."))
            except Exception as e:
                self.root.after(0, lambda err=e: messagebox.showerror("Preview Error", str(err)))
            finally:
                self.root.after(0, self.progress.stop)
                self.root.after(0, lambda: self.status.config(text="Ready • Waveform + Crossfader Edition"))

        threading.Thread(target=task, daemon=True).start()

    def render(self):
        params = self.get_params()
        if not self.validate_mix(params):
            return
        self.status.config(text="Rendering full remix...")
        self.progress.start(12)
        self.root.update()

        def task():
            try:
                from mashup_engine import MashupEngine
                engine = MashupEngine()
                output = engine.render(params, preview=False)
                self.root.after(0, lambda out=output: messagebox.showinfo("Success", f"Remix saved as:\n{out}"))
                self.root.after(0, lambda out=output: self.status.config(text=f"Done → {out}"))
            except Exception as e:
                self.root.after(0, lambda err=e: messagebox.showerror("Render Error", str(err)))
                self.root.after(0, lambda: self.status.config(text="Render failed"))
            finally:
                self.root.after(0, self.progress.stop)

        threading.Thread(target=task, daemon=True).start()

    def separate_stems(self):
        """Create vocal, drum, bass, and other stems for the loaded songs."""
        selected = [(slot, path) for slot, path in enumerate(self.song_paths) if path]
        if not selected:
            messagebox.showwarning("No songs", "Load at least one song before separating stems.")
            return

        self.status.config(text="Separating stems — this may take several minutes...")
        self.progress.start(12)

        def task():
            try:
                from mashup_engine import MashupEngine
                created = MashupEngine().separate_stems([path for _, path in selected])
                for (slot, _), stem_set in zip(selected, created):
                    self.stem_paths[slot] = stem_set
                self.root.after(0, lambda: messagebox.showinfo(
                    "Stems ready",
                    "Vocals, drums, bass, and other stems are ready. The vertical faders now control vocals, drums/beats, and bass separately."))
                self.root.after(0, lambda: self.status.config(
                    text="Stems ready — precise vocal, beat, and bass control enabled"))
            except Exception as e:
                self.root.after(0, lambda err=e: messagebox.showerror("Stem Separation", str(err)))
                self.root.after(0, lambda: self.status.config(
                    text="Stem separation unavailable — full-track controls remain active"))
            finally:
                self.root.after(0, self.progress.stop)

        threading.Thread(target=task, daemon=True).start()

    def save_preset(self):
        name = filedialog.asksaveasfilename(initialdir=self.presets_dir,
                                            defaultextension=".json",
                                            filetypes=[("Preset", "*.json")])
        if name:
            data = {k: v.get() for k, v in self.sliders.items()}
            data["crossfader"] = self.crossfader.get()
            with open(name, "w") as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo("Saved", f"Preset saved")

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
            messagebox.showinfo("Loaded", "Preset loaded")


if __name__ == "__main__":
    root = tk.Tk()
    app = KolkataStudio(root)
    root.mainloop()

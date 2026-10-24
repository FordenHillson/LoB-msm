"""Tkinter front-end for transcribe.py: pick the WAV and JSON, press Start."""
import json
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import transcribe as tr

MODELS = ["tiny", "base", "small", "medium", "large-v3"]
LANGUAGES = {"ไทย (th)": "th", "English (en)": "en", "Auto-detect": None}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Voice Monitor Transcriber")
        self.geometry("720x520")
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None

        self.wav = tk.StringVar()
        self.json = tk.StringVar()
        self.model = tk.StringVar(value="small")
        self.language = tk.StringVar(value="ไทย (th)")
        self.overwrite = tk.BooleanVar(value=False)
        self.gpu = tk.BooleanVar(value=False)

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="ไฟล์เสียงผสม (.wav) *ไม่บังคับ").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.wav).grid(row=0, column=1, sticky="ew", padx=6, pady=3)
        ttk.Button(frm, text="เลือก...", command=self.pick_wav).grid(row=0, column=2)

        ttk.Label(frm, text="ไฟล์ timeline (.json)").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.json).grid(row=1, column=1, sticky="ew", padx=6, pady=3)
        ttk.Button(frm, text="เลือก...", command=self.pick_json).grid(row=1, column=2)

        opts = ttk.Frame(frm)
        opts.grid(row=2, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Label(opts, text="โมเดล").pack(side="left")
        ttk.Combobox(opts, textvariable=self.model, values=MODELS, width=10, state="readonly").pack(side="left", padx=(4, 14))
        ttk.Label(opts, text="ภาษา").pack(side="left")
        ttk.Combobox(opts, textvariable=self.language, values=list(LANGUAGES), width=12, state="readonly").pack(side="left", padx=(4, 14))
        ttk.Checkbutton(opts, text="ถอดซ้ำช่วงที่มีข้อความแล้ว", variable=self.overwrite).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(opts, text="ใช้ GPU (CUDA)", variable=self.gpu).pack(side="left")

        buttons = ttk.Frame(frm)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w")
        self.start_btn = ttk.Button(buttons, text="เริ่มถอดเสียง", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(buttons, text="ยกเลิก", command=self.cancel.set, state="disabled")
        self.stop_btn.pack(side="left", padx=6)

        self.bar = ttk.Progressbar(frm, mode="determinate")
        self.bar.grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        self.status = ttk.Label(frm, text="พร้อม")
        self.status.grid(row=5, column=0, columnspan=3, sticky="w")

        self.log = tk.Text(frm, height=14, wrap="word", state="disabled")
        self.log.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        frm.rowconfigure(6, weight=1)

        self.after(100, self.poll)

    def pick_wav(self):
        path = filedialog.askopenfilename(filetypes=[("WAV", "*.wav")])
        if not path:
            return
        self.wav.set(path)
        sibling = Path(path).with_suffix(".json")
        if sibling.exists() and not self.json.get():
            self.json.set(str(sibling))

    def pick_json(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        self.json.set(path)
        if not self.wav.get():
            sibling = Path(path).with_suffix(".wav")
            if sibling.exists():
                self.wav.set(str(sibling))

    def write(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def start(self):
        if not Path(self.json.get()).is_file():
            messagebox.showerror("ไฟล์ไม่ครบ", "กรุณาเลือกไฟล์ .json ให้ถูกต้อง (ไฟล์เสียงรายคนต้องอยู่โฟลเดอร์เดียวกับ .json)")
            return
        if self.wav.get() and not Path(self.wav.get()).is_file():
            messagebox.showerror("ไฟล์ไม่ครบ", "ไม่พบไฟล์เสียงผสมที่เลือก")
            return
        self.cancel.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.bar.configure(value=0)
        self.write("--- เริ่มงาน ---")
        args = (self.wav.get(), self.json.get(), self.model.get(), LANGUAGES[self.language.get()], self.overwrite.get(), self.gpu.get())
        self.worker = threading.Thread(target=self.run_job, args=args, daemon=True)
        self.worker.start()

    def run_job(self, wav, json_path, model, language, overwrite, gpu=False):
        put = self.events.put
        try:
            data = json.loads(Path(json_path).read_text(encoding="utf-8"))
            source = tr.AudioSource(json_path, data, wav or None)
            tracks = [sp for sp in sorted({g["speaker"] for g in data.get("segments", [])}) if source.uses_track(sp)]
            put(("status", f"ใช้ไฟล์เสียงรายคน: {', '.join(tracks) or 'ไม่มี (ใช้ไฟล์ผสมแทน)'}"))
            put(("status", f"กำลังโหลดโมเดล '{model}' (ครั้งแรกต้องดาวน์โหลด อาจใช้เวลานาน)..."))
            transcribe = tr.make_whisper(model, language, gpu)
            put(("status", "กำลังถอดเสียง..."))
            tr.fill_segments(
                data, source.for_segment, transcribe, overwrite=overwrite,
                log=lambda m: put(("log", m)),
                progress=lambda done, total: put(("progress", done, total)),
                cancelled=self.cancel.is_set,
            )
            out_json, out_txt = tr.save_outputs(data, json_path)
            put(("done", f"เสร็จแล้ว\n{out_json}\n{out_txt}"))
        except InterruptedError:
            put(("error", "ยกเลิกแล้ว (ยังไม่ได้บันทึกไฟล์)"))
        except ModuleNotFoundError as e:
            put(("error", f"ยังไม่ได้ติดตั้งไลบรารี '{e.name}' ใน Python ตัวนี้\nรัน: python -m pip install -r requirements.txt\n(Python ที่ใช้: {sys.executable})"))
        except Exception as e:
            put(("error", f"{type(e).__name__}: {e}"))

    def poll(self):
        try:
            while True:
                kind, *rest = self.events.get_nowait()
                if kind == "log":
                    self.write(rest[0])
                elif kind == "status":
                    self.status.configure(text=rest[0])
                    self.write(rest[0])
                elif kind == "progress":
                    done, total = rest
                    self.bar.configure(maximum=max(total, 1), value=done)
                    self.status.configure(text=f"ถอดแล้ว {done}/{total} ช่วง")
                elif kind in ("done", "error"):
                    self.write(rest[0])
                    self.status.configure(text="เสร็จแล้ว" if kind == "done" else "หยุดทำงาน")
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    (messagebox.showinfo if kind == "done" else messagebox.showwarning)("Transcriber", rest[0])
        except queue.Empty:
            pass
        self.after(100, self.poll)


if __name__ == "__main__":
    App().mainloop()

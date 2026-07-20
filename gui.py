#!/usr/bin/env python3
"""
gui.py — a tiny file-picker front end for strip_metadata.py.

No web server, no extra dependencies beyond Pillow — just Python's built-in
tkinter. Pick images (or a whole folder), choose your options, hit the
button.

Run with:
    python gui.py
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cli import SUPPORTED_EXTENSIONS, strip_image_metadata

FILETYPES = [
    ("Images", " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))),
    ("All files", "*.*"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Strip Metadata")
        self.geometry("560x480")
        self.minsize(480, 380)

        self.selected_files: list[Path] = []
        self.log_queue: queue.Queue = queue.Queue()

        self._build_widgets()
        self.after(100, self._poll_log_queue)

    def _build_widgets(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Button(top, text="Add Files…", command=self.add_files).pack(side="left")
        ttk.Button(top, text="Add Folder…", command=self.add_folder).pack(side="left", padx=6)
        ttk.Button(top, text="Clear", command=self.clear_files).pack(side="left")

        self.count_label = ttk.Label(top, text="No images selected")
        self.count_label.pack(side="right")

        # Scrollable list of selected files
        list_frame = ttk.Frame(self, padding=(10, 0))
        list_frame.pack(fill="both", expand=True)
        self.file_listbox = tk.Listbox(list_frame)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.file_listbox.yview)
        self.file_listbox.configure(yscrollcommand=scrollbar.set)
        self.file_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Options
        opts = ttk.Frame(self, padding=10)
        opts.pack(fill="x")

        self.recursive_var = tk.BooleanVar(value=True)
        self.keep_icc_var = tk.BooleanVar(value=False)
        self.in_place_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(opts, text="Include subfolders", variable=self.recursive_var).pack(side="left")
        ttk.Checkbutton(opts, text="Keep color profile (ICC)", variable=self.keep_icc_var).pack(side="left", padx=10)
        ttk.Checkbutton(opts, text="Overwrite originals", variable=self.in_place_var).pack(side="left")

        # Run button
        run_frame = ttk.Frame(self, padding=10)
        run_frame.pack(fill="x")
        self.run_button = ttk.Button(run_frame, text="Strip Metadata", command=self.run_strip)
        self.run_button.pack(fill="x")

        # Log output
        log_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True)

    # ---------- file selection ----------

    def add_files(self):
        paths = filedialog.askopenfilenames(title="Select images", filetypes=FILETYPES)
        for p in paths:
            path = Path(p)
            if path not in self.selected_files:
                self.selected_files.append(path)
        self._refresh_file_list()

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select a folder of images")
        if not folder:
            return
        pattern = "**/*" if self.recursive_var.get() else "*"
        found = [
            f for f in Path(folder).glob(pattern)
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        for path in found:
            if path not in self.selected_files:
                self.selected_files.append(path)
        self._refresh_file_list()

    def clear_files(self):
        self.selected_files.clear()
        self._refresh_file_list()

    def _refresh_file_list(self):
        self.file_listbox.delete(0, "end")
        for path in self.selected_files:
            self.file_listbox.insert("end", str(path))
        n = len(self.selected_files)
        self.count_label.configure(text=f"{n} image{'s' if n != 1 else ''} selected")

    # ---------- running the strip ----------

    def run_strip(self):
        if not self.selected_files:
            messagebox.showinfo("Nothing selected", "Add some images first.")
            return
        if self.in_place_var.get():
            confirmed = messagebox.askyesno(
                "Overwrite originals?",
                f"This will overwrite {len(self.selected_files)} original file(s). Continue?",
            )
            if not confirmed:
                return

        self.run_button.configure(state="disabled", text="Working…")
        self._set_log("")
        files = list(self.selected_files)
        in_place = self.in_place_var.get()
        keep_icc = self.keep_icc_var.get()

        thread = threading.Thread(
            target=self._strip_worker, args=(files, in_place, keep_icc), daemon=True
        )
        thread.start()

    def _strip_worker(self, files: list[Path], in_place: bool, keep_icc: bool):
        cleaned = skipped = failed = 0
        for src in files:
            if in_place:
                out_path = src
            else:
                out_dir = src.parent / "cleaned"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / src.name

            result = strip_image_metadata(src, out_path, keep_icc=keep_icc)

            if result.error:
                failed += 1
                self.log_queue.put(f"FAILED   {src}: {result.error}")
            elif not result.had_metadata:
                skipped += 1
                self.log_queue.put(f"clean    {src} (nothing to remove)")
            else:
                cleaned += 1
                tags = []
                if result.had_exif:
                    tags.append("EXIF")
                if result.had_icc:
                    tags.append("ICC" + (" [kept]" if keep_icc else ""))
                if result.other_keys:
                    tags.append(",".join(result.other_keys))
                self.log_queue.put(f"stripped {src}: {' + '.join(tags)}")

        self.log_queue.put(f"\nDone. Cleaned: {cleaned}  Already clean: {skipped}  Failed: {failed}")
        self.log_queue.put("__DONE__")

    def _poll_log_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__DONE__":
                    self.run_button.configure(state="normal", text="Strip Metadata")
                else:
                    self._append_log(line)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _set_log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", text)
        self.log_text.configure(state="disabled")

    def _append_log(self, line: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()
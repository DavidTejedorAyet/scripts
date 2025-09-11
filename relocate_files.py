#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Organizador de archivos multimedia (Películas/Series) con GUI Tkinter.

Cambios solicitados:
- Sin filtro de tamaño mínimo.
- Sin modo "simular".
- Analizar NO mueve nada (solo inspección).
- Múltiples carpetas de origen (listado editable en la UI). Por defecto:
    C:\Users\david\Downloads\Torrent
    C:\Users\david\Downloads\eMule\Incoming

Características:
- Detección híbrida:
  (1) "Franquicia NN - Título" -> PELÍCULA (ej.: "Shin Chan 01 - ...").
  (2) Series por patrones SxxEyy o N×M.
  (3) PTN (parse-torrent-name) si está instalado.
  (4) guessit si está instalado.
  (5) Fallback a película.
- Mueve al NAS con nombres normalizados:
    Películas/Título (Año).ext
    Series/<Serie>/Temporada XX/Serie - XXxYY.ext
- Mueve también archivos compañeros (.srt, .nfo, .jpg, .png, .txt).
- Botón para instalar dependencias con pip (UTF-8 forzado).
- ✔️ Barra de progreso por bytes reales.
"""

from __future__ import annotations

import errno
import functools
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional, DefaultDict
from collections import defaultdict

# ---------- Dependencias opcionales (cargadas dinámicamente) ----------
PTN = None
guessit = None
HAS_PTN = False
HAS_GUESSIT = False


def refresh_imports() -> None:
    """Reintenta importar librerías opcionales y actualiza banderas."""
    global PTN, guessit, HAS_PTN, HAS_GUESSIT
    try:
        import PTN as _PTN  # type: ignore
        PTN = _PTN
        HAS_PTN = True
    except Exception:
        PTN = None
        HAS_PTN = False
    try:
        from guessit import guessit as _guessit  # type: ignore
        guessit = _guessit
        HAS_GUESSIT = True
    except Exception:
        guessit = None
        HAS_GUESSIT = False


refresh_imports()

# ---------- Configuración ----------
VIDEO_EXTS = (".avi", ".mkv", ".mp4", ".mov", ".wmv", ".flv")
COMPANION_EXTS = (".srt", ".sub", ".idx", ".nfo", ".jpg", ".jpeg", ".png", ".txt")
SAMPLE_PATTERNS = re.compile(r"(sample|trailer|\b(rarbg|yts|ettv|eztv)\b)", re.IGNORECASE)

INVALID_WIN_CHARS = r'<>:"/\\|?*'
INVALID_WIN_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}

# “Franquicia NN - Título …”
FALLBACK_NUMBERED_TITLE = re.compile(
    r"""^\s*
        (?P<franchise>.+?)\s+(?P<num>\d{1,3})\s*[\-–—]\s*
        (?P<title>[^\[\(]+?)\s*(?:\[[^\]]*\]|\([^\)]*\))*\s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Series: SxxEyy | N×M
PATTERN_SxxEyy = re.compile(r"(?i)(?:^|[^A-Za-z0-9])S(?P<s>\d{1,2})E(?P<e>\d{1,3})(?:[^A-Za-z0-9]|$)")
PATTERN_NxM = re.compile(r"(?i)(?:^|[^A-Za-z0-9])(?P<s>\d{1,2})x(?P<e>\d{1,3})(?:[^A-Za-z0-9]|$)")


# ---------- Utilidades ----------
def sanitize_filename(name: str) -> str:
    name = "".join(("_" if c in INVALID_WIN_CHARS else c) for c in name)
    name = re.sub(r"\s+", " ", name).strip()
    base, dot, ext = name.partition(".")
    if base.upper() in INVALID_WIN_NAMES:
        base = f"_{base}"
    return base + (dot + ext if dot else "")


def file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def strip_release_tags(stem: str) -> str:
    s = stem
    while True:
        new = re.sub(r"\s*(?:\[[^\]]*\]|\([^\)]*\))\s*$", "", s)
        if new == s:
            break
        s = new
    s = re.sub(r"\s*[–—]\s*", " - ", s)
    s = re.sub(r"\s+", " ", s).strip(" -")
    return s


def _safe_int(v, default: Optional[int]) -> Optional[int]:
    try:
        m = re.search(r"\d+", str(v))
        return int(m.group(0)) if m else default
    except Exception:
        return default


def human_bytes(n: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    x = float(n)
    while x >= 1024 and i < len(units) - 1:
        x /= 1024.0
        i += 1
    return f"{x:.1f} {units[i]}"


# ---------- Modelos ----------
@dataclass
class MediaItem:
    src_path: str
    content_type: str  # "movie" | "series"
    show_title: Optional[str]
    season: Optional[int]
    episodes: Optional[List[int]]
    dst_filename: str
    dst_dir: str
    dst_path: str


# ---------- Análisis (NO mueve nada) ----------
def analyze_media_in_sources(src_folders: List[str], dst_root: str) -> list[MediaItem]:
    """
    Escanea recursivamente todas las carpetas de origen y genera un plan sin tocar el disco.
    """
    items: list[MediaItem] = []

    for src_folder in src_folders:
        if not src_folder or not os.path.isdir(src_folder):
            continue

        for root_dir, _dirs, files in os.walk(src_folder):
            for fname in files:
                if not fname.lower().endswith(VIDEO_EXTS):
                    continue
                if SAMPLE_PATTERNS.search(fname):
                    continue
                src_path = os.path.join(root_dir, fname)
                try:
                    item = build_media_item(src_path, dst_root)
                    if item:
                        items.append(item)
                except Exception as ex:
                    print(f"[WARN] Error analizando '{src_path}': {ex}")

    return items


def build_media_item(src_path: str, dst_root: str) -> Optional[MediaItem]:
    fname = os.path.basename(src_path)
    stem, ext = os.path.splitext(fname)
    ext = ext if ext else ".mkv"
    cleaned_stem = strip_release_tags(stem)

    m_force = FALLBACK_NUMBERED_TITLE.match(cleaned_stem)
    if m_force:
        franchise = re.sub(r"\s+", " ", m_force.group("franchise")).strip()
        num = _safe_int(m_force.group("num"), 1) or 1
        title_part = re.sub(r"\s+", " ", m_force.group("title")).strip(" -")
        final_title = sanitize_filename(f"{franchise} {num:02d} - {title_part}")
        dst_dir = os.path.join(dst_root, "Películas")
        dst_name = sanitize_filename(f"{final_title}{ext}")
        return MediaItem(src_path, "movie", None, None, None, dst_name, dst_dir, os.path.join(dst_dir, dst_name))

    for rx in (PATTERN_SxxEyy, PATTERN_NxM):
        m = rx.search(fname)
        if m:
            season = _safe_int(m.group("s"), 1) or 1
            ep = _safe_int(m.group("e"), 1) or 1
            title = sanitize_filename(cleaned_stem)
            ep_str = f"{season:02d}x{ep:02d}"
            dst_dir = os.path.join(dst_root, "Series", title, f"Temporada {season:02d}")
            dst_name = sanitize_filename(f"{title} - {ep_str}{ext}")
            return MediaItem(src_path, "series", title, season, [ep], dst_name, dst_dir, os.path.join(dst_dir, dst_name))

    if HAS_PTN and PTN is not None:
        try:
            info = PTN.parse(fname) or {}
            title = info.get("title")
            season = info.get("season")
            episode = info.get("episode")
            if season is not None or episode is not None:
                title = sanitize_filename(title or cleaned_stem or "Desconocido")
                season = _safe_int(season, 1) or 1
                episode = _safe_int(episode, 1) or 1
                ep_str = f"{season:02d}x{episode:02d}"
                dst_dir = os.path.join(dst_root, "Series", title, f"Temporada {season:02d}")
                dst_name = sanitize_filename(f"{title} - {ep_str}{ext}")
                return MediaItem(src_path, "series", title, season, [episode], dst_name, dst_dir, os.path.join(dst_dir, dst_name))
            movie = sanitize_filename(title or cleaned_stem or "Pelicula_Desconocida")
            year = info.get("year")
            dst_dir = os.path.join(dst_root, "Películas")
            dst_name = sanitize_filename(f"{movie} ({year}){ext}" if year else f"{movie}{ext}")
            return MediaItem(src_path, "movie", None, None, None, dst_name, dst_dir, os.path.join(dst_dir, dst_name))
        except Exception:
            pass

    if HAS_GUESSIT and guessit is not None:
        try:
            info = guessit(fname) or {}
            if info.get("type") == "episode":
                title = sanitize_filename(info.get("title", cleaned_stem or "Desconocido"))
                season = _safe_int(info.get("season", 1), 1) or 1
                eps_raw = info.get("episode_list")
                eps: List[int] = []
                if isinstance(eps_raw, list):
                    for e in eps_raw:
                        v = _safe_int(e, None)
                        if v is not None:
                            eps.append(v)
                if not eps:
                    v = _safe_int(info.get("episode", None), None)
                    eps = [v if v is not None else 1]
                ep_str = f"{season:02d}x{eps[0]:02d}" if len(eps) == 1 else f"{season:02d}x{eps[0]:02d}-{eps[-1]:02d}"
                dst_dir = os.path.join(dst_root, "Series", title, f"Temporada {season:02d}")
                dst_name = sanitize_filename(f"{title} - {ep_str}{ext}")
                return MediaItem(src_path, "series", title, season, eps, dst_name, dst_dir, os.path.join(dst_dir, dst_name))
            movie = sanitize_filename(cleaned_stem or info.get("title", "Pelicula_Desconocida"))
            year = info.get("year")
            dst_dir = os.path.join(dst_root, "Películas")
            dst_name = sanitize_filename(f"{movie} ({year}){ext}" if year else f"{movie}{ext}")
            return MediaItem(src_path, "movie", None, None, None, dst_name, dst_dir, os.path.join(dst_dir, dst_name))
        except Exception:
            pass

    base = sanitize_filename(cleaned_stem or "Pelicula_Desconocida")
    dst_dir = os.path.join(dst_root, "Películas")
    dst_name = f"{base}{ext}"
    return MediaItem(src_path, "movie", None, None, None, dst_name, dst_dir, os.path.join(dst_dir, dst_name))


# ---------- Progreso por bytes ----------
def list_companion_files(src_video_path: str) -> list[str]:
    src_dir = os.path.dirname(src_video_path)
    stem = os.path.splitext(os.path.basename(src_video_path))[0]
    out: list[str] = []
    try:
        for entry in os.listdir(src_dir):
            sp = os.path.join(src_dir, entry)
            if not os.path.isfile(sp):
                continue
            name, ext = os.path.splitext(entry)
            if name == stem and ext.lower() in COMPANION_EXTS:
                out.append(sp)
    except Exception:
        pass
    return out


def compute_total_bytes(plan: list[MediaItem]) -> int:
    total = 0
    for it in plan:
        total += file_size(it.src_path)
        for c in list_companion_files(it.src_path):
            total += file_size(c)
    return total


def copy_with_progress(src: str, dst: str, add_bytes: Callable[[int], None], chunk_size: int = 1024 * 1024) -> None:
    ensure_dir(os.path.dirname(dst))
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        while True:
            buf = fsrc.read(chunk_size)
            if not buf:
                break
            fdst.write(buf)
            add_bytes(len(buf))
    try:
        shutil.copystat(src, dst)
    except Exception:
        pass


def move_path(src: str, dst: str, add_bytes: Callable[[int], None]) -> None:
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    try:
        if os.path.exists(dst):
            os.remove(dst)
    except Exception:
        pass

    src_sz = file_size(src)
    try:
        ensure_dir(os.path.dirname(dst))
        os.replace(src, dst)  # rename (misma partición)
        add_bytes(src_sz)     # contamos todo de golpe
        return
    except OSError as ex:
        if ex.errno != errno.EXDEV:
            # Otro error -> seguimos con copia
            pass

    copy_with_progress(src, dst, add_bytes)
    try:
        os.remove(src)
    except Exception:
        pass


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def move_video_and_companions(item: MediaItem, add_bytes: Callable[[int], None]) -> None:
    move_path(item.src_path, item.dst_path, add_bytes)
    dest_dir = os.path.dirname(item.dst_path)
    dest_stem = os.path.splitext(os.path.basename(item.dst_path))[0]
    src_dir = os.path.dirname(item.src_path)
    src_stem = os.path.splitext(os.path.basename(item.src_path))[0]

    try:
        for entry in os.listdir(src_dir):
            sp = os.path.join(src_dir, entry)
            if not os.path.isfile(sp):
                continue
            name, ext = os.path.splitext(entry)
            if name == src_stem and ext.lower() in COMPANION_EXTS:
                new_name = sanitize_filename(f"{dest_stem}{ext}")
                dp = os.path.join(dest_dir, new_name)
                move_path(sp, dp, add_bytes)
    except Exception:
        pass


def perform_moves_bytes(
    plan: list[MediaItem],
    total_bytes: int,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[str]:
    """
    Mueve el plan informando por bytes.
    progress_cb(done_bytes, total_bytes, label) si se proporciona.
    """
    errors: list[str] = []
    done = 0

    def add_bytes(n: int, label: str = "") -> None:
        nonlocal done
        done += n
        if progress_cb:
            try:
                progress_cb(done, total_bytes, label)
            except Exception:
                pass

    for item in plan:
        label = os.path.basename(item.dst_path)
        try:
            ensure_dir(item.dst_dir)
            move_video_and_companions(item, lambda n, lbl=label: add_bytes(n, lbl))
        except Exception as ex:
            errors.append(f"Error al mover '{item.src_path}' → '{item.dst_path}': {ex}")

    return errors


# ---------- GUI ----------
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Organizador de archivos multimedia")
        self.geometry("1040x760")

        # Variables ligadas a este root
        self.dst_var = tk.StringVar(self, value=r"\\Nas\nas")
        self.plan: list[MediaItem] = []

        try:
            style = ttk.Style(self)
            style.configure("Warning.TFrame", background="#fff7e6")
        except Exception:
            pass

        self._build_ui()

        # Orígenes por defecto
        self._add_source(r"C:\Users\david\Downloads\Torrent")
        self._add_source(r"C:\Users\david\Downloads\eMule\Incoming")

    def _build_ui(self) -> None:
        # Banner dependencias
        self.deps_frame = ttk.Frame(self, style="Warning.TFrame")
        self.deps_frame.pack(fill="x", padx=10, pady=(10, 0))
        self.deps_label = ttk.Label(self.deps_frame, text="", justify="left")
        self.deps_label.pack(side="left", fill="x", expand=True)
        self.btn_install = ttk.Button(self.deps_frame, text="Instalar dependencias", command=self.on_install_deps)
        self.btn_install.pack(side="right")
        self._update_deps_banner()

        # ---- Orígenes múltiples ----
        frm_sources = ttk.LabelFrame(self, text="Carpetas Origen")
        frm_sources.pack(fill="x", padx=10, pady=10)
        self.lb_sources = tk.Listbox(frm_sources, height=5, selectmode=tk.EXTENDED)
        self.lb_sources.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=8)
        btns_src = ttk.Frame(frm_sources)
        btns_src.pack(side="left", padx=5, pady=8)
        ttk.Button(btns_src, text="Añadir carpeta…", command=self.add_source_dialog).pack(fill="x", pady=2)
        ttk.Button(btns_src, text="Eliminar seleccionadas", command=self.remove_selected_sources).pack(fill="x", pady=2)

        # ---- Destino ----
        frm_dest = ttk.Frame(self)
        frm_dest.pack(fill="x", padx=10, pady=5)
        ttk.Label(frm_dest, text="Carpeta Destino (NAS):").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm_dest, textvariable=self.dst_var, width=80).grid(row=0, column=1, sticky="we", padx=5)
        ttk.Button(frm_dest, text="Seleccionar", command=self.pick_dst).grid(row=0, column=2, padx=5)

        # ---- Botones ----
        frm_buttons = ttk.Frame(self); frm_buttons.pack(fill="x", padx=10, pady=5)
        self.btn_analyze = ttk.Button(frm_buttons, text="Analizar estructura", command=self.on_analyze); self.btn_analyze.pack(side="left", padx=5)
        self.btn_apply = ttk.Button(frm_buttons, text="Analizar y mover", command=self.on_apply, state="disabled"); self.btn_apply.pack(side="left", padx=5)

        # ---- Árbol ----
        frm_tree = ttk.Frame(self); frm_tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree = ttk.Treeview(frm_tree, show="tree")
        self.tree.pack(fill="both", expand=True)

        # ---- Progreso ----
        frm_progress = ttk.Frame(self); frm_progress.pack(fill="x", padx=10, pady=5)
        self.progress_var = tk.DoubleVar(self, value=0.0)  # bytes
        self.progress_bar = ttk.Progressbar(frm_progress, variable=self.progress_var, mode="determinate")
        self.progress_bar.pack(fill="x", expand=True)
        self.status_var = tk.StringVar(self, value="Listo.")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10, pady=(0, 10))

    # ---- Orígenes helpers ----
    def _add_source(self, path: str) -> None:
        if path and path not in self.lb_sources.get(0, tk.END):
            self.lb_sources.insert(tk.END, path)

    def add_source_dialog(self) -> None:
        p = filedialog.askdirectory()
        if p:
            self._add_source(p)

    def remove_selected_sources(self) -> None:
        selected = list(self.lb_sources.curselection())
        selected.reverse()
        for idx in selected:
            self.lb_sources.delete(idx)

    def get_sources(self) -> List[str]:
        return list(self.lb_sources.get(0, tk.END))

    # ---- Dependencias ----
    def _update_deps_banner(self) -> None:
        missing = []
        if not HAS_PTN:
            missing.append("parse-torrent-name (PTN)")
        if not HAS_GUESSIT:
            missing.append("guessit")
        if missing:
            msg = ("⚠️ Faltan dependencias opcionales: " + ", ".join(missing) +
                   ". Pulsa «Instalar dependencias» para instalarlas.")
            self.deps_label.configure(text=msg, foreground="#b76e00")
            self.btn_install.configure(state="normal")
        else:
            self.deps_label.configure(text="✅ Dependencias opcionales instaladas: PTN y guessit.", foreground="#1a7f37")
            self.btn_install.configure(state="disabled")

    def on_install_deps(self) -> None:
        pkgs = []
        if not HAS_PTN:
            pkgs.append("parse-torrent-name")
        if not HAS_GUESSIT:
            pkgs.append("guessit")
        if not pkgs:
            messagebox.showinfo("Dependencias", "Ya está todo instalado.")
            return

        win = tk.Toplevel(self); win.title("Instalando dependencias (pip)"); win.geometry("760x420")
        txt = tk.Text(win, wrap="word"); txt.pack(fill="both", expand=True)
        scr = ttk.Scrollbar(win, command=txt.yview); txt.configure(yscrollcommand=scr.set); scr.pack(side="right", fill="y")

        def append(line: str) -> None:
            txt.insert("end", line + "\n"); txt.see("end")

        self.btn_install.configure(state="disabled")
        self._set_busy(True)
        append(f"Usando intérprete: {sys.executable}")
        append("Actualizando pip/setuptools/wheel (UTF-8)…")

        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")

        def run(cmd: list[str]) -> int:
            append("\n$ " + " ".join(cmd))
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1, universal_newlines=True, env=env)
                for line in iter(p.stdout.readline, ""):
                    self._ui(lambda l=line.rstrip(): append(l))
                p.stdout.close()
                return p.wait()
            except Exception as ex:
                self._ui(lambda e=ex: append(f"❌ Excepción: {e}"))
                return 1

        def worker():
            ok = True
            base = [sys.executable, "-X", "utf8", "-m", "pip", "install", "--user", "-U"]
            if run(base + ["pip", "setuptools", "wheel"]) != 0:
                ok = False
            for pkg in pkgs:
                if run(base + [pkg]) != 0:
                    ok = False
                    self._ui(lambda p=pkg: append(f"❌ Error instalando {p}."))
                else:
                    self._ui(lambda p=pkg: append(f"✅ {p} instalado."))

            def finish():
                refresh_imports()
                self._update_deps_banner()
                self._set_busy(False)
                if ok and (HAS_PTN or HAS_GUESSIT):
                    messagebox.showinfo("Dependencias", "Instalación completada.")
                else:
                    messagebox.showerror(
                        "Dependencias",
                        "Alguna instalación falló.\nPrueba en consola:\n"
                        f"> py -3.13 -X utf8 -m pip install --user -U {' '.join(pkgs)}"
                    )
                win.lift()

            self._ui(finish)

        threading.Thread(target=worker, daemon=True).start()

    # ---- Acciones principales ----
    def pick_dst(self) -> None:
        p = filedialog.askdirectory()
        if p:
            self.dst_var.set(p)

    def on_analyze(self) -> None:
        sources = self.get_sources()
        dst = self.dst_var.get().strip()
        if not sources:
            messagebox.showerror("Error", "Añade al menos una carpeta de origen."); return
        if not dst:
            messagebox.showerror("Error", "Selecciona una carpeta de destino válida."); return

        self._set_busy(True)
        self.btn_apply.config(state="disabled")
        self._clear_tree()
        self.status_var.set("Analizando...")

        def worker():
            try:
                plan = analyze_media_in_sources(sources, dst)
            except Exception as ex:
                plan = []
                self._ui(lambda m=f"Fallo al analizar: {ex}": messagebox.showerror("Error", m))

            def finish():
                self.plan = plan
                self._populate_tree(plan)
                self.btn_apply.config(state=("normal" if plan else "disabled"))
                self._set_busy(False)
                self.status_var.set(f"Análisis completado. Ítems: {len(plan)}")

            self._ui(finish)

        threading.Thread(target=worker, daemon=True).start()

    def on_apply(self) -> None:
        if not self.plan:
            messagebox.showerror("Error", "No hay elementos que mover."); return

        total_bytes = compute_total_bytes(self.plan)
        if total_bytes <= 0:
            messagebox.showinfo("Nada que mover", "No hay bytes para mover."); return

        self._set_busy(True)
        self.progress_bar.config(maximum=float(total_bytes))
        self.progress_var.set(0.0)
        self.status_var.set(f"Moviendo... 0% (0 / {human_bytes(total_bytes)})")

        def progress_cb(done: int, total: int, label: str) -> None:
            pct = (done / total) * 100.0 if total else 100.0
            self._ui(lambda d=done, p=pct, t=total, lab=label: (
                self.progress_var.set(float(d)),
                self.status_var.set(f"Moviendo: {lab}  |  {human_bytes(d)} / {human_bytes(t)}  ({p:.1f}%)")
            ))

        def worker():
            try:
                errors = perform_moves_bytes(self.plan, total_bytes, progress_cb=progress_cb)
            except Exception as ex:
                errors = [f"Fallo general al mover: {ex}"]
            self._ui(functools.partial(self._finish_after_apply, errors, total_bytes))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_after_apply(self, errors: list[str], total_bytes: int) -> None:
        self._set_busy(False)
        if errors:
            messagebox.showerror("Errores durante la operación", "\n".join(errors))
            self.status_var.set(f"Completado con errores. Total: {human_bytes(total_bytes)}")
        else:
            messagebox.showinfo("Completado", "Los cambios han sido aplicados.")
            self.status_var.set(f"Completado. Total movido: {human_bytes(total_bytes)}")
        self.btn_apply.config(state="disabled")
        self._clear_tree()
        self.plan = []
        self.progress_var.set(0.0)

    # ---- Helpers UI ----
    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.btn_analyze.config(state=state)
        self.btn_apply.config(state=("disabled" if busy else self.btn_apply["state"]))
        self.btn_install.config(state=("disabled" if busy else self.btn_install["state"]))
        self.config(cursor="watch" if busy else "")
        self.update_idletasks()

    def _ui(self, fn) -> None:
        self.after(0, fn)

    def _clear_tree(self) -> None:
        for i in self.tree.get_children():
            self.tree.delete(i)

    def _populate_tree(self, plan: list[MediaItem]) -> None:
        """Pinta árbol: Películas / Series → Serie → Temporada → nombre destino."""
        self._clear_tree()
        movies = [it for it in plan if it.content_type == "movie"]
        series_map: DefaultDict[str, DefaultDict[int, List[MediaItem]]] = defaultdict(lambda: defaultdict(list))
        for it in plan:
            if it.content_type == "series":
                title = it.show_title or "Desconocido"
                season = it.season or 1
                series_map[title][season].append(it)

        if movies:
            n_movies = self.tree.insert("", "end", text=f"Películas ({len(movies)})", open=True)
            for it in sorted(movies, key=lambda x: x.dst_filename.lower()):
                self.tree.insert(n_movies, "end", text=it.dst_filename)

        if series_map:
            total_eps = sum(len(ep_list) for seas in series_map.values() for ep_list in seas.values())
            n_series = self.tree.insert("", "end", text=f"Series ({total_eps} archivos)", open=True)
            for title in sorted(series_map.keys(), key=lambda s: s.lower()):
                n_title = self.tree.insert(n_series, "end", text=title, open=True)
                for season in sorted(series_map[title].keys()):
                    n_seas = self.tree.insert(n_title, "end", text=f"Temporada {season:02d}", open=True)
                    for it in sorted(series_map[title][season], key=lambda x: x.dst_filename.lower()):
                        self.tree.insert(n_seas, "end", text=it.dst_filename)


# ---------- Main ----------
def main() -> None:
    destination_folder = r"\\Nas\nas"
    if destination_folder and not os.path.isdir(destination_folder):
        try:
            os.makedirs(destination_folder, exist_ok=True)
        except Exception as e:
            print(f"No se pudo crear la carpeta destino {destination_folder}: {e}")

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

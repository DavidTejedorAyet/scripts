# -*- coding: utf-8 -*-
"""
Lanzador de utilidades por categorías (modo oscuro)
- Raíz = carpeta donde está este archivo.
- Pestañas = subcarpetas inmediatas de tools/ (categorías).
- En cada pestaña, se listan TODOS los scripts .py/.pyw que haya
  dentro de esa categoría (recursivo), ignorando __init__.py.
- Texto del botón:
    1) __display_name__ (si existe)
    2) primera línea del docstring
    3) nombre del archivo
- Cada script se ejecuta en su propio proceso.
- En distribución (PyInstaller onefile):
    * Primero intenta descubrir módulos con importlib (paquete tools embebido).
    * Fallback: si no encuentra nada, escanea 'tools' incluido como datos
      (gracias a --add-data) en sys._MEIPASS/tools y ejecuta via --run tools.<...>.
- Iconos:
    * Se fija AppUserModelID (Windows) para que la barra de tareas muestre tu icono.
    * Se carga app.ico como icono de ventana (desde _MEIPASS si está congelado).
"""

from __future__ import annotations

import os
import sys
import ast
import runpy
import importlib
import pkgutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox

APP_TITLE = "Lanzador"
PY_EXTS = {".py", ".pyw"}

# Paleta (modo oscuro como antes)
DARK_BG     = "#1f1f1f"
DARK_FG     = "#e6e6e6"
DARK_SUBFG  = "#a8a8a8"
DARK_CARD   = "#262626"
DARK_ACCENT = "#3a3a3a"


# ===================== utilidades =====================

def is_frozen() -> bool:
    """True si está empaquetado con PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def root_dir() -> Path:
    """Carpeta donde reside este lanzador (no el CWD)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(rel: str) -> Path:
    """
    Devuelve la ruta a un recurso (p.ej. 'app.ico'):
    - En onefile: <_MEIPASS>/rel
    - En desarrollo: <carpeta_del_script>/rel
    """
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / rel
    return root_dir() / rel


def ensure_windows_appid():
    """
    En Windows, fija un AppUserModelID para que la barra de tareas
    use el icono correcto y agrupe la ventana por este EXE.
    """
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "com.david.tools.launcher"
            )
        except Exception:
            pass

ensure_windows_appid()


def preferred_python_for_child() -> str:
    """Usa pythonw.exe en Windows si está disponible; si no, sys.executable."""
    exe = Path(sys.executable)
    if os.name == "nt" and exe.name.lower() == "python.exe":
        cand = exe.with_name("pythonw.exe")
        if cand.exists():
            return str(cand)
    return str(exe)


def pretty_from_filename(name: str) -> str:
    base = Path(name).stem
    return base.replace("_", " ").replace("-", " ").title()


def safe_first_line(text: Optional[str]) -> str:
    if not text:
        return ""
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")


# ===================== listado (DESARROLLO) =====================

def _list_scripts_recursive(folder: Path) -> List[Path]:
    out: List[Path] = []
    try:
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith((".", "_")) and d.lower() not in {"__pycache__", "dist", "build"}
            ]
            for fn in sorted(filenames, key=lambda s: s.lower()):
                if fn.lower() == "__init__.py":
                    continue
                if Path(fn).suffix.lower() in PY_EXTS:
                    out.append(Path(dirpath) / fn)
    except Exception:
        return []
    return out


def _categories_under_tools(root: Path) -> List[Tuple[str, Path]]:
    tools = root / "tools"
    if not tools.is_dir():
        return []
    EXCLUDE = {"__pycache__", ".git", ".idea", ".vscode", "dist", "build", "mis scripts (build)"}
    parents = [
        p for p in tools.iterdir()
        if p.is_dir() and p.name.lower() not in EXCLUDE and not p.name.startswith((".", "_"))
    ]
    return [(p.name, p) for p in sorted(parents, key=lambda pp: pp.name.lower())]


def build_catalog_dev(root: Path) -> Dict[str, List[Path]]:
    catalog: Dict[str, List[Path]] = {}
    cats = _categories_under_tools(root)
    if cats:
        for cat_name, cat_dir in cats:
            catalog[cat_name] = _list_scripts_recursive(cat_dir)
    if not any(catalog.values()):
        # Fallback a subcarpetas del root si tools no existe/vacío
        EXCLUDE = {"__pycache__", ".git", ".idea", ".vscode", "dist", "build", "mis scripts (build)", "tools"}
        parents = [p for p in root.iterdir() if p.is_dir() and p.name.lower() not in EXCLUDE]
        for p in sorted(parents, key=lambda pp: pp.name.lower()):
            catalog[p.name] = _list_scripts_recursive(p)

    for k in list(catalog.keys()):
        catalog[k].sort(key=lambda f: f.name.lower())
    catalog = dict(sorted(catalog.items(), key=lambda kv: kv[0].lower()))
    return catalog


def extract_display_name(path: Path) -> str:
    fallback = path.stem
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return fallback
    try:
        module = ast.parse(src)
    except Exception:
        return fallback

    display = ""
    for n in module.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "__display_name__":
                    val = getattr(n, "value", None)
                    if isinstance(val, ast.Str):
                        display = val.s
                    elif isinstance(val, ast.Constant) and isinstance(val.value, str):
                        display = val.value
        if display:
            break

    if display and display.strip():
        return display.strip()

    doc = ast.get_docstring(module) or ""
    first = safe_first_line(doc)
    if first:
        return first

    return fallback


# ===================== listado (CONGELADO) =====================

@dataclass
class Item:
    label: str
    category: str
    path: Optional[Path]       # sólo usa en desarrollo
    module_fqn: Optional[str]  # tools.<...> para ejecución embebida


def _discover_embedded_importlib() -> Dict[str, List[Item]]:
    categories: Dict[str, List[Item]] = {}
    try:
        tools_pkg = importlib.import_module("tools")
    except Exception:
        return categories

    for _, name, ispkg in pkgutil.walk_packages(tools_pkg.__path__, prefix="tools."):
        if ispkg:
            continue
        parts = name.split(".")
        if len(parts) < 3 or parts[-1].startswith("_"):
            continue
        cat = parts[1]
        label = ""
        try:
            mod = importlib.import_module(name)
            label = getattr(mod, "__display_name__", "") or safe_first_line(getattr(mod, "__doc__", ""))
        except Exception:
            label = ""
        if not label:
            label = pretty_from_filename(parts[-1])
        categories.setdefault(cat, []).append(Item(label=label, category=cat, path=None, module_fqn=name))

    for k in list(categories.keys()):
        categories[k].sort(key=lambda it: it.label.lower())
    return dict(sorted(categories.items(), key=lambda kv: kv[0].lower()))


def _discover_embedded_from_meipass() -> Dict[str, List[Item]]:
    """
    Fallback: lista archivos fuente de 'tools' añadidos como datos (--add-data "tools;tools")
    y construye FQN 'tools.<...>' en base a la ruta relativa.
    """
    categories: Dict[str, List[Item]] = {}
    base = Path(getattr(sys, "_MEIPASS", "")) / "tools"
    if not base.exists():
        return categories

    for cat_dir in sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
        cat = cat_dir.name
        items: List[Item] = []
        for dirpath, dirnames, filenames in os.walk(cat_dir):
            dirnames[:] = [d for d in dirnames if d.lower() not in {"__pycache__"} and not d.startswith((".", "_"))]
            for fn in sorted(filenames, key=lambda s: s.lower()):
                if fn.lower() == "__init__.py":
                    continue
                if Path(fn).suffix.lower() in PY_EXTS:
                    fpath = Path(dirpath) / fn
                    rel = fpath.relative_to(base)
                    parts = list(rel.parts)
                    parts[-1] = Path(parts[-1]).stem
                    fqn = "tools." + ".".join(parts)
                    # label desde fuente (si se puede); si no, del nombre
                    try:
                        txt = fpath.read_text(encoding="utf-8", errors="replace")
                        try:
                            node = ast.parse(txt)
                            label = ""
                            for n in node.body:
                                if isinstance(n, ast.Assign):
                                    for t in n.targets:
                                        if isinstance(t, ast.Name) and t.id == "__display_name__":
                                            val = getattr(n, "value", None)
                                            if isinstance(val, ast.Str):
                                                label = val.s
                                            elif isinstance(val, ast.Constant) and isinstance(val.value, str):
                                                label = val.value
                                if label:
                                    break
                            if not label:
                                label = safe_first_line(ast.get_docstring(node) or "") or pretty_from_filename(fn)
                        except Exception:
                            label = pretty_from_filename(fn)
                    except Exception:
                        label = pretty_from_filename(fn)

                    items.append(Item(label=label, category=cat, path=None, module_fqn=fqn))
        if items:
            items.sort(key=lambda it: it.label.lower())
            categories[cat] = items

    return dict(sorted(categories.items(), key=lambda kv: kv[0].lower()))


def discover_embedded() -> Dict[str, List[Item]]:
    cats = _discover_embedded_importlib()
    if cats:
        return cats
    return _discover_embedded_from_meipass()


# ===================== ejecución =====================

def self_command_for_run(modname: str) -> List[str]:
    if is_frozen():
        return [sys.executable, "--run", modname]
    return [sys.executable, str(Path(__file__).resolve()), "--run", modname]


def run_embedded_module(modname: str) -> int:
    try:
        if not (modname and modname.startswith("tools.")):
            raise ValueError(f"Módulo no permitido: {modname!r}")
        runpy.run_module(modname, run_name="__main__", alter_sys=True)
        return 0
    except SystemExit as e:
        try:
            return int(e.code) if e.code is not None else 0
        except Exception:
            return 0
    except Exception as e:
        messagebox.showerror("Fallo ejecutando módulo", f"{modname}\n\n{e}")
        return 1


def launch_script(path: Path, *, use_python: str = ""):
    cmd = [use_python or preferred_python_for_child(), "-X", "utf8", str(path)]
    subprocess.Popen(cmd, cwd=str(root_dir()), shell=False, close_fds=(os.name != "nt"))


def launch_item(it: Item):
    if is_frozen():
        cmd = self_command_for_run(it.module_fqn or "")
        subprocess.Popen(cmd, cwd=str(root_dir()), shell=False, close_fds=(os.name != "nt"))
    else:
        if not it.path:
            raise RuntimeError("Ruta no disponible para desarrollo.")
        launch_script(it.path)


# ===================== UI (modo oscuro + pestañas como antes) =====================

class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x600")
        self.minsize(860, 500)

        self._apply_dark_theme()

        # === Establecer icono de ventana (título y barra de tareas) ===
        try:
            ico = resource_path("app.ico")
            if ico.exists():
                self.iconbitmap(default=str(ico))
        except Exception:
            pass

        self.root_path = root_dir()
        self._tabs: Dict[str, ttk.Frame] = {}
        self._catalog: Dict[str, List[Item]] = {}

        self._build_ui()
        self.populate()
        self.bind("<FocusIn>", lambda e: self.populate(preserve=True))

    def _apply_dark_theme(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self.configure(bg=DARK_BG)
        style.configure(".", background=DARK_BG, foreground=DARK_FG)
        for widget in ("TFrame", "TLabelframe", "TLabelframe.Label"):
            style.configure(widget, background=DARK_BG, foreground=DARK_FG)
        style.configure("TLabel", background=DARK_BG, foreground=DARK_FG)
        style.configure("Subtle.TLabel", background=DARK_BG, foreground=DARK_SUBFG)
        style.configure("TButton",
                        background=DARK_CARD, foreground=DARK_FG, borderwidth=1,
                        focusthickness=3, focuscolor=DARK_ACCENT, padding=(10, 6))
        style.map("TButton",
                  background=[("active", "#2A2A2A")],
                  foreground=[("disabled", "#777777")])
        style.configure("Card.TFrame", background=DARK_CARD)
        style.configure("TNotebook", background=DARK_BG, foreground=DARK_FG, borderwidth=0)
        style.configure("TNotebook.Tab", background=DARK_ACCENT, foreground=DARK_FG, padding=(12, 6))
        style.map("TNotebook.Tab",
                  background=[("selected", DARK_CARD)],
                  foreground=[("selected", DARK_FG)])

    def _build_ui(self):
        top = ttk.Frame(self, padding=10, style="TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Raíz:", font=("", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.folder_var = tk.StringVar(value=str(self.root_path))
        ttk.Label(top, textvariable=self.folder_var, style="Subtle.TLabel").grid(row=0, column=1, sticky="w", padx=8)
        ttk.Button(top, text="Refrescar", command=lambda: self.populate(preserve=True)).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(top, text="Abrir carpeta", command=self.open_root).grid(row=0, column=3, padx=(8, 0))

        self.nb = ttk.Notebook(self, style="TNotebook")
        self.nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.status = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status, anchor="w", padding=(10, 0), style="Subtle.TLabel").pack(fill="x", pady=(0, 10))

    def open_root(self):
        try:
            os.startfile(self.root_path)
        except Exception:
            messagebox.showinfo("Carpeta", str(self.root_path))

    def _clear_tabs(self):
        for tab_id in list(self.nb.tabs()):
            try:
                self.nb.forget(tab_id)
            except Exception:
                pass
        for frame in list(self._tabs.values()):
            try:
                frame.destroy()
            except Exception:
                pass
        self._tabs.clear()

    def populate(self, preserve: bool = False):
        selected_text = None
        if preserve and self.nb.tabs():
            try:
                current = self.nb.select()
                selected_text = self.nb.tab(current, "text")
            except Exception:
                selected_text = None

        if is_frozen():
            catalog = discover_embedded()
            modo = "Distribución (onefile)"
        else:
            modo = "Desarrollo"
            fs_catalog = build_catalog_dev(self.root_path)
            catalog: Dict[str, List[Item]] = {}
            for cat, files in fs_catalog.items():
                catalog[cat] = [
                    Item(label=(extract_display_name(f) or pretty_from_filename(f.name)),
                         category=cat, path=f, module_fqn=_guess_module_fqn_from_tools(f))
                    for f in files
                ]

        if catalog == self._catalog:
            total_scripts = sum(len(v) for v in catalog.values())
            self.status.set(f"Raíz: {self.root_path}   |   Modo: {modo}   |   {len(catalog)} categorías, {total_scripts} scripts")
            return

        self._catalog = catalog
        self._clear_tabs()

        for cat, items in catalog.items():
            frame = self._make_scrollable_tab()
            self._tabs[cat] = frame
            self.nb.add(frame, text=cat)
            if items:
                self._fill_scripts_list(frame.inner, items)
            else:
                ttk.Label(frame.inner, text="(No hay scripts en esta categoría)", style="Subtle.TLabel").pack(anchor="w", padx=12, pady=8)

        if selected_text and selected_text in self._tabs:
            idx = list(self._tabs.keys()).index(selected_text)
            try:
                self.nb.select(idx)
            except Exception:
                pass
        elif self._tabs:
            self.nb.select(0)

        total_scripts = sum(len(v) for v in catalog.values())
        self.status.set(f"Raíz: {self.root_path}   |   Modo: {modo}   |   {len(catalog)} categorías, {total_scripts} scripts")

    def _make_scrollable_tab(self):
        holder = ttk.Frame(self, style="TFrame")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)

        canvas = tk.Canvas(holder, highlightthickness=0, bd=0, bg=DARK_BG)
        vsb = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)

        inner = ttk.Frame(canvas, style="TFrame")
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        def on_canvas_configure(_event=None):
            canvas.itemconfigure(win, width=canvas.winfo_width())
        def on_frame_configure(_event=None):
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=bbox)

        canvas.bind("<Configure>", on_canvas_configure)
        inner.bind("<Configure>", on_frame_configure)

        holder.canvas = canvas
        holder.inner = inner
        return holder

    def _fill_scripts_list(self, parent: ttk.Frame, items: List[Item]):
        for it in items:
            btn = ttk.Button(parent, text=f"▶  {it.label}", style="TButton")
            btn.configure(command=lambda _it=it, b=btn: self._safe_launch(_it, b))
            btn.pack(fill="x", padx=10, pady=6)

    def _safe_launch(self, it: Item, button: ttk.Button | None):
        try:
            if button is not None:
                button.state(["disabled"])
            launch_item(it)
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            if button is not None:
                try:
                    self.after(1200, lambda: button.state(["!disabled"]))
                except Exception:
                    pass


# ===================== helpers =====================

def _guess_module_fqn_from_tools(path: Path) -> Optional[str]:
    try:
        full = path.resolve()
        tools_dir = (root_dir() / "tools").resolve()
        rel = full.relative_to(tools_dir)
        parts = list(rel.parts)
        if not parts:
            return None
        parts[-1] = Path(parts[-1]).stem
        return "tools." + ".".join(parts)
    except Exception:
        return None


# ===================== main =====================

def _parse_argv(argv: List[str]) -> Tuple[Optional[str], List[str]]:
    run_mod = None
    rest: List[str] = []
    it = iter(argv)
    for a in it:
        if a == "--run":
            try:
                run_mod = next(it)
            except StopIteration:
                run_mod = ""
        else:
            rest.append(a)
    return run_mod, rest


if __name__ == "__main__":
    run_mod, _ = _parse_argv(sys.argv[1:])
    if run_mod:
        code = run_embedded_module(run_mod)
        raise SystemExit(code)

    app = Launcher()
    app.mainloop()

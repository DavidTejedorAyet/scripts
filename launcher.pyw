#!/usr/bin/env python3
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lanzador de utilidades por categorías (Tkinter)
- Directorio raíz = carpeta donde está este archivo (no el cwd del sistema).
- Una pestaña (ttk.Notebook) por cada subcarpeta inmediata.
- En cada pestaña, un botón por cada .py dentro de esa subcarpeta.
- Cada script se ejecuta en su propio proceso (subprocess).
- Nombre del botón: __display_name__ si existe; si no, primera línea del docstring; si no, nombre de archivo.
"""

import os
import re
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.font import Font

# Configuración de tema oscuro
DARK_THEME = {
    "bg": "#1e1e1e",          # Fondo principal
    "bg_alt": "#252526",      # Fondo alternativo
    "fg": "#cccccc",          # Texto normal
    "fg_title": "#ffffff",    # Texto títulos
    "accent": "#007acc",      # Color de acento
    "button": "#323233",      # Fondo botón normal
    "button_hover": "#3e3e3e", # Fondo botón hover
    "border": "#3d3d3d"       # Color de bordes
}

APP_TITLE = "Mis utilidades"
PY_EXTS = (".py", ".pyw")
DISPLAY_NAME_RE = re.compile(r'^\s*__display_name__\s*=\s*[\'"](.+?)[\'"]\s*$', re.MULTILINE)

class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("940x560")
        self.minsize(820, 480)
        
        # Configurar tema oscuro
        self.configure(bg=DARK_THEME["bg"])
        self.style = ttk.Style(self)
        self.style.theme_use('clam')  # Usar clam como base para personalización
        
        # Configurar estilos
        self._setup_styles()
        
    def _setup_styles(self):
        """Configura los estilos de la interfaz"""
        # Fuentes
        self.font_normal = Font(family="Segoe UI", size=9)
        self.font_title = Font(family="Segoe UI", size=10, weight="bold")
        
        # Estilo general
        self.style.configure('.',
            background=DARK_THEME["bg"],
            foreground=DARK_THEME["fg"],
            font=self.font_normal)
        
        # Frame
        self.style.configure('TFrame',
            background=DARK_THEME["bg"])
            
        # Label
        self.style.configure('TLabel',
            background=DARK_THEME["bg"],
            foreground=DARK_THEME["fg"])
        
        self.style.configure('Title.TLabel',
            background=DARK_THEME["bg"],
            foreground=DARK_THEME["fg_title"],
            font=self.font_title)
        
        # Botón
        self.style.configure('TButton',
            background=DARK_THEME["button"],
            foreground=DARK_THEME["fg"],
            borderwidth=1,
            font=self.font_normal,
            padding=(10, 5))
            
        self.style.map('TButton',
            background=[("active", DARK_THEME["button_hover"])],
            foreground=[("active", DARK_THEME["fg_title"])])
        
        # Notebook
        self.style.configure('TNotebook',
            background=DARK_THEME["bg"],
            borderwidth=0)
            
        self.style.configure('TNotebook.Tab',
            background=DARK_THEME["button"],
            foreground=DARK_THEME["fg"],
            padding=(10, 5),
            font=self.font_normal)
            
        self.style.map('TNotebook.Tab',
            background=[("selected", DARK_THEME["bg_alt"])],
            foreground=[("selected", DARK_THEME["fg_title"])])
        
        # Scrollbar
        self.style.configure('TScrollbar',
            background=DARK_THEME["button"],
            troughcolor=DARK_THEME["bg"],
            borderwidth=0,
            arrowsize=0)
            
        self.style.map('TScrollbar',
            background=[("active", DARK_THEME["button_hover"])])
        
        # Inicializar variables
        self.root = os.path.abspath(os.path.dirname(__file__))
        self.folder_var = tk.StringVar(value=self.root)
        
        # Construir interfaz
        self._build_ui()
        
        # Cargar contenido
        self.populate()
    
    def _build_ui(self):
        # Barra superior
        top = ttk.Frame(self)
        top.pack(fill="x", padx=15, pady=15)
        
        # Título y ruta
        title_frame = ttk.Frame(top)
        title_frame.pack(side="left", fill="x", expand=True)
        
        ttk.Label(title_frame, text="Raíz:", style="Title.TLabel").pack(side="left")
        ttk.Label(title_frame, textvariable=self.folder_var).pack(side="left", padx=(8, 0))
        
        ttk.Button(top, text="↻ Refrescar", 
            command=self.populate).pack(side="right")
        ttk.Button(top, text="📂 Abrir", 
            command=self.open_root).pack(side="right", padx=5)
        
        # Notebook
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Barra de estado
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status).pack(
            fill="x", padx=10, pady=(0, 10))
    
    def populate(self):
        """Carga el contenido de las pestañas"""
        # Limpiar pestañas existentes
        for tab in self.nb.tabs():
            self.nb.forget(tab)
        
        # Buscar categorías
        total_scripts = 0
        for name in sorted(os.listdir(self.root)):
            if name.startswith(".") or name.startswith("_"):
                continue
                
            full_path = os.path.join(self.root, name)
            if not os.path.isdir(full_path):
                continue
            
            # Buscar scripts en la carpeta
            scripts = []
            for fname in os.listdir(full_path):
                if not any(fname.endswith(ext) for ext in PY_EXTS):
                    continue
                if fname == "__init__.py":
                    continue
                    
                script_path = os.path.join(full_path, fname)
                if os.path.isfile(script_path):
                    scripts.append(script_path)
            
            if not scripts:
                continue
            
            # Crear pestaña
            frame = ttk.Frame(self.nb)
            frame.grid_columnconfigure((0,1,2), weight=1)
            
            # Añadir botones
            row = col = 0
            for script in sorted(scripts):
                btn_text = os.path.splitext(os.path.basename(script))[0]
                
                # Frame contenedor para el botón
                btn_frame = ttk.Frame(frame)
                btn_frame.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
                
                btn = ttk.Button(btn_frame, text=btn_text,
                    command=lambda p=script: self.launch_script(p))
                btn.pack(expand=True, fill="both", padx=2, pady=2)
                
                col += 1
                if col > 2:
                    col = 0
                    row += 1
            
            self.nb.add(frame, text=name)
            total_scripts += len(scripts)
        
        if not self.nb.tabs():
            frame = ttk.Frame(self.nb)
            ttk.Label(frame, 
                text="No se encontraron categorías\nCrea subcarpetas con scripts Python",
                justify="center").pack(expand=True, pady=20)
            self.nb.add(frame, text="(Vacío)")
        
        self.status.set(f"{len(self.nb.tabs())} categorías, {total_scripts} scripts")
    
    def launch_script(self, path):
        """Ejecuta un script en proceso independiente"""
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            
            subprocess.Popen(
                [sys.executable, "-X", "utf8", path],
                cwd=os.path.dirname(path),
                creationflags=creationflags,
                close_fds=os.name != "nt"
            )
        except Exception as e:
            messagebox.showerror("Error",
                f"No se pudo ejecutar {os.path.basename(path)}:\n{e}")
    
    def open_root(self):
        """Abre la carpeta raíz"""
        try:
            if sys.platform.startswith("win"):
                os.startfile(self.root)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.root])
            else:
                subprocess.Popen(["xdg-open", self.root])
        except Exception as e:
            messagebox.showerror("Error",
                f"No se pudo abrir la carpeta:\n{e}")

if __name__ == "__main__":
    app = Launcher()
    app.mainloop()

import os
import re
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Any, Dict
import sys

class ThemeManager:
    """Gestor de temas para la aplicación"""
    DARK_THEME = {
        "window_bg": "#1e1e1e",
        "frame_bg": "#252526",
        "button_bg": "#333333",
        "button_fg": "#ffffff",
        "button_active_bg": "#404040",
        "text_primary": "#ffffff",
        "text_secondary": "#cccccc",
        "accent": "#007acc",
        "border": "#404040"
    }

    @classmethod
    def setup_theme(cls, root: tk.Tk) -> None:
        # Configurar tema oscuro
        style = ttk.Style(root)
        style.theme_use('clam')  # Usar 'clam' como base para personalización
        
        # Configurar estilos base
        root.configure(bg=cls.DARK_THEME["window_bg"])
        root.option_add("*Background", cls.DARK_THEME["window_bg"])
        root.option_add("*Foreground", cls.DARK_THEME["text_primary"])
        root.option_add("*selectBackground", cls.DARK_THEME["accent"])
        root.option_add("*selectForeground", cls.DARK_THEME["text_primary"])
        
        # Configurar ttk widgets
        style.configure('.',
            background=cls.DARK_THEME["window_bg"],
            foreground=cls.DARK_THEME["text_primary"],
            fieldbackground=cls.DARK_THEME["frame_bg"],
            troughcolor=cls.DARK_THEME["frame_bg"],
            selectbackground=cls.DARK_THEME["accent"],
            selectforeground=cls.DARK_THEME["text_primary"],
            borderwidth=1,
            relief=tk.FLAT)
        
        # Notebook
        style.configure('TNotebook',
            background=cls.DARK_THEME["window_bg"],
            borderwidth=0)
        style.configure('TNotebook.Tab',
            background=cls.DARK_THEME["button_bg"],
            foreground=cls.DARK_THEME["text_secondary"],
            padding=(10, 5),
            borderwidth=0)
        style.map('TNotebook.Tab',
            background=[("selected", cls.DARK_THEME["frame_bg"])],
            foreground=[("selected", cls.DARK_THEME["text_primary"])])
        
        # Botones
        style.configure('TButton',
            background=cls.DARK_THEME["button_bg"],
            foreground=cls.DARK_THEME["button_fg"],
            padding=(10, 5),
            borderwidth=1)
        style.map('TButton',
            background=[("active", cls.DARK_THEME["button_active_bg"])],
            foreground=[("active", cls.DARK_THEME["text_primary"])])
        
        # Labels
        style.configure('TLabel',
            background=cls.DARK_THEME["window_bg"],
            foreground=cls.DARK_THEME["text_primary"])
        
        # Frame
        style.configure('TFrame',
            background=cls.DARK_THEME["window_bg"])

class ToolTip:
    """Implementa tooltips para widgets de Tkinter."""
    def __init__(self, widget: Any, text: str, delay: int = 500, wrap_length: int = 180):
        self.widget = widget
        self.text = text
        self.delay = delay  # milisegundos antes de mostrar
        self.wrap_length = wrap_length
        self.id = None
        self.tw = None

        self.widget.bind('<Enter>', self.enter)
        self.widget.bind('<Leave>', self.leave)

    def enter(self, event=None) -> None:
        self.schedule()

    def leave(self, event=None) -> None:
        self.unschedule()
        self.hide()

    def schedule(self) -> None:
        self.unschedule()
        self.id = self.widget.after(self.delay, self.show)

    def unschedule(self) -> None:
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None

    def show(self) -> None:
        if self.tw:
            return

        # Coordenadas del widget
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25

        # Crear ventana tooltip
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        
        # Usar colores del tema
        label = ttk.Label(self.tw, text=self.text, justify='left',
                         background=ThemeManager.DARK_THEME["frame_bg"],
                         foreground=ThemeManager.DARK_THEME["text_primary"],
                         wraplength=self.wrap_length,
                         padding=(10, 6))
        label.pack()

        self.tw.wm_geometry(f"+{x}+{y}")

    def hide(self) -> None:
        if self.tw:
            self.tw.destroy()
            self.tw = None
from tkinter.font import Font

APP_TITLE = "Mis utilidades"

# Colores y estilos - Tema Oscuro
COLORS = {
    "primary": "#0d47a1",      # Azul oscuro
    "secondary": "#1e1e1e",   # Negro
    "bg": "#121212",         # Negro profundo
    "bg_light": "#1e1e1e",   # Negro más claro
    "button_bg": "#252525",  # Gris muy oscuro para botones
    "button_hover": "#2d2d2d", # Gris oscuro para hover
    "text": "#e0e0e0",       # Blanco suave
    "text_secondary": "#a0a0a0",  # Gris claro
    "accent": "#4d9eff",     # Azul claro para acentos
    "border": "#333333"      # Bordes sutiles
}
PY_EXTS = (".py", ".pyw")
DISPLAY_NAME_RE = re.compile(r'^\s*__display_name__\s*=\s*[\'"](.+?)[\'"]\s*$', re.MULTILINE)

def root_dir() -> str:
    # Carpeta donde está este launcher
    try:
        return os.path.abspath(os.path.dirname(__file__))
    except NameError:
        return os.path.abspath(os.getcwd())

def extract_display_name(path: str) -> str:
    """Devuelve nombre para mostrar a partir de __display_name__, docstring o filename."""
    filename = os.path.splitext(os.path.basename(path))[0]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(4096)
    except Exception:
        return filename

    m = DISPLAY_NAME_RE.search(head)
    if m:
        return m.group(1).strip()

    mdoc = re.search(r'^\s*(?:[rubfRUBF]{0,3})("""|\'\'\')([\s\S]*?)\1', head, re.MULTILINE)
    if mdoc:
        first_line = next((ln.strip() for ln in mdoc.group(2).splitlines() if ln.strip()), "")
        if first_line:
            return first_line
    return filename

def list_categories(root: str):
    """Lista subcarpetas inmediatas que contengan al menos un .py."""
    cats = []
    for name in sorted(os.listdir(root), key=str.lower):
        full = os.path.join(root, name)
        if not os.path.isdir(full):
            continue
        # Ignora carpetas 'ocultas' tipo .git, __pycache__, etc.
        if name.startswith('.') or name.startswith('_') or name.lower() in {"__pycache__"}:
            continue
        scripts = list_scripts_in_folder(full)
        cats.append((name, full, scripts))
    return cats

def list_scripts_in_folder(folder: str):
    """Lista scripts .py de la carpeta (no recursivo), excluyendo __init__ y el propio launcher si estuviera ahí."""
    items = []
    for name in sorted(os.listdir(folder), key=str.lower):
        if not any(name.lower().endswith(ext) for ext in PY_EXTS):
            continue
        if name.lower() in {"__init__.py"}:
            continue
        full = os.path.join(folder, name)
        if os.path.isfile(full):
            items.append(full)
    return items

def launch_script(path: str):
    """Ejecuta el script en un proceso independiente."""
    python = sys.executable or "python"
    cmd = [python, "-X", "utf8", path]
    creationflags = 0
    if os.name == "nt":
        try:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        except Exception:
            creationflags = 0
    try:
        subprocess.Popen(
            cmd,
            cwd=os.path.dirname(path) or None,
            creationflags=creationflags,
            close_fds=(os.name != "nt")
        )
    except Exception as e:
        messagebox.showerror("Error al ejecutar", f"No se pudo abrir {os.path.basename(path)}:\n{e}")

# ---------- UI ----------

class IconManager:
    """Gestiona los iconos de categorías usando emojis Unicode."""
    CATEGORY_ICONS = {
        "descargas": "💾",  # 💾
        "documentos": "📄",  # 📄
        "archivos": "📂",  # 📂
        "media": "🎥",  # 🎥
        "herramientas": "🔧",  # 🔧
        "red": "🌐",  # 🌐
        "configuración": "⚙️",  # ⚙️
        "otros": "📋",  # 📋
    }

    @classmethod
    def get_category_icon(cls, category_name: str) -> str:
        """Obtiene el icono para una categoría."""
        # Buscar por nombre exacto primero
        if category_name.lower() in cls.CATEGORY_ICONS:
            return cls.CATEGORY_ICONS[category_name.lower()]
        
        # Buscar por coincidencia parcial
        for key, icon in cls.CATEGORY_ICONS.items():
            if key in category_name.lower():
                return icon
        
        # Icono por defecto
        return cls.CATEGORY_ICONS["otros"]

class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        
        # Configuración inicial de la ventana
        self.title(APP_TITLE)
        self.geometry("940x560")
        self.minsize(820, 480)
        
        # Inicializar variables
        self.root = root_dir()
        self.folder_var = tk.StringVar(value=self.root)
        
        # Configurar tema oscuro
        ThemeManager.setup_theme(self)
        
        # Construir la interfaz
        self._build_ui()
        
        # Cargar contenido
        self.populate()

    def _make_scrollable_tab(self):
        """Crea un tab con área desplazable verticalmente."""
        # Crear frame principal
        frame = ttk.Frame(self.nb)
        
        # Crear canvas con scrollbar
        canvas = tk.Canvas(frame, highlightthickness=0)
        canvas.configure(bg=ThemeManager.DARK_THEME["window_bg"])
        
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        
        # Crear frame interior
        inner = ttk.Frame(canvas)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        
        # Configurar eventos de redimensionamiento
        def _on_configure(event=None):
            # Actualizar región de scroll
            canvas.configure(scrollregion=canvas.bbox("all"))
            # Ajustar ancho del contenido
            canvas.itemconfig(inner_id, width=canvas.winfo_width())
        
        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_configure)
        
        # Empaquetar widgets
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        
        return {"frame": frame, "canvas": canvas, "inner": inner}

    def open_root(self):
        """Abre la carpeta raíz en el explorador de archivos."""
        try:
            if sys.platform.startswith("win"):
                os.startfile(self.root)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.root])
            else:
                subprocess.Popen(["xdg-open", self.root])
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la carpeta:\n{e}")
        
    def _build_ui(self):
        # Panel superior
        top = ttk.Frame(self, padding=15)
        top.pack(fill="x", pady=(0, 10))
        
        # Título y controles
        title_frame = ttk.Frame(top)
        title_frame.pack(fill="x", expand=True)
        
        # Etiqueta Raíz
        ttk.Label(title_frame, text="Raíz:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(title_frame, textvariable=self.folder_var).grid(row=0, column=1, sticky="w", padx=8)
        
        # Botones de acción
        btn_frame = ttk.Frame(title_frame)
        btn_frame.grid(row=0, column=2, sticky="e")
        title_frame.grid_columnconfigure(2, weight=1)
        
        refresh_btn = ttk.Button(btn_frame, text="↻ Refrescar", command=self.populate)
        refresh_btn.pack(side="left", padx=5)
        ToolTip(refresh_btn, "Actualizar la lista de scripts")
        
        open_btn = ttk.Button(btn_frame, text="📂 Abrir carpeta", command=self.open_root)
        open_btn.pack(side="left", padx=5)
        ToolTip(open_btn, "Abrir la carpeta raíz en el explorador")
        
        # Notebook para pestañas
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(0,10))
        
        # Barra de estado
        self.status = tk.StringVar(value="")
        status_frame = ttk.Frame(self)
        status_frame.pack(fill="x", padx=10, pady=(0,10))
        ttk.Label(status_frame, textvariable=self.status).pack(side="left")
        
    def _setup_styles(self):
        """Configura los estilos de la aplicación"""
        style = ttk.Style(self)
        
        # Fuentes
        default_font = Font(family="Segoe UI", size=10)
        heading_font = Font(family="Segoe UI", size=11, weight="bold")
        
        # Estilo general
        style.configure(".", font=default_font)
        
        # Notebook (pestañas)
        style.configure("TNotebook", background=COLORS["bg"])
        style.configure("TNotebook.Tab", padding=(10, 5), font=default_font)
        style.map("TNotebook.Tab",
            background=[("selected", COLORS["primary"]), ("!selected", COLORS["secondary"])],
            foreground=[("selected", "white"), ("!selected", "white")])
        
        # Botones
        style.configure("TButton",
            padding=(10, 5),
            font=default_font,
            background=COLORS["primary"],
            foreground="white")
        
        style.map("TButton",
            background=[("active", COLORS["hover"])],
            foreground=[("active", "white")])
        
        # Etiquetas
        style.configure("TLabel", font=default_font)
        style.configure("Heading.TLabel", font=heading_font)
        
        # Frame
        style.configure("TFrame", background=COLORS["bg"])
        
        # Barra de estado
        style.configure("Status.TLabel",
            font=("Segoe UI", 9),
            foreground=COLORS["secondary"],
            background=COLORS["bg"])
        
        self.configure(bg=COLORS["bg"])
        self._build_ui()
        self.populate()

    def _build_ui(self):
        # Panel superior
        top = ttk.Frame(self, padding=15)
        top.pack(fill="x", pady=(0, 10))
        
        # Título y controles
        title_frame = ttk.Frame(top)
        title_frame.pack(fill="x", expand=True)
        
        # Etiqueta Raíz con estilo personalizado
        root_label = ttk.Label(title_frame, text="Raíz:", font=("Segoe UI", 10, "bold"))
        root_label.grid(row=0, column=0, sticky="w")
        
        # Etiqueta de ruta
        path_label = ttk.Label(title_frame, textvariable=self.folder_var)
        path_label.grid(row=0, column=1, sticky="w", padx=12)
        
        # Botones de acción
        btn_frame = ttk.Frame(title_frame, style="TFrame")
        btn_frame.grid(row=0, column=2, sticky="e")
        title_frame.grid_columnconfigure(2, weight=1)
        
        refresh_btn = ttk.Button(btn_frame, text="↻ Refrescar", command=self.populate)
        refresh_btn.pack(side="left", padx=5)
        ToolTip(refresh_btn, "Actualiza la lista de scripts disponibles")
        
        open_btn = ttk.Button(btn_frame, text="📂 Abrir carpeta", command=self.open_root)
        open_btn.pack(side="left", padx=5)
        ToolTip(open_btn, "Abre la carpeta raíz en el explorador de archivos")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(0,10))

        # Barra de estado mejorada
        status_frame = ttk.Frame(self, style="TFrame")
        status_frame.pack(fill="x", padx=10, pady=(0,10))
        
        # Contador de scripts
        self.status = tk.StringVar(value="")
        status_label = ttk.Label(status_frame, textvariable=self.status,
            style="Status.TLabel", anchor="w")
        status_label.pack(side="left")
        
        # Separador vertical
        ttk.Separator(status_frame, orient="vertical").pack(side="left", padx=10, fill="y")
        
        # Ruta actual
        path_status = ttk.Label(status_frame,
            text=f"Carpeta: {os.path.basename(self.root)}",
            style="Status.TLabel")
        path_status.pack(side="left")

    def open_root(self):
        try:
            if sys.platform.startswith("win"):
                os.startfile(self.root)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.root])
            else:
                subprocess.Popen(["xdg-open", self.root])
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la carpeta:\n{e}")

    def clear_tabs(self):
        for tab in self.nb.tabs():
            self.nb.forget(tab)

    def clear_tabs(self):
        """Elimina todas las pestañas existentes."""
        for tab in self.nb.tabs():
            self.nb.forget(tab)

    def populate(self):
        """Carga y muestra todas las categorías y scripts."""
        self.clear_tabs()
        cats = list_categories(self.root)
        total_scripts = 0

        if not cats:
            frame = ttk.Frame(self.nb)
            ttk.Label(frame, 
                text="No se encontraron categorías.\nCrea subcarpetas con scripts .py dentro.",
                anchor="center").pack(expand=True, fill="both", padx=16, pady=16)
            self.nb.add(frame, text="(Vacío)")
            self.status.set("0 categorías, 0 scripts.")
            return

        for cat_name, folder, scripts in cats:
            tab = self._make_scrollable_tab()
            if scripts:
                # Estilo personalizado para botones de script
                style = ttk.Style()
                style.configure("Script.TButton",
                    padding=(15, 10),
                    font=("Segoe UI", 10),
                    width=25)
                
                # Botones en grid con mejor espaciado
                max_cols = 3
                r = c = 0
                for script_path in scripts:
                    btn_text = extract_display_name(script_path)
                    
                    # Frame contenedor para el botón con efecto hover
                    btn_frame = ttk.Frame(tab["inner"], style="TFrame")
                    btn_frame.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")
                    
                    # Botón con estilo mejorado
                    btn = ttk.Button(btn_frame,
                        text=btn_text,
                        command=lambda p=script_path: launch_script(p))
                    btn.pack(expand=True, fill="both", padx=4, pady=4)
                    
                    # Tooltip con información del script
                    tooltip_text = f"Ruta: {os.path.relpath(script_path, self.root)}\n"
                    if script_path.lower().endswith('.pyw'):
                        tooltip_text += "Tipo: Script sin consola (pyw)"
                    else:
                        tooltip_text += "Tipo: Script Python (py)"
                    ToolTip(btn, tooltip_text)
                    
                    tab["inner"].grid_columnconfigure(c, weight=1)
                    tab["inner"].grid_rowconfigure(r, weight=1)
                    
                    c += 1
                    if c >= max_cols:
                        c = 0
                        r += 1
                total_scripts += len(scripts)
            else:
                ttk.Label(tab["inner"], text="(No hay scripts .py en esta categoría)").pack(padx=12, pady=12, anchor="w")

            # Agregar pestaña con icono
            icon = IconManager.get_category_icon(cat_name)
            self.nb.add(tab["frame"], text=f"{icon} {cat_name}")

        self.status.set(f"{len(cats)} categorías, {total_scripts} scripts.")

    def _make_scrollable_tab(self):
        """Crea un tab con área desplazable verticalmente."""
        frame = ttk.Frame(self.nb)
        canvas = tk.Canvas(frame, highlightthickness=0)
        canvas.configure(bg=ThemeManager.DARK_THEME["window_bg"])
        
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        
        inner = ttk.Frame(canvas)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        
        def _on_configure(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(inner_id, width=canvas.winfo_width())
        
        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_configure)
        
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        
        return {"frame": frame, "canvas": canvas, "inner": inner}

    def open_root(self):
        """Abre la carpeta raíz en el explorador de archivos."""
        try:
            if sys.platform.startswith("win"):
                os.startfile(self.root)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.root])
            else:
                subprocess.Popen(["xdg-open", self.root])
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la carpeta:\n{e}")

if __name__ == "__main__":
    app = Launcher()
    app.mainloop()

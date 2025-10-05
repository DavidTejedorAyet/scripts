#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Reubicar archivos multimedia

Cambios:
- Eliminado guardado de logs y función de “Deshacer”.
- Eliminada la UI de conflictos. Política fija: si hay colisión en destino -> se añade sufijo.
- Mantiene: overlay, alias YAML, progreso por bytes, limpieza de subcarpetas, nombres canónicos,
  prioridad del nombre de carpeta para películas salvo que el padre sea genérico (Torrent, Incoming, Descargas, …).
"""


from __future__ import annotations

import errno
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import unicodedata
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional, DefaultDict, Dict, Tuple
from collections import defaultdict

__display_name__ = "Reubicar archivos multimedia"

# ---------- Dependencias opcionales ----------
PTN = None
guessit = None
yaml = None
HAS_PTN = HAS_GUESSIT = HAS_YAML = False


def refresh_imports() -> None:
    global PTN, guessit, yaml, HAS_PTN, HAS_GUESSIT, HAS_YAML
    try:
        import PTN as _PTN  # type: ignore
        PTN = _PTN; HAS_PTN = True
    except Exception:
        PTN = None; HAS_PTN = False
    try:
        from guessit import guessit as _guessit  # type: ignore
        guessit = _guessit; HAS_GUESSIT = True
    except Exception:
        guessit = None; HAS_GUESSIT = False
    try:
        import yaml as _yaml  # PyYAML
        yaml = _yaml; HAS_YAML = True
    except Exception:
        yaml = None; HAS_YAML = False


refresh_imports()

# ---------- Config ----------
VIDEO_EXTS = (".avi", ".mkv", ".mp4", ".mov", ".wmv", ".flv")
COMPANION_EXTS = (".srt", ".sub", ".idx", ".nfo", ".jpg", ".jpeg", ".png", ".txt")
SAMPLE_PATTERNS = re.compile(r"(sample|trailer|\b(rarbg|yts|ettv|eztv)\b)", re.IGNORECASE)

INVALID_WIN_CHARS = r'<>:"/\\|?*'
INVALID_WIN_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}

# Carpetas genéricas que NUNCA deben borrarse y que no se usan como nombre de película
PROTECTED_DIRNAMES = {
    "torrent", "torrents",
    "incoming",
    "descargas", "descarga",
    "downloads", "download",
    "emule", "emule incoming",
}

FALLBACK_NUMBERED_TITLE = re.compile(
    r"""^\s*
        (?P<franchise>.+?)\s+(?P<num>\d{1,3})\s*[\-–—]\s*
        (?P<title>[^\[\(]+?)\s*(?:\[[^\]]*\]|\([^\)]*\))*\s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

SERIES_WITH_TITLE = [
    re.compile(r'^\s*(?P<title>.+?)[\s._\-]*S(?P<s>\d{1,2})E(?P<e>\d{1,3})\b', re.IGNORECASE),
    re.compile(r'^\s*(?P<title>.+?)[\s._\-]*(?P<s>\d{1,2})x(?P<e>\d{1,3})\b', re.IGNORECASE),
]
PATTERN_SxxEyy = re.compile(r'(?i)(?:^|[^A-Za-z0-9])S(?P<s>\d{1,2})E(?P<e>\d{1,3})(?:[^A-Za-z0-9]|$)')
PATTERN_NxM   = re.compile(r'(?i)(?:^|[^A-Za-z0-9])(?P<s>\d{1,2})x(?P<e>\d{1,3})(?:[^A-Za-z0-9]|$)')

RELEASE_KEYWORDS = {
    "hdtv","dvb","webrip","webdl","web-dl","hdrip","bdrip","brrip","bluray","bray","dvdrip","dvdscr","screener","remux",
    "xvid","divx","x264","x265","h264","h265","hevc","aac","ac3","dts","mp3","dual","multi","vose","vos","subs","sub","subesp",
    "castellano","esp","lat","eng","espanol","español","www","by","proper","repack","rip","digital","microhd","cam","ts","tc"
}
RESOLUTION_RE = re.compile(r"^\d{3,4}p$", re.IGNORECASE)

ALIAS_MAP: Dict[str, str] = {}
SHOW_CANON_MAP: Dict[str, str] = {}  # memoria de canónicos en runtime


# ---------- Utils ----------
_CAMEL_SPLIT_RE = re.compile(r'(?<=[a-z])(?=[A-Z])')

def decamel(s: str) -> str:
    return _CAMEL_SPLIT_RE.sub(' ', s)

def beautify_spaces(text: str) -> str:
    t = text.replace("_", " ").replace(".", " ")
    t = decamel(t)
    t = re.sub(r"\s*[-–—]\s*$", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

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

def strip_release_keywords(s: str) -> str:
    if not s:
        return ""
    tokens = re.split(r'[\s._\-\[\]\(\)]+', s)
    keep = []
    for tok in tokens:
        if not tok:
            continue
        tl = tok.lower()
        if tl in RELEASE_KEYWORDS or RESOLUTION_RE.match(tl) or tl.startswith("www") or tl.endswith(("com","net","org")):
            break
        keep.append(tok)
    return " ".join(keep)

def clean_episode_title(s: str) -> str:
    s = s or ""
    s = s.replace("_", " ").replace(".", " ")
    s = re.sub(r'^[\s.\-_:–—]+', '', s)
    s = re.sub(r'(?i)^(S?\s*\d{1,2}\s*[xE]\s*\d{1,3})(?:\s*[-_.])?\s*', '', s)
    s = re.sub(r'(?i)\s*(?:[-_.])?\s*(S?\s*\d{1,2}\s*[xE]\s*\d{1,3})\s*$', '', s)
    s = strip_release_tags(s)
    s = strip_release_keywords(s)
    s = beautify_spaces(s)
    return s

def ep_title_from_match(cleaned_stem: str, m: re.Match) -> str:
    return clean_episode_title(cleaned_stem[m.end():])

def _slug_noaccents(s: str) -> str:
    n = unicodedata.normalize("NFD", s)
    n = "".join(ch for ch in n if unicodedata.category(ch) != "Mn")
    n = n.lower()
    n = re.sub(r"[^a-z0-9]+", "", n)
    return n


# ---------- Alias loader ----------
def load_aliases() -> None:
    ALIAS_MAP.clear()
    candidates = []
    try:
        here = os.path.dirname(os.path.abspath(sys.argv[0]))
    except Exception:
        here = os.getcwd()
    candidates.append(os.path.join(here, "aliases.yml"))
    appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if appdata:
        candidates.append(os.path.join(appdata, "Relocator", "aliases.yml"))

    path = next((p for p in candidates if os.path.isfile(p)), None)
    if not path:
        return
    try:
        data = None
        if HAS_YAML and yaml is not None:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
    except Exception:
        return

    shows = data.get("shows") if isinstance(data, dict) else data
    if not isinstance(shows, dict):
        return

    def add_pair(canon: str, alias: str):
        key = _slug_noaccents(alias)
        if key:
            ALIAS_MAP[key] = canon

    for canon, spec in shows.items():
        canonical = sanitize_filename(beautify_spaces(str(canon)))
        if isinstance(spec, dict):
            aliases = spec.get("aliases", [])
        elif isinstance(spec, list):
            aliases = spec
        else:
            aliases = []
        add_pair(canonical, canonical)
        for al in aliases:
            add_pair(canonical, str(al))

load_aliases()

def canonicalize_show_title(candidate: str) -> str:
    cand = sanitize_filename(beautify_spaces(candidate or "")) or "Desconocido"
    key = _slug_noaccents(cand)
    if key in ALIAS_MAP:
        return ALIAS_MAP[key]
    prev = SHOW_CANON_MAP.get(key)
    if prev is None:
        SHOW_CANON_MAP[key] = cand
    else:
        has_accent_new = any(ord(c) > 127 for c in cand)
        has_accent_old = any(ord(c) > 127 for c in prev)
        if (has_accent_new and not has_accent_old) or (len(cand) > len(prev)):
            SHOW_CANON_MAP[key] = cand
    return SHOW_CANON_MAP[key]

def choose_show_title(*cands: Optional[str]) -> str:
    for c in cands:
        if c and c.strip():
            return canonicalize_show_title(c)
    return "Desconocido"


# ---------- Contexto por carpeta contenedora ----------
RE_SEASON_IN_DIR = re.compile(
    r'(?i)\b(?:temporada|season)\s*(?P<num>\d{1,2})\b|(?:^|\W)(?:s|t)\s*(?P<num2>\d{1,2})(?:\b|[^a-z0-9])'
)

def parent_dir(path: str) -> str:
    return os.path.basename(os.path.dirname(path)) if os.path.dirname(path) else ""

def _is_protected_dirname(name: str) -> bool:
    return name.strip().strip(". ").lower() in PROTECTED_DIRNAMES

def clean_folder_title(folder: str) -> str:
    if not folder:
        return ""
    s = beautify_spaces(strip_release_tags(folder))
    s = strip_release_keywords(s)
    return sanitize_filename(beautify_spaces(s))

def parse_parent_context(src_path: str) -> Dict[str, Optional[str]]:
    """
    Si el padre es una carpeta genérica (PROTECTED_DIRNAMES), NO usamos su nombre
    para titular películas ni para deducir serie/temporada.
    """
    folder = parent_dir(src_path)
    if _is_protected_dirname(folder):
        return {"folder": folder, "movie_title": None, "show_title": None, "season": None}

    cleaned = beautify_spaces(strip_release_tags(folder))
    cleaned_basic = clean_folder_title(folder)

    season = None
    m = RE_SEASON_IN_DIR.search(cleaned)
    if m:
        season = _safe_int(m.group("num") or m.group("num2"), None)

    show_title = None
    if season is not None:
        show_title = re.sub(r'(?i)\b(?:temporada|season)\s*\d{1,2}\b.*$', '', cleaned).strip(" -_.")
        show_title = re.sub(r'(?i)(?:^|\W)(?:s|t)\s*\d{1,2}.*$', '', show_title).strip(" -_.")
        show_title = clean_folder_title(show_title)

    movie_title = cleaned_basic

    return {
        "folder": folder,
        "movie_title": movie_title or None,
        "show_title": show_title or None,
        "season": season,
    }


# --- Helpers limpieza tras mover ---
def _dir_has_videos(path: str) -> bool:
    try:
        for r, _, files in os.walk(path):
            for f in files:
                if f.lower().endswith(VIDEO_EXTS):
                    return True
    except Exception:
        pass
    return False

def _cleanup_dirs_after_moves(
    plan: list["MediaItem"],
    source_roots: list[str],
    protected_names: Optional[set[str]] = None,
) -> Tuple[List[str], List[str]]:
    errs: list[str] = []
    deleted: list[str] = []
    if protected_names is None:
        protected_names = PROTECTED_DIRNAMES

    roots = [os.path.abspath(r).rstrip("\\/") for r in (source_roots or []) if r]
    candidates = {os.path.dirname(it.src_path) for it in plan if it and it.src_path}

    def _is_under(child: str, root: str) -> bool:
        c = os.path.abspath(child).rstrip("\\/")
        r = os.path.abspath(root).rstrip("\\/")
        return c.startswith(r + os.sep)

    for d in sorted(candidates, key=lambda p: len(os.path.abspath(p)), reverse=True):
        try:
            if not os.path.isdir(d):
                continue
            base = os.path.basename(os.path.normpath(d)).lower()
            if base in protected_names:
                continue
            if any(os.path.abspath(d).rstrip("\\/") == rt for rt in roots):
                continue
            if not any(_is_under(d, rt) for rt in roots):
                continue
            if _dir_has_videos(d):
                continue
            shutil.rmtree(d, ignore_errors=False)
            deleted.append(d)
        except Exception as ex:
            errs.append(f"No se pudo borrar la carpeta '{d}': {ex}")

    return errs, deleted


# ---------- Model ----------
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


# ---------- Análisis ----------
def analyze_media_in_sources(src_folders: List[str], dst_root: str) -> list[MediaItem]:
    items: list[MediaItem] = []
    for src_folder in src_folders:
        if not src_folder or not os.path.isdir(src_folder):
            continue
        for root_dir, dirs, files in os.walk(src_folder, topdown=True):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if fname.startswith("."):
                    continue
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

def guess_show_from_parent_dir(src_path: str) -> Optional[str]:
    parent = os.path.basename(os.path.dirname(src_path))
    if _is_protected_dirname(parent):
        return None
    parent = beautify_spaces(strip_release_tags(parent))
    m = re.search(r"^(?P<title>.+?)\s*-\s*Temporada\b", parent, flags=re.IGNORECASE)
    if m:
        return sanitize_filename(beautify_spaces(m.group("title")))
    parent = re.sub(r"\b(Temporada|Completa|DVDRip|HDTV|WEB[- ]?DL|BluRay)\b.*$", "", parent, flags=re.IGNORECASE).strip(" -")
    if parent:
        return sanitize_filename(parent)
    return None

def build_media_item(src_path: str, dst_root: str) -> Optional[MediaItem]:
    fname = os.path.basename(src_path)
    stem, ext = os.path.splitext(fname)
    ext = ext if ext else ".mkv"
    cleaned_stem = strip_release_tags(stem)

    # Contexto por carpeta
    ctx = parse_parent_context(src_path)
    folder_movie_title = ctx["movie_title"]  # será None si el padre es genérico
    folder_show_title = ctx["show_title"]
    folder_season = ctx["season"]

    # 1) "Franquicia 03 - Título" -> película numerada
    m_force = FALLBACK_NUMBERED_TITLE.match(cleaned_stem)
    if m_force:
        franchise = beautify_spaces(m_force.group("franchise"))
        num = _safe_int(m_force.group("num"), 1) or 1
        title_part = beautify_spaces(m_force.group("title"))
        final_title = sanitize_filename(f"{franchise} {num:02d} - {title_part}")
        dst_dir = os.path.join(dst_root, "Películas")
        dst_name = sanitize_filename(f"{final_title}{ext}")
        return MediaItem(src_path, "movie", None, None, None, dst_name, dst_dir, os.path.join(dst_dir, dst_name))

    # 2) Serie con título + SxxEyy / xxXyy en el archivo
    for rx in SERIES_WITH_TITLE:
        m = rx.match(cleaned_stem)
        if m:
            season = _safe_int(m.group("s"), 1) or 1
            episode = _safe_int(m.group("e"), 1) or 1
            raw_title = m.group("title") or ""
            raw_title = re.split(r"\bTemporada\b", raw_title, maxsplit=1, flags=re.IGNORECASE)[0]
            show_title = choose_show_title(raw_title, folder_show_title, guess_show_from_parent_dir(src_path), "Desconocido")
            ep_title = ep_title_from_match(cleaned_stem, m)
            ep_str = f"{season:02d}x{episode:02d}"
            dst_dir = os.path.join(dst_root, "Series", show_title, f"Temporada {season:02d}")
            base = f"{show_title} - {ep_str}" + (f" - {ep_title}" if ep_title else "")
            dst_name = sanitize_filename(f"{base}{ext}")
            return MediaItem(src_path, "series", show_title, season, [episode], dst_name, dst_dir, os.path.join(dst_dir, dst_name))

    # 3) Serie por patrones sin título explícito, usa carpeta si ayuda
    for rx in (PATTERN_SxxEyy, PATTERN_NxM):
        m = rx.search(cleaned_stem)
        if m:
            season = _safe_int(m.group("s"), 1) or folder_season or 1
            episode = _safe_int(m.group("e"), 1) or 1
            prefix = re.sub(r"[\s._\-]+$", "", cleaned_stem[: m.start()])
            show_title = choose_show_title(prefix, folder_show_title, guess_show_from_parent_dir(src_path), "Desconocido")
            ep_title = ep_title_from_match(cleaned_stem, m)
            ep_str = f"{season:02d}x{episode:02d}"
            dst_dir = os.path.join(dst_root, "Series", show_title, f"Temporada {season:02d}")
            base = f"{show_title} - {ep_str}" + (f" - {ep_title}" if ep_title else "")
            dst_name = sanitize_filename(f"{base}{ext}")
            return MediaItem(src_path, "series", show_title, season, [episode], dst_name, dst_dir, os.path.join(dst_dir, dst_name))

    # 4) Serie deducida por carpeta (Temporada X) y archivo numerado
    if folder_season is not None and folder_show_title:
        m = re.match(r'^\s*(?P<e>\d{1,3})(?:\s*[-_. ]\s*|)(?P<ttl>.*)$', cleaned_stem)
        if m:
            episode = _safe_int(m.group("e"), 1) or 1
            ep_title = clean_episode_title(m.group("ttl"))
            show_title = choose_show_title(folder_show_title, guess_show_from_parent_dir(src_path), "Desconocido")
            season = folder_season or 1
            ep_str = f"{season:02d}x{episode:02d}"
            dst_dir = os.path.join(dst_root, "Series", show_title, f"Temporada {season:02d}")
            base = f"{show_title} - {ep_str}" + (f" - {ep_title}" if ep_title else "")
            dst_name = sanitize_filename(f"{base}{ext}")
            return MediaItem(src_path, "series", show_title, season, [episode], dst_name, dst_dir, os.path.join(dst_dir, dst_name))

    # 5) PTN / guessit: PELÍCULA -> **preferir carpeta** si NO es protegida
    if HAS_PTN and PTN is not None:
        try:
            info = PTN.parse(fname) or {}
            title = info.get("title")
            season = info.get("season")
            episode = info.get("episode")
            if season is not None or episode is not None:
                tt = title or folder_show_title or cleaned_stem or "Desconocido"
                for rx in SERIES_WITH_TITLE:
                    mm = rx.match(tt)
                    if mm:
                        tt = mm.group("title"); break
                show_title = choose_show_title(tt, folder_show_title, guess_show_from_parent_dir(src_path), "Desconocido")
                season = _safe_int(season, folder_season or 1) or 1
                episode = _safe_int(episode, 1) or 1
                ep_title = clean_episode_title(info.get("episodeName") or info.get("episode_name") or info.get("episode_title") or "")
                if not ep_title:
                    m_any = PATTERN_SxxEyy.search(cleaned_stem) or PATTERN_NxM.search(cleaned_stem)
                    if m_any: ep_title = ep_title_from_match(cleaned_stem, m_any)
                ep_str = f"{season:02d}x{episode:02d}"
                dst_dir = os.path.join(dst_root, "Series", show_title, f"Temporada {season:02d}")
                base = f"{show_title} - {ep_str}" + (f" - {ep_title}" if ep_title else "")
                dst_name = sanitize_filename(f"{base}{ext}")
                return MediaItem(src_path, "series", show_title, season, [episode], dst_name, dst_dir, os.path.join(dst_dir, dst_name))
            # película por PTN -> usar carpeta si existe y no es protegida
            if title or folder_movie_title:
                movie_src = folder_movie_title or title or cleaned_stem or "Pelicula_Desconocida"
                movie = sanitize_filename(beautify_spaces(movie_src))
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
                show_title = info.get("title") or folder_show_title or cleaned_stem or "Desconocido"
                for rx in SERIES_WITH_TITLE:
                    mm = rx.match(show_title)
                    if mm:
                        show_title = mm.group("title"); break
                show_title = choose_show_title(show_title, folder_show_title, guess_show_from_parent_dir(src_path), "Desconocido")
                season = _safe_int(info.get("season", folder_season or 1), folder_season or 1) or 1
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
                ep_title = clean_episode_title(info.get("episode_title") or "")
                if not ep_title:
                    m_any = PATTERN_SxxEyy.search(cleaned_stem) or PATTERN_NxM.search(cleaned_stem)
                    if m_any: ep_title = ep_title_from_match(cleaned_stem, m_any)
                ep_str = f"{season:02d}x{eps[0]:02d}" if len(eps) == 1 else f"{season:02d}x{eps[0]:02d}-{eps[-1]:02d}"
                dst_dir = os.path.join(dst_root, "Series", show_title, f"Temporada {season:02d}")
                base = f"{show_title} - {ep_str}" + (f" - {ep_title}" if ep_title else "")
                dst_name = sanitize_filename(f"{base}{ext}")
                return MediaItem(src_path, "series", show_title, season, eps, dst_name, dst_dir, os.path.join(dst_dir, dst_name))
            # película por guessit -> usar carpeta si existe y no es protegida
            movie_src = folder_movie_title or info.get("title", cleaned_stem or "Pelicula_Desconocida")
            movie = sanitize_filename(beautify_spaces(movie_src))
            year = info.get("year")
            dst_dir = os.path.join(dst_root, "Películas")
            dst_name = sanitize_filename(f"{movie} ({year}){ext}" if year else f"{movie}{ext}")
            return MediaItem(src_path, "movie", None, None, None, dst_name, dst_dir, os.path.join(dst_dir, dst_name))
        except Exception:
            pass

    # 6) Película por carpeta (solo si no es protegida)
    if folder_movie_title:
        base = sanitize_filename(beautify_spaces(folder_movie_title))
        dst_dir = os.path.join(dst_root, "Películas")
        dst_name = f"{base}{ext}"
        return MediaItem(src_path, "movie", None, None, None, dst_name, dst_dir, os.path.join(dst_dir, dst_name))

    # 7) Fallback película por nombre de archivo limpio
    base = sanitize_filename(beautify_spaces(cleaned_stem) or "Pelicula_Desconocida")
    dst_dir = os.path.join(dst_root, "Películas")
    dst_name = f"{base}{ext}"
    return MediaItem(src_path, "movie", None, None, None, dst_name, dst_dir, os.path.join(dst_dir, dst_name))


# ---------- Movimiento + progreso ----------
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

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _suffix_path(dst: str, n: int) -> str:
    base, ext = os.path.splitext(dst)
    return f"{base} ({n}){ext}"

def move_path(src: str, dst: str, add_bytes: Callable[[int], None]) -> None:
    """Mueve/copias con progreso. Política fija: añadir sufijo si existe el destino."""
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    ensure_dir(os.path.dirname(dst))
    final_dst = dst
    i = 1
    while os.path.exists(final_dst):
        final_dst = _suffix_path(dst, i)
        i += 1

    src_sz = file_size(src)
    try:
        os.replace(src, final_dst)
        add_bytes(src_sz)
        return
    except OSError as ex:
        if ex.errno != errno.EXDEV:
            pass  # probamos copia manual

    with open(src, "rb") as fsrc, open(final_dst, "wb") as fdst:
        while True:
            buf = fsrc.read(1024 * 1024)
            if not buf:
                break
            fdst.write(buf)
            add_bytes(len(buf))
    try:
        shutil.copystat(src, final_dst)
    except Exception:
        pass
    try:
        os.remove(src)
    except Exception:
        pass

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
    source_roots: Optional[List[str]] = None,
) -> List[str]:
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
            move_video_and_companions(item, lambda n, lab=label: add_bytes(n, lab))
        except Exception as ex:
            errors.append(f"Error al mover '{item.src_path}' → '{item.dst_path}': {ex}")

    try:
        if source_roots:
            e2, _ = _cleanup_dirs_after_moves(plan, source_roots)
            errors.extend(e2)
    except Exception as ex:
        errors.append(f"Fallo en limpieza de carpetas: {ex}")

    return errors


# ---------- GUI ----------
class App(tk.Tk):
    ICON_CHECKED = "☑"
    ICON_UNCHECKED = "☐"
    ICON_PARTIAL = "◪"

    def __init__(self) -> None:
        super().__init__()
        self.title("Reubicar archivos multimedia")
        self.geometry("1100x780")

        self.dst_var = tk.StringVar(self, value=r"\\Nas\nas")
        self.plan: list[MediaItem] = []
        self.filter_var = tk.StringVar(self, value="")

        try:
            style = ttk.Style(self)
            style.configure("Warning.TFrame", background="#fff7e6")
        except Exception:
            pass

        self._build_ui()
        self._add_source(r"C:\Users\david\Downloads\Torrent")
        self._add_source(r"C:\Users\david\Downloads\eMule\Incoming")
        self._add_source(r"\\NAS\nas\Descargas")

    # ---------- UI ----------
    def _build_ui(self) -> None:
        # Banner dependencias
        self.deps_frame = ttk.Frame(self, style="Warning.TFrame")
        self.deps_frame.pack(fill="x", padx=10, pady=(10, 0))
        self.deps_label = ttk.Label(self.deps_frame, text="", justify="left")
        self.deps_label.pack(side="left", fill="x", expand=True)
        self.btn_install = ttk.Button(self.deps_frame, text="Instalar dependencias", command=self.on_install_deps)
        self.btn_install.pack(side="right")
        self._update_deps_banner()

        # Orígenes
        frm_sources = ttk.LabelFrame(self, text="Carpetas Origen")
        frm_sources.pack(fill="x", padx=10, pady=10)
        self.lb_sources = tk.Listbox(frm_sources, height=4, selectmode=tk.EXTENDED)
        self.lb_sources.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=8)
        btns_src = ttk.Frame(frm_sources); btns_src.pack(side="left", padx=5, pady=8)
        ttk.Button(btns_src, text="Añadir carpeta…", command=self.add_source_dialog).pack(fill="x", pady=2)
        ttk.Button(btns_src, text="Eliminar seleccionadas", command=self.remove_selected_sources).pack(fill="x", pady=2)

        # Destino
        frm_dest = ttk.Frame(self); frm_dest.pack(fill="x", padx=10, pady=5)
        ttk.Label(frm_dest, text="Carpeta Destino (NAS):").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm_dest, textvariable=self.dst_var, width=80).grid(row=0, column=1, sticky="we", padx=5)
        ttk.Button(frm_dest, text="Seleccionar", command=self.pick_dst).grid(row=0, column=2, padx=5)

        # Botones
        frm_buttons = ttk.Frame(self); frm_buttons.pack(fill="x", padx=10, pady=5)
        self.btn_analyze = ttk.Button(frm_buttons, text="Analizar", command=self.on_analyze)
        self.btn_analyze.pack(side="left", padx=5)
        self.btn_apply = ttk.Button(frm_buttons, text="Mover", command=self.on_apply, state="disabled")
        self.btn_apply.pack(side="left", padx=5)

        # Filtro
        frm_filter = ttk.Frame(self); frm_filter.pack(fill="x", padx=10, pady=(0,5))
        ttk.Label(frm_filter, text="Filtro:").pack(side="left")
        ent = ttk.Entry(frm_filter, textvariable=self.filter_var, width=40)
        ent.pack(side="left", padx=5)
        ttk.Button(frm_filter, text="Limpiar", command=lambda: (self.filter_var.set(""), self._populate_tree(self.plan))).pack(side="left")
        ent.bind("<KeyRelease>", lambda e: self._populate_tree(self.plan))

        # Árbol
        self.frm_tree = ttk.Frame(self)
        self.frm_tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree = ttk.Treeview(self.frm_tree, show="tree")
        self.tree.pack(fill="both", expand=True)

        # Estados del árbol
        self._init_tree_state()
        self.tree.bind("<Button-1>", self._on_tree_click)

        # Overlay (loader)
        self._init_overlay()

        # Progreso
        frm_progress = ttk.Frame(self); frm_progress.pack(fill="x", padx=10, pady=5)
        self.progress_var = tk.DoubleVar(self, value=0.0)
        self.progress_bar = ttk.Progressbar(frm_progress, variable=self.progress_var, mode="determinate")
        self.progress_bar.pack(fill="x", expand=True)
        self.status_var = tk.StringVar(self, value="Listo.")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10, pady=(0, 10))

    # ---------- Overlay ----------
    def _init_overlay(self) -> None:
        self.overlay = tk.Toplevel(self)
        self.overlay.withdraw()
        self.overlay.overrideredirect(True)
        self.overlay.transient(self)
        self._overlay_alpha_ok = True
        try:
            self.overlay.attributes("-alpha", 0.85)
        except Exception:
            self._overlay_alpha_ok = False
        try:
            self.overlay.attributes("-topmost", True)
            self.overlay.attributes("-topmost", False)
        except Exception:
            pass

        container = tk.Frame(self.overlay, bg="#202020" if self._overlay_alpha_ok else "#000000")
        container.pack(fill="both", expand=True)
        inner = tk.Frame(container, bg=container["bg"])
        inner.place(relx=0.5, rely=0.5, anchor="center")
        self.overlay_label = tk.Label(inner, text="Analizando...", fg="white", bg=container["bg"], font=("Segoe UI", 14, "bold"))
        self.overlay_label.pack(pady=(0, 8))
        self.overlay_bar = ttk.Progressbar(inner, mode="indeterminate", length=260)
        self.overlay_bar.pack()
        self.overlay_hint = tk.Label(inner, text="Esto puede tardar unos segundos…", fg="white", bg=container["bg"])
        self.overlay_hint.pack(pady=(8,0))

        self.bind("<Configure>", lambda e: self._position_overlay())
        self.frm_tree.bind("<Configure>", lambda e: self._position_overlay())
        self.tree.bind("<Configure>", lambda e: self._position_overlay())

    def _position_overlay(self) -> None:
        if not self._overlay_visible():
            return
        try:
            x = self.tree.winfo_rootx()
            y = self.tree.winfo_rooty()
            w = self.tree.winfo_width()
            h = self.tree.winfo_height()
            if w <= 1 or h <= 1:
                return
            self.overlay.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _overlay_visible(self) -> bool:
        try:
            return self.overlay.state() == "normal"
        except Exception:
            return False

    def _overlay_show(self, text: str = "Cargando…") -> None:
        self.overlay_label.configure(text=text)
        self.overlay.deiconify()
        self._position_overlay()
        try:
            self.overlay_bar.start(10)
        except Exception:
            pass
        self.config(cursor="watch")
        self.update_idletasks()

    def _overlay_hide(self) -> None:
        try:
            self.overlay_bar.stop()
        except Exception:
            pass
        try:
            self.overlay.withdraw()
        except Exception:
            pass
        self.config(cursor="")
        self.update_idletasks()

    # ---------- Helpers orígenes ----------
    def _add_source(self, path: str) -> None:
        if path and path not in self.lb_sources.get(0, tk.END):
            self.lb_sources.insert(tk.END, path)

    def add_source_dialog(self) -> None:
        p = filedialog.askdirectory()
        if p: self._add_source(p)

    def remove_selected_sources(self) -> None:
        for idx in sorted(self.lb_sources.curselection(), reverse=True):
            self.lb_sources.delete(idx)

    def get_sources(self) -> List[str]:
        return list(self.lb_sources.get(0, tk.END))

    # ---------- Dependencias ----------
    def _update_deps_banner(self) -> None:
        missing = []
        if not HAS_PTN: missing.append("parse-torrent-name (PTN)")
        if not HAS_GUESSIT: missing.append("guessit")
        if not HAS_YAML: missing.append("PyYAML (para aliases.yml)")
        if missing:
            msg = "⚠️ Faltan dependencias opcionales: " + ", ".join(missing) + "."
            self.deps_label.configure(text=msg, foreground="#b76e00")
            self.btn_install.configure(state="normal")
        else:
            self.deps_label.configure(text="✅ Dependencias opcionales instaladas.", foreground="#1a7f37")
            self.btn_install.configure(state="disabled")

    def on_install_deps(self) -> None:
        pkgs = []
        if not HAS_PTN: pkgs.append("parse-torrent-name")
        if not HAS_GUESSIT: pkgs.append("guessit")
        if not HAS_YAML: pkgs.append("PyYAML")
        if not pkgs:
            messagebox.showinfo("Dependencias", "Ya está todo instalado."); return

        win = tk.Toplevel(self); win.title("Instalando dependencias (pip)"); win.geometry("780x420")
        txt = tk.Text(win, wrap="word"); txt.pack(fill="both", expand=True)
        scr = ttk.Scrollbar(win, command=txt.yview); txt.configure(yscrollcommand=scr.set); scr.pack(side="right", fill="y")
        def append(line: str) -> None:
            txt.insert("end", line + "\n"); txt.see("end")
        self.btn_install.configure(state="disabled"); self._set_busy(True)
        append(f"Usando intérprete: {sys.executable}"); append("Actualizando pip/setuptools/wheel…")
        env = os.environ.copy(); env["PYTHONUTF8"] = "1"; env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")

        def run(cmd: list[str]) -> int:
            append("\n$ " + " ".join(cmd))
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1, universal_newlines=True, env=env)
                for line in iter(p.stdout.readline, ""):
                    self._ui(lambda l=line.rstrip(): append(l))
                p.stdout.close(); return p.wait()
            except Exception as ex:
                self._ui(lambda e=ex: append(f"❌ Excepción: {e}")); return 1

        def worker():
            base = [sys.executable, "-X", "utf8", "-m", "pip", "install", "--user", "-U"]
            run(base + ["pip","setuptools","wheel"])
            for pkg in pkgs:
                run(base + [pkg])
            def finish():
                refresh_imports(); load_aliases(); self._update_deps_banner(); self._set_busy(False); win.lift()
                messagebox.showinfo("Dependencias", "Proceso finalizado. Repite el análisis si procede.")
            self._ui(finish)
        threading.Thread(target=worker, daemon=True).start()

    # ---------- Acciones ----------
    def pick_dst(self) -> None:
        p = filedialog.askdirectory()
        if p: self.dst_var.set(p)

    def on_analyze(self) -> None:
        sources = self.get_sources(); dst = self.dst_var.get().strip()
        if not sources:
            messagebox.showerror("Error", "Añade al menos una carpeta de origen."); return
        if not dst:
            messagebox.showerror("Error", "Selecciona una carpeta de destino válida."); return

        self._set_busy(True); self.btn_apply.config(state="disabled")
        self._clear_tree(); self.status_var.set("Analizando...")
        self._overlay_show("Analizando biblioteca…")

        def worker():
            try:
                plan = analyze_media_in_sources(sources, dst)
            except Exception as ex:
                plan = []; self._ui(lambda m=f"Fallo al analizar: {ex}": messagebox.showerror("Error", m))
            def finish():
                self.plan = plan; self._populate_tree(plan)
                self._set_busy(False); self._overlay_hide()
                self.status_var.set(f"Análisis completado. Ítems: {len(plan)}")
            self._ui(finish)
        threading.Thread(target=worker, daemon=True).start()

    def on_apply(self) -> None:
        selected_plan = self.get_selected_items()
        if not selected_plan:
            messagebox.showerror("Error", "No hay elementos seleccionados para mover."); return

        total_bytes = compute_total_bytes(selected_plan)
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
                errors = perform_moves_bytes(
                    selected_plan, total_bytes, progress_cb=progress_cb,
                    source_roots=self.get_sources(),
                )
            except Exception as ex:
                errors = [f"Fallo general al mover: {ex}"]
            def finish():
                self._finish_after_apply(errors, total_bytes)
            self._ui(finish)
        threading.Thread(target=worker, daemon=True).start()

    def _finish_after_apply(self, errors: list[str], total_bytes: int) -> None:
        self._set_busy(False)
        if errors:
            messagebox.showerror("Resultado", "Completado con errores:\n" + "\n".join(errors))
            self.status_var.set(f"Terminado con errores. Total: {human_bytes(total_bytes)}")
        else:
            messagebox.showinfo("Resultado", "Completado.")
            self.status_var.set(f"Completado. Total: {human_bytes(total_bytes)}")
        self.btn_apply.config(state="disabled"); self._clear_tree(); self.plan = []; self.progress_var.set(0.0)

    # ---------- Árbol y checkboxes ----------
    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.btn_analyze.config(state=state)
        self.btn_apply.config(state=("disabled" if busy else self.btn_apply["state"]))
        self.btn_install.config(state=("disabled" if busy else self.btn_install["state"]))
        self.config(cursor="watch" if busy else ""); self.update_idletasks()

    def _ui(self, fn) -> None:
        self.after(0, fn)

    def _clear_tree(self) -> None:
        for i in self.tree.get_children():
            self.tree.delete(i)
        self._init_tree_state()

    def _init_tree_state(self):
        self.node_checked: dict[str, Optional[bool]] = {}
        self.node_kind: dict[str, str] = {}
        self.node_payload: dict[str, Optional[MediaItem]] = {}
        self.node_children: dict[str, list[str]] = {}
        self.node_parent: dict[str, Optional[str]] = {}

    def _icon(self, state: Optional[bool]) -> str:
        return "☑" if state is True else ("◪" if state is None else "☐")

    def _row_text(self, label: str, state: Optional[bool]) -> str:
        return f"{self._icon(state)}  {label}"

    def _strip_icon(self, text: str) -> str:
        return re.sub(r'^[☑☐◪]\s+', '', text)

    def _make_node(self, parent: str, label: str, checked: bool = True, kind: str = 'file', payload: Optional[MediaItem] = None) -> str:
        nid = self.tree.insert(parent, "end", text=self._row_text(label, checked), open=True)
        self.node_checked[nid] = checked; self.node_kind[nid] = kind
        self.node_payload[nid] = payload; self.node_children[nid] = []
        if parent:
            self.node_children[parent].append(nid); self.node_parent[nid] = parent
        else:
            self.node_parent[nid] = None
        return nid

    def _set_node_state(self, nid: str, state: Optional[bool]) -> None:
        self.node_checked[nid] = state
        label = self._strip_icon(self.tree.item(nid, "text"))
        self.tree.item(nid, text=self._row_text(label, state))

    def _set_descendants(self, nid: str, state_bool: bool) -> None:
        self._set_node_state(nid, state_bool)
        for ch in self.node_children.get(nid, []):
            self._set_descendants(ch, state_bool)

    def _recalc_ancestors(self, nid: str) -> None:
        parent = self.node_parent.get(nid)
        while parent:
            states = [self.node_checked[ch] for ch in self.node_children[parent]]
            if all(s is True for s in states):
                st: Optional[bool] = True
            elif all(s is False for s in states):
                st = False
            else:
                st = None
            self._set_node_state(parent, st)
            parent = self.node_parent.get(parent)

    def _toggle_node(self, nid: str, new_state: Optional[bool] = None) -> None:
        cur = self.node_checked.get(nid, True)
        if new_state is None:
            new_state = True if cur is None else (not cur)
        self._set_descendants(nid, bool(new_state))
        self._recalc_ancestors(nid)
        self.btn_apply.config(state=("normal" if self._has_any_leaf_selected() else "disabled"))

    def _on_tree_click(self, event):
        row = self.tree.identify_row(event.y)
        if not row: return
        col = self.tree.identify_column(event.x)
        elem = self.tree.identify("element", event.x, event.y) or ""
        if elem.endswith("indicator") or elem.endswith("button"):
            return  # permite colapsar/expandir
        if col == "#0":
            self._toggle_node(row)
            return "break"

    def _has_any_leaf_selected(self) -> bool:
        for nid, kind in self.node_kind.items():
            if kind == "file" and self.node_checked.get(nid) is True:
                return True
        return False

    def get_selected_items(self) -> List["MediaItem"]:
        out: List[MediaItem] = []
        for nid, kind in self.node_kind.items():
            if kind == "file" and self.node_checked.get(nid) is True:
                it = self.node_payload.get(nid)
                if it: out.append(it)
        return out

    def _current_selection_set(self) -> set:
        sel = set()
        for nid, kind in self.node_kind.items():
            if kind == "file" and self.node_checked.get(nid) is True:
                it = self.node_payload.get(nid)
                if it: sel.add(it.src_path)
        return sel

    def _populate_tree(self, plan: list["MediaItem"]) -> None:
        keep = self._current_selection_set()
        self._clear_tree()
        filt = self.filter_var.get().strip().lower()

        def pass_filter(label: str) -> bool:
            return (not filt) or (filt in label.lower())

        movies = [it for it in plan if it.content_type == "movie" and pass_filter(it.dst_filename)]
        series_map: DefaultDict[str, DefaultDict[int, List["MediaItem"]]] = defaultdict(lambda: defaultdict(list))
        for it in plan:
            if it.content_type == "series":
                if filt and not any(pass_filter(x) for x in [it.show_title or "", it.dst_filename, f"Temporada {it.season:02d}"]):
                    continue
                series_map[it.show_title or "Desconocido"][it.season or 1].append(it)

        if movies:
            n_movies = self._make_node("", f"Películas ({len(movies)})", checked=True, kind="movies")
            for it in sorted(movies, key=lambda x: x.dst_filename.lower()):
                self._make_node(n_movies, it.dst_filename, checked=(it.src_path in keep or not keep), kind="file", payload=it)

        if series_map:
            total_eps = sum(len(lst) for seas in series_map.values() for lst in seas.values())
            n_series = self._make_node("", f"Series ({total_eps} archivos)", checked=True, kind="series")
            for title in sorted(series_map.keys(), key=lambda s: s.lower()):
                n_title = self._make_node(n_series, title, checked=True, kind="show")
                for season in sorted(series_map[title].keys()):
                    n_seas = self._make_node(n_title, f"Temporada {season:02d}", checked=True, kind="season")
                    for it in sorted(series_map[title][season], key=lambda x: x.dst_filename.lower()):
                        checked = (it.src_path in keep) or (not keep)
                        self._make_node(n_seas, it.dst_filename, checked=checked, kind="file", payload=it)

        self.btn_apply.config(state=("normal" if self._has_any_leaf_selected() else "disabled"))


# ---------- Main ----------
def main() -> None:
    destination_folder = r"\\Nas\nas"
    if destination_folder and not os.path.isdir(destination_folder):
        try:
            os.makedirs(destination_folder, exist_ok=True)
        except Exception as e:
            print(f"No se pudo crear la carpeta destino {destination_folder}: {e}")
    app = App(); app.mainloop()


if __name__ == "__main__":
    main()

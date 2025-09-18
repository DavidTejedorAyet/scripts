# -*- coding: utf-8 -*-
"""
GUI para buscar y descargar .torrent desde una web dada.
- Modo "URL": si pegas una ficha (/pelicula/ o /serie/) extrae .torrent; si pegas una búsqueda (/buscar/...) lista resultados (con paginación) para elegir.
- Modo "Nombre": resuelve el proxy desde donproxies.com y hace la búsqueda -> lista resultados (con paginación) -> eliges uno -> extrae .torrent.
- Anti-bloqueo de /buscar: precalienta sesión con /tor y usa Referer adecuado.
- Resultados muestran: (icono) Tipo - Título (Año) - Calidad. Ej.: "🎬 Película - El gran dictador (1940) - BluRay-1080p"
- Lista de enlaces .torrent con checkboxes (marcados por defecto).
- Carpeta de destino por defecto: \\NAS\\nas\\Descargas\\.torrent
- Descarga con barra de progreso general.
- Log con timestamps y opción de guardar HTML (depuración) en una carpeta segura del usuario.
Requisitos: requests, beautifulsoup4
"""

__display_name__ = "Descargar .torrent (scrapping)"

import os
import re
import time
import threading
import queue
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urljoin, urlparse, quote
from urllib.parse import unquote as url_unquote

import requests
from bs4 import BeautifulSoup

# ------------------ Config HTTP ------------------ #

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

session = requests.Session()
session.headers.update(DEFAULT_HEADERS)

# ------------------ Utilidades ------------------ #

def _safe_basename_from_url(u: str) -> str:
    """Nombre de archivo limpio desde URL (sin querystring)."""
    path = urlparse(u).path
    name = os.path.basename(path)
    name = url_unquote(name)
    return name or "archivo.torrent"

def _get_debug_dir():
    """Carpeta segura de depuración en el HOME del usuario (evita problemas de permisos)."""
    home = os.path.expanduser("~")
    base = os.path.join(home, "torrent_scraper_debug")
    os.makedirs(base, exist_ok=True)
    return base

# ------------------ Scraping: .torrent en fichas ------------------ #

def extract_torrent_links(soup: BeautifulSoup, base_url: str):
    """
    Extrae enlaces .torrent de forma robusta:
    - <a> cuyo href termine en .torrent
    - <a> cuyo href contenga '/torrents/'
    - <a> con texto 'Descargar' cuyo href resuelva a .torrent
    - Tags con id/class que contengan 'download' o data-url/data-href a .torrent
    """
    links = set()

    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        txt = (a.get_text(strip=True) or "").lower()
        full = urljoin(base_url, href)
        if href.endswith(".torrent") or "/torrents/" in href:
            links.add(full)
            continue
        if txt == "descargar" and full.endswith(".torrent"):
            links.add(full)

    for tag in soup.select('[id*="download"],[class*="download"],[data-url],[data-href]'):
        candidate = tag.get("href") or tag.get("data-url") or tag.get("data-href")
        if candidate:
            full = urljoin(base_url, candidate.strip())
            if full.endswith(".torrent") or "/torrents/" in full:
                links.add(full)

    unique = []
    seen = set()
    for l in links:
        if l not in seen:
            unique.append(l)
            seen.add(l)
    return unique

def gather_torrent_links(url: str, log_cb=None, save_html_dir: str | None = None):
    """
    Carga una ficha y devuelve la lista de URLs .torrent presentes.
    (Repare NameError: esta función faltaba en la versión anterior).
    """
    soup, err = fetch_soup(url, log_cb=log_cb, save_html_dir=save_html_dir, tag="ficha", referer=None)
    if err or soup is None:
        return [], err or "No se pudo cargar la ficha"
    torrents = extract_torrent_links(soup, url)
    return torrents, None

# ------------------ Scraping: resultados de búsqueda ------------------ #

ONCLICK_URL_RE = re.compile(r"""location\.href\s*=\s*['"]([^'"]+)['"]""", re.I)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

QUALITY_HINTS = [
    "1080p", "2160p", "720p", "480p", "4k", "uhd", "hdr", "hdr10", "dolby",
    "bluray", "bdrip", "brrip", "microhd", "webrip", "web-dl", "webdl", "web",
    "hdtv", "dvdrip", "dvdr", "cam", "ts", "hdrip", "limitada", "remux"
]

def _derive_meta_from_anchor(a: BeautifulSoup):
    """
    Dada una <a> candidata, intenta derivar:
    - title_text: texto del enlace sin calidades [..]
    - type_label: 'Serie' / 'Película' si aparece en un badge del <p> contenedor
    - quality: texto entre paréntesis o [corchetes] cercano (e.g., (HDTV-720p) o [1080p])
    - year: año si aparece en el mismo <p> o en el propio texto
    """
    title_text_raw = a.get_text(" ", strip=True) or ""
    # quita [ ... ] del título
    title_text = re.sub(r"\s*\[[^\]]+\]\s*", " ", title_text_raw).strip()

    type_label = None
    quality = None
    year = None

    p = a.find_parent("p")
    if p:
        # badge "Serie"/"Película"
        for b in p.find_all("span", class_=re.compile("badge", re.I)):
            t = (b.get_text(strip=True) or "").strip()
            if t:
                type_label = t
                break
        # calidad en paréntesis o corchetes
        text_candidates = []
        for sp in p.find_all("span"):
            t = sp.get_text(" ", strip=True) or ""
            if t:
                text_candidates.append(t)
        text_candidates.append(title_text_raw)

        # busca quality: heurística -> frase que contenga hints típicos
        for t in text_candidates:
            # ( ... )
            m1 = re.search(r"\(([^)]+)\)", t)
            if m1 and any(h in m1.group(1).lower() for h in QUALITY_HINTS):
                quality = m1.group(1).strip()
                break
            # [ ... ]
            m2 = re.search(r"\[([^\]]+)\]", t)
            if m2 and any(h in m2.group(1).lower() for h in QUALITY_HINTS):
                quality = m2.group(1).strip()
                break

        # año
        joined = " ".join(text_candidates)
        ym = YEAR_RE.search(joined)
        if ym:
            year = ym.group(0)

    # fallback año/calidad en el propio título si no hubo <p>
    if year is None:
        ym = YEAR_RE.search(title_text_raw)
        if ym:
            year = ym.group(0)
    if quality is None:
        m2 = re.search(r"\[([^\]]+)\]", title_text_raw)
        if m2 and any(h in m2.group(1).lower() for h in QUALITY_HINTS):
            quality = m2.group(1).strip()

    return title_text, type_label, year, quality

def _format_display_title(title_text, type_label, year, quality, url: str):
    # icono por tipo o por URL
    icon = "📺" if (type_label and "serie" in type_label.lower()) or "/serie/" in url else "🎬"
    kind = ("Serie" if (type_label and "serie" in type_label.lower()) or "/serie/" in url else "Película")
    parts = [f"{icon} {kind} -", title_text]
    if year:
        parts.append(f"({year})")
    if quality:
        parts.append(f"- {quality}")
    return " ".join(parts)

def parse_search_results(soup: BeautifulSoup, base_url: str, log_cb=None):
    """
    Devuelve una lista de dicts:
      { 'display': str, 'url': str, 'title': str, 'type': 'Serie'|'Película'|None, 'year': str|None, 'quality': str|None }
    Heurísticas: patrón <p> con <a>, anchors genéricos, data-href/url, onclick, y fallback conservador.
    """
    items = []
    seen = set()
    scanned = 0
    r1 = r2 = r3 = r4 = r5 = 0

    # R1: patrón típico en <p> (tu ejemplo)
    for p in soup.find_all("p"):
        a = p.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if "/pelicula/" in href or "/serie/" in href:
            full = urljoin(base_url, href)
            title_text, type_label, year, quality = _derive_meta_from_anchor(a)
            display_title = _format_display_title(title_text, type_label, year, quality, full)
            if full not in seen:
                seen.add(full)
                kind = "Serie" if (type_label and "serie" in type_label.lower()) or "/serie/" in full else "Película"
                items.append({
                    "display": display_title,
                    "url": full,
                    "title": title_text,
                    "type": kind,
                    "year": year,
                    "quality": quality
                })
                r1 += 1

    # R2: anchors genéricos
    for a in soup.find_all("a", href=True):
        scanned += 1
        href = a["href"]
        if "/pelicula/" in href or "/serie/" in href:
            full = urljoin(base_url, href)
            if full in seen:
                continue
            title_text, type_label, year, quality = _derive_meta_from_anchor(a)
            display_title = _format_display_title(title_text, type_label, year, quality, full)
            seen.add(full)
            kind = "Serie" if (type_label and "serie" in type_label.lower()) or "/serie/" in full else "Película"
            items.append({
                "display": display_title,
                "url": full,
                "title": title_text,
                "type": kind,
                "year": year,
                "quality": quality
            })
            r2 += 1

    # R3: data-href / data-url
    for tag in soup.select("[data-href],[data-url]"):
        href = tag.get("data-href") or tag.get("data-url")
        if not href:
            continue
        if "/pelicula/" in href or "/serie/" in href:
            full = urljoin(base_url, href)
            if full in seen:
                continue
            t = tag.get_text(strip=True) or full
            # Intentar derivar meta con heurística mínima
            title_text, type_label, year, quality = (t, None, None, None)
            display_title = _format_display_title(title_text, type_label, year, quality, full)
            seen.add(full)
            kind = "Serie" if "/serie/" in full else "Película"
            items.append({
                "display": display_title,
                "url": full,
                "title": title_text,
                "type": kind,
                "year": year,
                "quality": quality
            })
            r3 += 1

    # R4: onclick location.href
    for tag in soup.find_all(onclick=True):
        oc = tag.get("onclick") or ""
        m = ONCLICK_URL_RE.search(oc)
        if not m:
            continue
        href = m.group(1)
        if "/pelicula/" in href or "/serie/" in href:
            full = urljoin(base_url, href)
            if full in seen:
                continue
            t = tag.get_text(strip=True) or full
            title_text, type_label, year, quality = (t, None, None, None)
            display_title = _format_display_title(title_text, type_label, year, quality, full)
            seen.add(full)
            kind = "Serie" if "/serie/" in full else "Película"
            items.append({
                "display": display_title,
                "url": full,
                "title": title_text,
                "type": kind,
                "year": year,
                "quality": quality
            })
            r4 += 1

    # R5: fallback conservador
    if not items:
        base_host = urlparse(base_url).netloc
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full = urljoin(base_url, href)
            host = urlparse(full).netloc
            if host != base_host:
                continue
            if any(seg in href for seg in ("/buscar/", "/torrents/", "/categoria/", "/genero/", "/page/", "/contacto", "/acerca", "/terminos")):
                continue
            if re.search(r"/\d{3,}/", href):
                if full in seen:
                    continue
                t = a.get_text(strip=True) or full
                title_text, type_label, year, quality = (t, None, None, None)
                display_title = _format_display_title(title_text, type_label, year, quality, full)
                seen.add(full)
                kind = "Serie" if "/serie/" in full else "Película"
                items.append({
                    "display": display_title,
                    "url": full,
                    "title": title_text,
                    "type": kind,
                    "year": year,
                    "quality": quality
                })
                r5 += 1

    if log_cb:
        log_cb(f"[parse_search_results] Inspeccionados={scanned} | R1={r1} R2={r2} R3={r3} R4={r4} R5={r5} | Total={len(items)}")
    return items

# ------------------ Paginación de /buscar/ ------------------ #

PAGE_NUM_RE = re.compile(r"/page/(\d+)", re.I)

def enumerate_search_pages(first_url: str, soup: BeautifulSoup, log_cb=None):
    """
    Devuelve la lista de URLs de páginas de búsqueda a visitar (incluyendo la primera),
    basándose en el 'page-navigator' y sus 'a.page-link'.
    """
    pages = set([first_url])
    nav = None

    for c in ["page-navigator", "pagination", "pager"]:
        nav = soup.find(class_=re.compile(c, re.I))
        if nav:
            break

    links = []
    if nav:
        candidates = nav.find_all("a", href=True)
        for a in candidates:
            cls = " ".join(a.get("class", [])) if a.has_attr("class") else ""
            if ("page-link" in cls) or True:
                href = a["href"]
                if href:
                    full = urljoin(first_url, href)
                    links.append(full)

    for u in links:
        pages.add(u)

    def page_key(u):
        m = PAGE_NUM_RE.search(u)
        return int(m.group(1)) if m else (0 if u.rstrip("/").endswith("/buscar") else 1)

    ordered = sorted(pages, key=page_key)
    if log_cb:
        log_cb(f"[PAGINATION] page-link detectados={len(links)} | páginas únicas={len(ordered)}")
        if len(ordered) > 1:
            log_cb("[PAGINATION] Páginas: " + " , ".join(ordered))
    return ordered

# ------------------ HTTP helpers (con Referer) ------------------ #

def fetch_soup(url: str, log_cb=None, save_html_dir: str | None = None, tag: str = "page", referer: str | None = None):
    try:
        if log_cb:
            log_cb(f"[HTTP] GET {url} {'(with Referer)' if referer else ''}")
        headers = {}
        if referer:
            headers["Referer"] = referer
        r = session.get(url, timeout=20, headers=headers, allow_redirects=True)
        if log_cb:
            log_cb(f"[HTTP] Status {r.status_code} ({len(r.content)} bytes) para {url}")
        # Guardado opcional
        if save_html_dir:
            try:
                base = _get_debug_dir()
                if save_html_dir:
                    base = os.path.join(base, os.path.basename(save_html_dir))
                os.makedirs(base, exist_ok=True)
                fname = os.path.join(base, f"debug_{tag}.html")
                with open(fname, "wb") as fh:
                    fh.write(r.content)
                if log_cb:
                    log_cb(f"[DEBUG] HTML guardado en: {fname}")
            except Exception as e:
                if log_cb:
                    log_cb(f"[WARN] No se pudo guardar HTML: {e}")
        if r.status_code != 200:
            return None, f"Error {r.status_code} al acceder a {url}"
        return BeautifulSoup(r.content, "html.parser"), None
    except Exception as e:
        if log_cb:
            log_cb(f"[ERROR] Excepción al solicitar {url}: {e}")
            log_cb(traceback.format_exc())
        return None, f"Error al acceder a {url}: {e}"

def warmup_tor(host: str, log_cb=None, save_html_dir: str | None = None):
    """Precalienta sesión visitando /tor para que el buscador acepte /buscar/."""
    tor_url = f"https://{host}/tor"
    soup, err = fetch_soup(tor_url, log_cb=log_cb, save_html_dir=save_html_dir, tag="warmup_tor", referer=None)
    if log_cb:
        log_cb(f"[WARMUP] /tor -> {'OK' if not err else err or 'error'}")
    return err is None

def page_contains_use_search_message(soup: BeautifulSoup) -> bool:
    """Detecta la página de bloqueo 'Necesitas utilizar el buscador.'"""
    txt = soup.get_text(" ", strip=True).lower()
    return "necesitas utilizar el buscador" in txt

def collect_search_results_from_url(search_url: str, log_cb=None, save_html_dir: str | None = None, force_host: str | None = None):
    """
    Carga la URL de búsqueda (y sus páginas) y agrega todos los resultados.
    Incluye lógica anti-bloqueo: reintenta con Referer /tor si detecta bloqueo.
    Devuelve lista de dicts (ver parse_search_results).
    """
    # Primer intento directo
    soup, err = fetch_soup(search_url, log_cb=log_cb, save_html_dir=save_html_dir, tag="busqueda_p1", referer=None)
    if err or soup is None:
        return None, err or "No se pudo cargar la búsqueda"

    host = force_host or urlparse(search_url).netloc
    referer = f"https://{host}/tor"

    # ¿Bloqueo?
    if page_contains_use_search_message(soup):
        if log_cb:
            log_cb("[ANTI-BLOCK] Detectado mensaje 'Necesitas utilizar el buscador.' -> precalentar y reintentar con Referer.")
        warmup_tor(host, log_cb=log_cb, save_html_dir=save_html_dir)
        soup, err = fetch_soup(search_url, log_cb=log_cb, save_html_dir=save_html_dir, tag="busqueda_p1_retry", referer=referer)
        if err or soup is None:
            return None, err or "Búsqueda bloqueada (tras reintento con Referer)."

    pages = enumerate_search_pages(search_url, soup, log_cb=log_cb)

    all_results = []
    seen = set()

    def add_results(res):
        for item in res:
            url = item["url"]
            if url not in seen:
                seen.add(url)
                all_results.append(item)

    # página 1
    res1 = parse_search_results(soup, base_url=search_url, log_cb=log_cb)
    add_results(res1)

    # resto de páginas
    for idx, page_url in enumerate(pages[1:], start=2):
        soup_i, err_i = fetch_soup(page_url, log_cb=log_cb, save_html_dir=save_html_dir, tag=f"busqueda_p{idx}", referer=referer)
        if err_i or soup_i is None:
            if log_cb:
                log_cb(f"[PAGINATION][WARN] No se pudo cargar {page_url}: {err_i}")
            continue
        if page_contains_use_search_message(soup_i):
            if log_cb:
                log_cb(f"[ANTI-BLOCK] Página {page_url} mostró el bloqueo; reintento con Referer tras warmup.")
            warmup_tor(host, log_cb=log_cb, save_html_dir=save_html_dir)
            soup_i, err_i = fetch_soup(page_url, log_cb=log_cb, save_html_dir=save_html_dir, tag=f"busqueda_p{idx}_retry", referer=referer)
            if err_i or soup_i is None:
                if log_cb:
                    log_cb(f"[PAGINATION][WARN] {page_url} sigue bloqueada.")
                continue
        res_i = parse_search_results(soup_i, base_url=page_url, log_cb=log_cb)
        add_results(res_i)

    if log_cb:
        log_cb(f"[PAGINATION] Total resultados agregados: {len(all_results)}")
    return all_results, None

# ------------------ Resolver proxy + búsqueda por nombre ------------------ #

def resolve_proxy_host(log_cb=None, save_html_dir: str | None = None):
    """
    Obtiene el host del proxy desde https://donproxies.com/#proxy
    Heurísticas:
      1) Anchor cuyo texto contenga 'Ingresar' y 'Proxy' (o 'Prxy').
      2) Anchors a dominios con '.mirror.' o '-don.'.
      3) URLs en <script> con esos patrones.
    """
    url = "https://donproxies.com/#proxy"
    soup, err = fetch_soup(url, log_cb=log_cb, save_html_dir=save_html_dir, tag="donproxies_hash")
    if err or soup is None:
        if log_cb:
            log_cb(f"[WARN] No se pudo cargar con hash: {err}. Reintentando sin hash…")
        soup, err = fetch_soup("https://donproxies.com/", log_cb=log_cb, save_html_dir=save_html_dir, tag="donproxies")
        if soup is None:
            return None, err or "No se pudo acceder a donproxies.com"

    for a in soup.find_all("a", href=True):
        txt = (a.get_text(" ", strip=True) or "").lower()
        if ("ingresar" in txt and "proxy" in txt) or ("ingresar" in txt and "prxy" in txt):
            href = a["href"]
            if href.startswith("http"):
                host = urlparse(href).netloc
                if host:
                    if log_cb:
                        log_cb(f"[RESOLVE] Host por anchor ‘Ingresar…’: {host}")
                    return host, None

    pattern = re.compile(r"https?://([^/\s]+)")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = pattern.match(href)
        if m:
            host = urlparse(href).netloc
            if (".mirror." in host) or ("-don." in host):
                if log_cb:
                    log_cb(f"[RESOLVE] Host por anchor mirror: {host}")
                return host, None

    for sc in soup.find_all("script"):
        text = sc.string or sc.get_text() or ""
        for m in re.finditer(r"https?://([^/\s\"']+)", text):
            host = m.group(1)
            if (".mirror." in host) or ("-don." in host):
                if log_cb:
                    log_cb(f"[RESOLVE] Host por script: {host}")
                return host, None

    return None, "No se pudo resolver un proxy válido desde donproxies.com (¿contenido dinámico por JS?)"

def search_by_name(query: str, manual_host: str | None, log_cb=None, save_html_dir: str | None = None):
    """
    Si manual_host está definido, se usa directamente.
    Si no, resuelve el proxy y realiza la búsqueda con paginación y anti-bloqueo.
    Devuelve lista de dicts (ver parse_search_results).
    """
    if manual_host:
        host = manual_host.strip().replace("https://", "").replace("http://", "").rstrip("/")
        if log_cb:
            log_cb(f"[SEARCH] Usando host manual: {host}")
    else:
        host, err = resolve_proxy_host(log_cb=log_cb, save_html_dir=save_html_dir)
        if err:
            return None, err

    warmup_tor(host, log_cb=log_cb, save_html_dir=save_html_dir)
    first_url = f"https://{host}/buscar/{quote(query, safe='')}"
    return collect_search_results_from_url(first_url, log_cb=log_cb, save_html_dir=save_html_dir, force_host=host)

# ------------------ Descarga ------------------ #

def download_file(url: str, dest_folder: str, progress_cb=None):
    """Descarga un archivo a dest_folder. No abre el fichero al terminar."""
    os.makedirs(dest_folder, exist_ok=True)
    filename = os.path.join(dest_folder, _safe_basename_from_url(url))
    try:
        r = session.get(url, stream=True, timeout=30)
        if r.status_code != 200:
            return False, f"Error {r.status_code} al descargar: {url}"
        total = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        with open(filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total:
                        progress_cb(downloaded, total)
    except Exception as e:
        return False, f"Error al descargar {url}: {e}"
    return True, filename

# ------------------ UI: widgets auxiliares ------------------ #

class ScrollableCheckFrame(ttk.Frame):
    """Lista con checkboxes y scroll (para enlaces .torrent)."""
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.inner = ttk.Frame(self.canvas)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.vars = []   # Lista[tk.BooleanVar]
        self.labels = [] # Lista de textos (urls)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.vars.clear()
        self.labels.clear()

    def add_item(self, text, checked=True):
        var = tk.BooleanVar(value=checked)
        cb = ttk.Checkbutton(self.inner, text=text, variable=var)
        cb.pack(fill="x", padx=6, pady=2, anchor="w")
        self.vars.append(var)
        self.labels.append(text)

    def get_checked_items(self):
        return [t for v, t in zip(self.vars, self.labels) if v.get()]

    def select_all(self, value=True):
        for v in self.vars:
            v.set(value)

# ------------------ App ------------------ #

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Buscador/Descargador de Torrents")
        self.geometry("1000x780")
        self.minsize(880, 700)

        # Estado
        self.dest_folder = r"\\NAS\nas\Descargas\.torrent"

        # Variables UI
        self.mode_var = tk.StringVar(value="name")  # "url" | "name"
        self.input_var = tk.StringVar(value="")
        self.manual_proxy_var = tk.StringVar(value="")  # opcional
        self.save_html_var = tk.BooleanVar(value=False)  # guardar HTML de depuración
        self.status_var = tk.StringVar(value="Listo.")
        self.total_var = tk.IntVar(value=0)
        self.done_var = tk.IntVar(value=0)

        # Resultados de búsqueda (cada item es dict con keys: display, url, title, type, year, quality)
        self.search_results = []

        # Spinner / “cargando…”
        self._spinner_running = False
        self._spinner_job = None
        self._spinner_idx = 0
        self._spinner_text = "Cargando"
        self._spinner_frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

        # Layout
        self._build_topbar()
        self._build_search_results()
        self._build_torrent_list()
        self._build_actions()
        self._build_progress()
        self._build_log_panel()

    # ---------- Logging ---------- #

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        try:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except Exception:
            pass
        print(line, end="")

    # ---------- Spinner / Loading ---------- #

    def _spin_tick(self):
        if not self._spinner_running:
            return
        ch = self._spinner_frames[self._spinner_idx % len(self._spinner_frames)]
        self._spinner_idx += 1
        self.status_var.set(f"{self._spinner_text} {ch}")
        self._spinner_job = self.after(100, self._spin_tick)

    def start_loading(self, text="Cargando…"):
        self._spinner_text = text
        self._spinner_running = True
        self._spinner_idx = 0
        try:
            self.progress.configure(mode="indeterminate")
            self.progress.start(30)
        except Exception:
            pass
        self._spin_tick()

    def stop_loading(self, final_text="Listo."):
        self._spinner_running = False
        try:
            if self._spinner_job:
                self.after_cancel(self._spinner_job)
                self._spinner_job = None
        except Exception:
            pass
        try:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
        except Exception:
            pass
        self.status_var.set(final_text)

    # ---------- Secciones UI ---------- #

    def _build_topbar(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="x")

        rb1 = ttk.Radiobutton(frm, text="Buscar por URL", variable=self.mode_var, value="url")
        rb2 = ttk.Radiobutton(frm, text="Buscar por nombre", variable=self.mode_var, value="name")
        rb1.grid(row=0, column=0, sticky="w", padx=(0, 12))
        rb2.grid(row=0, column=1, sticky="w")

        ttk.Label(frm, text="Entrada:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        entry = ttk.Entry(frm, textvariable=self.input_var)
        entry.grid(row=1, column=1, sticky="ew", padx=6, pady=(8, 0))
        frm.grid_columnconfigure(1, weight=1)

        ttk.Label(frm, text="Proxy manual (host opcional):").grid(row=2, column=0, sticky="w", pady=(8, 0))
        proxy_entry = ttk.Entry(frm, textvariable=self.manual_proxy_var)
        proxy_entry.grid(row=2, column=1, sticky="ew", padx=6, pady=(8, 0))

        self.search_btn = ttk.Button(frm, text="Buscar", command=self.on_search)
        self.search_btn.grid(row=1, column=2, padx=6, pady=(8, 0))

        self.dest_btn = ttk.Button(frm, text="Elegir carpeta…", command=self.on_choose_dest)
        self.dest_btn.grid(row=1, column=3, padx=6, pady=(8, 0))

        self.save_html_cb = ttk.Checkbutton(frm, text="Guardar HTML (depuración)", variable=self.save_html_var)
        self.save_html_cb.grid(row=2, column=2, padx=6, pady=(8, 0), sticky="w")

        self.dest_lbl = ttk.Label(frm, text=f"Destino: {self.dest_folder}")
        self.dest_lbl.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _build_search_results(self):
        frm = ttk.LabelFrame(self, text="Resultados de búsqueda", padding=6)
        frm.pack(fill="both", expand=False, padx=10, pady=(6, 0))

        self.results_list = tk.Listbox(frm, height=10)
        self.results_list.pack(side="left", fill="both", expand=True)
        self.results_list.bind("<Double-Button-1>", lambda e: self.on_open_selected_result())

        sb = ttk.Scrollbar(frm, orient="vertical", command=self.results_list.yview)
        sb.pack(side="right", fill="y")
        self.results_list.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 6))
        self.open_result_btn = ttk.Button(btns, text="Cargar selección", command=self.on_open_selected_result, state="disabled")
        self.open_result_btn.pack(side="left")
        self.clear_results_btn = ttk.Button(btns, text="Limpiar resultados", command=self.clear_search_results, state="disabled")
        self.clear_results_btn.pack(side="left", padx=6)

    def _build_torrent_list(self):
        frm = ttk.LabelFrame(self, text="Enlaces .torrent encontrados", padding=6)
        frm.pack(fill="both", expand=True, padx=10, pady=6)
        self.list_frame = ScrollableCheckFrame(frm)
        self.list_frame.pack(fill="both", expand=True)

    def _build_actions(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="x")
        self.sel_all_btn = ttk.Button(frm, text="Seleccionar todo", command=lambda: self.list_frame.select_all(True), state="disabled")
        self.sel_all_btn.pack(side="left")
        self.sel_none_btn = ttk.Button(frm, text="Deseleccionar todo", command=lambda: self.list_frame.select_all(False), state="disabled")
        self.sel_none_btn.pack(side="left", padx=6)

        self.download_btn = ttk.Button(frm, text="Descargar seleccionados", command=self.on_download, state="disabled")
        self.download_btn.pack(side="right")

    def _build_progress(self):
        frm = ttk.Frame(self, padding=(10, 0, 10, 6))
        frm.pack(fill="x")
        self.progress = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.progress.pack(fill="x", expand=True, side="left")
        self.status = ttk.Label(frm, textvariable=self.status_var)
        self.status.pack(side="left", padx=10)

    def _build_log_panel(self):
        frm = ttk.LabelFrame(self, text="Log", padding=6)
        frm.pack(fill="both", expand=False, padx=10, pady=(0, 10))

        self.log_text = tk.Text(frm, height=10, state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(frm, orient="vertical", command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Copiar log", command=self.copy_log).pack(side="left")
        ttk.Button(btns, text="Limpiar log", command=self.clear_log).pack(side="left", padx=6)

    # ---------- Helpers UI ---------- #

    def enable_torrent_actions(self, enabled: bool):
        self.sel_all_btn.configure(state="normal" if enabled else "disabled")
        self.sel_none_btn.configure(state="normal" if enabled else "disabled")
        self.download_btn.configure(state="normal" if enabled else "disabled")

    def show_torrents(self, links):
        self.list_frame.clear()
        if links:
            for l in links:
                self.list_frame.add_item(l, checked=True)
            self.enable_torrent_actions(True)
            self.status_var.set(f"Encontrados {len(links)} enlaces .torrent.")
            self.log(f"[OK] .torrent encontrados: {len(links)}")
        else:
            self.enable_torrent_actions(False)
            self.status_var.set("No se encontraron enlaces .torrent.")
            self.log("[WARN] No se encontraron enlaces .torrent en la página cargada.")

    def populate_search_results(self, results):
        self.results_list.delete(0, tk.END)
        self.search_results = results[:]  # copia (lista de dicts)
        for item in results:
            self.results_list.insert(tk.END, item["display"])
        has = len(results) > 0
        self.open_result_btn.configure(state="normal" if has else "disabled")
        self.clear_results_btn.configure(state="normal" if has else "disabled")
        self.log(f"[RESULT] Items en la lista: {len(results)}")

    def clear_search_results(self):
        self.results_list.delete(0, tk.END)
        self.search_results.clear()
        self.open_result_btn.configure(state="disabled")
        self.clear_results_btn.configure(state="disabled")
        self.log("[UI] Resultados limpiados.")

    def copy_log(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.log_text.get("1.0", "end"))
            self.log("[UI] Log copiado al portapapeles.")
        except Exception as e:
            messagebox.showwarning("Error", f"No se pudo copiar el log: {e}")

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.log("[UI] Log borrado.")

    # ---------- Handlers ---------- #

    def on_choose_dest(self):
        folder = filedialog.askdirectory(initialdir=self.dest_folder, title="Elige carpeta de destino")
        if folder:
            self.dest_folder = folder
            self.dest_lbl.configure(text=f"Destino: {self.dest_folder}")
            self.log(f"[UI] Carpeta de destino cambiada a: {self.dest_folder}")

    def on_search(self):
        text = self.input_var.get().strip()
        if not text:
            messagebox.showwarning("Falta entrada", "Introduce una URL o un nombre.")
            return

        self.start_loading("Buscando")
        self.enable_torrent_actions(False)
        self.list_frame.clear()

        mode = self.mode_var.get()
        manual_host = self.manual_proxy_var.get().strip() or None
        save_dir = "debug_html" if self.save_html_var.get() else None

        self.log(f"[SEARCH] Modo: {mode} | Entrada: {text!r} | Proxy manual: {manual_host or '-'} | Guardar HTML: {bool(save_dir)}")

        def worker():
            try:
                if mode == "url":
                    if "/buscar/" in text:
                        host = urlparse(text).netloc
                        warmup_tor(host, log_cb=self.log, save_html_dir=save_dir)
                        results, err = collect_search_results_from_url(text, log_cb=self.log, save_html_dir=save_dir, force_host=host)
                        if err:
                            self.after(0, lambda s=err: messagebox.showerror("Error", s))
                            self.after(0, lambda: self.stop_loading("Error en la búsqueda (URL)."))
                            return
                        self.after(0, lambda r=results: self.populate_search_results(r))
                        self.after(0, lambda: self.stop_loading(f"{len(results)} resultados. Elige uno y pulsa 'Cargar selección'."))
                        return

                    # Si es ficha -> extraer torrents directamente
                    links, err = gather_torrent_links(text, log_cb=self.log, save_html_dir=save_dir)
                    if err:
                        self.after(0, lambda s=err: self.log(f"[WARN] {s}"))
                        self.after(0, lambda s=err: messagebox.showinfo("Aviso", s))
                    self.after(0, lambda l=links: self.show_torrents(l))
                    self.after(0, lambda: self.stop_loading("Listo."))

                else:  # mode == "name"
                    results, err = search_by_name(text, manual_host, log_cb=self.log, save_html_dir=save_dir)
                    if err:
                        self.after(0, lambda s=err: self.log(f"[ERROR] Búsqueda por nombre falló: {s}"))
                        self.after(0, lambda s=err: messagebox.showerror("Error resolviendo proxy/búsqueda", s))
                        self.after(0, lambda: self.stop_loading("Error en la búsqueda (Nombre)."))
                        return
                    self.after(0, lambda r=results: self.populate_search_results(r))
                    self.after(0, lambda: self.stop_loading(f"{len(results)} resultados. Elige uno y pulsa 'Cargar selección'."))

            except Exception as ex:
                err_str = str(ex)
                tb_str = traceback.format_exc()
                self.after(0, lambda s=err_str: self.log(f"[EXC] {s}"))
                self.after(0, lambda s=tb_str: self.log(s))
                self.after(0, lambda s=err_str: messagebox.showerror("Excepción", s))
                self.after(0, lambda: self.stop_loading("Error."))
        threading.Thread(target=worker, daemon=True).start()

    def on_open_selected_result(self):
        idxs = self.results_list.curselection()
        if not idxs:
            messagebox.showinfo("Selecciona un resultado", "Elige un resultado de la lista primero.")
            return
        idx = idxs[0]
        try:
            item = self.search_results[idx]
            url = item["url"]
            title = item["display"]
        except Exception:
            messagebox.showwarning("Selección inválida", "No se pudo leer la URL seleccionada.")
            return

        self.start_loading("Cargando ficha")
        self.enable_torrent_actions(False)
        self.list_frame.clear()
        self.log(f"[OPEN] Cargando ficha: {title} | {url}")

        save_dir = "debug_html" if self.save_html_var.get() else None

        def worker():
            try:
                links, err = gather_torrent_links(url, log_cb=self.log, save_html_dir=save_dir)
                if err:
                    self.after(0, lambda s=err: self.log(f"[WARN] {s}"))
                    self.after(0, lambda s=err: messagebox.showinfo("Aviso", s))
                self.after(0, lambda l=links: self.show_torrents(l))
                self.after(0, lambda: self.stop_loading("Listo."))
            except Exception as ex:
                err_str = str(ex)
                tb_str = traceback.format_exc()
                self.after(0, lambda s=err_str: self.log(f"[EXC] {s}"))
                self.after(0, lambda s=tb_str: self.log(s))
                self.after(0, lambda s=err_str: messagebox.showerror("Excepción", s))
                self.after(0, lambda: self.stop_loading("Error."))
        threading.Thread(target=worker, daemon=True).start()

    def on_download(self):
        selected = self.list_frame.get_checked_items()
        if not selected:
            messagebox.showinfo("Sin selección", "Marca al menos un enlace para descargar.")
            return

        self.status_var.set("Descargando…")
        self.progress.configure(mode="determinate", value=0)
        self.total_var.set(len(selected))
        self.done_var.set(0)
        self.log(f"[DL] Descargando {len(selected)} archivos a: {self.dest_folder}")

        q = queue.Queue()
        for link in selected:
            q.put(link)

        def per_file_progress(downloaded, total):
            pass  # progreso por archivo (global solo usa cantidad de archivos)

        def worker():
            results = []
            while not q.empty():
                link = q.get()
                ok, msg = download_file(link, self.dest_folder, progress_cb=per_file_progress)
                results.append((link, ok, msg))
                q.task_done()
                done = self.done_var.get() + 1
                self.done_var.set(done)
                total = self.total_var.get()
                pct = int((done / total) * 100) if total else 0
                self.after(0, lambda v=pct: self.progress.configure(value=v))
                self.after(0, lambda d=done, t=total: self.status_var.set(f"Descargando… {d}/{t}"))
                self.after(0, lambda l=link, ok=ok, m=msg: self.log(f"[DL][{'OK' if ok else 'ERR'}] {l} -> {m}"))
            def finish_ui():
                self.status_var.set("Completado.")
                errores = [f"- {l}\n  {m}" for (l, ok, m) in results if not ok]
                if errores:
                    messagebox.showwarning("Descargas con errores", "\n\n".join(errores))
                else:
                    messagebox.showinfo("Descargas", f"Se completaron {len(results)} descargas.")
                self.log("[DL] Finalizado.")
            self.after(0, finish_ui)

        threading.Thread(target=worker, daemon=True).start()

# --------------- main --------------- #

if __name__ == "__main__":
    app = App()
    app.mainloop()

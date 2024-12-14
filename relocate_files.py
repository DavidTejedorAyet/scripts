import os
import re
import shutil
from guessit import guessit
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

def extract_info(filename):
    info = guessit(filename)
    if info.get('type') == 'episode':
        series_name = info.get('title', 'Desconocido')
        season = info.get('season')
        episode = info.get('episode')
        ext = '.' + info.get('container', 'mkv')
        new_filename = f"{series_name} - {season}x{episode:02d}{ext}"
        return ('series', series_name, season, episode, new_filename)
    elif info.get('type') == 'movie':
        movie_name = info.get('title', 'Pelicula_Desconocida')
        year = info.get('year')
        ext = '.' + info.get('container', 'mkv')
        if year:
            new_filename = f"{movie_name} ({year}){ext}"
        else:
            new_filename = f"{movie_name}{ext}"
        return ('movie', movie_name, None, None, new_filename)
    else:
        ext = '.' + info.get('container', 'mkv') if 'container' in info else '.mkv'
        return ('movie', 'Pelicula_Desconocida', None, None, f"Pelicula_Desconocida{ext}")

def standardize_filenames_preview(folder):
    video_extensions = ['.avi', '.mkv', '.mp4', '.mov', '.wmv', '.flv']
    structure = {}
    
    for filename in os.listdir(folder):
        if any(filename.lower().endswith(ext) for ext in video_extensions):
            content_type, name, season, episode, new_filename = extract_info(filename)
            if content_type == 'series':
                series_folder = name
                season_folder = f"Temporada {season}"
                structure.setdefault(series_folder, {}).setdefault(season_folder, []).append((filename, new_filename))
            else:
                structure.setdefault("Películas", []).append((filename, new_filename))
    
    return structure

def standardize_filenames(folder, structure, destination, progress_var, progress_bar, root):
    series_destination = os.path.join(destination, "Series")
    os.makedirs(series_destination, exist_ok=True)
    movies_destination = os.path.join(destination, "Películas")
    os.makedirs(movies_destination, exist_ok=True)

    total_files = sum(
        sum(len(ep_list) for ep_list in seasons.values()) if isinstance(seasons, dict) else len(seasons)
        for seasons in structure.values()
    )

    current_count = 0
    progress_var.set(0)
    progress_bar['maximum'] = total_files

    # Forzar actualización de interfaz
    root.update_idletasks()

    for series, seasons in structure.items():
        if isinstance(seasons, dict):  # Caso para series
            series_folder = os.path.join(folder, series)
            dest_series_folder = os.path.join(series_destination, series)
            os.makedirs(series_folder, exist_ok=True)
            os.makedirs(dest_series_folder, exist_ok=True)
            for season, episodes in seasons.items():
                season_folder = os.path.join(series_folder, season)
                dest_season_folder = os.path.join(dest_series_folder, season)
                os.makedirs(season_folder, exist_ok=True)
                os.makedirs(dest_season_folder, exist_ok=True)
                for original, new in episodes:
                    old_filepath = os.path.join(folder, original)
                    new_filepath = os.path.join(season_folder, new)
                    dest_filepath = os.path.join(dest_season_folder, new)
                    try:
                        if os.path.exists(new_filepath):
                            os.remove(new_filepath)
                        shutil.move(old_filepath, new_filepath)
                        shutil.move(new_filepath, dest_filepath)
                    except Exception as e:
                        messagebox.showerror("Error", f"Error al mover '{original}': {e}")
                    current_count += 1
                    progress_var.set(current_count)
                    root.update_idletasks()
        else:  # Caso para películas
            movies_folder = os.path.join(folder, "Películas")
            dest_movies_folder = movies_destination
            os.makedirs(movies_folder, exist_ok=True)
            os.makedirs(dest_movies_folder, exist_ok=True)
            for original, new in seasons:
                old_filepath = os.path.join(folder, original)
                new_filepath = os.path.join(movies_folder, new)
                dest_filepath = os.path.join(dest_movies_folder, new)
                try:
                    if os.path.exists(new_filepath):
                        os.remove(new_filepath)
                    shutil.move(old_filepath, new_filepath)
                    shutil.move(new_filepath, dest_filepath)
                except Exception as e:
                    messagebox.showerror("Error", f"Error al mover '{original}': {e}")
                current_count += 1
                progress_var.set(current_count)
                root.update_idletasks()

    messagebox.showinfo("Completado", "Los cambios han sido aplicados.")


def move_videos_and_delete_subfolders(parent_folder):
    video_extensions = ['.avi', '.mkv', '.mp4', '.mov', '.wmv', '.flv']
    for root, dirs, files in os.walk(parent_folder, topdown=False):
        for file in files:
            if any(file.lower().endswith(ext) for ext in video_extensions):
                file_path = os.path.join(root, file)
                try:
                    shutil.move(file_path, parent_folder)
                except Exception as e:
                    messagebox.showerror("Error", f"Error al mover '{file_path}': {e}")
        for dir in dirs:
            dir_path = os.path.join(root, dir)
            try:
                os.rmdir(dir_path)
            except OSError as e:
                # Puede no ser vacía, ignoramos o mostramos un error
                pass

def populate_treeview(tree, structure):
    # Limpia el treeview
    for i in tree.get_children():
        tree.delete(i)

    # Estructura:
    # si key es "Películas", entonces es una lista: [(orig,new), ...]
    # si key es una serie, es un dict: { "Temporada X": [(orig,new), ...], ... }

    for series, seasons in structure.items():
        # Crear nodo principal
        parent_node = tree.insert("", "end", text=series, open=True)
        if isinstance(seasons, dict):
            # Es una serie, con temporadas
            for season, episodes in seasons.items():
                season_node = tree.insert(parent_node, "end", text=season, open=True)
                for original, new in episodes:
                    tree.insert(season_node, "end", text=new)
        else:
            # Es películas (lista)
            for original, new in seasons:
                tree.insert(parent_node, "end", text=new)

def analizar_carpeta():
    carpeta = carpeta_var.get()
    if not carpeta or not os.path.isdir(carpeta):
        messagebox.showerror("Error", "Por favor seleccione una carpeta de origen válida")
        return
    move_videos_and_delete_subfolders(carpeta)
    struct = standardize_filenames_preview(carpeta)

    if not struct:
        messagebox.showinfo("Resultado", "No se han encontrado archivos de video para procesar.")
        estructura_actual.clear()
        # Limpiar el treeview
        for i in tree.get_children():
            tree.delete(i)
        btn_confirmar.config(state='disabled')
        return

    populate_treeview(tree, struct)
    estructura_actual.clear()
    estructura_actual.update(struct)
    btn_confirmar.config(state='normal')


def elegir_carpeta_origen():
    ruta = filedialog.askdirectory()
    if ruta:
        carpeta_var.set(ruta)

def elegir_carpeta_destino():
    ruta = filedialog.askdirectory()
    if ruta:
        destino_var.set(ruta)

def confirmar():
    if not estructura_actual:
        messagebox.showerror("Error", "No hay estructura analizada")
        return
    destino = destino_var.get()
    if not destino or not os.path.isdir(destino):
        messagebox.showerror("Error", "Por favor seleccione una carpeta de destino válida")
        return
    carpeta = carpeta_var.get()
    standardize_filenames(carpeta, estructura_actual, destino, progress_var, progress_bar, root)


# Rutas por defecto
current_folder = os.path.dirname(os.path.abspath(__file__))
destination_folder = r'\\Nas\nas'

# Ventana principal
root = tk.Tk()
root.title("Organizador de archivos multimedia")

# Variables de control
carpeta_var = tk.StringVar(value=current_folder)
destino_var = tk.StringVar(value=destination_folder)
estructura_actual = {}

frame_input = ttk.Frame(root)
frame_input.pack(padx=10, pady=10, fill='x')

ttk.Label(frame_input, text="Carpeta Origen:").pack(anchor='w')
entry_carpeta = ttk.Entry(frame_input, textvariable=carpeta_var, width=50)
entry_carpeta.pack(side='left', padx=5, pady=5)
ttk.Button(frame_input, text="Seleccionar", command=elegir_carpeta_origen).pack(side='left', padx=5, pady=5)

frame_destino = ttk.Frame(root)
frame_destino.pack(padx=10, pady=10, fill='x')

ttk.Label(frame_destino, text="Carpeta Destino:").pack(anchor='w')
entry_destino = ttk.Entry(frame_destino, textvariable=destino_var, width=50)
entry_destino.pack(side='left', padx=5, pady=5)
ttk.Button(frame_destino, text="Seleccionar", command=elegir_carpeta_destino).pack(side='left', padx=5, pady=5)

frame_buttons = ttk.Frame(root)
frame_buttons.pack(padx=10, pady=10, fill='x')

ttk.Button(frame_buttons, text="Analizar Estructura", command=analizar_carpeta).pack(side='left', padx=5)
btn_confirmar = ttk.Button(frame_buttons, text="Confirmar y Mover", command=confirmar)
btn_confirmar.pack(side='left', padx=5)
btn_confirmar.config(state='disabled')

frame_tree = ttk.Frame(root)
frame_tree.pack(padx=10, pady=10, fill='both', expand=True)

tree = ttk.Treeview(frame_tree, columns=('name',), show='tree')
tree.pack(fill='both', expand=True)

# Barra de progreso
frame_progress = ttk.Frame(root)
frame_progress.pack(padx=10, pady=10, fill='x')
progress_var = tk.IntVar()
progress_bar = ttk.Progressbar(frame_progress, variable=progress_var, orient='horizontal', mode='determinate')
progress_bar.pack(fill='x', expand=True, padx=5, pady=5)

root.mainloop()

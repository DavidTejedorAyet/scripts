import os
import re
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading

# Intentar importar guessit
try:
    from guessit import guessit
except ImportError:
    # No podemos mostrar un messagebox aquí porque posiblemente la ventana no exista todavía.
    # Imprimiremos el error y salimos. Si usas un entorno donde ya existe un root, podrías usar messagebox.
    print("La librería 'guessit' no está instalada. Ejecuta 'pip install guessit'.")
    raise SystemExit

def extract_info(filename):
    try:
        info = guessit(filename)
    except Exception:
        # Si guessit falla, lo tratamos como película desconocida
        info = {'type': 'movie', 'container': 'mkv'}

    if info.get('type') == 'episode':
        series_name = info.get('title', 'Desconocido')
        season = info.get('season', 1)
        episode = info.get('episode', 1)
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
    
    try:
        items = os.listdir(folder)
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo listar la carpeta origen: {e}")
        return {}
    
    for filename in items:
        if any(filename.lower().endswith(ext) for ext in video_extensions):
            content_type, name, season, episode, new_filename = extract_info(filename)
            if content_type == 'series':
                series_folder = name
                season_folder = f"Temporada {season}"
                structure.setdefault(series_folder, {}).setdefault(season_folder, []).append((filename, new_filename))
            else:
                structure.setdefault("Películas", []).append((filename, new_filename))
    
    return structure

def standardize_filenames(folder, structure, destination, progress_var, progress_bar, root, on_complete):
    def task():
        errors = []
        try:
            series_destination = os.path.join(destination, "Series")
            os.makedirs(series_destination, exist_ok=True)
            movies_destination = os.path.join(destination, "Películas")
            os.makedirs(movies_destination, exist_ok=True)

            total_files = sum(
                sum(len(ep_list) for ep_list in seasons.values()) if isinstance(seasons, dict) else len(seasons)
                for seasons in structure.values()
            )

            current_count = 0
            root.after(0, lambda: progress_bar.config(maximum=total_files))

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
                                if old_filepath != new_filepath and os.path.exists(old_filepath):
                                    shutil.move(old_filepath, new_filepath)
                                if new_filepath != dest_filepath and os.path.exists(new_filepath):
                                    shutil.move(new_filepath, dest_filepath)
                            except Exception as e:
                                errors.append(f"Error al mover '{original}': {e}")
                            current_count += 1
                            # Actualizar la barra de progreso
                            root.after(0, lambda c=current_count: progress_var.set(c))

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
                            if old_filepath != new_filepath and os.path.exists(old_filepath):
                                shutil.move(old_filepath, new_filepath)
                            if new_filepath != dest_filepath and os.path.exists(new_filepath):
                                shutil.move(new_filepath, dest_filepath)
                        except Exception as e:
                            errors.append(f"Error al mover '{original}': {e}")
                        current_count += 1
                        # Actualizar la barra de progreso
                        root.after(0, lambda c=current_count: progress_var.set(c))

        except Exception as e:
            errors.append(f"Error general: {e}")

        # Llamar a on_complete en el hilo principal
        def finish():
            on_complete(errors)

        root.after(0, finish)

    threading.Thread(target=task, daemon=True).start()

def move_videos_and_delete_subfolders(parent_folder):
    video_extensions = ['.avi', '.mkv', '.mp4', '.mov', '.wmv', '.flv']
    for root_dir, dirs, files in os.walk(parent_folder, topdown=False):
        for file in files:
            if any(file.lower().endswith(ext) for ext in video_extensions):
                file_path = os.path.join(root_dir, file)
                # Si el archivo ya está en la carpeta principal no lo movemos
                if file_path != os.path.join(parent_folder, file):
                    try:
                        shutil.move(file_path, parent_folder)
                    except:
                        pass
        for dir in dirs:
            dir_path = os.path.join(root_dir, dir)
            try:
                os.rmdir(dir_path)
            except OSError:
                pass

def populate_treeview(tree, structure):
    for i in tree.get_children():
        tree.delete(i)

    for series, seasons in structure.items():
        parent_node = tree.insert("", "end", text=series, open=True)
        if isinstance(seasons, dict):
            for season, episodes in seasons.items():
                season_node = tree.insert(parent_node, "end", text=season, open=True)
                for original, new in episodes:
                    tree.insert(season_node, "end", text=new)
        else:
            for original, new in seasons:
                tree.insert(parent_node, "end", text=new)

def analizar_carpeta():
    carpeta = carpeta_var.get()
    if not carpeta or not os.path.isdir(carpeta):
        messagebox.showerror("Error", "Por favor seleccione una carpeta de origen válida")
        return
    btn_analizar.config(state='disabled')
    btn_confirmar.config(state='disabled')

    def task():
        move_videos_and_delete_subfolders(carpeta)
        struct = standardize_filenames_preview(carpeta)
        root.after(0, lambda: finalizar_analisis(struct))

    threading.Thread(target=task, daemon=True).start()

def finalizar_analisis(struct):
    if not struct:
        messagebox.showinfo("Resultado", "No se han encontrado archivos de video para procesar.")
        estructura_actual.clear()
        for i in tree.get_children():
            tree.delete(i)
        btn_confirmar.config(state='disabled')
    else:
        populate_treeview(tree, struct)
        estructura_actual.clear()
        estructura_actual.update(struct)
        btn_confirmar.config(state='normal')
    btn_analizar.config(state='normal')

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

    btn_analizar.config(state='disabled')
    btn_confirmar.config(state='disabled')

    def on_complete(errors):
        if errors:
            msg = "\n".join(errors)
            messagebox.showerror("Errores durante la operación", msg)
        else:
            messagebox.showinfo("Completado", "Los cambios han sido aplicados.")
        btn_analizar.config(state='normal')
        for i in tree.get_children():
            tree.delete(i)
        estructura_actual.clear()
        btn_confirmar.config(state='disabled')
        progress_var.set(0)

    standardize_filenames(carpeta, estructura_actual, destino, progress_var, progress_bar, root, on_complete)


if __name__ == "__main__":
    # Usar rutas con doble barra invertida en Windows
    current_folder = "C:\\Users\\david\\Downloads\\Torrent"
    destination_folder = "\\\\Nas\\nas"

    # Comprobar carpeta origen
    if not os.path.isdir(current_folder):
        try:
            os.makedirs(current_folder, exist_ok=True)
        except Exception as e:
            print(f"No se pudo crear la carpeta origen {current_folder}: {e}")
            raise SystemExit

    # Comprobar carpeta destino
    if not os.path.isdir(destination_folder):
        try:
            os.makedirs(destination_folder, exist_ok=True)
        except Exception as e:
            print(f"No se pudo crear la carpeta destino {destination_folder}: {e}")

    root = tk.Tk()
    root.title("Organizador de archivos multimedia")

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

    btn_analizar = ttk.Button(frame_buttons, text="Analizar Estructura", command=analizar_carpeta)
    btn_analizar.pack(side='left', padx=5)
    btn_confirmar = ttk.Button(frame_buttons, text="Confirmar y Mover", command=confirmar)
    btn_confirmar.pack(side='left', padx=5)
    btn_confirmar.config(state='disabled')

    frame_tree = ttk.Frame(root)
    frame_tree.pack(padx=10, pady=10, fill='both', expand=True)

    tree = ttk.Treeview(frame_tree, columns=('name',), show='tree')
    tree.pack(fill='both', expand=True)

    frame_progress = ttk.Frame(root)
    frame_progress.pack(padx=10, pady=10, fill='x')
    progress_var = tk.IntVar()
    progress_bar = ttk.Progressbar(frame_progress, variable=progress_var, orient='horizontal', mode='determinate')
    progress_bar.pack(fill='x', expand=True, padx=5, pady=5)

    root.mainloop()

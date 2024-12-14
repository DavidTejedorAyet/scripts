import os
import re
import shutil
from tqdm import tqdm
from guessit import guessit

def extract_info(filename):
    info = guessit(filename)
    # Ejemplo de la estructura que guessit puede devolver:
    # {
    #  'title': 'Breaking Bad',
    #  'season': 1,
    #  'episode': 1,
    #  'type': 'episode',
    #  'container': 'mkv'
    # }
    #
    # Si es película:
    # {
    #  'title': 'Inception',
    #  'year': 2010,
    #  'type': 'movie',
    #  'container': 'mp4'
    # }

    if info.get('type') == 'episode':
        series_name = info.get('title', 'Desconocido')
        season = info.get('season')
        episode = info.get('episode')
        ext = '.' + info.get('container', 'mkv')
        # Estandarizar nombre de episodio de serie
        new_filename = f"{series_name} - {season}x{episode:02d}{ext}"
        return ('series', series_name, season, episode, new_filename)
    elif info.get('type') == 'movie':
        movie_name = info.get('title', 'Pelicula_Desconocida')
        year = info.get('year')
        ext = '.' + info.get('container', 'mkv')
        # Estandarizar nombre de película
        if year:
            new_filename = f"{movie_name} ({year}){ext}"
        else:
            new_filename = f"{movie_name}{ext}"
        return ('movie', movie_name, None, None, new_filename)
    else:
        # Caso no identificado, lo tratamos como película genérica
        ext = '.' + info.get('container', 'mkv') if 'container' in info else '.mkv'
        return ('movie', 'Pelicula_Desconocida', None, None, f"Pelicula_Desconocida{ext}")

def standardize_filenames_preview(folder):
    video_extensions = ['.avi', '.mkv', '.mp4', '.mov', '.wmv', '.flv']
    structure = {}
    
    for filename in os.listdir(folder):
        if any(filename.lower().endswith(ext) for ext in video_extensions):
            file_path = os.path.join(folder, filename)
            content_type, name, season, episode, new_filename = extract_info(filename)

            if content_type == 'series':
                series_folder = name
                season_folder = f"Temporada {season}"
                structure.setdefault(series_folder, {}).setdefault(season_folder, []).append((filename, new_filename))
            else:
                # Es película
                structure.setdefault("Películas", []).append((filename, new_filename))
    
    return structure

def print_structure(structure):
    for series, seasons in structure.items():
        print(series)
        if isinstance(seasons, dict):
            for season, episodes in seasons.items():
                print(f"    - {season}")
                for original, new in episodes:
                    print(f"        + {new}")
        else:
            for original, new in seasons:
                print(f"    + {new}")

def standardize_filenames(folder, structure, destination):
    series_destination = os.path.join(destination, "Series")
    os.makedirs(series_destination, exist_ok=True)
    movies_destination = os.path.join(destination, "Películas")
    os.makedirs(movies_destination, exist_ok=True)

    # Sumar el número de archivos
    total_files = sum(
    sum(len(ep_list) for ep_list in seasons.values()) if isinstance(seasons, dict) else len(seasons)
    for seasons in structure.values()
    )


    with tqdm(total=total_files, desc="Moviendo archivos", unit="archivo") as pbar:
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
                                print(f"Eliminado archivo existente {new_filepath}")
                            shutil.move(old_filepath, new_filepath)
                            shutil.move(new_filepath, dest_filepath)
                            print(f"Movido '{original}' a '{dest_filepath}'")
                        except FileNotFoundError:
                            print(f"Archivo no encontrado: '{old_filepath}'")
                        except Exception as e:
                            print(f"Error al mover '{original}': {e}")
                        pbar.update(1)
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
                            print(f"Eliminado archivo existente {new_filepath}")
                        shutil.move(old_filepath, new_filepath)
                        shutil.move(new_filepath, dest_filepath)
                        print(f"Movido '{original}' a '{dest_filepath}'")
                    except FileNotFoundError:
                        print(f"Archivo no encontrado: '{old_filepath}'")
                    except Exception as e:
                        print(f"Error al mover '{original}': {e}")
                    pbar.update(1)

def move_videos_and_delete_subfolders(parent_folder):
    video_extensions = ['.avi', '.mkv', '.mp4', '.mov', '.wmv', '.flv']
    for root, dirs, files in os.walk(parent_folder, topdown=False):
        for file in files:
            if any(file.lower().endswith(ext) for ext in video_extensions):
                file_path = os.path.join(root, file)
                try:
                    shutil.move(file_path, parent_folder)
                    print(f"Movido '{file_path}' a '{parent_folder}'")
                except Exception as e:
                    print(f"Error al mover '{file_path}': {e}")
        for dir in dirs:
            dir_path = os.path.join(root, dir)
            try:
                os.rmdir(dir_path)
                print(f"Eliminada la carpeta '{dir_path}'")
            except OSError as e:
                print(f"Error al eliminar la carpeta '{dir_path}': {e}")

if __name__ == "__main__":
    current_folder = os.path.dirname(os.path.abspath(__file__))
    
    # Mover videos a la carpeta principal y eliminar subcarpetas
    move_videos_and_delete_subfolders(current_folder)
    
    # Estandarizar nombres de archivos y mover a destino
    destination_folder = r'\\Nas\nas'  # La ubicación de destino proporcionada
    structure = standardize_filenames_preview(current_folder)
    print("La siguiente estructura será creada:")
    print_structure(structure)
    confirm = input("¿Deseas proceder con estos cambios? (s/n): ")
    if confirm.lower() == "s":
        standardize_filenames(current_folder, structure, destination_folder)
        print("Los cambios han sido aplicados.")
    else:
        print("No se realizaron cambios.")

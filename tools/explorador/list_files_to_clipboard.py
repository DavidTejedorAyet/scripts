import os
import pyperclip  # queda embebido en el exe por PyInstaller

def listar_archivos_y_directorios(carpeta: str) -> str:
    try:
        elementos = os.listdir(carpeta)
    except Exception as e:
        elementos = [f"[ERROR] {e}"]
    return "\n".join(elementos)

def main() -> None:
    carpeta = os.getcwd()  # Carpeta actual
    lista_elementos = listar_archivos_y_directorios(carpeta)
    pyperclip.copy(lista_elementos)
    print("Lista de archivos y directorios copiada al portapapeles.")

if __name__ == "__main__":
    main()

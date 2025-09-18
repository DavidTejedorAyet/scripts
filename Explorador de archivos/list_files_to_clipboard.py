import os
import pyperclip

def listar_archivos_y_directorios(carpeta):
    elementos = os.listdir(carpeta)
    lista = '\n'.join(elementos)
    return lista

def main():
    carpeta = os.getcwd()  # Carpeta actual
    lista_elementos = listar_archivos_y_directorios(carpeta)
    pyperclip.copy(lista_elementos)
    print("Lista de archivos y directorios copiada al portapapeles.")

if __name__ == "__main__":
    try:
        import pyperclip
    except ImportError:
        print("Instalando la librería pyperclip...")
        os.system('pip install pyperclip')
    main()
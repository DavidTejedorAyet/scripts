import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin

def gather_torrent_links(url):
    response = requests.get(url)
    torrent_links = []
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        
        for button in soup.find_all(id='download_torrent'):
            link = button.get('href') or button.get('data-url')
            if link:
                full_link = urljoin(url, link)
                torrent_links.append(full_link)
    else:
        print(f'Error al acceder a {url}: {response.status_code}')
    
    return torrent_links

def download_files(download_links):
    if not os.path.exists('downloads'):
        os.makedirs('downloads')
    
    for link in download_links:
        filename = os.path.join('downloads', link.split('/')[-1])
        
        file_response = requests.get(link)
        if file_response.status_code == 200:
            with open(filename, 'wb') as file:
                file.write(file_response.content)
            print(f'Descargado: {filename}')
            
            try:
                if os.name == 'nt':
                    os.startfile(filename)
                elif os.name == 'posix':
                    os.system(f'xdg-open "{filename}"')
                else:
                    print(f"No se puede abrir el archivo automáticamente en este sistema operativo.")
            except Exception as e:
                print(f"Error al intentar abrir el archivo: {e}")
        else:
            print(f'Error al descargar: {link}')

def main():
    url = input("Introduce la URL del sitio web: ")
    option = input("¿Deseas entrar a todos los enlaces y buscar los torrent'? (s/n): ")
    
    if option.lower() == 's':
        main_page_response = requests.get(url)
        if main_page_response.status_code == 200:
            soup = BeautifulSoup(main_page_response.content, 'html.parser')
            
            pelicula_links = []
            for a in soup.find_all('a', href=True):
                if '/pelicula/' in a['href']:
                    full_link = urljoin(url, a['href'])
                    pelicula_links.append(full_link)
            
            all_torrent_links = []
            for pelicula_url in pelicula_links:
                print(f"Procesando: {pelicula_url}")
                torrent_links = gather_torrent_links(pelicula_url)
                all_torrent_links.extend(torrent_links)
            
            # Mostrar todos los enlaces de torrents encontrados
            print("Enlaces de descarga encontrados:")
            for link in all_torrent_links:
                print(link)
            
            # Solicitar confirmación del usuario antes de descargar todos los archivos
            confirm = input("¿Deseas descargar estos archivos? (s/n): ")
            if confirm.lower() == 's':
                download_files(all_torrent_links)
            else:
                print("Descarga cancelada por el usuario.")
        else:
            print(f'Error: {main_page_response.status_code}')
    else:
        torrent_links = gather_torrent_links(url)
        
        print("Enlaces de descarga encontrados:")
        for link in torrent_links:
            print(link)
        
        confirm = input("¿Deseas descargar estos archivos? (s/n): ")
        if confirm.lower() == 's':
            download_files(torrent_links)
        else:
            print("Descarga cancelada por el usuario.")

if __name__ == '__main__':
    main()

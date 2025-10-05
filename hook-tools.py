# hook-tools.py
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# --- Tu paquete y submódulos ---
hiddenimports = []
hiddenimports += collect_submodules('tools')

# --- Deps opcionales de tus herramientas ---
hiddenimports += collect_submodules('PTN')        # parse-torrent-name
hiddenimports += collect_submodules('guessit')
hiddenimports += collect_submodules('yaml')       # PyYAML
hiddenimports += collect_submodules('babelfish')  # guessit dep
hiddenimports += collect_submodules('rebulk')     # guessit dep

# --- Requests y dependencias habituales ---
hiddenimports += collect_submodules('requests')
hiddenimports += collect_submodules('urllib3')
hiddenimports += collect_submodules('idna')
hiddenimports += collect_submodules('chardet')
hiddenimports += collect_submodules('certifi')

# --- BeautifulSoup4 (bs4) y soupsieve ---
hiddenimports += collect_submodules('bs4')
hiddenimports += collect_submodules('soupsieve')

# --- Datos útiles (scripts/configs dentro de tools + cacert.pem de certifi) ---
datas  = collect_data_files('tools', includes=[
    '**/*.py', '**/*.pyw',
    '**/*.txt', '**/*.ini', '**/*.json',
    '**/*.yaml', '**/*.yml', '**/*.csv', '**/*.md'
], excludes=['**/__pycache__/**'])

datas += collect_data_files('guessit')
datas += collect_data_files('babelfish')
datas += collect_data_files('PTN')
datas += collect_data_files('yaml')
datas += collect_data_files('certifi')
datas += collect_data_files('bs4')
datas += collect_data_files('soupsieve')

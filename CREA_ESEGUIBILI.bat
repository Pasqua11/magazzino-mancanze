@echo off
echo ==========================================
echo      CREAZIONE ESEGUIBILI MAGAZZINO
echo ==========================================
echo.

echo 1. Installazione PyInstaller (se manca)...
python -m pip install pypiwin32
python -m pip install pyinstaller
python -m pip install pystray Pillow

echo.
echo 2. Creazione Eseguibile SERVER...
echo    Includendo cartella templates...
python -m PyInstaller --name ServerMagazzino --onefile --noconsole --add-data "server/templates;templates" --hidden-import pystray._win32 server/app.py

echo.
echo 3. Creazione Eseguibile CLIENT...
python -m PyInstaller --name ClientMagazzino --onefile --noconsole client/client.py

echo.
echo ==========================================
echo      OPERAZIONE COMPLETATA!
echo ==========================================
echo.
echo I file .exe si trovano nella cartella 'dist'.
echo Puoi spostare questi file dove vuoi.
echo.
echo NOTA: Il ServerMagazzino.exe deve rimanere aperto
echo per far funzionare i Client. Una volta avviato compare
echo un'icona verde nella barra, in basso a destra: da li'
echo si apre la pagina, la cartella dati e si spegne il server.
echo.
pause

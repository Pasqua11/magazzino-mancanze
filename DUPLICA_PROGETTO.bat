@echo off
cd /d "%~dp0"
set "DEST=..\Magazzino2"

if exist "%DEST%" (
    echo La cartella %DEST% esiste gia.
    echo Per sicurezza, cancellala o spostala prima di procedere.
    pause
    exit /b
)

echo Creazione copia in %DEST% ...
xcopy . "%DEST%" /E /I /Y /Q

echo.
echo Copia completata!
echo La nuova cartella si trova in %DEST%

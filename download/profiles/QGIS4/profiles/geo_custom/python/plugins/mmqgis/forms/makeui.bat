@echo off

REM https://pypi.org/project/PyQt6/
REM https://www.pythontutorial.net/pyqt/qt-designer/
REM https://stackoverflow.com/questions/2772456/string-replacement-in-batch-file

setlocal enabledelayedexpansion

FOR %%f IN (*.ui) DO (
SET xml=%%f
CALL SET python=%%xml:ui=py%%
ECHO !python! !xml!
pyuic6 -o !python! !xml! )

endlocal

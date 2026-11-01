@echo off
rem Build EXVS2OB_en.exe from the pristine launcher and verify the result.
cd /d "%~dp0"
echo === Patching ===
python patch.py patch --exe ..\EXVS2OB.exe --out ..\EXVS2OB_en.exe
if errorlevel 1 goto :failed
echo.
echo === Verifying ===
python patch.py verify --src ..\EXVS2OB.exe --patched ..\EXVS2OB_en.exe
if errorlevel 1 goto :failed
echo.
echo Done: ..\EXVS2OB_en.exe
pause
exit /b 0

:failed
echo.
echo Translation is incomplete - see the messages above.
pause
exit /b 1

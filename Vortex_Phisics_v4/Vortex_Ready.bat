@echo off
title Vortex Dynamic Theory - Ready

:: Activate the vortex environment and set the no-user-site flag
call "%USERPROFILE%\miniconda3\Scripts\activate.bat" vortex
set PYTHONNOUSERSITE=1

echo =============================================
echo Vortex environment activated successfully!
echo PYTHONNOUSERSITE=1 is set (global packages ignored)
echo You are now ready to run your scripts.
echo =============================================
echo.

:: Optional: show current environment info
echo Python location: 
where python
echo.

cmd /k
@echo off
rem Daily refresh of the Kenya Short Rains forecast (CHIRPS observations, SEAS5 re-run, agronomic onset,
rem ECMWF ENS 1-15 day outlook, site reports). Registered in Windows Task Scheduler as "OND Forecast Update",
rem daily at 19:30 (from 26 Nov 2026; it was 12:30, when the laptop was often moved and put to sleep mid-run).
rem
rem The pull below can rewrite this file, and cmd reads a batch file as it goes: the script first runs from a copy.
rem (Run without CALL, the copy takes over and this file is not read again.)
if "%~1"=="--from-copy" goto body
copy /y "%~f0" "%TEMP%\run_update_forecast_copy.bat" >nul
"%TEMP%\run_update_forecast_copy.bat" --from-copy
:body
cd /d D:\Operational-Multi-Model-Seasonal-Forecasting-System
set PYTHONIOENCODING=utf-8
echo ===== %DATE% %TIME% ===== >> outputs\update_forecast.log
rem on main, take the latest merged code first (publishing needs the checkout to match origin/main).
rem The data files the update regenerates are discarded first: left modified by a run that did not publish,
rem they would block the pull and the run would go ahead on old code. The run rebuilds them anyway.
rem Untracked forecast runs and tracker data files (e.g. nwp_runs/nwp_<date>.csv) are removed too: a published file
rem of the same name would block the pull.
rem
rem The pull is tried PULL_TRIES times, PULL_WAIT seconds apart: on 20 Nov 2026 github.com could not be resolved at
rem 12:30, the run went ahead on the day before's code, and neither publish went out (the code differed from
rem origin/main). A stalled transfer is dropped after a minute below 1 kB/s. If every try fails the update is not run:
rem the live data stays as it is and the next day's run tries again.
set DATA_FILES=frontend/public/tracker/data backend/demo_short_rains_extra.npz backend/demo_short_rains_rules.npz backend/rain_stats.npz backend/data_status.json backend/forecast_runs
if not defined PULL_TRIES set PULL_TRIES=6
if not defined PULL_WAIT set PULL_WAIT=300
set BRANCH=
for /f %%b in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%b
if not "%BRANCH%"=="main" goto run
git checkout -q -- %DATA_FILES% >> outputs\update_forecast.log 2>&1
git clean -fq -- backend/forecast_runs frontend/public/tracker/data >> outputs\update_forecast.log 2>&1
set TRY=1
:pull
git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=60 pull -q --ff-only origin main >> outputs\update_forecast.log 2>&1
if not errorlevel 1 goto run
if %TRY% GEQ %PULL_TRIES% goto nopull
echo pull failed (try %TRY% of %PULL_TRIES%); trying again in %PULL_WAIT% s >> outputs\update_forecast.log
powershell -NoProfile -Command "Start-Sleep -Seconds %PULL_WAIT%"
set /a TRY+=1
goto pull
:nopull
echo pull failed %PULL_TRIES% times; update not run (the live data stays as it is; the next run tries again) >> outputs\update_forecast.log
exit /b 1
:run
.venv\Scripts\python.exe scripts\update_forecast.py --publish >> outputs\update_forecast.log 2>&1

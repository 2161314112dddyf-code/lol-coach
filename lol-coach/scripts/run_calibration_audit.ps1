$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$env:PYTHONIOENCODING = 'utf-8'
& "$projectRoot\.venv\Scripts\python.exe" "$PSScriptRoot\audit_calibration.py" `
  --log 'D:\WeGameApps\英雄联盟\Game\Logs\GameLogs\2026-10-10T14-34-57\2026-10-10T14-34-57_r3dlog.txt' `
  --replay 'C:\Users\21613\Documents\League of Legends\Replays\HN1-11363093470.rofl' `
  --track "$projectRoot\..\controlled-11363093470-route-analysis.json" `
  --game-id 11363093470 --patch 16.20
exit $LASTEXITCODE

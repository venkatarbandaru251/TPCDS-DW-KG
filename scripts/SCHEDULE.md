# Scheduling the daily ingest on Windows

The CEO persona wants data ready by 7:00 AM. The pipeline runs in ~1–2 minutes
on SF1, so scheduling for 5:00 AM gives plenty of headroom.

## One-time setup — Windows Task Scheduler

Open an **elevated** PowerShell and run:

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\projects\sdd\dw\scripts\run_daily_ingest.bat"
$trigger = New-ScheduledTaskTrigger -Daily -At 5:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable
Register-ScheduledTask -TaskName "dw_daily_ingest" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest
```

Verify:

```powershell
Get-ScheduledTask -TaskName "dw_daily_ingest" | Format-List *
Start-ScheduledTask -TaskName "dw_daily_ingest"   # trigger a test run
```

Logs land in `logs/ingest_<timestamp>.log`. Each run also writes to
`ops.ingest_runs` / `ops.ingest_table_stats` / `ops.dbt_test_results` in
Postgres — those are what the dashboard reads.

## Manual invocation

```bash
scripts/run_daily_ingest.bat
# or
.venv/Scripts/python.exe -m ingestion.run_pipeline
```

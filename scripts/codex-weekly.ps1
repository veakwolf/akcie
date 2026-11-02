# Weekly "spracuj akcie" via Codex, started by Windows Task Scheduler.
# Log: akcie\codex-weekly.log (not committed).
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$log  = Join-Path $repo "codex-weekly.log"
Set-Location $repo

"`n===== $(Get-Date -Format 'yyyy-MM-dd HH:mm') =====" | Out-File $log -Append -Encoding utf8
git pull --ff-only 2>&1 | Out-File $log -Append -Encoding utf8

# --full-auto lets Codex edit files and run commands in this folder without asking.
# If your Codex version names this flag differently, see `codex exec --help`.
codex exec --full-auto "spracuj akcie" 2>&1 | Out-File $log -Append -Encoding utf8
"exit code: $LASTEXITCODE" | Out-File $log -Append -Encoding utf8

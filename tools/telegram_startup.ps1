param([switch]$Remove,[string]$Python='',[switch]$LegacyController)
$ErrorActionPreference = 'Stop'
$telegramRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$telegramTaskName = 'AutoClippingTelegram-' + (([System.Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($telegramRoot)) | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0,12)
if ($Remove) {
    Unregister-ScheduledTask -TaskName $telegramTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output 'Removed this checkout Telegram logon task.'
    exit
}
$telegramPython = if ($Python) { (Resolve-Path -LiteralPath $Python).Path } else { Join-Path $telegramRoot '.venv/Scripts/pythonw.exe' }
if (-not (Test-Path -LiteralPath $telegramPython)) { throw 'Install this checkout .venv first. No task registered.' }
$telegramEntry = if ($LegacyController) { 'telegram_bot.py' } else { 'telegram_relay.py' }
$telegramArguments = '"' + (Join-Path $telegramRoot $telegramEntry) + '" run' + $(if ($LegacyController) { '' } else { ' --persistent' })
$telegramAction = New-ScheduledTaskAction -Execute $telegramPython -Argument $telegramArguments -WorkingDirectory $telegramRoot
$telegramUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$telegramTrigger = New-ScheduledTaskTrigger -AtLogOn -User $telegramUser
$telegramPrincipal = New-ScheduledTaskPrincipal -UserId $telegramUser -LogonType Interactive -RunLevel Limited
$telegramSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $telegramTaskName -Action $telegramAction -Trigger $telegramTrigger -Principal $telegramPrincipal -Settings $telegramSettings -Description 'Private Telegram controller; local Codex/media setup and explicit owner trigger required.' -Force | Out-Null
Write-Output ('Registered current-user logon task: ' + $telegramTaskName + '. Requires the configured Codex daemon; PC must remain on, awake and signed in. No workflow was started.')

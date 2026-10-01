# Giữ WSL chạy khi không mở terminal/VS Code nào (WSL tự tắt khi không còn client, dừng luôn livesp-capture).
# Cách làm: tác vụ Task Scheduler chạy lúc đăng nhập Windows, giữ một tiến trình `wsl.exe ... sleep infinity`
# ở chế độ ẩn. Còn client đó thì WSL còn chạy; systemd tự bật livesp-capture.
#
# Cài (PowerShell thường, không cần admin):  powershell -ExecutionPolicy Bypass -File scripts\wsl\install_keepalive.ps1
# Gỡ:                                        Unregister-ScheduledTask -TaskName livesp-wsl-keepalive -Confirm:$false
# Kiểm tra:                                  Get-ScheduledTask -TaskName livesp-wsl-keepalive | Get-ScheduledTaskInfo
# Lưu ý: máy Windows ngủ/ngủ đông thì mọi thứ vẫn dừng -> đặt "Sleep: Never" khi cắm sạc trong thời gian thu.
param(
    [string]$Distro = "Ubuntu",
    [string]$TaskName = "livesp-wsl-keepalive"
)

$wsl = Join-Path $env:SystemRoot "System32\wsl.exe"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -Command `"& '$wsl' -d $Distro --exec sleep infinity`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Keep WSL ($Distro) running for livesp capture" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State

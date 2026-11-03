# 创建两个带全局热键的开始菜单快捷方式。
# .lnk 放在开始菜单或桌面时，Windows 才会注册它上面的 Hotkey。
$ErrorActionPreference = 'Stop'
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$ws = New-Object -ComObject WScript.Shell

function New-CcodeShortcut {
    param([string]$FileName, [string]$ArgLine, [string]$Hotkey, [string]$Desc)
    $path = Join-Path $startMenu $FileName
    $sc = $ws.CreateShortcut($path)
    $sc.TargetPath = Join-Path $PSScriptRoot 'ccode.cmd'
    $sc.Arguments = $ArgLine
    $sc.WorkingDirectory = $PSScriptRoot
    $sc.WindowStyle = 7          # 最小化启动，避免闪窗
    $sc.Hotkey = $Hotkey
    $sc.Description = $Desc
    $sc.Save()
    Write-Output ("created: {0}  [{1}]" -f $path, $Hotkey)
}

New-CcodeShortcut -FileName 'ccode-gen.lnk' -ArgLine 'gen' -Hotkey 'CTRL+I' -Desc 'ccode: AI 生成 C 代码'
New-CcodeShortcut -FileName 'ccode-complete.lnk' -ArgLine 'complete' -Hotkey 'CTRL+ALT+K' -Desc 'ccode: AI 补全 C 代码'

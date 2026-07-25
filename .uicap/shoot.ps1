$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$base = 'http://127.0.0.1:8931/wf/index.html'
$out = 'A:\Dev\Dev Tool\adb-auto-game\.uicap\shots'
New-Item -ItemType Directory -Path $out -Force | Out-Null

$shots = @(
  @{n='edit-1600';      u="$base";            w=1600; h=1000},
  @{n='runmenu-1600';   u="$base#runmenu";    w=1600; h=1000},
  @{n='devmenu-1600';   u="$base#devmenu";    w=1600; h=1000},
  @{n='speedpop-1600';  u="$base#speedpop";   w=1600; h=1000},
  @{n='speedon-1600';   u="$base#speedon";    w=1600; h=1000},
  @{n='select-1600';    u="$base#select";     w=1600; h=1000},
  @{n='preview-1600';   u="$base#preview";    w=1600; h=1000},
  @{n='validate-1600';  u="$base#validate";   w=1600; h=1000},
  @{n='edit-1366';      u="$base";            w=1366; h=768},
  @{n='edit-1100';      u="$base";            w=1100; h=700}
)
foreach ($s in $shots) {
  & $chrome --headless=new --disable-gpu --hide-scrollbars `
    --window-size="$($s.w),$($s.h)" --virtual-time-budget=9000 `
    --screenshot="$out\$($s.n).png" $s.u 2>$null | Out-Null
  Write-Output "shot $($s.n)"
}
Get-ChildItem $out -Filter *.png | Select-Object Name, Length

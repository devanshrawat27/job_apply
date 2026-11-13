import { execFile } from 'child_process'

/**
 * Minimize the automation Chromium window on Windows.
 *
 * The browser must stay headed (some X chat/DM flows render better with a real
 * window), but it should not cover the desktop. Minimizing keeps a taskbar entry
 * so the human can restore it when they want to watch.
 */
/**
 * Restore (un-minimize) the automation Chromium window.
 *
 * Chromium throttles timers/rendering in a minimized window, so flows that must
 * read the DOM right after an action (e.g. verifying a DM persisted after a
 * reload) restore the window for the duration of the check and minimize again
 * afterwards.
 */
export function restoreBrowserWindow(profileName = 'browser-profile') {
  if (process.platform !== 'win32') return Promise.resolve(false)

  const script = `
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class JPWinRestore {
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
}
'@
$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*--user-data-dir=*${profileName}*' }
foreach ($p in $procs) {
  $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
  if ($gp -and $gp.MainWindowHandle -ne 0) {
    [JPWinRestore]::ShowWindow($gp.MainWindowHandle, 9) | Out-Null
  }
}
`

  return new Promise((resolve) => {
    execFile(
      'powershell',
      ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
      { timeout: 15000, windowsHide: true },
      (err) => resolve(!err),
    )
  })
}

export function minimizeBrowserWindow(profileName = 'browser-profile') {
  if (process.platform !== 'win32') return Promise.resolve(false)

  const script = `
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class JPWin {
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
'@
$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*--user-data-dir=*${profileName}*' }
foreach ($p in $procs) {
  $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
  if ($gp -and $gp.MainWindowHandle -ne 0) {
    [JPWin]::ShowWindow($gp.MainWindowHandle, 6) | Out-Null
  }
}
`

  return new Promise((resolve) => {
    execFile(
      'powershell',
      ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
      { timeout: 15000, windowsHide: true },
      (err) => resolve(!err),
    )
  })
}

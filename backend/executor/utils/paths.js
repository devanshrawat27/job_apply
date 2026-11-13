import path from 'path'
import os from 'os'

/** Platform data dir, same as the reference executor. */
export function getAppDataDir() {
  const override = process.env.AUTOMATION_DATA_DIR
  if (override) return override

  const platform = process.platform
  if (platform === 'darwin') {
    return path.join(os.homedir(), 'Library', 'Application Support', 'jobpilot')
  }
  if (platform === 'win32') {
    return path.join(process.env.APPDATA || os.homedir(), 'jobpilot')
  }
  const xdg = process.env.XDG_DATA_HOME
  return xdg ? path.join(xdg, 'jobpilot') : path.join(os.homedir(), '.local', 'share', 'jobpilot')
}

/**
 * Persistent Chromium profile.
 *
 * X's encrypted chat keeps its keys in IndexedDB. A fresh profile every run has
 * no keys, so the chat renders blank. Keeping one profile means the chat stays
 * unlocked after the first passcode entry.
 */
export function getBrowserProfileDir() {
  return path.join(getAppDataDir(), 'browser-profile')
}

import fs from 'fs'
import os from 'os'
import path from 'path'
import { execFileSync } from 'node:child_process'
import { chromium } from 'playwright'

import { getStealthConfig } from './stealthConfig.js'
import { getAppDataDir, getProfileSuffix } from './paths.js'

/**
 * Dedicated Chromium profile for chatgpt.com.
 *
 * It is deliberately separate from the X profile: the X browser is attached
 * over CDP while scanning, and two scripts must never share one profile.
 */
const LAUNCH_ARGS = [
  '--disable-blink-features=AutomationControlled',
  '--disable-features=IsolateOrigins,site-per-process',
  '--disable-site-isolation-trials',
  '--no-first-run',
  '--no-default-browser-check',
]

const USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

export function getChatgptProfileDir() {
  return path.join(getAppDataDir(), `chatgpt-profile${getProfileSuffix()}`)
}

export function getConnectedMarker() {
  return path.join(getChatgptProfileDir(), '.jobpilot-connected')
}

export function markConnected() {
  try {
    fs.mkdirSync(getChatgptProfileDir(), { recursive: true })
    fs.writeFileSync(getConnectedMarker(), new Date().toISOString(), 'utf8')
  } catch {
    // best effort
  }
}

async function launchFromProfile(profileDir, headless) {
  const config = getStealthConfig()
  const context = await chromium.launchPersistentContext(profileDir, {
    headless: headless ?? config.headless,
    args: LAUNCH_ARGS,
    ignoreDefaultArgs: ['--enable-automation'],
    chromiumSandbox: true,
    locale: config.locale,
    timezoneId: config.timezone,
    viewport: { width: 1280, height: 900 },
    colorScheme: 'light',
    userAgent: USER_AGENT,
  })

  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined })
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] })
  })

  const page = context.pages()[0] || (await context.newPage())
  return { context, page }
}

function releaseProfileLock(profileDir) {
  if (process.platform !== "win32") return
  try {
    const needle = path.basename(profileDir)
    const listScript =
      `Get-CimInstance Win32_Process | ` +
      `Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*${needle}*' } | ` +
      `Select-Object -ExpandProperty ProcessId`
    const output = execFileSync("powershell.exe", ["-NoProfile", "-Command", listScript], {
      timeout: 15000,
      encoding: "utf8",
    })
    for (const line of String(output || "").split(/\s+/)) {
      if (!/^\d+$/.test(line)) continue
      try {
        execFileSync("taskkill", ["/F", "/T", "/PID", line], { stdio: "ignore", timeout: 8000 })
      } catch {
        // already gone
      }
    }
    // Chrome leaves a stale SingletonLock behind when it is force-closed.
    // Launching with that file makes Chromium think another process owns the
    // profile ("Opening in existing browser session") and the page closes.
    for (const name of ["SingletonLock", "SingletonCookie", "SingletonSocket"]) {
      try {
        fs.rmSync(path.join(profileDir, name), { force: true })
      } catch {
        // best effort
      }
    }
  } catch {
    // best effort
  }
}

export async function launchChatgpt({ headless, copyOnLock = true } = {}) {
  const profileDir = getChatgptProfileDir()
  fs.mkdirSync(profileDir, { recursive: true })

  // A timed-out ask can leave its Chrome process behind. That locks the profile
  // and makes every later redraft fail with "element is not visible" or
  // "browser has been closed". Clear our own profile before every launch.
  releaseProfileLock(profileDir)
  await new Promise((resolve) => setTimeout(resolve, 600))

  try {
    return await launchFromProfile(profileDir, headless)
  } catch (error) {
    const message = String(error?.message || '')
    // Chrome only allows one process per user-data-dir.
    if (!copyOnLock || !/existing browser session|Target page, context or browser has been closed/i.test(message)) {
      throw error
    }

    releaseProfileLock(profileDir)
    await new Promise((resolve) => setTimeout(resolve, 1200))
    try {
      return await launchFromProfile(profileDir, headless)
    } catch {
      // Still locked: copy the profile as a last resort.
      try {
        const tempDir = path.join(os.tmpdir(), `jobpilot-chatgpt-${process.pid}-${Date.now()}`)
        fs.cpSync(profileDir, tempDir, { recursive: true })
        const result = await launchFromProfile(tempDir, headless)
        result.context.__jobpilotTempProfile = tempDir
        return result
      } catch {
        throw new Error(
          "ChatGPT is open in another window. Close it and press Redraft again.",
        )
      }
    }
  }
}

export async function cleanupChatgpt(context) {
  const tempDir = context?.__jobpilotTempProfile
  await context?.close().catch(() => {})
  if (tempDir) {
    try {
      fs.rmSync(tempDir, { recursive: true, force: true })
    } catch {
      // best effort
    }
  }
}

export const CHATGPT_COMPOSER = '#prompt-textarea, div[contenteditable="true"], textarea'
export const CHATGPT_ASSISTANT = '[data-message-author-role="assistant"]'

export async function isLoggedIn(page) {
  const composer = await page.locator(CHATGPT_COMPOSER).count().catch(() => 0)
  if (!composer) return false
  const loginCta = await page
    .locator('button:has-text("Log in"), a:has-text("Log in"), [data-testid="login-button"]')
    .count()
    .catch(() => 0)
  return loginCta === 0
}

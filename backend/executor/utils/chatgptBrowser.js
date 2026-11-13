import fs from 'fs'
import path from 'path'
import { chromium } from 'playwright'

import { getStealthConfig } from './stealthConfig.js'
import { getAppDataDir } from './paths.js'

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
  return path.join(getAppDataDir(), 'chatgpt-profile')
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

export async function launchChatgpt({ headless } = {}) {
  const config = getStealthConfig()
  const profileDir = getChatgptProfileDir()
  fs.mkdirSync(profileDir, { recursive: true })

  const context = await chromium.launchPersistentContext(profileDir, {
    headless: headless ?? config.headless,
    args: LAUNCH_ARGS,
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

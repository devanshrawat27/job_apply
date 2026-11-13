import fs from 'fs'
import { chromium } from 'playwright'
import { getStealthConfig } from './stealthConfig.js'
import { injectCookies } from './cookies.js'
import { getBrowserProfileDir } from './paths.js'

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

/** Attach to the persistent host browser over CDP when one is running. */
async function attachToHost() {
  const endpoint = process.env.BROWSER_CDP_ENDPOINT
  if (!endpoint) return null

  try {
    const browser = await chromium.connectOverCDP(endpoint, { timeout: 8000 })
    const context = browser.contexts()[0]
    if (!context) return null

    // Reuse the host's page: it already holds the logged-in X session.
    const page = context.pages()[0] || (await context.newPage())

    const safeBrowser = new Proxy(browser, {
      get(target, prop, receiver) {
        if (prop === 'close') return async () => {}
        const value = Reflect.get(target, prop, receiver)
        return typeof value === 'function' ? value.bind(target) : value
      },
    })

    return { browser: safeBrowser, context, page }
  } catch (err) {
    console.log(`[browser.js] CDP attach failed: ${err.message}`)
    return null
  }
}

/**
 * Launch a browser ready for X automation.
 *
 * Uses a persistent profile (like the reference executor) so X's encrypted
 * chat keeps its IndexedDB keys between runs. Falls back to a throwaway context
 * if the profile cannot be opened.
 */
export async function launchBrowser({ withSession = true } = {}) {
  const shared = await attachToHost()
  if (shared) {
    console.log('[browser.js] attached to persistent host')
    return shared
  }

  const config = getStealthConfig()
  const profileDir = getBrowserProfileDir()

  const baseOptions = {
    headless: config.headless,
    args: LAUNCH_ARGS,
    proxy: config.proxy,
    userAgent: USER_AGENT,
    locale: config.locale,
    timezoneId: config.timezone,
    viewport: { width: 1366, height: 850 },
    colorScheme: 'light',
  }
  if (config.channel) baseOptions.channel = config.channel

  try {
    fs.mkdirSync(profileDir, { recursive: true })
    const context = await chromium.launchPersistentContext(profileDir, baseOptions)

    await context.addInitScript(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined })
      Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] })
    })

    if (withSession) await injectCookies(context, config.credentials)

    const page = context.pages()[0] || (await context.newPage())
    // A persistent profile starts on about:blank; land on X so the window is
    // not an empty white page between runs.
    if (withSession && page.url() === 'about:blank') {
      await page
        .goto('https://x.com/home', { waitUntil: 'domcontentloaded', timeout: 45000 })
        .catch(() => {})
    }
    console.log('[browser.js] persistent profile ready')

    // Playwright exposes only a context here; give scripts a browser-like handle.
    const browserLike = {
      close: async () => context.close().catch(() => {}),
    }
    return { browser: browserLike, context, page }
  } catch (err) {
    console.log(`[browser.js] persistent profile failed (${err.message}), using a fresh context`)
  }

  const browser = await chromium.launch({
    headless: config.headless,
    args: LAUNCH_ARGS,
    proxy: config.proxy,
    channel: config.channel,
  })

  const context = await browser.newContext({
    userAgent: USER_AGENT,
    locale: config.locale,
    timezoneId: config.timezone,
    viewport: { width: 1366, height: 850 },
    colorScheme: 'light',
  })

  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined })
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] })
  })

  if (withSession) await injectCookies(context, config.credentials)

  const page = await context.newPage()
  return { browser, context, page }
}

/** X shows the logged-out shell when the cookies are dead. */
export async function isLoggedOut(page) {
  const loginInput = await page
    .locator('input[name="text"], input[name="username"], a[href="/login"]')
    .count()
    .catch(() => 0)
  return loginInput > 0
}

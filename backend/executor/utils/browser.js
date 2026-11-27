import fs from 'fs'
import { chromium } from 'playwright'
import { getStealthConfig } from './stealthConfig.js'
import { injectCookies } from './cookies.js'
import { getBrowserProfileDir } from './paths.js'

const LAUNCH_ARGS = [
  '--disable-blink-features=AutomationControlled',
  '--no-first-run',
  '--no-default-browser-check',
]
// Naukri's edge rejects headless Chromium, but the user still wants the window
// out of the way. A real Chrome placed far off-screen renders normally without
// covering the desktop.
if (process.env.STEALTH_OFFSCREEN === '1') {
  LAUNCH_ARGS.push('--window-position=-32000,-32000', '--window-size=1366,850')
}

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

    // Reuse the host's page: it already holds the logged-in session. Prefer a
    // real site page over a leftover about:blank tab.
    const pages = context.pages()
    const page =
      pages.find((item) => !/^about:blank$/i.test(item.url()) && !item.url().startsWith('devtools://')) ||
      pages[0] ||
      (await context.newPage())

    const safeBrowser = new Proxy(browser, {
      get(target, prop, receiver) {
        if (prop === 'close') return async () => {}
        const value = Reflect.get(target, prop, receiver)
        return typeof value === 'function' ? value.bind(target) : value
      },
    })

    return { browser: safeBrowser, context, page, attached: true }
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
    // Playwright adds --enable-automation by default, which shows Chrome's
    // "controlled by automated test software" bar. X treats that as a bot sign.
    ignoreDefaultArgs: ['--enable-automation'],
    // Keep the Chromium sandbox: launching with --no-sandbox shows
    // "unsupported command-line flag", another clear automation signal.
    chromiumSandbox: true,
    proxy: config.proxy,
    userAgent: USER_AGENT,
    locale: config.locale,
    timezoneId: config.timezone,
    viewport: { width: 1366, height: 850 },
    colorScheme: 'light',
  }
  // With the installed Chrome, keep its real user agent: a hardcoded UA that
  // disagrees with the client hints is an easy bot signal for Cloudflare.
  if (!config.channel) baseOptions.userAgent = USER_AGENT
  if (config.channel) baseOptions.channel = config.channel

  try {
    if (process.env.JOBPILOT_EPHEMERAL === '1') {
      // Headless scans must not fight the visible Naukri window for its profile
      // lock; a fresh context with the stored cookies is enough.
      throw new Error('ephemeral context requested')
    }
    fs.mkdirSync(profileDir, { recursive: true })
    let context
    try {
      context = await chromium.launchPersistentContext(profileDir, baseOptions)
    } catch (err) {
      // Installed Chrome is far less suspicious to X than bundled Chromium,
      // but never fail the run if it is missing or already busy.
      if (!baseOptions.channel) throw err
      console.log(
        `[browser.js] ${baseOptions.channel} launch failed (${err.message}); retrying with bundled Chromium`,
      )
      const { channel: _channel, ...rest } = baseOptions
      context = await chromium.launchPersistentContext(profileDir, rest)
    }

    await context.addInitScript(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined })
      Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] })
    })

    if (withSession) await injectCookies(context, config.credentials)

    // A killed or timed-out run can leave empty tabs in the persistent profile;
    // every new launch would restore them and the window would fill up.
    for (const existing of context.pages()) {
      if (existing.url() === 'about:blank') {
        await existing.close().catch(() => {})
      }
    }
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
    return { browser: browserLike, context, page, attached: false }
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
  return { browser, context, page, attached: false }
}

/** X shows the logged-out shell when the cookies are dead. */
export async function isLoggedOut(page) {
  const loginInput = await page
    .locator('input[name="text"], input[name="username"], a[href="/login"]')
    .count()
    .catch(() => 0)
  return loginInput > 0
}

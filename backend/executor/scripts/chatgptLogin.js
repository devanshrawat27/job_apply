/**
 * Open chatgpt.com in the dedicated profile and wait for the human to log in.
 *
 * The browser stays visible on purpose: the human types their own credentials
 * into OpenAI's page. We only watch for the composer to appear.
 */

import { CHATGPT_COMPOSER, isLoggedIn, launchChatgpt, markConnected } from '../utils/chatgptBrowser.js'
import { reportFail, reportOk } from '../utils/report.js'

const TIMEOUT_MS = 300000
const watchdog = setTimeout(() => {
  reportFail('LOGIN_TIMEOUT', 'ChatGPT login was not completed in 5 minutes')
  process.exit(1)
}, TIMEOUT_MS + 15000)

async function main() {
  const { context, page } = await launchChatgpt({ headless: false })

  try {
    await page.goto('https://chatgpt.com/', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(3000)

    const deadline = Date.now() + TIMEOUT_MS
    while (Date.now() < deadline) {
      if (await isLoggedIn(page)) {
        markConnected()
        reportOk({ logged_in: true })
        return
      }
      await page.waitForTimeout(3000)
    }

    const composer = await page.locator(CHATGPT_COMPOSER).count().catch(() => 0)
    reportFail(
      'LOGIN_TIMEOUT',
      composer
        ? 'ChatGPT loaded but the login prompt is still showing - finish the login and retry'
        : 'ChatGPT login was not completed in 5 minutes',
    )
  } finally {
    clearTimeout(watchdog)
    await context.close().catch(() => {})
  }
}

main().catch((err) => {
  clearTimeout(watchdog)
  reportFail('ERROR', err.message)
  process.exitCode = 1
})

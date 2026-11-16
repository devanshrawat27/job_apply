/**
 * Open the JobPilot Chromium profile on X and wait for the human to finish
 * login / verification. Never clicks, never types. When the session is live it
 * prints the fresh auth cookies so the backend can store them.
 */

import { launchBrowser } from '../utils/browser.js'

const LIMIT_MIN = 30
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function main() {
  const { context } = await launchBrowser()
  try {
    let page = context.pages()[0] || (await context.newPage())
    await page
      .goto('https://x.com/home', { waitUntil: 'domcontentloaded', timeout: 60000 })
      .catch(() => {})
    await page.bringToFront().catch(() => {})

    const deadline = Date.now() + LIMIT_MIN * 60 * 1000
    while (Date.now() < deadline) {
      await sleep(5000)
      try {
        const pages = context.pages()
        page = pages[pages.length - 1] || page
        const loggedIn = await page
          .locator('[data-testid="SideNav_AccountSwitcher_Button"]')
          .count()
          .catch(() => 0)
        if (loggedIn > 0) {
          const cookies = await context.cookies('https://x.com')
          const pick = (name) => cookies.find((c) => c.name === name)?.value || ''
          console.log(
            'X_CREDS ' +
              JSON.stringify({
                auth_token: pick('auth_token'),
                ct0: pick('ct0'),
                twid: pick('twid'),
                url: page.url(),
              }),
          )
          await sleep(3000)
          return
        }
      } catch {
        // Tab replaced or navigated: keep waiting, the human is still working.
      }
    }
    console.log(`X_LOGIN_NOT_DONE ${context.pages().at(-1)?.url() || 'closed'}`)
  } finally {
    await context.close().catch(() => {})
  }
}

main().catch((err) => {
  console.log('ERROR', err.message)
  process.exitCode = 1
})

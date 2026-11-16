/**
 * Open the JobPilot X profile on the account-access page and leave the window
 * open so the human can finish X's verification. Read-only: it never clicks.
 */

import { launchBrowser } from '../utils/browser.js'

const HARD_LIMIT_MIN = 20

async function main() {
  const { context, page } = await launchBrowser()
  try {
    await page.goto('https://x.com/account/access', {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    })
    await page.bringToFront().catch(() => {})

    const deadline = Date.now() + HARD_LIMIT_MIN * 60 * 1000
    while (Date.now() < deadline) {
      await page.waitForTimeout(5000)
      const url = page.url()
      const composer = await page
        .locator('[data-testid="tweetTextarea_0"], [contenteditable="true"]')
        .count()
        .catch(() => 0)
      if (url.includes('/home') || composer > 0) {
        console.log(`X_OK ${url}`)
        await page.waitForTimeout(5000)
        return
      }
    }
    console.log(`X_STILL_BLOCKED ${page.url()}`)
  } finally {
    await context.close().catch(() => {})
  }
}

main().catch((err) => {
  console.log('ERROR', err.message)
  process.exitCode = 1
})

/**
 * Follow a user. Used only as a fallback: some accounts only accept DMs from
 * people they have a connection with, so the engine follows and retries.
 *
 *   SCRIPT_ARG_USERNAME   handle without @
 */

import { launchBrowser } from '../utils/browser.js'
import { humanClick, randomWait } from '../utils/humanize.js'
import { reportOk, reportFail } from '../utils/report.js'

const HARD_DEADLINE_MS = 90000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'follow script exceeded its deadline')
  process.exit(1)
}, HARD_DEADLINE_MS)

const USERNAME = (process.env.SCRIPT_ARG_USERNAME || '').trim().replace(/^@/, '')

async function follow() {
  const { browser, page } = await launchBrowser()

  try {
    await page.goto(`https://x.com/${USERNAME}`, { waitUntil: 'domcontentloaded', timeout: 45000 })
    await randomWait(2500, 4000)

    const body = await page.locator('body').innerText().catch(() => '')
    if (/this account doesn.?t exist|account not found/i.test(body)) {
      reportFail('TARGET_NOT_FOUND', `@${USERNAME} does not exist`)
      return
    }
    if (/rate limit|something went wrong\. try reloading/i.test(body)) {
      reportFail('RATE_LIMITED', 'X is rate-limiting this session')
      return
    }

    const already = page.locator('[data-testid$="-unfollow"]').first()
    if ((await already.count()) > 0) {
      reportOk({ username: USERNAME, already_following: true })
      return
    }

    const button = page.locator('[data-testid$="-follow"]').first()
    if ((await button.count()) === 0) {
      reportFail('SELECTOR_MISS', 'follow button not found on the profile')
      return
    }

    await humanClick(page, button)
    await randomWait(1500, 3000)

    // The button flips to "unfollow" once the follow lands. "Pending" also
    // means the request was sent, which is enough for a DM attempt.
    const confirmDeadline = Date.now() + 12000
    let confirmed = false
    while (Date.now() < confirmDeadline) {
      const flip = await page.locator('[data-testid$="-unfollow"]').count().catch(() => 0)
      const pending = await page
        .locator('text=/^Pending$/i')
        .first()
        .isVisible()
        .catch(() => false)
      if (flip > 0 || pending) {
        confirmed = true
        break
      }
      await new Promise((resolve) => setTimeout(resolve, 800))
    }

    if (!confirmed) {
      reportFail('UNKNOWN', 'clicked follow but could not confirm the state change')
      return
    }

    reportOk({ username: USERNAME, followed: true })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
  } finally {
    await browser?.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

if (!USERNAME) {
  reportFail('VALIDATION', 'SCRIPT_ARG_USERNAME is required')
  process.exitCode = 1
  clearTimeout(watchdog)
} else {
  follow().finally(() => clearTimeout(watchdog))
}

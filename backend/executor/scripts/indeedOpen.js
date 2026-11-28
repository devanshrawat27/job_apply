/**
 * Navigate the already-open Indeed window to a URL without opening another one.
 */

import { launchBrowser } from '../utils/browser.js'
import { reportFail, reportOk } from '../utils/report.js'

const URL = (process.env.SCRIPT_ARG_URL || '').trim()

async function run() {
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-indeed`
  process.env.STEALTH_HEADLESS = '0'
  process.env.STEALTH_OFFSCREEN = '1'
  const { browser, page } = await launchBrowser({ withSession: false })
  try {
    if (URL) {
      await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {})
      await page.waitForTimeout(2500)
    }
    await page.bringToFront().catch(() => {})
    reportOk({ ok: true, url: page.url() })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
  } finally {
    await browser?.close().catch(() => {})
  }
}

if (!URL) {
  reportFail('VALIDATION', 'SCRIPT_ARG_URL is required')
  process.exit(1)
} else {
  run()
    .then(() => setTimeout(() => process.exit(0), 100))
    .catch(() => process.exit(1))
}

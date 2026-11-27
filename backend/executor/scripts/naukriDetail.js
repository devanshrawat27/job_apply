/**
 * Classify Naukri job pages as direct-apply, external, already applied or unknown.
 *
 *   SCRIPT_ARG_URLS   comma separated Naukri job URLs (max 6)
 *   NAUKRI_COOKIES    JSON cookie object (optional)
 */

import { launchBrowser } from '../utils/browser.js'
import { reportFail, reportOk } from '../utils/report.js'

const URLS = (process.env.SCRIPT_ARG_URLS || '')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean)
  .slice(0, 6)

const HARD_DEADLINE_MS = 300000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Naukri detail check did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

function storedCookies() {
  try {
    const parsed = JSON.parse(process.env.NAUKRI_COOKIES || '{}')
    if (!parsed || typeof parsed !== 'object') return []
    return Object.entries(parsed)
      .filter(([name, value]) => name && value)
      .map(([name, value]) => ({ name, value: String(value), domain: '.naukri.com', path: '/' }))
  } catch {
    return []
  }
}

async function classify(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
  await page.waitForTimeout(6500)
  return page.evaluate(() => {
    const text = (document.body?.innerText || '').replace(/\s+/g, ' ')
    const applyButton = document.querySelector('.apply-button')
    const companyButton = document.querySelector('.company-site-button')
    if (companyButton) return { type: 'external', url: location.href }
    if (applyButton) return { type: 'direct', url: location.href }
    if (/already applied|applied on/i.test(text) && !/apply on company site/i.test(text)) {
      return { type: 'applied', url: location.href }
    }
    if (/apply on company site|apply on company website|external apply/i.test(text)) {
      return { type: 'external', url: location.href }
    }
    if (/\bapply\b/i.test(text)) return { type: 'direct', url: location.href }
    return { type: 'unknown', url: location.href }
  })
}

async function run() {
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-naukri`
  process.env.JOBPILOT_EPHEMERAL = '1'
  const { browser, context, page } = await launchBrowser({ withSession: false })
  try {
    const cookies = storedCookies()
    if (cookies.length) await context.addCookies(cookies).catch(() => {})

    const results = []
    for (const url of URLS) {
      const result = await classify(page, url).catch((err) => ({
        type: 'unknown',
        url,
        error: String(err),
      }))
      results.push(result)
    }
    reportOk({ results })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
    throw err
  } finally {
    await browser?.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

if (!URLS.length) {
  reportFail('VALIDATION', 'SCRIPT_ARG_URLS is required')
  process.exit(1)
} else {
  run()
    .then(() => {
      clearTimeout(watchdog)
      setTimeout(() => process.exit(0), 100)
    })
    .catch(() => process.exit(1))
}

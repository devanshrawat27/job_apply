/**
 * Classify Indeed job pages: direct Indeed apply, external company site, or
 * already applied.
 *
 *   SCRIPT_ARG_URLS   comma-separated Indeed viewjob URLs
 *   INDEED_COOKIES    JSON cookie object (optional)
 */

import { launchBrowser } from '../utils/browser.js'
import { reportFail, reportOk } from '../utils/report.js'

const URLS = (process.env.SCRIPT_ARG_URLS || '')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean)
const HARD_DEADLINE_MS = 240000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Indeed detail check did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

function clean(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

async function classify(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
  await page.waitForTimeout(6000)
  const info = await page.evaluate(() => {
    const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim()
    const links = [...document.querySelectorAll('a')]
    const buttons = [...document.querySelectorAll('button')]
    const direct = links.find(
      (el) =>
        /apply now/i.test(norm(el.innerText)) ||
        /smartapply\.indeed\.com|indeedapply/i.test(el.getAttribute('href') || ''),
    )
    const external = buttons.find((el) => /apply on company site/i.test(norm(el.innerText)))
    const body = norm(document.body?.innerText)
    return {
      url: location.href,
      body: body.slice(0, 1200),
      direct: Boolean(direct),
      external: Boolean(external),
      applied: /application submitted|you have applied|already applied|applied on/i.test(body),
      cloudflare: /just a moment|performing security verification|additional verification required/i.test(body),
      blocked: /access denied|unusual traffic|captcha/i.test(body),
    }
  })
  if (info.cloudflare || info.blocked) return { type: 'unknown', url, error: "Indeed's bot check" }
  if (info.applied) return { type: 'applied', url }
  if (info.direct) return { type: 'direct', url }
  if (info.external) return { type: 'external', url }
  return { type: 'unknown', url, error: 'no apply control found' }
}

async function run() {
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-indeed`
  process.env.JOBPILOT_EPHEMERAL = '1'
  const { browser, context, page } = await launchBrowser({ withSession: false })

  try {
    const stored = (() => {
      try {
        return JSON.parse(process.env.INDEED_COOKIES || '{}')
      } catch {
        return {}
      }
    })()
    const cookies = Object.entries(stored)
      .filter(([name, value]) => name && value)
      .map(([name, value]) => ({ name, value: String(value), domain: '.indeed.com', path: '/' }))
    if (cookies.length) await context.addCookies(cookies).catch(() => {})

    const results = []
    for (const url of URLS) {
      results.push(await classify(page, url).catch((err) => ({ type: 'unknown', url, error: err.message })))
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
      setTimeout(() => process.exit(0), 120)
    })
    .catch(() => process.exit(1))
}

/**
 * Search Naukri.com and return the job cards.
 *
 * Naukri's edge rejects headless Chromium, so the backend launches installed
 * Chrome in a hidden (off-screen) window. The user's Naukri cookies are
 * injected when an account is connected; guest search works without them.
 *
 *   SCRIPT_ARG_QUERIES   comma separated search terms
 *   SCRIPT_ARG_LIMIT     cards per query (default 20)
 *   NAUKRI_COOKIES       JSON object of cookie name/value pairs (optional)
 */

import { launchBrowser } from '../utils/browser.js'
import { reportFail, reportOk } from '../utils/report.js'

const QUERIES = (process.env.SCRIPT_ARG_QUERIES || process.env.SCRIPT_ARG_QUERY || '')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean)
  .slice(0, 3)
const LIMIT = Math.max(1, Math.min(Number(process.env.SCRIPT_ARG_LIMIT || 20), 40))

const HARD_DEADLINE_MS = 300000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Naukri search did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

function slug(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
}

function parseCookies() {
  const raw = process.env.NAUKRI_COOKIES || ''
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return []
    return Object.entries(parsed)
      .filter(([name, value]) => name && value)
      .map(([name, value]) => ({ name, value: String(value), domain: '.naukri.com', path: '/' }))
  } catch {
    return []
  }
}

async function extractCards(page) {
  return page.evaluate(() => {
    const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim()
    const cards = [...document.querySelectorAll('.srp-jobtuple-wrapper')]
    return cards.map((card) => {
      const link = card.querySelector('h2 a.title')
      const id = card.getAttribute('data-job-id') || ''
      const title = clean(link?.getAttribute('title') || link?.innerText || '')
      const company = clean(card.querySelector('.comp-name')?.innerText || '')
      const experience = clean(
        card.querySelector('.expwdth')?.getAttribute('title') ||
          card.querySelector('.expwdth')?.innerText ||
          '',
      )
      const location = clean(
        card.querySelector('.locWdth')?.getAttribute('title') ||
          card.querySelector('.locWdth')?.innerText ||
          '',
      )
      const snippet = clean(card.querySelector('.job-desc')?.innerText || '')
      const posted = clean(card.querySelector('.job-post-day')?.innerText || '')
      const skills = [...card.querySelectorAll('.tags-gt li')]
        .map((item) => clean(item.innerText))
        .filter(Boolean)
      return {
        id,
        title,
        company,
        experience,
        location,
        snippet,
        posted,
        skills,
        url: link?.getAttribute('href') || '',
      }
    })
  })
}

async function search() {
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-naukri`
  process.env.JOBPILOT_EPHEMERAL = '1'

  const { browser, context, page } = await launchBrowser({ withSession: false })
  try {
    const stored = parseCookies()
    if (stored.length) {
      await context.addCookies(stored).catch(() => {})
    }

    const jobs = []
    const seen = new Set()
    for (const query of QUERIES) {
      const url =
        `https://www.naukri.com/${slug(query)}-jobs` +
        `?k=${encodeURIComponent(query)}&experience=0&jobAge=1`
      await page
        .goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 })
        .catch(() => {})
      await page.waitForTimeout(9000)

      const body = (await page.locator('body').innerText().catch(() => '')).toLowerCase()
      if (/access denied|errors\.edgesuite\.net/.test(body)) {
        return reportFail(
          'NAUKRI_BLOCKED',
          'Naukri blocked this browser session. Close other Naukri windows and retry.',
        )
      }

      const cards = await extractCards(page)
      for (const card of cards.slice(0, LIMIT)) {
        if (!card.id || seen.has(card.id)) continue
        seen.add(card.id)
        jobs.push({ ...card, query })
      }
    }

    console.log(`naukri: ${jobs.length} cards for ${QUERIES.length} queries`)
    reportOk({ jobs, queries: QUERIES })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
    throw err
  } finally {
    await browser?.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

if (!QUERIES.length) {
  reportFail('VALIDATION', 'SCRIPT_ARG_QUERIES is required')
  process.exit(1)
} else {
  search()
    .then(() => {
      clearTimeout(watchdog)
      setTimeout(() => process.exit(0), 100)
    })
    .catch(() => process.exit(1))
}

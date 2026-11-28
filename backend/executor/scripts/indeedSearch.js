/**
 * Search Indeed India for fresh job cards.
 *
 * Indeed's public search works in installed Chrome's headless mode, so this
 * runs without a visible window. Login is only needed later, when applying.
 *
 *   SCRIPT_ARG_QUERIES  comma-separated search terms
 *   SCRIPT_ARG_LIMIT    max cards per query (default 20)
 *   INDEED_COOKIES      JSON cookie object (optional)
 */

import { launchBrowser } from '../utils/browser.js'
import { reportFail, reportOk } from '../utils/report.js'

const QUERIES = (process.env.SCRIPT_ARG_QUERIES || '')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean)
const LIMIT = Math.max(1, Math.min(parseInt(process.env.SCRIPT_ARG_LIMIT || '20', 10) || 20, 40))
const DETAIL_LIMIT = Math.max(
  0,
  Math.min(parseInt(process.env.SCRIPT_ARG_DETAIL_LIMIT || '10', 10) || 10, 20),
)
const HARD_DEADLINE_MS = 300000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Indeed search did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

function clean(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

async function extractCards(page) {
  return page.evaluate(() => {
    const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim()
    const nodes = [
      ...document.querySelectorAll(
        'div.job_seen_beacon, li.css-5lfssm, div[data-testid="slider_item"], .jobsearch-ResultsList > li',
      ),
    ]
    const seen = new Set()
    const out = []
    for (const node of nodes) {
      const link = node.querySelector('a[href*="jk="], a[href*="/viewjob"]')
      const href = link?.getAttribute('href') || ''
      const jk =
        (href.match(/[?&]jk=([a-f0-9]+)/i) || [])[1] ||
        node.querySelector('[data-jk]')?.getAttribute('data-jk') ||
        ''
      if (!jk || seen.has(jk)) continue
      seen.add(jk)

      const title =
        norm(node.querySelector('h2, .jobTitle, [data-testid="jobTitle"]')?.innerText) ||
        norm(link?.innerText)
      const company = norm(
        node.querySelector(
          '[data-testid="company-name"], .companyName, .company_location .companyName',
        )?.innerText,
      )
      const location = norm(
        node.querySelector('[data-testid="text-location"], .companyLocation')?.innerText,
      )
      const salary = norm(
        node.querySelector(
          '[data-testid="attribute_snippet_testid"], .salary-snippet-container, .metadata.salary-snippet-container',
        )?.innerText,
      )
      const snippet = norm(
        node.querySelector('.job-snippet, [data-testid="belowJobSnippet"]')?.innerText,
      )
      const posted = norm(
        node.querySelector('.date, [data-testid="myJobsStateDate"], .jobsearch-JobMetadataFooter')
          ?.innerText,
      )
      const text = norm(node.innerText)
      out.push({
        id: jk,
        title: title.slice(0, 140),
        company: company.slice(0, 120),
        location: location.slice(0, 120),
        salary: salary.slice(0, 80),
        snippet: snippet.slice(0, 500),
        posted: posted.slice(0, 80),
        easily_apply: /easily apply/i.test(text),
        url: `https://in.indeed.com/viewjob?jk=${jk}`,
      })
    }
    return out
  })
}

async function classifyDetail(page, url) {
  // Visit details in the same context as the search. A fresh context gets
  // Cloudflare's "additional verification" page; the warmed search context does
  // not, so this is the reliable way to tell direct vs company-site applies.
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
  await page.waitForTimeout(5500)
  const info = await page.evaluate(() => {
    const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim()
    const body = norm(document.body?.innerText)
    const links = [...document.querySelectorAll('a')]
    const buttons = [...document.querySelectorAll('button')]
    return {
      url: location.href,
      cloudflare: /just a moment|performing security verification|additional verification required/i.test(body),
      blocked: /access denied|unusual traffic|captcha/i.test(body),
      direct: links.some(
        (el) =>
          /apply now/i.test(norm(el.innerText)) ||
          /smartapply\.indeed\.com|indeedapply/i.test(el.getAttribute('href') || ''),
      ),
      external: buttons.some((el) => /apply on company site/i.test(norm(el.innerText))),
      applied: /application submitted|you have applied|already applied|applied on/i.test(body),
    }
  })
  if (info.cloudflare || info.blocked) return { type: 'unknown', blocked: true }
  if (info.applied) return { type: 'applied' }
  if (info.direct) return { type: 'direct' }
  if (info.external) return { type: 'external' }
  return { type: 'unknown' }
}

async function search() {
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

    const jobs = []
    const seen = new Set()
    for (const query of QUERIES) {
      const url =
        `https://in.indeed.com/jobs?q=${encodeURIComponent(query)}` +
        '&l=India&fromage=1&sort=date'
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
      await page.waitForTimeout(9000)

      const body = clean(await page.locator('body').innerText().catch(() => ''))
      if (/just a moment|performing security verification/i.test(body)) {
        return reportFail('INDEED_BLOCKED', 'Indeed is showing a Cloudflare verification page')
      }
      if (/access denied|unusual traffic|captcha/i.test(body)) {
        return reportFail('INDEED_BLOCKED', 'Indeed blocked this search')
      }

      const cards = await extractCards(page)
      for (const card of cards.slice(0, LIMIT)) {
        if (!card.id || seen.has(card.id)) continue
        seen.add(card.id)
        jobs.push({ ...card, query })
      }
    }

    if (DETAIL_LIMIT) {
      for (const card of jobs.slice(0, DETAIL_LIMIT)) {
        const detail = await classifyDetail(page, card.url)
        card.apply_type = detail.type
        if (detail.blocked) break
      }
    }

    console.log(
      `indeed: ${jobs.length} cards for ${QUERIES.length} queries, ` +
        `${jobs.filter((job) => job.apply_type === 'direct').length} direct`,
    )
    reportOk({ jobs, queries: QUERIES, detail_limit: DETAIL_LIMIT })
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
      setTimeout(() => process.exit(0), 120)
    })
    .catch(() => process.exit(1))
}

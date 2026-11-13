/**
 * Search X for fresh posts and return them as structured data.
 *
 *   SCRIPT_ARG_QUERY   a full X search query (already includes filters)
 *   SCRIPT_ARG_COUNT   max posts to return (default 25)
 *   SCRIPT_ARG_TAB     "live" (default) or "top"
 *
 * Uses the Latest tab so we only see fresh posts. Returns OK with an empty
 * list when the query genuinely has no matches - that is not an error.
 */

import { launchBrowser, isLoggedOut } from '../utils/browser.js'
import { randomWait } from '../utils/humanize.js'
import { reportOk, reportFail } from '../utils/report.js'

const TWEET_SELECTORS = ['article[data-testid="tweet"]', 'article[role="article"]']

const HARD_DEADLINE_MS = 80000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', `search exceeded ${HARD_DEADLINE_MS / 1000}s`)
  process.exit(1)
}, HARD_DEADLINE_MS)

const QUERY = (process.env.SCRIPT_ARG_QUERY || '').trim()
const COUNT = Math.max(1, Math.min(parseInt(process.env.SCRIPT_ARG_COUNT || '25', 10) || 25, 100))
const TAB = process.env.SCRIPT_ARG_TAB === 'top' ? 'top' : 'live'

function searchUrl(query, tab) {
  const param = tab === 'top' ? '' : '&f=live'
  return `https://x.com/search?q=${encodeURIComponent(query)}&src=typed_query${param}`
}

async function waitForTweets(page, timeoutMs = 18000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    for (const selector of TWEET_SELECTORS) {
      const count = await page
        .locator(selector)
        .filter({ has: page.locator('time') })
        .count()
        .catch(() => 0)
      if (count > 0) return selector
    }
    await page.evaluate(() => window.scrollBy(0, 600)).catch(() => {})
    await new Promise((r) => setTimeout(r, 900))
  }
  return null
}

async function extract(page, selector) {
  return page.$$eval(selector, (nodes) => {
    const clean = (value) => (value || '').replace(/\s+\n/g, '\n').trim()
    const out = []

    for (const node of nodes) {
      const fullText = clean(node.innerText)
      if (!fullText) continue

      const text = clean(node.querySelector('[data-testid="tweetText"]')?.innerText)
      const userName = node.querySelector('[data-testid="User-Name"]')
      const nameLines = userName ? userName.innerText.split('\n').map((s) => s.trim()).filter(Boolean) : []

      const handleLink = userName?.querySelector('a[href^="/"]')
      const href = handleLink?.getAttribute('href') || ''
      const handle = href.replace(/^\//, '').split('/')[0]

      const statusLinks = Array.from(node.querySelectorAll('a[href*="/status/"]'))
      const statusLink =
        statusLinks.find((a) => /\/status\/\d+$/.test(a.getAttribute('href') || '')) || statusLinks[0]

      const link = statusLink?.href || ''
      const match = link.match(/\/status\/(\d+)/)
      if (!match) continue

      const time = node.querySelector('time')?.getAttribute('datetime') || ''
      const isReply = /Replying to/i.test(fullText)
      const isPromoted = /^(promoted|ad)\b/i.test(fullText.slice(0, 40))

      out.push({
        post_id: match[1],
        post_url: `https://x.com/i/web/status/${match[1]}`,
        post_content: text || clean(fullText).slice(0, 800),
        author_handle: handle,
        author_name: nameLines[0] || '',
        posted_at: time,
        is_reply: isReply,
        is_promoted: isPromoted,
      })
    }
    return out
  })
}

async function run() {
  const { browser, page } = await launchBrowser()

  try {
    const url = searchUrl(QUERY, TAB)
    console.log(`searching ${TAB}: ${QUERY.slice(0, 120)}`)
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 })
    await randomWait(1500, 2500)

    if (await isLoggedOut(page)) {
      reportFail('SESSION_EXPIRED', 'X is showing a login page - the session cookies are invalid')
      return
    }

    const body = await page.locator('body').innerText().catch(() => '')
    if (/rate limit|something went wrong\. try reloading/i.test(body)) {
      reportFail('RATE_LIMITED', 'X is rate-limiting this search')
      return
    }

    const selector = await waitForTweets(page)
    if (!selector) {
      reportOk({ query: QUERY, tab: TAB, count: 0, posts: [] })
      return
    }

    const seen = new Map()

    for (let round = 0; round < 3 && seen.size < COUNT; round++) {
      const batch = await extract(page, selector)
      for (const post of batch) {
        if (seen.has(post.post_id)) continue
        if (post.is_reply || post.is_promoted) continue
        if (!post.author_handle) continue
        seen.set(post.post_id, post)
        if (seen.size >= COUNT) break
      }
      if (seen.size >= COUNT) break
      await page.evaluate(() => window.scrollBy(0, 1600)).catch(() => {})
      await randomWait(1200, 2200)
    }

    const posts = [...seen.values()]
    console.log(`found ${posts.length} unique posts`)
    reportOk({ query: QUERY, tab: TAB, count: posts.length, posts })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
  } finally {
    await browser?.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

if (!QUERY) {
  reportFail('VALIDATION', 'SCRIPT_ARG_QUERY is required')
  process.exitCode = 1
  clearTimeout(watchdog)
} else {
  run().finally(() => clearTimeout(watchdog))
}

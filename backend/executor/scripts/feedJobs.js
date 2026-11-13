/**
 * Scroll the logged-in home feed and return fresh posts as structured data.
 *
 * The search queries only see posts that match the keywords. The home feed adds
 * people/companies the account already follows - often founders who post a
 * role directly.
 *
 *   SCRIPT_ARG_COUNT    max posts to return (default 40)
 *   SCRIPT_ARG_SCROLLS  how many feed pages to scroll (default 8)
 */

import { launchBrowser, isLoggedOut } from '../utils/browser.js'
import { randomWait } from '../utils/humanize.js'
import { reportOk, reportFail } from '../utils/report.js'

const TWEET_SELECTORS = ['article[data-testid="tweet"]', 'article[role="article"]']

const HARD_DEADLINE_MS = 90000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', `feed scan exceeded ${HARD_DEADLINE_MS / 1000}s`)
  process.exit(1)
}, HARD_DEADLINE_MS)

const COUNT = Math.max(1, Math.min(parseInt(process.env.SCRIPT_ARG_COUNT || '40', 10) || 40, 120))
const SCROLLS = Math.max(1, Math.min(parseInt(process.env.SCRIPT_ARG_SCROLLS || '8', 10) || 8, 20))

async function waitForTweets(page, timeoutMs = 20000) {
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
    console.log('scrolling home feed')
    await page.goto('https://x.com/home', { waitUntil: 'domcontentloaded', timeout: 30000 })
    await randomWait(1500, 2500)

    if (await isLoggedOut(page)) {
      reportFail('SESSION_EXPIRED', 'X is showing a login page - the session cookies are invalid')
      return
    }

    const body = await page.locator('body').innerText().catch(() => '')
    if (/rate limit|something went wrong\. try reloading/i.test(body)) {
      reportFail('RATE_LIMITED', 'X is rate-limiting the home feed')
      return
    }

    const selector = await waitForTweets(page)
    if (!selector) {
      reportOk({ count: 0, scrolls: 0, posts: [] })
      return
    }

    const seen = new Map()
    let rounds = 0

    for (; rounds < SCROLLS && seen.size < COUNT; rounds++) {
      const batch = await extract(page, selector)
      for (const post of batch) {
        if (seen.has(post.post_id)) continue
        if (post.is_reply || post.is_promoted) continue
        if (!post.author_handle) continue
        seen.set(post.post_id, post)
        if (seen.size >= COUNT) break
      }
      if (seen.size >= COUNT) break
      await page.evaluate(() => window.scrollBy(0, 1800)).catch(() => {})
      await randomWait(1200, 2000)
    }

    const posts = [...seen.values()]
    console.log(`feed: ${posts.length} unique posts after ${rounds} scrolls`)
    reportOk({ count: posts.length, scrolls: rounds, posts })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
  } finally {
    await browser?.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

run().finally(() => clearTimeout(watchdog))

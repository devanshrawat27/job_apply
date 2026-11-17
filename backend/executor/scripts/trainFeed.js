/**
 * Train the home feed towards hiring content while the agent is idle.
 *
 * Scrolling alone changes nothing: X only learns from engagement. The script
 * first looks at the home feed, then (if nothing hiring-related is there) goes
 * to a hiring search and likes a couple of real hiring posts plus follows one
 * recruiter/job-board account. Over time the home feed fills with hiring posts.
 *
 *   SCRIPT_ARG_LIKES    max likes per pass (default 2)
 *   SCRIPT_ARG_FOLLOWS  max follows per pass (default 1)
 *   SCRIPT_ARG_SCROLLS  pages to look at per source (default 5)
 */

import { launchBrowser, isLoggedOut } from '../utils/browser.js'
import { randomWait } from '../utils/humanize.js'
import { reportFail, reportOk } from '../utils/report.js'

const HARD_DEADLINE_MS = 150000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'feed training exceeded 2.5 minutes')
  process.exit(1)
}, HARD_DEADLINE_MS)

const clamp = (value, fallback, max) => {
  const number = parseInt(value || '', 10)
  return Math.max(0, Math.min(Number.isFinite(number) ? number : fallback, max))
}

const LIKES = clamp(process.env.SCRIPT_ARG_LIKES, 2, 5)
const FOLLOWS = clamp(process.env.SCRIPT_ARG_FOLLOWS, 1, 3)
const SCROLLS = clamp(process.env.SCRIPT_ARG_SCROLLS, 5, 10)

const HIRING_RE =
  /(we'?re hiring|we are hiring|now hiring|is hiring|hiring a|hiring an|looking to hire|open role|open position|job opening|vacancy|internship|join our team|apply (?:here|at|now|with)|send (?:your )?(?:resume|cv)|dm (?:me|us) your (?:resume|cv))/i
const RECRUITER_RE = /(jobs?|hiring|careers?|recruit|talent|vacanc|internship)/i
const SKIP_RE = /^(promoted|ad|suggested)/i

const SEARCH_QUERY =
  '("we are hiring" OR "we\'re hiring" OR "now hiring") (developer OR engineer OR intern) lang:en'

async function findTweets(page, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const count = await page.locator('article[data-testid="tweet"]').count().catch(() => 0)
    if (count > 0) return true
    await page.evaluate(() => window.scrollBy(0, 600)).catch(() => {})
    await randomWait(700, 1200)
  }
  return false
}

async function act(page, result, likedTexts) {
  if (result.liked >= LIKES && result.followed >= FOLLOWS) return

  const tweets = page.locator('article[data-testid="tweet"]')
  const count = await tweets.count().catch(() => 0)
  const limit = Math.min(count, 60)

  for (let i = 0; i < limit; i += 1) {
    if (result.liked >= LIKES && result.followed >= FOLLOWS) return

    const tweet = tweets.nth(i)
    const text = (await tweet.innerText().catch(() => '')).trim()
    if (!text) continue
    result.seen += 1
    if (SKIP_RE.test(text.slice(0, 40))) continue
    if (!HIRING_RE.test(text)) continue

    const key = text.slice(0, 80)
    if (result.liked < LIKES && !likedTexts.has(key)) {
      const like = tweet.locator('[data-testid="like"]').first()
      if ((await like.count().catch(() => 0)) > 0) {
        await like.click({ timeout: 5000 }).catch(() => {})
        likedTexts.add(key)
        result.liked += 1
        await randomWait(900, 1800)
      }
    }

    if (result.followed < FOLLOWS) {
      const handleLink = tweet.locator('[data-testid="User-Name"] a[href^="/"]').first()
      const href = (await handleLink.getAttribute('href').catch(() => '')) || ''
      const handle = href.replace(/^\//, '').split('/')[0]
      if (handle && RECRUITER_RE.test(handle)) {
        const follow = tweet
          .locator('button[data-testid$="-follow"], button[aria-label^="Follow "]')
          .first()
        if ((await follow.count().catch(() => 0)) > 0) {
          await follow.click({ timeout: 5000 }).catch(() => {})
          result.followed += 1
          await randomWait(1200, 2200)
        }
      }
    }
  }
}

async function scrollAndAct(page, result, likedTexts) {
  for (let pageIndex = 0; pageIndex < SCROLLS; pageIndex += 1) {
    if (result.liked >= LIKES && result.followed >= FOLLOWS) return
    await act(page, result, likedTexts)
    await page.evaluate(() => window.scrollBy(0, 1200)).catch(() => {})
    await randomWait(1500, 2600)
  }
}

async function main() {
  const { context, page } = await launchBrowser()
  const result = { liked: 0, followed: 0, seen: 0, source: 'home' }
  const likedTexts = new Set()

  try {
    await page.goto('https://x.com/home', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await randomWait(3000, 5000)

    if (await isLoggedOut(page)) {
      reportFail('X_LOGGED_OUT', 'X is logged out - reconnect the account')
      return
    }

    if (await findTweets(page)) {
      await scrollAndAct(page, result, likedTexts)
    }

    // The home feed often has nothing hiring-related yet - that is exactly why
    // it needs training. Search for hiring posts and engage there instead.
    if (result.liked === 0 && result.followed === 0) {
      result.source = 'search'
      const url = `https://x.com/search?q=${encodeURIComponent(SEARCH_QUERY)}&src=typed_query&f=live`
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 })
      await randomWait(3500, 5500)
      if (await findTweets(page)) {
        await scrollAndAct(page, result, likedTexts)
      }
    }

    reportOk(result)
  } finally {
    clearTimeout(watchdog)
    await context.close().catch(() => {})
  }
}

main().catch((err) => {
  clearTimeout(watchdog)
  reportFail('ERROR', err.message)
  process.exitCode = 1
})

import { randomWait } from './humanize.js'

const LOGIN_SELECTOR = 'input[name="text"], input[name="username"], a[href="/login"]'
const UNAVAILABLE_RE =
  /this post is unavailable|this page doesn.?t exist|posts are protected|account owner limits who can view/i
const RATE_LIMIT_RE = /something went wrong.*try reloading|rate limit/i

function targetError(code, message) {
  const err = new Error(message)
  err.code = code
  return err
}

export function extractStatusId(input) {
  const str = String(input || '').trim()
  const fromUrl = str.match(/\/status\/(\d+)/)
  if (fromUrl) return fromUrl[1]
  return /^\d{5,25}$/.test(str) ? str : null
}

export function normalizePostUrl(input) {
  const id = extractStatusId(input)
  if (!id) return null
  const str = String(input).trim()
  if (/^https?:\/\//i.test(str)) {
    return str.replace(/^(https?:\/\/)?(www\.|mobile\.)?twitter\.com/i, '$1x.com')
  }
  return `https://x.com/i/web/status/${id}`
}

/**
 * Navigate to the post and return a locator for that exact article.
 * The conversation page renders parents above and replies below, so the target
 * is found by its own status id, never by position.
 */
export async function resolvePost(page, postUrlOrId, { timeout = 25000 } = {}) {
  const id = extractStatusId(postUrlOrId)
  const url = normalizePostUrl(postUrlOrId)
  if (!id || !url) {
    throw targetError('VALIDATION', `invalid post url "${postUrlOrId}"`)
  }

  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 })
  await randomWait(1800, 3200)

  if ((await page.locator(LOGIN_SELECTOR).count()) > 0) {
    throw targetError('SESSION_EXPIRED', 'X is showing a login page - the session cookies are invalid')
  }

  try {
    await page.waitForSelector('article[data-testid="tweet"]', { timeout })
  } catch {
    const body = await page.locator('body').innerText().catch(() => '')
    if (RATE_LIMIT_RE.test(body)) {
      throw targetError('RATE_LIMITED', 'X is rate-limiting this session')
    }
    if (UNAVAILABLE_RE.test(body)) {
      throw targetError('TARGET_NOT_FOUND', `post ${id} is unavailable or restricted`)
    }
    throw targetError('SELECTOR_MISS', 'no tweet rendered on the post page')
  }

  const article = page
    .locator('article[data-testid="tweet"]')
    .filter({ has: page.locator(`a[href*="/status/${id}"]`) })
    .first()

  if ((await article.count()) === 0) {
    throw targetError('TARGET_NOT_FOUND', `target post ${id} was not found on the page`)
  }

  return { id, url, article }
}

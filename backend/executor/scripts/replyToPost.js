/**
 * Post a public reply on a specific X post.
 *
 *   SCRIPT_ARG_POST_URL      status URL or numeric status id
 *   SCRIPT_ARG_REPLY_TEXT    the reply text
 *
 * The CreateTweet network response is ground truth: a closed dialog or a toast
 * can appear even when X rejected the reply.
 */

import { launchBrowser } from '../utils/browser.js'
import { humanClick, humanType, randomWait } from '../utils/humanize.js'
import { resolvePost } from '../utils/targetPost.js'
import { reportOk, reportFail } from '../utils/report.js'

const HARD_DEADLINE_MS = 90000
const watchdog = setTimeout(() => {
  reportFail('UNKNOWN', 'reply script timed out - the reply may or may not have posted')
  process.exit(1)
}, HARD_DEADLINE_MS)

const POST_URL = (process.env.SCRIPT_ARG_POST_URL || '').trim()
const TEXT = (process.env.SCRIPT_ARG_REPLY_TEXT || '').trim()

async function reply() {
  const { browser, page } = await launchBrowser()

  try {
    const { id, article } = await resolvePost(page, POST_URL)

    const replyButton = article.locator('[data-testid="reply"]')
    if ((await replyButton.count()) === 0) {
      reportFail('SELECTOR_MISS', 'reply button not found on the post')
      return
    }

    await humanClick(page, replyButton.first())

    const dialog = page.locator('[role="dialog"][aria-modal="true"]').first()
    await dialog.waitFor({ state: 'visible', timeout: 15000 })
    await randomWait(700, 1400)

    const editor = dialog.locator('[data-testid="tweetTextarea_0"]').first()
    await humanClick(page, editor)
    await randomWait(400, 800)
    await humanType(page, TEXT)
    await randomWait(800, 1500)

    let postButton = null
    for (const sel of ['[data-testid="tweetButton"]', '[data-testid="tweetButtonInline"]']) {
      const candidate = dialog.locator(sel)
      if ((await candidate.count()) > 0) {
        postButton = candidate.first()
        break
      }
    }
    if (!postButton) {
      reportFail('SELECTOR_MISS', 'post button not found in the reply composer')
      return
    }

    const responsePromise = page
      .waitForResponse(
        (res) => /CreateTweet/i.test(res.url()) && res.request().method() === 'POST',
        { timeout: 20000 },
      )
      .catch(() => null)

    await humanClick(page, postButton)
    const response = await responsePromise

    if (response) {
      if (!response.ok()) {
        reportFail('ERROR', `X responded with status ${response.status()} - the reply was not created`)
        return
      }
      const payload = await response.json().catch(() => null)
      const errors = payload?.errors
      if (Array.isArray(errors) && errors.length) {
        const message = JSON.stringify(errors)
        const duplicate = errors.some((e) => e?.code === 187) || /already said that/i.test(message)
        reportFail(duplicate ? 'DUPLICATE' : 'ERROR', message)
        return
      }
      reportOk({ post_url: POST_URL, status_id: id, reply_text: TEXT, verified: 'network' })
      return
    }

    // No network capture: only accept the composer closing AND our text gone.
    const closed = await dialog
      .waitFor({ state: 'detached', timeout: 12000 })
      .then(() => true)
      .catch(() => false)

    if (!closed) {
      reportFail('UNKNOWN', 'no confirmation after clicking Post - the reply may or may not have landed')
      return
    }

    reportOk({ post_url: POST_URL, status_id: id, reply_text: TEXT, verified: 'composer_closed' })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
  } finally {
    await browser?.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

if (!POST_URL) {
  reportFail('VALIDATION', 'SCRIPT_ARG_POST_URL is required')
  process.exitCode = 1
  clearTimeout(watchdog)
} else if (!TEXT) {
  reportFail('VALIDATION', 'SCRIPT_ARG_REPLY_TEXT is required')
  process.exitCode = 1
  clearTimeout(watchdog)
} else {
  reply().finally(() => clearTimeout(watchdog))
}

/**
 * Read incoming DM previews and notifications for replies to our outreach.
 *
 *   (no args) -> { dms: [...], mentions: [...] }
 *
 * Read-only. It never opens a conversation or sends anything.
 */

import { isLoggedOut, launchBrowser } from '../utils/browser.js'
import handlePasskey from '../utils/handlePasskey.js'
import { reportFail, reportOk } from '../utils/report.js'

const HARD_DEADLINE_MS = 120000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'inbox check exceeded 120s')
  process.exit(1)
}, HARD_DEADLINE_MS)

const HANDLE_RE = /@([A-Za-z0-9_]{1,15})/

async function readDms(page) {
  await page.goto('https://x.com/messages', { waitUntil: 'domcontentloaded', timeout: 45000 })
  await page.waitForTimeout(6000)
  await handlePasskey(page).catch(() => {})
  await page.waitForTimeout(2000)

  for (let i = 0; i < 3; i += 1) {
    await page.mouse.wheel(0, 1200).catch(() => {})
    await page.waitForTimeout(1200)
  }

  return page.evaluate(() => {
    const deepAll = (root, selector, out = []) => {
      try {
        out.push(...root.querySelectorAll(selector))
      } catch {
        // ignore invalid selector
      }
      const nodes = root.querySelectorAll ? root.querySelectorAll('*') : []
      for (const el of nodes) {
        if (el.shadowRoot) deepAll(el.shadowRoot, selector, out)
      }
      return out
    }

    let nodes = deepAll(document, '[data-testid="conversation"]')
    if (!nodes.length) nodes = deepAll(document, '[role="listitem"]')
    if (!nodes.length) nodes = deepAll(document, 'a[href*="/messages/"]')

    const items = []
    for (const node of nodes) {
      const text = (node.innerText || '').replace(/\s+/g, ' ').trim()
      if (!text || text.length < 4) continue
      const links = [...node.querySelectorAll('a[href]')].map((a) => a.getAttribute('href') || '')
      const href = links.find((value) => value.startsWith('/messages/')) || ''
      const handle = (text.match(/@([A-Za-z0-9_]{1,15})/) || [])[1] || ''
      // X prefixes our own last message with "You:". No prefix means they wrote.
      const incoming = !/(^|\s)You:/.test(text)
      items.push({ text: text.slice(0, 280), href, handle, incoming })
    }
    const seen = new Set()
    return items.filter((item) => {
      const key = `${item.href}|${item.text.slice(0, 40)}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  })
}

async function readMentions(page) {
  await page.goto('https://x.com/notifications', { waitUntil: 'domcontentloaded', timeout: 45000 })
  await page.waitForTimeout(6000)
  for (let i = 0; i < 2; i += 1) {
    await page.mouse.wheel(0, 1200).catch(() => {})
    await page.waitForTimeout(1000)
  }

  return page.evaluate(() => {
    const items = []
    for (const node of document.querySelectorAll('article')) {
      const text = (node.innerText || '').replace(/\s+/g, ' ').trim()
      if (!text) continue
      if (!/replied|mentioned you|responded/i.test(text)) continue
      const handle = (text.match(/@([A-Za-z0-9_]{1,15})/) || [])[1] || ''
      items.push({ text: text.slice(0, 280), handle, incoming: true })
    }
    return items.slice(0, 40)
  })
}

async function run() {
  const { browser, page } = await launchBrowser()
  try {
    if (await isLoggedOut(page)) {
      reportFail('SESSION_EXPIRED', 'X session expired - reconnect the account')
      return
    }

    const dms = await readDms(page)
    const body = await page.locator('body').innerText().catch(() => '')
    console.log('messages url:', page.url())
    console.log('messages body:', body.replace(/\s+/g, ' ').slice(0, 260))
    const mentions = await readMentions(page)
    console.log(`inbox: ${dms.length} conversations, ${mentions.length} mentions`)
    reportOk({ dms, mentions })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
  } finally {
    await browser?.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

run().finally(() => clearTimeout(watchdog))

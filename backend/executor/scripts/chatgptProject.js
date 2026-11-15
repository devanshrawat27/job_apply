/**
 * Ensure the ChatGPT project that holds every JobPilot conversation exists.
 *
 *   SCRIPT_ARG_NAME   project name (default: JobPilot)
 *
 * Returns { project_url, created, name }. If the ChatGPT UI does not expose
 * projects (or the layout changed) it fails with PROJECT_UI_UNKNOWN and a short
 * diagnostic instead of guessing, so the human can create it once by hand.
 */

import {
  isLoggedIn,
  launchChatgpt,
  markConnected,
} from '../utils/chatgptBrowser.js'
import { reportFail, reportOk } from '../utils/report.js'

const HARD_DEADLINE_MS = 190000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Could not set up the ChatGPT project in 3 minutes')
  process.exit(1)
}, HARD_DEADLINE_MS)

const NAME = (process.env.SCRIPT_ARG_NAME || 'JobPilot').trim() || 'JobPilot'

const PROJECT_LINK = 'a[href*="/g/g-p-"]'

async function openSidebar(page) {
  const open = page
    .locator('button[aria-label="Open sidebar"], button[data-testid="open-sidebar-button"]')
    .first()
  if ((await open.count().catch(() => 0)) > 0) {
    await open.click().catch(() => {})
    await page.waitForTimeout(1200)
  }
}

async function findProject(page) {
  const links = page.locator(PROJECT_LINK)
  const count = await links.count().catch(() => 0)
  for (let i = 0; i < count; i += 1) {
    const link = links.nth(i)
    const text = ((await link.innerText().catch(() => '')) || '').trim()
    if (text.toLowerCase() === NAME.toLowerCase()) {
      const href = await link.getAttribute('href').catch(() => '')
      if (href) return new URL(href, 'https://chatgpt.com').toString()
    }
  }
  return ''
}

async function createProject(page) {
  // The sidebar button, or the empty-state button on /projects.
  const candidates = [
    page.locator('button:has-text("New project")').first(),
    page.locator('[role="button"]:has-text("New project")').first(),
    page.locator('button[aria-label*="project" i]').first(),
    page.locator('text=New project').first(),
  ]
  let clicked = false
  for (const candidate of candidates) {
    if ((await candidate.count().catch(() => 0)) > 0) {
      await candidate.click({ timeout: 8000 }).catch(() => {})
      clicked = true
      break
    }
  }
  if (!clicked) return { ok: false, reason: 'no "New project" control' }

  await page.waitForTimeout(2500)

  const inputs = [
    page.locator('input[placeholder*="project" i]').first(),
    page.locator('input[name*="project" i]').first(),
    page.locator('input[type="text"]').first(),
    page.locator('[contenteditable="true"]').first(),
  ]
  let filled = false
  for (const input of inputs) {
    if ((await input.count().catch(() => 0)) > 0) {
      await input.click().catch(() => {})
      await input.fill(NAME).catch(async () => {
        await input.type(NAME, { delay: 20 }).catch(() => {})
      })
      filled = true
      break
    }
  }
  if (!filled) return { ok: false, reason: 'no project name field' }

  await page.waitForTimeout(700)

  const submit = [
    page.locator('button:has-text("Create project")').first(),
    page.locator('button:has-text("Create")').first(),
    page.locator('button[type="submit"]').first(),
  ]
  let submitted = false
  for (const button of submit) {
    if ((await button.count().catch(() => 0)) > 0 && (await button.isEnabled().catch(() => false))) {
      await button.click().catch(() => {})
      submitted = true
      break
    }
  }
  if (!submitted) await page.keyboard.press('Enter').catch(() => {})

  // The new project opens immediately; otherwise wait for the sidebar link.
  const deadline = Date.now() + 30000
  while (Date.now() < deadline) {
    await page.waitForTimeout(1500)
    if (page.url().includes('/g/g-p-')) return { ok: true, url: page.url() }
    await openSidebar(page)
    const url = await findProject(page)
    if (url) return { ok: true, url }
  }
  return { ok: false, reason: 'project did not appear after create' }
}

async function main() {
  const { context, page } = await launchChatgpt()
  try {
    await page.goto('https://chatgpt.com/', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(5000)

    if (!(await isLoggedIn(page))) {
      reportFail(
        'CHATGPT_LOGIN_REQUIRED',
        'ChatGPT is not logged in. Open Settings -> AI analyst and press "Connect ChatGPT".',
      )
      return
    }
    markConnected()

    await openSidebar(page)
    const existing = await findProject(page)
    if (existing) {
      reportOk({ project_url: existing, created: false, name: NAME })
      return
    }

    const created = await createProject(page)
    if (!created.ok) {
      const diagnostic = (await page.locator('body').innerText().catch(() => '')).slice(0, 600)
      reportFail(
        'PROJECT_UI_UNKNOWN',
        `Could not create the project (${created.reason}). Create "${NAME}" once in ChatGPT, then reconnect. ${diagnostic}`,
      )
      return
    }

    reportOk({ project_url: created.url, created: true, name: NAME })
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

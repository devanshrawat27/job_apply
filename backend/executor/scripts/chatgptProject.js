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
const PROJECTS_URL = 'https://chatgpt.com/projects'

async function findProject(page) {
  const links = page.locator('a[href*="/g/g-p-"]')
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

async function openProjects(page) {
  await page.goto(PROJECTS_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
  const deadline = Date.now() + 45000
  while (Date.now() < deadline) {
    const text = await page.locator('body').innerText().catch(() => '')
    if (
      text.includes('Search projects') ||
      text.includes('Locked chats') ||
      text.includes('New project')
    ) {
      return true
    }
    if ((await page.locator('a[href*="/g/g-p-"]').count().catch(() => 0)) > 0) return true
    await page.waitForTimeout(1500)
  }
  return false
}

async function createProject(page) {
  const candidates = page.getByRole('button', { name: 'Create', exact: true })
  let create = null
  const total = await candidates.count().catch(() => 0)
  for (let i = 0; i < total; i += 1) {
    const button = candidates.nth(i)
    if (await button.isVisible().catch(() => false)) {
      create = button
      break
    }
  }
  if (create === null) {
    return { ok: false, reason: 'no Create button on the projects page' }
  }
  await create.click({ timeout: 10000 }).catch(() => {})

  const dialog = page.locator('[role="dialog"]').last()
  const dialogDeadline = Date.now() + 15000
  while (Date.now() < dialogDeadline) {
    if ((await dialog.count().catch(() => 0)) > 0) break
    await page.waitForTimeout(500)
  }
  if ((await dialog.count().catch(() => 0)) === 0) {
    return { ok: false, reason: 'Create did not open a project dialog' }
  }

  const input = dialog.locator('input').first()
  await input.click({ timeout: 8000 }).catch(() => {})
  await input.fill(NAME).catch(async () => {
    await input.type(NAME, { delay: 20 }).catch(() => {})
  })
  await page.waitForTimeout(500)

  const submit = dialog.getByRole('button', { name: 'Create project' }).first()
  if ((await submit.count().catch(() => 0)) === 0) {
    return { ok: false, reason: 'no Create project button in the dialog' }
  }
  await submit.click({ timeout: 10000 }).catch(() => {})

  // The dialog closes and the new project opens. If it does not navigate,
  // fall back to finding the new row in the projects list.
  const deadline = Date.now() + 40000
  while (Date.now() < deadline) {
    await page.waitForTimeout(1500)
    if (page.url().includes('/g/g-p-')) return { ok: true, url: page.url() }
    const found = await findProject(page)
    if (found) return { ok: true, url: found }
    if ((await dialog.count().catch(() => 0)) === 0) {
      await page.waitForTimeout(2000)
      const after = await findProject(page)
      if (after) return { ok: true, url: after }
    }
  }
  return { ok: false, reason: 'project did not appear after create' }
}

async function main() {
  const { context, page } = await launchChatgpt()
  try {
    await page.goto('https://chatgpt.com/', { waitUntil: 'domcontentloaded', timeout: 60000 })

    let ready = false
    const loginDeadline = Date.now() + 40000
    while (Date.now() < loginDeadline) {
      await page.waitForTimeout(2500)
      if (await isLoggedIn(page)) {
        ready = true
        break
      }
    }
    if (!ready) {
      reportFail(
        'CHATGPT_LOGIN_REQUIRED',
        'ChatGPT is not logged in. Open Settings -> AI analyst and press "Connect ChatGPT".',
      )
      return
    }
    markConnected()

    const projectsReady = await openProjects(page)
    if (!projectsReady) {
      const diagnostic = (await page.locator('body').innerText().catch(() => '')).slice(0, 400)
      reportFail(
        'PROJECT_UI_UNKNOWN',
        `The projects page did not load. Try again in a moment. ${diagnostic}`,
      )
      return
    }

    const existing = await findProject(page)
    if (existing) {
      reportOk({ project_url: existing, created: false, name: NAME })
      return
    }

    const created = await createProject(page)
    if (!created.ok) {
      const diagnostic = (await page.locator('body').innerText().catch(() => '')).slice(0, 400)
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

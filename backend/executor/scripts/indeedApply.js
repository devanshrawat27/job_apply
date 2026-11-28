/**
 * Apply to an Indeed job in the connected Indeed Chrome window.
 *
 * Indeed only offers its Quick Apply flow to a signed-in session. This script
 * reuses the visible Indeed window over CDP, clicks Apply now, follows the
 * wizard, and stops for the human when a real question or a sign-in wall shows
 * up. It never applies on a company site.
 *
 *   SCRIPT_ARG_URL      Indeed viewjob URL
 *   SCRIPT_ARG_ANSWERS  JSON {question: answer} chosen by the human
 *   INDEED_COOKIES      JSON cookie object
 */

import { launchBrowser } from '../utils/browser.js'
import { reportFail, reportOk } from '../utils/report.js'

const URL = (process.env.SCRIPT_ARG_URL || '').trim()
const ANSWERS = (() => {
  try {
    const value = JSON.parse(process.env.SCRIPT_ARG_ANSWERS || '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) return []
    return Object.entries(value)
      .map(([question, answer]) => ({ question: clean(question), answer: clean(answer) }))
      .filter((item) => item.question && item.answer)
  } catch {
    return []
  }
})()
const HARD_DEADLINE_MS = 300000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Indeed apply did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

function clean(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function successText(text) {
  return /application submitted|your application has been submitted|you have applied|already applied|application sent/i.test(
    text,
  )
}

async function pageText(page) {
  return page
    .locator('body')
    .innerText()
    .then((value) => clean(value))
    .catch(() => '')
}

async function isLoginWall(page) {
  if (/secure\.indeed\.com\/(auth|account\/login)|\/auth\?/i.test(page.url())) return true
  return (await page.locator('input[type="password"], input[name="password"]').count().catch(() => 0)) > 0
}

async function isExternal(page) {
  return (await page.getByText('Apply on company site', { exact: false }).count().catch(() => 0)) > 0
}

async function isApplied(page) {
  return successText(await pageText(page))
}

/** Visible questions on the current wizard step. */
async function questionState(page) {
  return page.evaluate(() => {
    const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim()
    const visible = (el) => {
      const rect = el.getBoundingClientRect()
      const style = window.getComputedStyle(el)
      return rect.width > 2 && rect.height > 2 && style.visibility !== 'hidden' && style.display !== 'none'
    }
    const radios = [...document.querySelectorAll('input[type="radio"]')]
      .filter(visible)
      .map((input) => ({
        id: input.id || '',
        value: input.value || '',
        label:
          norm(document.querySelector(`label[for="${input.id}"]`)?.innerText) || input.value || '',
      }))
    const selects = [...document.querySelectorAll('select')].filter(visible).map((select) => ({
      id: select.id || '',
      name: select.getAttribute('name') || '',
      options: [...select.querySelectorAll('option')].map((o) => norm(o.innerText)).filter(Boolean),
    }))
    const textFields = [...document.querySelectorAll('input[type="text"], input[type="number"], textarea')]
      .filter(visible)
      .map((input) => ({
        id: input.id || '',
        name: input.getAttribute('name') || '',
        placeholder: input.getAttribute('placeholder') || '',
        type: input.getAttribute('type') || input.tagName,
      }))
    const body = norm(document.body?.innerText).slice(0, 1800)
    return { body, radios, selects, textFields }
  })
}

async function chooseRadio(page, value) {
  const wanted = clean(value).toLowerCase()
  const labels = page.locator('label')
  const count = await labels.count().catch(() => 0)
  for (let index = 0; index < count; index += 1) {
    const item = labels.nth(index)
    if (!(await item.isVisible().catch(() => false))) continue
    const text = clean(await item.innerText().catch(() => '')).toLowerCase()
    if (text === wanted) {
      await item.click({ timeout: 6000, force: true }).catch(() => {})
      return true
    }
  }
  return false
}

async function fillText(page, answer) {
  const box = page
    .locator('input[type="text"]:visible, input[type="number"]:visible, textarea:visible')
    .first()
  if (!(await box.count().catch(() => 0))) return false
  await box.fill(answer).catch(() => {})
  return true
}

async function clickPrimary(page) {
  const button = page
    .locator('button, [role="button"], a')
    .filter({ hasText: /^(continue|next|review|review your application|submit|submit application|apply)$/i })
    .filter({ hasNotText: /company site/i })
    .first()
  if (!(await button.count().catch(() => 0))) return false
  if (!(await button.isVisible().catch(() => false))) return false
  await button.click({ timeout: 8000, force: true }).catch(() => {})
  return true
}

async function run() {
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-indeed`
  process.env.STEALTH_HEADLESS = '0'
  process.env.STEALTH_OFFSCREEN = '1'
  const { browser, context, page } = await launchBrowser({ withSession: false })

  async function finish(payload) {
    let cookies = {}
    if (payload.code !== 'LOGIN_REQUIRED') {
      try {
        for (const cookie of await context.cookies('https://in.indeed.com')) {
          if (String(cookie.domain || '').includes('indeed')) cookies[cookie.name] = cookie.value
        }
      } catch {
        cookies = {}
      }
    }
    return reportOk({ ...payload, ...(Object.keys(cookies).length ? { cookies } : {}) })
  }

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

    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
    await page.waitForTimeout(6000)
    await page.bringToFront().catch(() => {})

    if (await isLoginWall(page)) {
      return finish({
        applied: false,
        code: 'LOGIN_REQUIRED',
        message: 'Connect Indeed and sign in before auto-applying.',
      })
    }
    if (await isApplied(page)) {
      return finish({ applied: true, code: 'ALREADY_APPLIED', message: 'Indeed shows this job as applied.' })
    }
    if (await isExternal(page)) {
      return finish({
        applied: false,
        code: 'EXTERNAL',
        message: 'This job applies on the company site.',
      })
    }

    const applyLink = page
      .locator('a[href*="smartapply.indeed.com"], a[href*="indeedapply"]')
      .filter({ hasText: /apply now/i })
      .first()
    const applyButton = page.locator('#indeedApplyButton, button').filter({ hasText: /^apply now$/i }).first()
    const control = (await applyLink.count().catch(() => 0)) ? applyLink : applyButton
    if (!(await control.count().catch(() => 0))) {
      return finish({
        applied: false,
        code: 'NO_APPLY',
        message: 'No Indeed apply control was found.',
      })
    }

    const popupPromise = page.waitForEvent('popup', { timeout: 12000 }).catch(() => null)
    await control.click({ timeout: 8000, force: true }).catch(() => {})
    const popup = await popupPromise
    const target = popup || page
    await target.waitForTimeout(6000)
    await target.bringToFront().catch(() => {})

    if (await isLoginWall(target)) {
      return finish({
        applied: false,
        code: 'LOGIN_REQUIRED',
        message: 'Indeed needs you to sign in before applying.',
      })
    }

    let lastState = null
    for (let step = 0; step < 10; step += 1) {
      const text = await pageText(target)
      if (successText(text)) {
        return finish({ applied: true, code: 'APPLIED', message: 'Indeed confirms the application.' })
      }
      if (await isExternal(target)) {
        return finish({
          applied: false,
          code: 'EXTERNAL',
          message: 'Indeed redirected to the company site.',
        })
      }

      const state = await questionState(target)
      lastState = state
      if (state.radios.length || state.textFields.length || state.selects.length) {
        let accepted = false
        for (const item of ANSWERS) {
          const question = clean(state.body).toLowerCase()
          const asked = clean(item.question).toLowerCase()
          if (!asked || !(question.includes(asked) || asked.includes(question.slice(0, 80)))) continue
          if (state.radios.length) accepted = await chooseRadio(target, item.answer)
          else accepted = await fillText(target, item.answer)
          if (accepted) break
        }
        if (!accepted) {
          return finish({
            applied: false,
            code: 'NEEDS_REVIEW',
            message: 'Indeed asks a question that needs your answer.',
            questions: state.body.slice(0, 1600),
            question: state.body.slice(0, 200),
            options: state.radios.map((item) => clean(item.label)).filter(Boolean),
          })
        }
        await target.waitForTimeout(600)
      }

      if (!(await clickPrimary(target))) {
        return finish({
          applied: false,
          code: 'NEEDS_REVIEW',
          message: 'Indeed did not show a clear next step.',
          questions: text.slice(0, 1600),
        })
      }
      await target.waitForTimeout(3500)
    }

    return finish({
      applied: false,
      code: 'NEEDS_REVIEW',
      message: 'Indeed still has more steps.',
      questions: (lastState?.body || '').slice(0, 1600),
    })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
    throw err
  } finally {
    await browser?.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

if (!URL) {
  reportFail('VALIDATION', 'SCRIPT_ARG_URL is required')
  process.exit(1)
} else {
  run()
    .then(() => {
      clearTimeout(watchdog)
      setTimeout(() => process.exit(0), 150)
    })
    .catch(() => process.exit(1))
}

/**
 * Apply to a Naukri job with the connected session.
 *
 * Direct Naukri jobs can be submitted from the job page. External ("Apply on
 * company site") jobs are reported back so the human gets the link instead.
 * When Naukri asks a questionnaire, nothing is submitted: the questions are
 * returned for review.
 *
 *   SCRIPT_ARG_URL    Naukri job URL
 *   NAUKRI_COOKIES    JSON cookie object
 */

import { launchBrowser } from '../utils/browser.js'
import { reportFail, reportOk } from '../utils/report.js'

const URL = (process.env.SCRIPT_ARG_URL || '').trim()
const HARD_DEADLINE_MS = 240000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Naukri apply did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

function storedCookies() {
  try {
    const parsed = JSON.parse(process.env.NAUKRI_COOKIES || '{}')
    if (!parsed || typeof parsed !== 'object') return []
    return Object.entries(parsed)
      .filter(([name, value]) => name && value)
      .map(([name, value]) => ({ name, value: String(value), domain: '.naukri.com', path: '/' }))
  } catch {
    return []
  }
}

const bodyText = (page) =>
  page
    .locator('body')
    .innerText()
    .then((value) => value.replace(/\s+/g, ' ').trim())
    .catch(() => '')

async function visibleButton(page, patterns) {
  const buttons = page.locator('button, [role="button"], a')
  const count = await buttons.count().catch(() => 0)
  for (let index = 0; index < count; index += 1) {
    const item = buttons.nth(index)
    const visible = await item.isVisible().catch(() => false)
    if (!visible) continue
    const label = ((await item.innerText().catch(() => '')) || '').replace(/\s+/g, ' ').trim()
    if (!label) continue
    if (patterns.some((pattern) => pattern.test(label))) return item
  }
  return null
}

async function run() {
  delete process.env.BROWSER_CDP_ENDPOINT
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-naukri`
  process.env.STEALTH_HEADLESS = '0'
  process.env.STEALTH_OFFSCREEN = '1'
  const { browser, context, page } = await launchBrowser({ withSession: false })
  try {
    const cookies = storedCookies()
    if (cookies.length) await context.addCookies(cookies).catch(() => {})

    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
    await page.waitForTimeout(7000)

    const text = await bodyText(page)
    if (await page.locator('.company-site-button').count().catch(() => 0)) {
      return reportOk({
        applied: false,
        code: 'EXTERNAL',
        message: 'This job applies on the company site.',
      })
    }
    if (/already applied|applied on/i.test(text) && !/apply on company site/i.test(text)) {
      return reportOk({
        applied: true,
        code: 'ALREADY_APPLIED',
        message: 'Naukri already shows this job as applied.',
      })
    }

    const applyButton = page.locator('.apply-button').first()
    const hasApply = await applyButton.count().catch(() => 0)
    const button =
      hasApply > 0
        ? applyButton
        : await visibleButton(page, [/^apply$/i, /^apply now$/i, /^apply for this job$/i])
    if (!button) {
      return reportOk({
        applied: false,
        code: 'NO_APPLY',
        message: 'No direct Naukri apply button was found.',
      })
    }

    await button.click({ timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(5000)
    const afterApply = await bodyText(page)

    if (/already applied|application sent|successfully applied|applied successfully/i.test(afterApply)) {
      return reportOk({
        applied: true,
        code: 'APPLIED',
        message: 'Naukri confirms the application.',
      })
    }

    const questionFields = await page
      .locator('textarea, input[type="text"], input[type="number"], input[type="radio"]')
      .count()
      .catch(() => 0)
    const questions = /questionnaire|answer the following|please answer|chat/i.test(afterApply)
    if (questionFields > 0 || questions) {
      return reportOk({
        applied: false,
        code: 'NEEDS_REVIEW',
        message: 'Naukri opened questions that need your answers.',
        questions: afterApply.slice(0, 1500),
      })
    }

    const submit = await visibleButton(page, [/^submit$/i, /^apply$/i, /^send application$/i])
    if (submit) {
      await submit.click({ timeout: 8000 }).catch(() => {})
      await page.waitForTimeout(5000)
      const finalText = await bodyText(page)
      if (/already applied|application sent|successfully applied|applied successfully/i.test(finalText)) {
        return reportOk({
          applied: true,
          code: 'APPLIED',
          message: 'Naukri confirms the application.',
        })
      }
      return reportOk({
        applied: false,
        code: 'NEEDS_REVIEW',
        message: 'The apply flow did not confirm. Open the job and finish it.',
        questions: finalText.slice(0, 1500),
      })
    }

    return reportOk({
      applied: false,
      code: 'NEEDS_REVIEW',
      message: 'Naukri did not show a clear submit step.',
      questions: afterApply.slice(0, 1500),
    })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
  } finally {
    await browser?.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

if (!URL) {
  reportFail('VALIDATION', 'SCRIPT_ARG_URL is required')
  process.exitCode = 1
  clearTimeout(watchdog)
} else {
  run().finally(() => clearTimeout(watchdog))
}

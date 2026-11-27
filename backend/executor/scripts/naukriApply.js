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
const ANSWERS = (() => {
  try {
    const value = JSON.parse(process.env.SCRIPT_ARG_ANSWERS || '[]')
    return Array.isArray(value) ? value.map((item) => String(item)) : []
  } catch {
    return []
  }
})()
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

async function questionText(page, fallback) {
  for (const selector of ['[role="dialog"]', '[class*="modal" i]', '[class*="chat" i]']) {
    const locator = page.locator(selector).first()
    const count = await locator.count().catch(() => 0)
    if (!count) continue
    const text = (await locator.innerText().catch(() => ''))
      .replace(/\s+/g, ' ')
      .trim()
    if (text.length > 10) return text.slice(0, 1800)
  }
  return fallback.slice(0, 1800)
}

async function visibleButton(page, patterns) {
  // Naukri renders its Save/Submit controls as divs, not <button>, so include
  // the class names it uses as well as normal buttons.
  const buttons = page.locator(
    'button, [role="button"], a, div[class*="sendMsgbtn"], div[class*="btn" i]',
  )
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

async function answerButton(page, answer) {
  const escaped = String(answer).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const locator = page
    .locator('button, [role="button"], [role="radio"], label')
    .filter({ hasText: new RegExp(`^\\s*${escaped}\\s*$`, 'i') })
    .first()
  const count = await locator.count().catch(() => 0)
  if (!count) return null
  const visible = await locator.isVisible().catch(() => false)
  return visible ? locator : null
}

async function fillAnswer(page, answer) {
  // Naukri uses custom radio rows; clicking the label does not always fire the
  // app's change handler, so check the real radio input first.
  const radios = page.locator('input[type="radio"]')
  const radioCount = await radios.count().catch(() => 0)
  for (let index = 0; index < radioCount; index += 1) {
    const radio = radios.nth(index)
    const value = (
      (await radio.getAttribute('value')) ||
      (await radio.getAttribute('aria-label')) ||
      ''
    ).trim()
    if (value.toLowerCase() === String(answer).trim().toLowerCase()) {
      await radio.check({ timeout: 6000, force: true }).catch(() => {})
      return true
    }
  }

  const option = await answerButton(page, answer)
  if (option) {
    await option.click({ timeout: 6000 }).catch(() => {})
    return true
  }
  // Native selects are common on older Naukri forms.
  const selects = page.locator('select')
  const count = await selects.count().catch(() => 0)
  for (let index = 0; index < count; index += 1) {
    const select = selects.nth(index)
    const labels = await select.locator('option').allInnerTexts().catch(() => [])
    const match = labels.find(
      (label) => label.trim().toLowerCase() === String(answer).trim().toLowerCase(),
    )
    if (match) {
      await select.selectOption({ label: match }).catch(() => {})
      return true
    }
  }
  return false
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
      // A direct job stops showing Apply after it has been submitted. Check the
      // applied history by Naukri job id before calling this a failure.
      const jobId = (URL.match(/-(\d{6,})\/?$/) || [])[1] || ''
      let inHistory = false
      if (jobId) {
        await page
          .goto('https://www.naukri.com/myapply/historypage', {
            waitUntil: 'domcontentloaded',
            timeout: 45000,
          })
          .catch(() => {})
        await page.waitForTimeout(6000)
        inHistory = await page
          .evaluate((id) => {
            const links = [...document.querySelectorAll('a[href]')].map(
              (item) => item.getAttribute('href') || '',
            )
            const text = document.body?.innerText || ''
            return links.some((href) => href.includes(id)) || text.includes(id)
          }, jobId)
          .catch(() => false)
      }
      if (inHistory) {
        return reportOk({
          applied: true,
          code: 'ALREADY_APPLIED',
          message: 'Naukri applied history shows this application.',
        })
      }
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
        questions: await questionText(page, afterApply),
      })
    }

    if (ANSWERS.length) {
      // The human reviewed the question and chose the answers in JobPilot.
      for (const answer of ANSWERS) {
        if (await fillAnswer(page, answer)) {
          await page.waitForTimeout(500)
        }
      }
      const save = await visibleButton(page, [
        /^save$/i,
        /^submit$/i,
        /^next$/i,
        /^apply$/i,
      ])
      if (save) {
        await save.click({ timeout: 6000 }).catch(() => {})
        await page.waitForTimeout(5000)
      }
      const afterAnswer = await bodyText(page)
      if (
        /already applied|application sent|successfully applied|applied successfully/i.test(
          afterAnswer,
        )
      ) {
        return reportOk({
          applied: true,
          code: 'APPLIED',
          message: 'Naukri confirms the application.',
          questions: await questionText(page, afterAnswer),
        })
      }
      return reportOk({
        applied: false,
        code: 'NEEDS_REVIEW',
        message: 'Naukri still asks for more details.',
        questions: await questionText(page, afterAnswer),
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
        questions: await questionText(page, afterApply),
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

/**
 * Refresh the Naukri profile's freshness signals.
 *
 * 1. Downloads the resume currently on the profile and re-uploads it as
 *    "Full Name_Resume_Role_YYYY-MM-DD.pdf" so the filename and "Uploaded on"
 *    date show today.
 * 2. Makes one small, safe wording change in the Profile Summary. Naukri then
 *    marks the profile as updated, which helps it show up as active.
 *
 * Nothing else on the profile is changed. If the known safe wording is not
 * present, the summary is left exactly as it is.
 *
 *   SCRIPT_ARG_URL      Naukri profile URL
 *   SCRIPT_ARG_NAME     Candidate name (for the file name)
 *   SCRIPT_ARG_ROLE     Role label (for the file name)
 *   SCRIPT_ARG_OUT_DIR  Folder to keep the dated copy in
 *   NAUKRI_COOKIES      JSON cookie object
 */

import fs from 'fs'
import os from 'os'
import path from 'path'
import { launchBrowser } from '../utils/browser.js'
import { reportFail, reportOk } from '../utils/report.js'

const URL = (process.env.SCRIPT_ARG_URL || 'https://www.naukri.com/mnjuser/profile').trim()
const NAME = process.env.SCRIPT_ARG_NAME || 'Resume'
const ROLE = process.env.SCRIPT_ARG_ROLE || 'Software Engineer'
const OUT_DIR = (process.env.SCRIPT_ARG_OUT_DIR || '').trim()
const DEFAULT_OUT =
  process.platform === 'win32' ? 'D:\\resume naukri' : path.join(os.homedir(), 'resume naukri')

const PHRASE_A = 'internship opportunities'
const PHRASE_B = 'internships'
const LAST_A =
  'Interested in Software Development Engineer, Backend Engineer, and Full Stack Developer internship opportunities, with a focus on building reliable, scalable software products.'
const LAST_B =
  'Looking for Software Development Engineer, Backend Engineer, and Full Stack Developer internships where I can build reliable, scalable software products.'

const HARD_DEADLINE_MS = 240000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Naukri profile refresh did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

function clean(value) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .trim()
}

function safe(value) {
  return (
    String(value || '')
      .replace(/[^A-Za-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'Resume'
  )
}

function today() {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

/** Change one small phrase in the Profile Summary and save it. */
async function tweakSummary(page) {
  const pencil = page.locator('.profileSummary .new-pencil').first()
  if (!(await pencil.count().catch(() => 0))) {
    return { changed: false, note: 'Summary edit control was not found.' }
  }
  await pencil.click({ timeout: 8000, force: true }).catch(() => {})

  const box = page.locator('textarea#summary, textarea[name="summary"]').first()
  await box.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {})
  if (!(await box.count().catch(() => 0))) {
    return { changed: false, note: 'The summary editor did not open.' }
  }

  const current = clean(await box.inputValue().catch(() => ''))
  if (!current) return { changed: false, note: 'The summary is empty.' }

  let target = ''
  let replacement = ''
  if (current.includes(PHRASE_A)) {
    target = PHRASE_A
    replacement = PHRASE_B
  } else if (current.includes(PHRASE_B)) {
    target = PHRASE_B
    replacement = PHRASE_A
  } else if (current.includes(LAST_A)) {
    target = LAST_A
    replacement = LAST_B
  } else if (current.includes(LAST_B)) {
    target = LAST_B
    replacement = LAST_A
  } else {
    return { changed: false, note: 'The summary has no known safe wording to change.' }
  }

  const proposed = current.replace(target, replacement)
  if (!proposed || proposed === current) {
    return { changed: false, note: 'The summary was already up to date.' }
  }
  if (proposed.length > 1000) {
    return { changed: false, note: 'The summary would exceed the 1000 character limit.' }
  }

  // Type the replacement instead of fill(): Naukri's React state ignores a
  // programmatic value change, so Save would close the modal without saving.
  const start = current.indexOf(target)
  await box.evaluate(
    (element, range) => {
      element.focus()
      element.setSelectionRange(range.start, range.start + range.length)
    },
    { start, length: target.length },
  )
  await page.keyboard.type(replacement, { delay: 12 })
  await page.waitForTimeout(500)

  const typed = clean(await box.inputValue().catch(() => ''))
  if (!typed.includes(replacement) || typed.includes(target)) {
    return { changed: false, note: 'The summary text did not change in the editor.' }
  }

  const save = page
    .locator('.fn-modal .btn.btn-blue, .fn-modal button')
    .filter({ hasText: /^save$/i })
    .first()
  if (!(await save.count().catch(() => 0))) {
    return { changed: false, note: 'The summary Save button was not found.' }
  }
  await save.click({ timeout: 8000 }).catch(() => {})

  for (let attempt = 0; attempt < 25; attempt += 1) {
    await page.waitForTimeout(400)
    if (!(await page.locator('.fn-modal').isVisible().catch(() => false))) break
  }

  // Naukri can show the new text before the save request finishes, so reopen
  // the editor and verify what was actually stored.
  await pencil.click({ timeout: 8000, force: true }).catch(() => {})
  await page.waitForTimeout(1200)
  const stored = clean(await box.inputValue().catch(() => ''))
  const changed = stored.includes(replacement) && !stored.includes(target)
  await page.keyboard.press('Escape').catch(() => {})
  return { changed, note: changed ? '' : 'The summary change was not stored.' }
}

async function run() {
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-naukri`
  process.env.JOBPILOT_EPHEMERAL = '1'
  process.env.STEALTH_HEADLESS = '1'
  const { browser, context, page } = await launchBrowser({ withSession: false })

  async function finish(payload) {
    let cookies = {}
    if (payload.code !== 'LOGIN_REQUIRED') {
      try {
        for (const cookie of await context.cookies('https://www.naukri.com')) {
          if (String(cookie.domain || '').includes('naukri')) cookies[cookie.name] = cookie.value
        }
      } catch {
        cookies = {}
      }
    }
    const extra = Object.keys(cookies).length ? { cookies } : {}
    return reportOk({ ...payload, ...extra })
  }

  try {
    const stored = (() => {
      try {
        return JSON.parse(process.env.NAUKRI_COOKIES || '{}')
      } catch {
        return {}
      }
    })()
    const cookies = Object.entries(stored)
      .filter(([name, value]) => name && value)
      .map(([name, value]) => ({ name, value: String(value), domain: '.naukri.com', path: '/' }))
    if (cookies.length) await context.addCookies(cookies).catch(() => {})

    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
    await page.waitForTimeout(7000)
    await page.bringToFront().catch(() => {})

    if (/\/nlogin\//i.test(page.url())) {
      return finish({
        ok: false,
        code: 'LOGIN_REQUIRED',
        error: 'The Naukri session expired. Reconnect Naukri and sign in again.',
      })
    }

    const resume = page.locator('.section.resume, .resume').first()
    await resume.waitFor({ state: 'visible', timeout: 20000 }).catch(() => {})
    const nameNode = page.locator('.section.resume .file-name, .resume .file-name').first()
    const current = clean(await nameNode.innerText().catch(() => ''))
    const outDir = OUT_DIR || DEFAULT_OUT
    fs.mkdirSync(outDir, { recursive: true })

    let datedName = `${safe(NAME)}_Resume_${safe(ROLE)}_${today()}.pdf`
    let target = path.join(outDir, datedName)
    let resumeSkipped = current === datedName
    let resumeError = ''
    let uploadedOn = ''

    if (!resumeSkipped) {
      const downloadPromise = page.waitForEvent('download', { timeout: 30000 }).catch(() => null)
      await page
        .locator('.section.resume .download, .resume .download')
        .first()
        .click({ timeout: 8000 })
        .catch(() => {})
      const download = await downloadPromise
      if (!download) {
        resumeError = 'Naukri did not provide the current resume to download.'
      } else {
        const suggested = download.suggestedFilename() || 'resume.pdf'
        const extension = path.extname(suggested) || '.pdf'
        datedName = `${safe(NAME)}_Resume_${safe(ROLE)}_${today()}${extension}`
        target = path.join(outDir, datedName)
        resumeSkipped = current === datedName
        const downloaded = path.join(outDir, `downloaded-${Date.now()}${extension}`)
        try {
          await download.saveAs(downloaded)
          fs.copyFileSync(downloaded, target)

          if (!resumeSkipped) {
            const chooserPromise = page
              .waitForEvent('filechooser', { timeout: 20000 })
              .catch(() => null)
            await page
              .getByText('Update resume', { exact: true })
              .first()
              .click({ timeout: 8000 })
              .catch(() => {})
            const chooser = await chooserPromise
            if (!chooser) {
              resumeError = 'Naukri did not open the resume upload.'
            } else {
              await chooser.setFiles(target)
              let uploaded = false
              for (let attempt = 0; attempt < 60; attempt += 1) {
                await page.waitForTimeout(500)
                const shown = clean(await nameNode.innerText().catch(() => ''))
                if (shown === datedName) {
                  uploaded = true
                  uploadedOn = clean(
                    await page
                      .locator('.section.resume .uploaded-date, .resume .uploaded-date')
                      .first()
                      .innerText()
                      .catch(() => ''),
                  )
                  break
                }
              }
              if (!uploaded) resumeError = 'The resume name did not change after the upload.'
            }
          }
        } catch (err) {
          resumeError = err.message || 'The resume could not be uploaded.'
        } finally {
          fs.rmSync(downloaded, { force: true })
        }
      }
    }

    // Update the summary even when the resume is already dated today, so one
    // click always refreshes the profile's "last updated" signal.
    const summary = await tweakSummary(page).catch((err) => ({
      changed: false,
      note: err.message || 'The summary could not be updated.',
    }))

    if (resumeError) {
      return finish({
        ok: false,
        code: 'RESUME_FAILED',
        error: resumeError,
        filename: datedName,
        skipped: resumeSkipped,
        summary_updated: summary.changed,
        summary_note: summary.note || '',
      })
    }

    return finish({
      ok: true,
      skipped: resumeSkipped,
      filename: datedName,
      uploaded_on: uploadedOn,
      previous: current,
      summary_updated: summary.changed,
      summary_note: summary.note || '',
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

run()
  .then(() => {
    clearTimeout(watchdog)
    setTimeout(() => process.exit(0), 150)
  })
  .catch(() => process.exit(1))

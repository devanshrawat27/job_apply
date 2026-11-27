/**
 * Refresh the Naukri resume name with today's date.
 *
 * Downloads the resume currently on the profile, renames it to
 * "Full Name_Resume_Role_YYYY-MM-DD.pdf" and uploads it again. Naukri saves the
 * upload immediately and shows a fresh "Uploaded on" date. The profile summary
 * is never touched.
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
const HARD_DEADLINE_MS = 180000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Naukri resume refresh did not finish in time')
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

async function run() {
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-naukri`
  process.env.STEALTH_HEADLESS = '0'
  process.env.STEALTH_OFFSCREEN = '1'
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
    const filename = `${safe(NAME)}_Resume_${safe(ROLE)}_${today()}.pdf`

    if (current === filename) {
      return finish({
        ok: true,
        skipped: true,
        filename,
        message: 'Resume is already dated today.',
      })
    }

    const outDir = OUT_DIR && fs.existsSync(OUT_DIR) ? OUT_DIR : os.tmpdir()
    fs.mkdirSync(outDir, { recursive: true })
    const downloaded = path.join(outDir, `downloaded-${Date.now()}.pdf`)

    const downloadPromise = page.waitForEvent('download', { timeout: 30000 }).catch(() => null)
    await page
      .locator('.section.resume .download, .resume .download')
      .first()
      .click({ timeout: 8000 })
      .catch(() => {})
    const download = await downloadPromise
    if (!download) {
      return finish({
        ok: false,
        code: 'NO_DOWNLOAD',
        error: 'Naukri did not provide the current resume to download.',
      })
    }
    const suggested = download.suggestedFilename() || 'resume.pdf'
    const extension = path.extname(suggested) || '.pdf'
    const datedName = `${safe(NAME)}_Resume_${safe(ROLE)}_${today()}${extension}`
    await download.saveAs(downloaded)
    const target = path.join(outDir, datedName)
    fs.copyFileSync(downloaded, target)
    fs.rmSync(downloaded, { force: true })

    const chooserPromise = page.waitForEvent('filechooser', { timeout: 20000 }).catch(() => null)
    await page
      .getByText('Update resume', { exact: true })
      .first()
      .click({ timeout: 8000 })
      .catch(() => {})
    const chooser = await chooserPromise
    if (!chooser) {
      return finish({
        ok: false,
        code: 'NO_FILE_CHOOSER',
        error: 'Naukri did not open the resume upload.',
      })
    }
    await chooser.setFiles(target)

    let uploaded = false
    let uploadedOn = ''
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
    if (!uploaded) {
      return finish({
        ok: false,
        code: 'NOT_UPDATED',
        error: 'The resume name did not change after the upload.',
      })
    }

    return finish({
      ok: true,
      skipped: false,
      filename: datedName,
      uploaded_on: uploadedOn,
      previous: current,
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

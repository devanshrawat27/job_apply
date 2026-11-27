/**
 * Apply to a Naukri job in the one visible Naukri Chrome window.
 *
 * Direct Naukri jobs can be submitted from the job page. External ("Apply on
 * company site") jobs are reported back so the human gets the link instead.
 *
 * Naukri's questionnaire is a chat drawer. It asks one question at a time, so
 * this script loops: answer, Save, wait for the next question, and repeat until
 * Naukri shows the job as Applied. Questions that can be answered from the
 * profile are filled automatically; anything subjective (e.g. a bond) is
 * returned for the human. Naukri stores answered questions server-side, so the
 * next run resumes at the next unanswered question.
 *
 *   SCRIPT_ARG_URL      Naukri job URL
 *   SCRIPT_ARG_PROFILE  JSON profile facts used for automatic answers
 *   SCRIPT_ARG_ANSWERS  JSON {question: answer} chosen by the human
 *   NAUKRI_COOKIES      JSON cookie object
 */

import { launchBrowser } from '../utils/browser.js'
import { reportFail, reportOk } from '../utils/report.js'

const URL = (process.env.SCRIPT_ARG_URL || '').trim()
const PROFILE = (() => {
  try {
    const value = JSON.parse(process.env.SCRIPT_ARG_PROFILE || '{}')
    return value && typeof value === 'object' ? value : {}
  } catch {
    return {}
  }
})()
const HUMAN_ANSWERS = (() => {
  try {
    const value = JSON.parse(process.env.SCRIPT_ARG_ANSWERS || '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) return []
    return Object.entries(value)
      .map(([question, answer]) => ({
        question: clean(question),
        answer: clean(answer),
      }))
      .filter((item) => item.question && item.answer)
  } catch {
    return []
  }
})()
const HARD_DEADLINE_MS = 300000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Naukri apply did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

function clean(value) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .trim()
}

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

async function bodyText(page) {
  return page
    .locator('body')
    .innerText()
    .then((value) => clean(value))
    .catch(() => '')
}

/** Naukri swaps Apply for this badge once an application exists. */
async function isApplied(page) {
  return (await page.locator('.already-applied').count().catch(() => 0)) > 0
}

async function loginWall(page) {
  if (/\/nlogin\//i.test(page.url())) return true
  return (await page.locator('input[type="password"]').count().catch(() => 0)) > 0
}

/** Everything the script needs to know about Naukri's current question. */
async function drawerState(page) {
  return page.evaluate(() => {
    const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim()
    const drawer = document.querySelector('.chatbot_Drawer')
    if (!drawer) {
      return { open: false, question: '', options: [], freeText: false, saveReady: false }
    }
    const messages = [...drawer.querySelectorAll('.botMsg span')]
      .map((node) => norm(node.innerText))
      .filter(Boolean)
    const question = messages.length ? messages[messages.length - 1] : ''
    const options = [...drawer.querySelectorAll('input[type="radio"]')].map((input) => {
      const label = input.id
        ? drawer.querySelector(`label[for="${input.id.replace(/"/g, '\\"')}"]`)
        : null
      return {
        id: input.id || '',
        value: input.value || '',
        label: norm(label?.innerText) || input.value || '',
      }
    })
    const freeBox = drawer.querySelector(
      '[contenteditable="true"], textarea, input[type="text"]',
    )
    const send = drawer.querySelector('.sendMsgbtn_container .send')
    return {
      open: true,
      question,
      options,
      freeText: Boolean(freeBox),
      saveReady: send ? !String(send.className).includes('disabled') : false,
      drawerText: norm(drawer.innerText).slice(0, 2000),
    }
  })
}

function optionFor(state, value) {
  const wanted = clean(value).toLowerCase()
  if (!wanted) return null
  return (
    state.options.find((option) => clean(option.label).toLowerCase() === wanted) ||
    state.options.find((option) => clean(option.value).toLowerCase() === wanted) ||
    null
  )
}

/** The human answer for exactly this question, if they already gave one. */
function humanAnswerFor(state) {
  const current = clean(state.question).toLowerCase()
  if (!current) return ''
  for (const item of HUMAN_ANSWERS) {
    const asked = clean(item.question).toLowerCase()
    if (!asked) continue
    const askedQuestion = asked.split('options:')[0].trim()
    if (
      askedQuestion === current ||
      askedQuestion.includes(current) ||
      current.includes(askedQuestion)
    ) {
      return item.answer
    }
  }
  return ''
}

/** Answer the questions that are plain profile facts, without guessing. */
function autoAnswer(state) {
  const question = clean(state.question).toLowerCase()
  const has = (value) => Boolean(optionFor(state, value))
  const experienced = Number(PROFILE.experience_months || 0) >= 12

  if (/year of (passed|passing)|passout|pass out|graduation year|year of graduation|batch/.test(question)) {
    const year = String(PROFILE.graduation_year || '')
    if (!year) return ''
    if (!state.options.length) return year
    return has(year) ? year : ''
  }
  if (/degree/.test(question)) {
    if (state.options.length) {
      const degree = clean(PROFILE.degree).toLowerCase()
      if (degree) {
        const match = state.options.find((option) => {
          const label = clean(option.label).toLowerCase()
          return label && (degree.includes(label) || label.includes(degree.split(' ')[0]))
        })
        if (match) return match.label
      }
      return ''
    }
    return clean(PROFILE.degree)
  }
  if (/qualification/.test(question)) {
    if (has('UG')) return 'UG'
    if (has('PG') && /post|master|m\.?\s?tech/i.test(clean(PROFILE.degree))) return 'PG'
    return ''
  }
  if (/experience|experienc/.test(question)) {
    if (has('No')) return experienced ? 'Yes' : 'No'
    return ''
  }
  if (/\bpf\b|provident fund/.test(question)) {
    if (has('No')) return experienced ? 'Yes' : 'No'
    return ''
  }
  if (/relocat|willing to (travel|relocate|move)|shift/.test(question)) {
    if (has('Yes')) return PROFILE.willing_to_relocate ? 'Yes' : 'No'
    return ''
  }
  if (/notice period/.test(question)) {
    if (has('Immediate')) return 'Immediate'
    if (!state.options.length) return 'Immediate'
    return ''
  }
  if (/cgpa|percentage|marks/.test(question) && !state.options.length) {
    return clean(PROFILE.cgpa)
  }
  if (/current location|location|city/.test(question) && !state.options.length) {
    return clean(PROFILE.location)
  }
  return ''
}

async function chooseOption(page, option) {
  if (!option) return false
  if (option.id) {
    const label = page
      .locator(`.chatbot_Drawer label[for="${option.id.replace(/"/g, '\\"')}"]`)
      .first()
    if (await label.count().catch(() => 0)) {
      await label.click({ timeout: 8000, force: true }).catch(() => {})
      return true
    }
  }
  const radio = page
    .locator(`.chatbot_Drawer input[type="radio"][value="${option.value.replace(/"/g, '\\"')}"]`)
    .first()
  if (await radio.count().catch(() => 0)) {
    await radio.click({ timeout: 8000, force: true }).catch(() => {})
    return true
  }
  return false
}

async function typeAnswer(page, answer) {
  const box = page
    .locator(
      '.chatbot_Drawer [contenteditable="true"], .chatbot_Drawer textarea, .chatbot_Drawer input[type="text"]',
    )
    .first()
  if (!(await box.count().catch(() => 0))) return false
  await box.click({ timeout: 8000, force: true }).catch(() => {})
  await box.fill(answer).catch(() => {})
  return true
}

async function saveEnabled(page) {
  return page
    .locator('.sendMsgbtn_container .send')
    .first()
    .evaluate((node) => !String(node.className).includes('disabled'))
    .catch(() => false)
}

/** Click the drawer's own Save. Never the page's "Save job" bookmark. */
async function clickSave(page) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (await saveEnabled(page)) break
    await page.waitForTimeout(250)
  }
  const save = page.locator('.sendMsgbtn_container .sendMsg').first()
  if (!(await save.count().catch(() => 0))) return false
  await save.click({ timeout: 8000, force: true }).catch(() => {})
  return true
}

function successText(text) {
  return /you have successfully applied|successfully applied to|application sent|applied successfully/i.test(
    text,
  )
}

function formattedQuestion(state) {
  if (!state.question) return ''
  if (!state.options.length) return state.question
  const options = state.options.map((option) => clean(option.label)).filter(Boolean)
  return `${state.question}\nOptions: ${options.join(' / ')}`
}

function review(state, message) {
  return {
    applied: false,
    code: 'NEEDS_REVIEW',
    message,
    question: state.question || '',
    options: state.options.map((option) => clean(option.label)).filter(Boolean),
    questions: formattedQuestion(state),
  }
}

async function run() {
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-naukri`
  process.env.STEALTH_HEADLESS = '0'
  process.env.STEALTH_OFFSCREEN = '1'
  const { browser, context, page } = await launchBrowser({ withSession: false })

  /** Report a result and persist the current Naukri cookies for the next run. */
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
    console.log(`[naukriApply] page ${page.url()}`)

    // Use the visible window's own session first, so a manual sign-in is not
    // thrown away. Only fall back to the stored cookies if it is logged out.
    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
    await page.waitForTimeout(6000)
    await page.bringToFront().catch(() => {})
    if (await loginWall(page)) {
      const cookies = storedCookies()
      if (cookies.length) {
        await context.addCookies(cookies).catch(() => {})
        await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
        await page.waitForTimeout(6000)
      }
    }
    console.log(`[naukriApply] job page ${page.url()}`)

    if (await loginWall(page)) {
      return finish({
        applied: false,
        code: 'LOGIN_REQUIRED',
        message: 'The Naukri session expired. Reconnect Naukri and sign in again.',
      })
    }

    if (await page.locator('.company-site-button').count().catch(() => 0)) {
      return finish({
        applied: false,
        code: 'EXTERNAL',
        message: 'This job applies on the company site.',
      })
    }

    if (await isApplied(page)) {
      return finish({
        applied: true,
        code: 'ALREADY_APPLIED',
        message: 'Naukri already shows this job as applied.',
      })
    }

    const applyButton = page.locator('.apply-button').first()
    const hasApply = await applyButton.count().catch(() => 0)
    const drawerBefore = await drawerState(page)

    // A previous run may have left the question drawer open.
    if (!drawerBefore.open) {
      if (!hasApply) {
        return finish({
          applied: false,
          code: 'NO_APPLY',
          message: 'No direct Naukri apply button was found.',
        })
      }
      await applyButton.click({ timeout: 10000, force: true }).catch(() => {})
      await page.waitForTimeout(5000)
    }

    for (let round = 0; round < 12; round += 1) {
      if (await loginWall(page)) {
        return finish({
          applied: false,
          code: 'LOGIN_REQUIRED',
          message: 'The Naukri session expired. Reconnect Naukri and sign in again.',
        })
      }
      const state = await drawerState(page)
      const text = await bodyText(page)

      if (!state.open) {
        if ((await isApplied(page)) || successText(text)) {
          return finish({
            applied: true,
            code: 'APPLIED',
            message: 'Naukri confirms the application.',
          })
        }
        return finish({
          applied: false,
          code: 'NEEDS_REVIEW',
          message: 'Naukri did not show a clear submit step.',
          questions: text.slice(0, 1500),
        })
      }

      if (successText(state.drawerText) && !state.question) {
        return finish({
          applied: true,
          code: 'APPLIED',
          message: 'Naukri confirms the application.',
        })
      }

      if (!state.question && !state.options.length && !state.freeText) {
        return finish(review(state, 'Naukri opened a step that needs you.'))
      }

      const human = humanAnswerFor(state)
      const automatic = human ? '' : autoAnswer(state)
      const answer = human || automatic
      if (!answer) {
        return finish(review(state, 'Naukri asks a question that needs your answer.'))
      }

      let accepted = false
      if (state.options.length) {
        const option = optionFor(state, answer)
        if (!option) {
          return finish(
            review(state, `Naukri does not offer "${answer}" for this question. Pick one of its options.`),
          )
        }
        accepted = await chooseOption(page, option)
      } else if (state.freeText) {
        accepted = await typeAnswer(page, answer)
      }

      if (!accepted) {
        return finish(review(state, 'Naukri did not accept the answer automatically.'))
      }

      await page.waitForTimeout(500)
      if (!(await saveEnabled(page))) {
        return finish(review(state, 'Naukri did not enable Save after the answer.'))
      }
      if (!(await clickSave(page))) {
        return finish(review(state, 'Naukri did not show its Save button.'))
      }

      // Wait for the next question or the applied badge.
      let changed = false
      let finished = false
      for (let wait = 0; wait < 30; wait += 1) {
        await page.waitForTimeout(500)
        if (await isApplied(page)) {
          finished = true
          break
        }
        const next = await drawerState(page)
        const pageText = await bodyText(page)
        if (!next.open) {
          finished = true
          break
        }
        if (successText(next.drawerText) || successText(pageText)) {
          finished = true
          break
        }
        if (
          next.question !== state.question ||
          next.options.length !== state.options.length ||
          next.options.some((option, index) => option.label !== state.options[index]?.label)
        ) {
          changed = true
          break
        }
      }

      if (finished) {
        return finish({
          applied: true,
          code: 'APPLIED',
          message: 'Naukri confirms the application.',
        })
      }
      if (!changed) {
        return finish(review(await drawerState(page), 'Naukri did not advance after the answer.'))
      }
    }

    return finish(review(await drawerState(page), 'Naukri still has more questions.'))
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
  clearTimeout(watchdog)
  process.exit(1)
} else {
  run()
    .then(() => {
      clearTimeout(watchdog)
      // When attached over CDP the DevTools socket is still open, so Node would
      // stay alive after the RESULT_JSON line. Exit now that the result is out.
      setTimeout(() => process.exit(0), 150)
    })
    .catch(() => {
      clearTimeout(watchdog)
      process.exit(1)
    })
}

/**
 * Read-only: which ChatGPT account is logged in on the dedicated profile?
 * Uses ChatGPT's own session endpoint, so nothing is sent or changed.
 */

import { launchChatgpt } from '../utils/chatgptBrowser.js'
import { minimizeBrowserWindow } from '../utils/minimize.js'
import { reportFail, reportOk } from '../utils/report.js'

const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Could not read the ChatGPT account in 90s')
  process.exit(1)
}, 90000)

async function main() {
  const { context, page } = await launchChatgpt()
  try {
    await page.goto('https://chatgpt.com/', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(3000)

    const session = await page.evaluate(async () => {
      try {
        const res = await fetch('/api/auth/session', { credentials: 'include' })
        if (!res.ok) return { error: `HTTP ${res.status}` }
        const data = await res.json()
        return {
          email: data?.user?.email || '',
          name: data?.user?.name || '',
          plan: data?.account?.planType || data?.planType || '',
        }
      } catch (err) {
        return { error: String(err) }
      }
    })

    if (!session || session.error || !session.email) {
      reportFail(
        'NOT_LOGGED_IN',
        session?.error || 'No ChatGPT session found - reconnect ChatGPT in Settings',
      )
      return
    }

    if (process.env.STEALTH_HEADLESS !== '1') await minimizeBrowserWindow('chatgpt-profile')
    reportOk(session)
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

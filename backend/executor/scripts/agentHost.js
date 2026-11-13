/**
 * Persistent browser host (reference pattern).
 *
 * Every action script used to launch and close its own browser. X's encrypted
 * chat app needs a warm, already-logged-in page, so instead we launch ONE
 * browser, expose it over CDP, and every child script attaches to the same
 * context + page.
 *
 * Protocol:
 *   stdout -> "AGENT_HOST_READY <endpoint>"
 *   stdin  -> "close"
 */

import { launchBrowser } from '../utils/browser.js'
import { minimizeBrowserWindow } from '../utils/minimize.js'

async function main() {
  const port = process.env.BROWSER_CDP_PORT
  if (!port) {
    console.error('agentHost: BROWSER_CDP_PORT not set')
    process.exit(1)
  }

  const { browser, context, page } = await launchBrowser()
  const endpoint = `http://127.0.0.1:${port}`

  // Keep the window in the taskbar but out of the user's way. Headless mode
  // has no window at all; the interactive login flow is separate.
  if (process.env.STEALTH_HEADLESS !== '1') {
    await new Promise((resolve) => setTimeout(resolve, 1500))
    await minimizeBrowserWindow()
  }

  // Wait for the feed so the first child script does not race a cold page.
  try {
    await page.waitForSelector('[data-testid="tweet"]', { timeout: 30000 })
  } catch {
    // Not fatal - child scripts retry.
  }

  process.stdout.write(`AGENT_HOST_READY ${endpoint}\n`)

  for await (const chunk of process.stdin) {
    if (String(chunk).trim() === 'close') break
  }

  await page?.close().catch(() => {})
  await context?.close().catch(() => {})
  await browser?.close().catch(() => {})
  process.exit(0)
}

main().catch((err) => {
  console.error('agentHost failed:', err.message)
  process.exit(1)
})

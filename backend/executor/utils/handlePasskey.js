import { humanClick, humanSettle } from './humanize.js'

/**
 * Dismiss the X passkey / security-key prompt if it appears.
 * Straight from the reference executor.
 */
export default async function handlePasskey(page) {
  const combinedSelector = [
    '[data-testid="app-bar-close"]',
    '[data-testid="sheet-close"]',
    'button[aria-label*="Close" i]',
    'button[aria-label*="Dismiss" i]',
    'button[aria-label*="Not now" i]',
    'div[role="button"]:has-text("Not now")',
    'div[role="button"]:has-text("Maybe later")',
    'button:has-text("Not now")',
    'button:has-text("Maybe later")',
  ].join(', ')

  try {
    const locator = page.locator(combinedSelector).first()
    await locator.waitFor({ state: 'visible', timeout: 1500 })
    await humanClick(page, locator)
    await humanSettle(400, 900)
  } catch {
    // no passkey modal appeared
  }
}

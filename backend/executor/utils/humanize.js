import { randomInt } from 'crypto'

/** Random integer in [min, max]. */
function jitter(min, max) {
  return randomInt(min, max + 1)
}

/** Sleep for a random duration in milliseconds. */
export async function randomWait(min = 800, max = 2200) {
  await new Promise((r) => setTimeout(r, jitter(min, max)))
}

export async function humanSettle(min = 300, max = 900) {
  await randomWait(min, max)
}

/**
 * Move the mouse along a curved path, then click with a small random offset.
 * Falls back to a plain locator click if the geometry is unavailable.
 */
export async function humanClick(pageOrLocator, selector) {
  const page = pageOrLocator?.page ? pageOrLocator.page() : pageOrLocator
  const locator =
    typeof selector === 'string' ? page.locator(selector).first() : selector

  try {
    await locator.scrollIntoViewIfNeeded({ timeout: 5000 })
    const box = await locator.boundingBox()
    if (box) {
      const targetX = box.x + jitter(2, Math.max(3, Math.floor(box.width - 4)))
      const targetY = box.y + jitter(2, Math.max(3, Math.floor(box.height - 4)))
      const viewport = page.viewportSize() || { width: 1280, height: 800 }
      const startX = jitter(100, Math.max(120, viewport.width - 100))
      const startY = jitter(100, Math.max(120, viewport.height - 100))
      const cp1X = startX + (targetX - startX) / 2 + jitter(-60, 60)
      const cp1Y = startY + (targetY - startY) / 2 + jitter(-60, 60)

      const steps = jitter(8, 18)
      for (let i = 0; i <= steps; i++) {
        const t = i / steps
        const oneMinusT = 1 - t
        const x = oneMinusT ** 2 * startX + 2 * oneMinusT * t * cp1X + t ** 2 * targetX
        const y = oneMinusT ** 2 * startY + 2 * oneMinusT * t * cp1Y + t ** 2 * targetY
        await page.mouse.move(x, y)
        await new Promise((r) => setTimeout(r, jitter(5, 14)))
      }

      await new Promise((r) => setTimeout(r, jitter(80, 240)))
      await page.mouse.down()
      await new Promise((r) => setTimeout(r, jitter(40, 110)))
      await page.mouse.up()
      return
    }
  } catch {
    // fall through to a normal click
  }

  await locator.click({ timeout: 10000 })
}

/**
 * Type like a person: per-key jitter, occasional pauses. Never logs the text.
 */
export async function humanType(pageOrLocator, selectorOrText, maybeText, opts = {}) {
  let page = pageOrLocator
  const selector = typeof maybeText === 'string' ? selectorOrText : undefined
  const text = typeof maybeText === 'string' ? maybeText : selectorOrText

  if (pageOrLocator?.page) page = pageOrLocator.page()

  if (selector) {
    const locator = page.locator(selector).first()
    await humanClick(page, locator)
    await humanSettle(150, 400)
  }

  const { burstChance = 0.15 } = opts

  for (const char of text) {
    if (char === '\n') {
      await page.keyboard.press('Shift+Enter')
      await new Promise((r) => setTimeout(r, jitter(80, 220)))
      continue
    }
    if (Math.random() < 0.02) await randomWait(400, 1200)
    const delay = Math.random() < burstChance ? jitter(15, 45) : jitter(45, 140)
    await page.keyboard.type(char, { delay: 0 })
    await new Promise((r) => setTimeout(r, delay))
  }
}

export async function waitForVisible(page, selector, timeout = 10000) {
  const locator = page.locator(selector).first()
  await locator.waitFor({ state: 'visible', timeout })
  await humanSettle(200, 600)
}

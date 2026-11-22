import { launchBrowser } from './utils/browser.js'

const { context, page } = await launchBrowser({ withSession: false })
try {
  const before = await context.cookies('https://www.linkedin.com')
  console.log('before url:', page.url())
  console.log('before cookies:', before.map((c) => `${c.name}:${String(c.value).length}`).join(', '))
  await page.goto('https://www.linkedin.com/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2500)
  console.log('after url:', page.url())
  const after = await context.cookies('https://www.linkedin.com')
  console.log('after cookies:', after.map((c) => `${c.name}:${String(c.value).length}`).join(', '))
  console.log('body:', (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 300))
} catch (error) {
  console.log('ERR', error.message)
} finally {
  await context.close().catch(() => {})
}

import { launchBrowser } from './utils/browser.js'

const { context, page } = await launchBrowser({ withSession: false })
try {
  await page.goto('https://www.linkedin.com/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(3000)
  console.log('url:', page.url())
  console.log('title:', await page.title())
  const inputs = await page.locator('input').evaluateAll((nodes) =>
    nodes.slice(0, 16).map((node) => ({
      id: node.id,
      name: node.name,
      type: node.type,
      autocomplete: node.autocomplete,
      visible: Boolean(node.offsetWidth || node.offsetHeight),
    })),
  )
  console.log('inputs:', JSON.stringify(inputs, null, 2))
  console.log('body:', (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 600))
} catch (error) {
  console.log('ERR', error.message)
} finally {
  await context.close().catch(() => {})
}

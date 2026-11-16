/** Read-only: is the X session healthy? */

import fs from 'fs'

import { launchBrowser } from '../utils/browser.js'

const OUT = 'D:\\CODING\\twitterJobAppyly\\job_apply\\backend\\_x_state.json'
const SHOT = 'D:\\CODING\\twitterJobAppyly\\job_apply\\backend\\_x_state.png'

async function main() {
  const { context, page } = await launchBrowser()
  const data = {}
  try {
    // A stale Cloudflare clearance from another browser build can keep the
    // challenge looping. Drop only Cloudflare cookies, never the X session.
    for (const name of ['cf_clearance', '__cf_bm', '_cfuvid', 'cf_chl_2']) {
      await context.clearCookies({ name }).catch(() => {})
    }
    await page.goto('https://x.com/home', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(12000)

    data.url = page.url()
    data.title = await page.title()
    const text = await page.locator('body').innerText().catch(() => '')
    data.text = text.replace(/\s+/g, ' ').slice(0, 600)
    data.challenge = /verifying you are human|just a moment|verify you are human/i.test(
      await page.title() + ' ' + text,
    )
    data.accountAccess = page.url().includes('/account/access')
    data.loginWall = /log in|sign in/i.test(data.text.slice(0, 200)) && !text.includes('For you')
    data.composer = await page
      .locator('[data-testid="tweetTextarea_0"], [contenteditable="true"]')
      .count()
      .catch(() => 0)
    await page.screenshot({ path: SHOT, fullPage: false }).catch(() => {})
  } finally {
    fs.writeFileSync(OUT, JSON.stringify(data, null, 2), 'utf8')
    await context.close().catch(() => {})
  }
  console.log(JSON.stringify(data, null, 2))
}

main().catch((err) => {
  fs.writeFileSync(OUT, JSON.stringify({ error: String(err) }, null, 2), 'utf8')
  console.log('ERROR', err.message)
  process.exitCode = 1
})

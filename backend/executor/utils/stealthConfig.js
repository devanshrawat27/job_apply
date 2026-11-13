/**
 * Browser settings. Every value comes from the environment - the Python
 * backend injects it, so the executor never reads a .env file itself.
 *
 *   STEALTH_HEADLESS=1        run without a window (servers only)
 *   PROXY_SERVER / PROXY_USERNAME / PROXY_PASSWORD
 *   STEALTH_LOCALE=en-US
 *   STEALTH_TIMEZONE=Asia/Kolkata
 *   BROWSER_CHANNEL=chrome    use the installed Chrome instead of bundled Chromium
 */
export function getStealthConfig() {
  const proxy = process.env.PROXY_SERVER
    ? {
        server: process.env.PROXY_SERVER,
        username: process.env.PROXY_USERNAME || undefined,
        password: process.env.PROXY_PASSWORD || undefined,
      }
    : undefined

  return {
    proxy,
    locale: process.env.STEALTH_LOCALE || 'en-US',
    timezone: process.env.STEALTH_TIMEZONE || 'Asia/Kolkata',
    headless: process.env.STEALTH_HEADLESS === '1',
    channel: process.env.BROWSER_CHANNEL || undefined,
    credentials: {
      authToken: process.env.TWITTER_AUTH_TOKEN || undefined,
      ct0: process.env.TWITTER_CT0 || undefined,
      twid: process.env.TWITTER_TWID || undefined,
    },
  }
}

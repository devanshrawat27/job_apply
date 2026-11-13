/** Inject the X session cookies into a Playwright BrowserContext. */
export async function injectCookies(context, credentials) {
  const { authToken, ct0, twid } = credentials || {}
  if (!authToken || !ct0) return

  const cookies = [
    {
      name: 'auth_token',
      value: authToken,
      domain: '.x.com',
      path: '/',
      httpOnly: true,
      secure: true,
    },
    {
      name: 'ct0',
      value: ct0,
      domain: '.x.com',
      path: '/',
      secure: true,
    },
  ]

  if (twid) {
    cookies.push({ name: 'twid', value: twid, domain: '.x.com', path: '/', secure: true })
  }

  await context.addCookies(cookies)
}

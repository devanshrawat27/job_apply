/**
 * Structured result contract between the Playwright scripts and the Python
 * backend.
 *
 * Every script prints EXACTLY ONE machine line on stdout:
 *
 *   RESULT_JSON:{"success":true,"code":"OK","data":{...}}
 *   RESULT_JSON:{"success":false,"code":"SESSION_EXPIRED","error":"..."}
 *
 * Codes: OK | SESSION_EXPIRED | RATE_LIMITED | TARGET_NOT_FOUND | SELECTOR_MISS |
 *        VALIDATION | TIMEOUT | DUPLICATE | UNKNOWN | EMPTY | ERROR
 *
 * UNKNOWN means a write may or may not have landed. The backend must never
 * retry an UNKNOWN write automatically.
 */

const MARKER = 'RESULT_JSON:'

function emit(payload) {
  process.stdout.write(MARKER + JSON.stringify(payload) + '\n')
}

export function reportOk(data = {}) {
  emit({ success: true, code: 'OK', data })
}

export function reportFail(code, error, data = {}) {
  emit({ success: false, code, error: String(error), data })
}

let csrfToken = ''
export const setCsrfToken = (value: string) => { csrfToken = value }
export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch('/api' + path, {
      ...options,
      credentials: 'same-origin',
      headers: {
        ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...(csrfToken && !['GET', 'HEAD'].includes(options.method || 'GET') ? { 'X-CSRF-Token': csrfToken } : {}),
        ...options.headers,
      },
    })
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error
    throw new Error('暂时无法连接工作台，请检查网络后重试。')
  }
  if (!response.ok) {
    let message = '操作失败，请稍后重试。'
    try {
      const body = await response.json()
      message = typeof body.detail === 'string' ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((item: { msg: string }) => item.msg).join('；')
          : body.detail?.message || message
    } catch { /* Keep the readable fallback for a proxy or non-JSON error. */ }
    if (response.status === 401 && !['/auth/login', '/auth/register'].includes(path)) {
      window.dispatchEvent(new Event('xuzhang-session-expired'))
    }
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

export const post = <T>(path: string, body: unknown) => api<T>(path, { method: 'POST', body: JSON.stringify(body) })

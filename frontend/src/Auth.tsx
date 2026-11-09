import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ArrowRight, BookOpen, Loader2 } from 'lucide-react'
import { api, ApiError, post, setCsrfToken } from './api'
import type { AuthSession, User } from './types'

export function broadcastAccountChange() {
  try { localStorage.setItem('xuzhang-auth-change', `${Date.now()}-${Math.random()}`) } catch { /* Storage may be disabled. */ }
}

export function AccountGate({ children }: { children: (user: User, signOut: () => Promise<void>) => ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  async function restore() {
    setLoading(true); setError('')
    try {
      const session = await api<AuthSession>('/auth/me')
      setCsrfToken(session.csrf_token); setUser(session.user)
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) setError((e as Error).message)
    } finally { setLoading(false) }
  }
  useEffect(() => {
    const expired = () => { setCsrfToken(''); setUser(null) }
    const changed = (event: StorageEvent) => { if (event.key === 'xuzhang-auth-change') window.location.reload() }
    window.addEventListener('xuzhang-session-expired', expired)
    window.addEventListener('storage', changed)
    void restore()
    return () => { window.removeEventListener('xuzhang-session-expired', expired); window.removeEventListener('storage', changed) }
  }, [])
  async function signOut() {
    await post('/auth/logout', {})
    setCsrfToken(''); setUser(null); broadcastAccountChange()
    window.location.hash = '/projects'
  }
  if (loading) return <main className="page-loading"><Loader2 className="spin" size={24} /><p>正在打开你的故事工作台…</p></main>
  if (error) return <main className="page-loading"><p role="alert">{error}</p><button className="button button-primary" onClick={() => void restore()}>重新连接</button></main>
  if (!user) return <LoginPage onSession={session => { setCsrfToken(session.csrf_token); setUser(session.user); broadcastAccountChange() }} />
  return children(user, signOut)
}

function LoginPage({ onSession }: { onSession: (session: AuthSession) => void }) {
  const [register, setRegister] = useState(false)
  const [registrationEnabled, setRegistrationEnabled] = useState(false)
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { void api<{ registration_enabled: boolean }>('/auth/config').then(config => setRegistrationEnabled(config.registration_enabled)).catch(e => setError(e.message)) }, [])
  useEffect(() => { document.title = `${register ? '注册' : '登录'} · 续章` }, [register])
  function switchMode(next: boolean) {
    setRegister(next); setError(''); setPassword(''); setConfirmation('')
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); setError('')
    if (register && password !== confirmation) { setError('两次输入的密码不一致'); return }
    setBusy(true)
    try {
      const session = await post<AuthSession>(register ? '/auth/register' : '/auth/login', { username, password, ...(register ? { display_name: displayName } : {}) })
      onSession(session)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <main className="auth-page">
    <section className="auth-story"><div className="auth-brand"><BookOpen size={28} strokeWidth={1.4} /><span>续章<small>XUZHANG</small></span></div>
      <div><h1>好故事，<br />从你的书架继续。</h1></div>
      <p className="auth-caption">小说改编工作台</p>
    </section>
    <section className="auth-panel"><div className="auth-form-wrap">{registrationEnabled ? <div className="auth-tabs" aria-label="账号访问"><button type="button" aria-pressed={!register} className={!register ? 'active' : ''} disabled={busy} onClick={() => switchMode(false)}>登录</button><button type="button" aria-pressed={register} className={register ? 'active' : ''} disabled={busy} onClick={() => switchMode(true)}>注册</button></div> : <h2>登录</h2>}
      <form className="account-form" onSubmit={submit}>
        {register && <label>显示名称<input autoComplete="nickname" maxLength={60} value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="你希望被怎样称呼（选填）" /></label>}
        <label>账号<input required autoComplete="username" autoCapitalize="none" spellCheck={false} minLength={3} maxLength={40} pattern="[a-zA-Z0-9][a-zA-Z0-9_.\-]{2,39}" value={username} onChange={e => setUsername(e.target.value)} placeholder="3–40 位字母、数字、点、下划线或短横线" /></label>
        <label>密码<input required type="password" autoComplete={register ? 'new-password' : 'current-password'} minLength={register ? 6 : 1} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} placeholder={register ? '至少 6 位，可使用纯数字' : '输入你的密码'} /></label>
        {register && <label>确认密码<input required type="password" autoComplete="new-password" minLength={6} maxLength={128} value={confirmation} onChange={e => setConfirmation(e.target.value)} placeholder="再输入一次密码" /></label>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="button button-primary auth-submit" disabled={busy}>{busy ? <Loader2 className="spin" size={17} /> : <ArrowRight size={17} />}{register ? '注册并进入' : '登录'}</button>
      </form>
      {!registrationEnabled && <p className="auth-switch">账号由站点管理员创建。</p>}
      <p className="auth-note">忘记密码时，请联系站点管理员重置。</p>
    </div></section>
  </main>
}

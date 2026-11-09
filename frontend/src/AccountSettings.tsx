import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Cable, KeyRound, Loader2, LogOut, ShieldCheck } from 'lucide-react'
import { api, post } from './api'
import { broadcastAccountChange } from './Auth'
import { CopyBlock } from './components'
import type { ApiToken, SystemInfo, User } from './types'

const date = (value: string) => new Date(value).toLocaleDateString('zh-CN')

export function SettingsPage({ system, online, user, signOut }: { system: SystemInfo | null; online: boolean; user: User; signOut: () => Promise<void> }) {
  const [tokens, setTokens] = useState<ApiToken[]>([])
  const [loading, setLoading] = useState(true)
  const [name, setName] = useState('我的 Codex')
  const [days, setDays] = useState(90)
  const [fresh, setFresh] = useState<(ApiToken & { token: string }) | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  async function refresh() {
    setLoading(true)
    try { setTokens(await api<ApiToken[]>('/auth/tokens')) }
    finally { setLoading(false) }
  }
  useEffect(() => { void refresh().catch(e => setError(e.message)) }, [])
  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const token = await post<ApiToken & { token: string }>('/auth/tokens', { name, expires_days: days })
      setFresh(token); await refresh()
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  async function revoke(id: string) {
    setBusy(true); setError('')
    try {
      await api(`/auth/tokens/${id}`, { method: 'DELETE' })
      if (fresh?.id === id) setFresh(null)
      await refresh()
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  async function password(event: FormEvent) {
    event.preventDefault(); setError('')
    if (newPassword !== confirmation) { setError('两次新密码不一致'); return }
    setBusy(true)
    try {
      await post('/auth/password', { current_password: oldPassword, new_password: newPassword })
      broadcastAccountChange(); window.dispatchEvent(new Event('xuzhang-session-expired'))
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  const config = `[mcp_servers.novelstudio]\nurl = ${JSON.stringify(system?.mcp.url || `${window.location.origin}/mcp/`)}\nbearer_token_env_var = "NOVEL_API_TOKEN"\ntool_timeout_sec = 120`
  return <main className="page-main settings-main">
    <div className="page-heading"><h1>账号与连接<span className="heading-dot">。</span></h1></div>
    {error && <div className="account-alert" role="alert">{error}</div>}
    <div className="settings-grid"><div className="settings-side">
      <section className="settings-card"><div className="settings-card-title"><span className="settings-icon"><KeyRound size={23} /></span><div><h2>个人 MCP 密钥</h2><p>密钥仅可访问当前账号的数据。</p></div></div>
        <form className="token-create-form account-form" onSubmit={create}><label>连接名称<input required maxLength={80} value={name} onChange={e => setName(e.target.value)} placeholder="例如：家里的 Codex" /></label><label>有效期<select value={days} onChange={e => setDays(Number(e.target.value))}><option value={30}>30 天</option><option value={90}>90 天</option><option value={365}>365 天</option></select></label><button className="button button-primary" disabled={busy || !name.trim()}>{busy ? <Loader2 size={16} className="spin" /> : <KeyRound size={16} />}创建密钥</button></form>
        {fresh && <div className="new-token" role="status"><h3>密钥已创建，仅本次显示</h3><p>请复制保存，离开后无法再次查看。遗失后可撤销并重新创建。</p><CopyBlock value={fresh.token} /><button className="text-button" onClick={() => setFresh(null)}>已保存，隐藏密钥</button></div>}
        <div className="token-list" aria-label="我的 MCP 密钥">{loading ? <p><Loader2 size={16} className="spin" /> 正在读取密钥…</p> : !tokens.length ? <p className="settings-description">还没有密钥。</p> : tokens.map(token => {
          const inactive = !!token.revoked_at || new Date(token.expires_at).getTime() <= Date.now()
          return <article className="token-row" key={token.id}><div><strong>{token.name}</strong><small>{token.revoked_at ? '已撤销' : inactive ? '已过期' : `有效至 ${date(token.expires_at)}`} · {token.last_used_at ? `最近使用 ${date(token.last_used_at)}` : '尚未使用'}</small></div><button className="button button-secondary" disabled={busy || inactive} onClick={() => void revoke(token.id)}>{inactive ? '已失效' : '撤销'}</button></article>
        })}</div>
      </section>
      <section className="settings-card"><div className="settings-card-title"><span className="settings-icon"><Cable size={23} /></span><div><h2>连接 Codex</h2></div><span className={`badge ${online ? 'badge-green' : 'badge-amber'}`}>{online ? '服务可用' : '等待连接'}</span></div>
        <div className="setup-step"><span>01</span><div><h3>设置个人密钥</h3><p>设置环境变量 NOVEL_API_TOKEN，再启动或重新连接 Codex。</p><CopyBlock value={'export NOVEL_API_TOKEN="替换为你的个人密钥"'} /></div></div>
        <div className="setup-step"><span>02</span><div><h3>添加连接配置</h3><p>加入 Codex 的 MCP 配置，并确保应用能读取该环境变量。</p><CopyBlock value={config} /></div></div>
        <details className="config-details"><summary>其他 MCP 客户端</summary><p className="settings-description">使用上面的 URL，添加请求头 Authorization: Bearer 你的个人密钥。</p></details>
        <details className="config-details"><summary>使用已有本地 STDIO 连接</summary><p className="settings-description">在本地 MCP 的 env 中加入以下配置，即可上传本机文件并访问你的线上项目。</p><CopyBlock value={`[mcp_servers.novelstudio.env]\nNOVEL_API_URL = ${JSON.stringify(system?.mcp.api_url || window.location.origin)}\nNOVEL_API_TOKEN = "替换为你的个人密钥"`} /></details>
      </section>
    </div><div className="settings-side">
      <section className="settings-card"><div className="settings-card-title"><span className="settings-icon"><ShieldCheck size={23} /></span><div><h2>{user.display_name}</h2><p>@{user.username}</p></div></div><div className="local-data-row"><span>空间范围</span><strong>仅当前账号可访问</strong></div><div className="local-data-row"><span>保存内容</span><strong>原著、项目、审稿与版本</strong></div><div className="local-data-row"><span>上传上限</span><strong>{system?.limits.max_upload_mb || 30} MB / 文件</strong></div><div className="local-data-row"><span>注册时间</span><strong>{date(user.created_at)}</strong></div><button className="button button-secondary account-signout" disabled={busy} onClick={() => { setBusy(true); void signOut().catch(e => { setError(e.message); setBusy(false) }) }}><LogOut size={15} />退出登录</button></section>
      <section className="settings-card"><details className="settings-password"><summary>修改密码</summary><p className="settings-description">修改后会退出所有设备，并撤销现有 MCP 密钥。请重新登录并创建新的连接密钥。</p><form className="account-form" onSubmit={password}><label>当前密码<input type="password" required autoComplete="current-password" maxLength={128} value={oldPassword} onChange={e => setOldPassword(e.target.value)} /></label><label>新密码<input type="password" required autoComplete="new-password" minLength={6} maxLength={128} value={newPassword} onChange={e => setNewPassword(e.target.value)} /></label><label>确认新密码<input type="password" required autoComplete="new-password" minLength={6} maxLength={128} value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label><button className="button button-secondary" disabled={busy}>保存新密码</button></form></details></section>
    </div></div>
  </main>
}

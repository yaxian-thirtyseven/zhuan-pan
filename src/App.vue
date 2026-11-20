<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  ArrowDown, CircleHelp, Clock3, FileUp, ListPlus, LoaderCircle, LogOut, Plus,
  RefreshCw, ShieldCheck, Sparkles, Trash2, Trophy, UserRound, X,
} from 'lucide-vue-next'
import Wheel from './Wheel.vue'

const user = ref(null)
const loading = ref(true)
const page = ref('wheel')
const register = ref(false)
const username = ref('')
const password = ref('')
const authBusy = ref(false)
const authMessage = ref('')
const notice = ref('')
const error = ref('')
const items = ref([])
const history = ref([])
const users = ref([])
const manual = ref('')
const rotation = ref(0)
const spinning = ref(false)
const busy = ref(false)
const last = ref([])
const drawCount = ref(1)
const allowRepeats = ref(false)
const maxDrawCount = 500
const fileInput = ref(null)
const extracting = ref(false)
const importDialog = ref(null)
const imported = ref('')
const filename = ref('')
const importError = ref('')
const clearDialog = ref(null)
const clearTarget = ref(null)
const clearError = ref('')
const sample = ['幸运大奖', '再试一次', '惊喜礼品', '积分奖励', '专属好礼', '神秘奖励', '特别奖', '幸运加倍']
const lines = (value) => value.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
const importCount = computed(() => lines(imported.value).length)
const wheelItems = computed(() => {
  if (allowRepeats.value) return items.value
  const firstByName = new Map()
  for (const item of items.value) {
    if (!firstByName.has(item.text)) firstByName.set(item.text, item)
  }
  return [...firstByName.values()]
})
const drawLimit = computed(() => allowRepeats.value ? maxDrawCount : wheelItems.value.length)
const drawMessage = computed(() => {
  if (!Number.isInteger(drawCount.value) || drawCount.value < 1) return '请输入大于 0 的整数'
  if (drawCount.value > maxDrawCount) return `单次最多可抽取 ${maxDrawCount} 人次`
  if (!allowRepeats.value && drawLimit.value && drawCount.value > drawLimit.value) {
    return `不允许重复时最多可抽取 ${drawLimit.value} 人`
  }
  return ''
})
const canDraw = computed(() => items.value.length > 0 && !drawMessage.value && !busy.value && !spinning.value)
const date = new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

async function api(path, { method = 'GET', data, anonymous = false } = {}) {
  let response
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers: data && !(data instanceof FormData) ? { 'Content-Type': 'application/json' } : undefined,
      body: data instanceof FormData ? data : data ? JSON.stringify(data) : undefined,
    })
  } catch {
    throw new Error('无法连接后台，请确认网站已启动')
  }
  if (response.status === 204) return
  const result = await response.json().catch(() => null)
  if (!response.ok) {
    if (!anonymous && response.status === 401) clearAccount()
    if (response.status === 403 && user.value) {
      if (result?.detail === '账号已停用') {
        user.value.enabled = false
        page.value = 'wheel'
        users.value = []
      } else if (result?.detail === '此操作需要管理员权限') {
        user.value.admin = false
        page.value = 'wheel'
        users.value = []
      }
    }
    throw new Error(typeof result?.detail === 'string' ? result.detail :
      response.status === 422 ? '输入超出允许范围或格式有误' : '后台暂时无法完成操作，请稍后重试')
  }
  return result
}

function resetWheel() {
  items.value = []
  history.value = []
  last.value = []
  drawCount.value = 1
  allowRepeats.value = false
  rotation.value = 0
  manual.value = ''
}

function clearAccount() {
  user.value = null
  resetWheel()
  users.value = []
  password.value = ''
  page.value = 'wheel'
}

async function loadWheel() {
  const data = await api('/wheel')
  items.value = data.items
  history.value = data.history
  last.value = data.last_results ?? data.history.slice(0, 1)
}

async function synchronize() {
  user.value = await api('/me')
  if (user.value.enabled) await loadWheel()
}

onMounted(async () => {
  try {
    await synchronize()
  } catch (problem) {
    if (problem.message !== '请先登录') authMessage.value = problem.message
  } finally {
    loading.value = false
  }
})

async function authenticate() {
  if (authBusy.value) return
  authBusy.value = true
  authMessage.value = ''
  error.value = ''
  notice.value = ''
  try {
    const data = { username: username.value, password: password.value }
    user.value = await api(register.value ? '/register' : '/login', { method: 'POST', data, anonymous: true })
    register.value = false
    password.value = ''
    if (user.value.enabled) await loadWheel()
  } catch (problem) {
    if (user.value) error.value = problem.message
    else authMessage.value = problem.message
  } finally {
    authBusy.value = false
  }
}

async function perform(action) {
  if (busy.value || spinning.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await action()
  } catch (problem) {
    error.value = problem.message
  } finally {
    busy.value = false
  }
}

function signOut() {
  perform(async () => {
    await api('/logout', { method: 'POST' })
    clearAccount()
    authMessage.value = ''
  })
}

async function updateItems(values) {
  items.value.push(...await api('/items', { method: 'POST', data: { items: values } }))
  rotation.value = 0
  notice.value = `已添加 ${values.length} 个选项`
}

function addManual() {
  perform(async () => {
    await updateItems(lines(manual.value))
    manual.value = ''
  })
}

function remove(id) {
  perform(async () => {
    await api(`/items/${id}`, { method: 'DELETE' })
    items.value = items.value.filter(item => item.id !== id)
    rotation.value = 0
  })
}

function importFile(event) {
  const file = event.target.files[0]
  event.target.value = ''
  if (!file) return
  perform(async () => {
    if (file.size > 20 * 1024 * 1024) throw new Error('单个文件最大为 20 MB')
    extracting.value = true
    try {
      const data = new FormData()
      data.append('file', file)
      const result = await api('/extract', { method: 'POST', data })
      filename.value = file.name
      imported.value = result.items.join('\n')
      importDialog.value.showModal()
    } finally {
      extracting.value = false
    }
  })
}

function confirmImport() {
  perform(async () => {
    try {
      await updateItems(lines(imported.value))
      importDialog.value.close()
    } catch (problem) {
      importError.value = problem.message
    }
  })
}

function chooseFile() {
  importError.value = ''
  fileInput.value.click()
}

function openClear(scope, account) {
  clearError.value = ''
  if (scope === 'all') {
    clearTarget.value = { path: '/admin/wheel', name: '所有账号', includesMe: true }
  } else if (scope === 'account') {
    clearTarget.value = {
      path: `/admin/users/${encodeURIComponent(account.username)}/wheel`,
      name: account.username,
      includesMe: account.username === user.value.username,
    }
  } else {
    clearTarget.value = { path: '/wheel', name: '我的账号', includesMe: true }
  }
  clearDialog.value.showModal()
}

function confirmClear() {
  perform(async () => {
    const target = clearTarget.value
    clearError.value = ''
    try {
      await api(target.path, { method: 'DELETE' })
      if (target.includesMe) resetWheel()
      clearDialog.value?.close()
      notice.value = `已清空${target.name}的转盘选项和抽取记录`
    } catch (problem) {
      clearError.value = problem.message
    }
  })
}

async function draw() {
  if (!canDraw.value) return
  error.value = ''
  notice.value = ''
  spinning.value = true
  try {
    const result = await api('/draw', {
      method: 'POST',
      data: { count: drawCount.value, allow_repeats: allowRepeats.value },
    })
    items.value = result.items
    const firstIndex = wheelItems.value.findIndex(item => item.id === result.results[0].item_id)
    const target = (360 - firstIndex * 360 / wheelItems.value.length) % 360
    rotation.value += 360 * 5 + (target - rotation.value % 360 + 360) % 360
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    await new Promise(resolve => setTimeout(resolve, reduced ? 30 : 3300))
    last.value = result.results
    history.value = [...result.results.slice().reverse(), ...history.value].slice(0, 30)
  } catch (problem) {
    error.value = problem.message
  } finally {
    spinning.value = false
  }
}

function openAdmin() {
  perform(async () => {
    users.value = await api('/admin/users')
    page.value = 'admin'
  })
}

function setPermission(account) {
  perform(async () => {
    const result = await api(`/admin/users/${account.username}`, { method: 'PATCH', data: { enabled: !account.enabled } })
    account.enabled = result.enabled
    notice.value = result.enabled ? `已为 ${account.username} 开通权限` : `已停用 ${account.username}`
  })
}

function setAdminRole(account) {
  perform(async () => {
    const result = await api(`/admin/users/${encodeURIComponent(account.username)}/role`, {
      method: 'PATCH',
      data: { admin: !account.admin },
    })
    account.admin = result.admin
    notice.value = result.admin ? `已授予 ${account.username} 管理员身份` : `已撤销 ${account.username} 的管理员身份`
  })
}
</script>

<template>
  <div v-if="loading" class="loading-screen"><LoaderCircle class="loader" :size="30" aria-label="加载中" /></div>
  <main v-else-if="!user" class="auth-layout">
    <section class="auth-hero">
      <div class="auth-brand"><span class="brand-icon"><Sparkles :size="20" /></span> 转盘工坊</div>
      <div class="hero-content">
        <h1>随机一转，<br />见分晓。</h1>
        <p>导入名单、奖励或备选方案，让转盘帮你随机抽取。</p>
        <Wheel preview />
      </div>
    </section>
    <section class="auth-side">
      <form class="auth-form" @submit.prevent="authenticate">
        <span class="auth-icon"><UserRound :size="24" /></span>
        <h2>{{ register ? '创建账号' : '欢迎回来' }}</h2>
        <p>{{ register ? '注册后即可使用转盘。' : '登录后继续使用你保存的转盘。' }}</p>
        <label for="username">账号</label>
        <input id="username" v-model="username" autocomplete="username" required maxlength="32" placeholder="请输入账号" />
        <label for="password">密码</label>
        <input id="password" v-model="password" type="password" :autocomplete="register ? 'new-password' : 'current-password'" required maxlength="128" :placeholder="register ? '至少 6 位，包含英文字母和数字' : '请输入密码'" />
        <p v-if="authMessage" class="auth-message" role="status">{{ authMessage }}</p>
        <button class="primary auth-submit" :disabled="authBusy" type="submit">
          <LoaderCircle v-if="authBusy" class="loader" :size="18" />{{ register ? '注册账号' : '登录' }}
        </button>
        <p class="auth-switch">
          {{ register ? '已有账号？' : '还没有账号？' }}
          <button class="text-button" type="button" @click="register = !register; authMessage = ''; password = ''">{{ register ? '返回登录' : '立即注册' }}</button>
        </p>
      </form>
    </section>
  </main>

  <template v-else>
    <header class="topbar">
      <div class="topbar-inner">
        <div class="brand"><span class="brand-icon"><Sparkles :size="20" /></span><span>转盘工坊</span></div>
        <nav v-if="user.enabled" aria-label="主导航">
          <button :class="{ active: page === 'wheel' }" :disabled="busy || spinning" @click="page = 'wheel'; notice = ''; error = ''"><Sparkles :size="16" /> 抽奖转盘</button>
          <button v-if="user.admin" :class="{ active: page === 'admin' }" :disabled="busy || spinning" @click="openAdmin"><ShieldCheck :size="16" /> 账号管理</button>
        </nav>
        <div class="profile">
          <span class="avatar"><UserRound :size="16" /></span><span class="account-name">{{ user.username }}</span>
          <button class="icon-button" title="退出登录" aria-label="退出登录" :disabled="busy || spinning" @click="signOut"><LogOut :size="18" /></button>
        </div>
      </div>
    </header>
    <main class="workspace">
      <p v-if="error" class="feedback error" role="alert">{{ error }}</p>
      <p v-if="notice" class="feedback success" role="status">{{ notice }}</p>

      <section v-if="!user.enabled" class="card pending">
        <span class="section-icon"><ShieldCheck :size="26" /></span>
        <h1>账号已停用</h1>
        <p>请联系管理员恢复 {{ user.username }} 的转盘使用权限。</p>
        <div class="pending-actions">
          <button class="primary" :disabled="busy" @click="perform(synchronize)"><RefreshCw :size="16" /> 刷新账号状态</button>
          <button class="danger-outline" :disabled="busy" @click="openClear('own')"><Trash2 :size="16" /> 清空我的数据</button>
        </div>
      </section>

      <template v-else-if="page === 'admin' && user.admin">
        <div class="page-title page-title-actions">
          <div><h1>账号管理</h1><p>管理各账号的转盘使用权限及转盘数据。</p></div>
          <button class="danger-outline" :disabled="busy" @click="openClear('all')"><Trash2 :size="16" /> 清空全站转盘数据</button>
        </div>
        <section class="card admin-card">
          <div class="card-heading"><h2>注册账号</h2><button class="secondary" :disabled="busy" @click="openAdmin"><RefreshCw :size="16" /> 刷新</button></div>
          <ul class="admin-list">
            <li v-for="account in users" :key="account.username">
              <span class="avatar"><UserRound :size="17" /></span>
              <strong>{{ account.username }}</strong>
              <span class="permission" :class="{ enabled: account.enabled }">
                {{ account.owner ? '内置管理员' : account.admin ? '管理员' : account.enabled ? '已开通' : '已停用' }}{{ account.admin && !account.enabled ? ' · 已停用' : '' }}
              </span>
              <div class="admin-actions">
                <button v-if="!account.owner && (user.owner || !account.admin)" :class="account.enabled ? 'secondary' : 'primary'" :disabled="busy" @click="setPermission(account)">{{ account.enabled ? '停用' : '开通权限' }}</button>
                <button v-if="user.owner && !account.owner" class="secondary" :disabled="busy" @click="setAdminRole(account)">{{ account.admin ? '撤销管理员' : '设为管理员' }}</button>
                <button class="danger-outline" :aria-label="`清空 ${account.username} 的转盘数据`" :disabled="busy" @click="openClear('account', account)">清空数据</button>
              </div>
            </li>
          </ul>
        </section>
      </template>

      <template v-else>
        <div class="page-title page-title-actions">
          <div><h1>抽奖转盘</h1><p>添加你的选项，转动转盘，揭晓本次抽取结果。</p></div>
          <button class="danger-outline" :disabled="busy || spinning" @click="openClear('own')"><Trash2 :size="16" /> 清空我的数据</button>
        </div>
        <div class="dashboard">
          <section class="card wheel-card">
            <div class="card-heading"><div class="heading-label"><span class="section-icon"><Sparkles :size="19" /></span><h2>我的转盘</h2></div><span class="count">{{ wheelItems.length }} 个选项</span></div>
            <Wheel :items="wheelItems" :rotation="rotation" :spinning="spinning" :disabled="!canDraw" @draw="draw" />
            <form class="draw-controls" novalidate @submit.prevent="draw">
              <div class="draw-settings">
                <label class="draw-quantity" for="draw-count">抽取数量
                  <input id="draw-count" v-model.number="drawCount" type="number" min="1" :max="Math.max(1, drawLimit)" step="1" :disabled="busy || spinning" :aria-invalid="Boolean(drawMessage)" aria-describedby="draw-note" />
                </label>
                <label class="draw-repeat">
                  <input v-model="allowRepeats" type="checkbox" :disabled="busy || spinning" aria-describedby="draw-note" @change="rotation = 0" />
                  允许重复
                </label>
              </div>
              <p id="draw-note" class="wheel-note" :class="{ 'draw-error': drawMessage }" aria-live="polite"><CircleHelp :size="15" /> {{ drawMessage || (!items.length ? '请先在选项管理中添加内容' : allowRepeats ? '同一人本次可被多次抽中' : '相同姓名本次最多抽中一次') }}</p>
              <button class="primary draw-button" type="submit" :disabled="!canDraw"><LoaderCircle v-if="spinning" class="loader" :size="18" /><Sparkles v-else :size="18" /> {{ spinning ? '正在抽取…' : '开始抽取' }}</button>
            </form>
          </section>

          <div class="right-stack">
            <section class="card result-card">
              <div class="heading-label"><span class="section-icon gold"><Trophy :size="19" /></span><h2>抽取结果</h2></div>
              <div aria-live="polite">
                <div v-if="last.length > 1" class="batch-results">
                  <p>本次抽取 {{ last.length }} 人次</p>
                  <ol tabindex="0" aria-label="本次抽取名单">
                    <li v-for="entry in last" :key="entry.id">{{ entry.text }}</li>
                  </ol>
                </div>
                <div v-else class="result-display">
                  <Trophy :size="30" :stroke-width="1.5" />
                  <strong v-if="last.length">{{ last[0].text }}</strong>
                  <span v-else>等待抽取</span>
                </div>
              </div>
            </section>

            <section class="card options-card">
              <div class="card-heading"><div class="heading-label"><span class="section-icon"><ListPlus :size="20" /></span><h2>选项管理</h2></div><span class="count">{{ items.length }} / 500</span></div>
              <form class="manual-form" @submit.prevent="addManual">
                <label class="visually-hidden" for="manual">输入选项，每行一项</label>
                <textarea id="manual" v-model="manual" rows="2" placeholder="输入选项，每行一项" :disabled="busy || spinning"></textarea>
                <button type="submit" class="primary add-button" :disabled="busy || spinning || !manual.trim()"><Plus :size="17" /> 添加</button>
              </form>
              <input ref="fileInput" type="file" hidden accept=".png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff,.heic,.heif,.doc,.docx,.xls,.xlsx,.pdf" @change="importFile" />
              <button class="upload" :disabled="busy || spinning" @click="chooseFile">
                <span class="upload-icon"><LoaderCircle v-if="extracting" class="loader" :size="20" /><FileUp v-else :size="20" /></span><span><strong>{{ extracting ? '正在提取文件内容…' : '导入文件' }}</strong><small>图片、Word、Excel、PDF · 最大 20 MB</small></span>
              </button>
              <ul v-if="items.length" class="item-list">
                <li v-for="item in items" :key="item.id"><span>{{ item.text }}</span><button class="icon-button delete" type="button" :aria-label="`删除 ${item.text}`" :disabled="busy || spinning" @click="remove(item.id)"><Trash2 :size="16" /></button></li>
              </ul>
              <div v-else class="empty-options"><span>还没有选项</span><button class="text-button" :disabled="busy || spinning" @click="perform(() => updateItems(sample))">使用示例选项</button></div>
            </section>

            <section class="card history-card">
              <div class="heading-label"><span class="section-icon muted"><Clock3 :size="19" /></span><h2>最近抽取</h2></div>
              <ul v-if="history.length" class="history-list"><li v-for="entry in history" :key="entry.id"><span>{{ entry.text }}</span><time :datetime="new Date(entry.drawn_at * 1000).toISOString()">{{ date.format(entry.drawn_at * 1000) }}</time></li></ul>
              <p v-else class="empty-history">暂无抽取记录</p>
            </section>
          </div>
        </div>

        <dialog ref="importDialog" class="import-dialog">
          <div class="card-heading"><h2>确认导入</h2><button class="icon-button" aria-label="关闭" @click="importDialog.close()"><X :size="19" /></button></div>
          <p class="file-name">{{ filename }} · {{ importCount }} 项</p>
          <label for="imported">识别结果，可逐行修改</label>
          <textarea id="imported" v-model="imported" rows="9" @input="importError = ''"></textarea>
          <p v-if="importError" class="feedback error" role="alert">{{ importError }}</p>
          <div class="dialog-actions"><button class="secondary" @click="importDialog.close()">取消</button><button class="primary" :disabled="busy || !importCount" @click="confirmImport"><ArrowDown :size="16" /> 加入转盘</button></div>
        </dialog>
      </template>
      <dialog ref="clearDialog" class="import-dialog clear-dialog" aria-labelledby="clear-title" @cancel="busy && $event.preventDefault()">
        <form @submit.prevent="confirmClear">
          <h2 id="clear-title">确认清空转盘数据</h2>
          <p>将永久删除 <strong>{{ clearTarget?.name }}</strong> 的所有转盘选项和抽取记录。</p>
          <p v-if="clearError" class="feedback error" role="alert">{{ clearError }}</p>
          <div class="dialog-actions">
            <button class="secondary" type="button" autofocus :disabled="busy" @click="clearDialog.close()">取消</button>
            <button class="danger" type="submit" :disabled="busy">确认清空</button>
          </div>
        </form>
      </dialog>
    </main>
  </template>
</template>

import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
process.chdir(root)
const windows = process.platform === 'win32'
const python = resolve(windows ? '.venv/Scripts/python.exe' : '.venv/bin/python')
const children = new Set()
let stopping = false
let exitCode = 0

function stop(code) {
  if (stopping) return
  stopping = true
  exitCode = code
  for (const child of children) child.kill('SIGTERM')
  const timer = setTimeout(() => {
    for (const child of children) child.kill('SIGKILL')
  }, 2500)
  timer.unref()
  process.exitCode = exitCode
}

function launch(command, args, name) {
  return new Promise((done) => {
    const child = spawn(command, args, {
      stdio: 'inherit',
      env: { ...process.env, WHEEL_NODE: process.execPath },
    })
    children.add(child)
    child.once('error', (error) => {
      console.error(name, error.message)
      stop(1)
    })
    child.once('close', (code) => {
      children.delete(child)
      done(code ?? 1)
    })
  })
}

process.on('SIGINT', () => stop(0))
process.on('SIGTERM', () => stop(0))

async function start() {
  const candidates = windows ? [['py', '-3'], ['python']] : [['python3'], ['python']]
  const selected = candidates.find(([exe, ...args]) =>
    spawnSync(exe, [...args, '-c', 'import sys; assert sys.version_info >= (3, 10)'], { stdio: 'ignore' }).status === 0)
  if (!existsSync(python)) {
    if (!selected) throw new Error('请安装 Python 3.10 或更新版本。')
    const [exe, ...prefix] = selected
    const hasEnsurePip = spawnSync(exe, [...prefix, '-m', 'ensurepip', '--version'], { stdio: 'ignore' }).status === 0
    const args = [...prefix, '-m', 'venv', ...(hasEnsurePip ? [] : ['--without-pip']), '.venv']
    if (await launch(exe, args, 'Python') || stopping) return stop(1)
  }

  const requirements = 'backend/requirements.txt'
  const hash = createHash('sha256').update(readFileSync(requirements)).digest('hex')
  const stamp = '.venv/wheel-requirements'
  if (!existsSync(stamp) || readFileSync(stamp, 'utf8') !== hash) {
    console.log('正在安装 FastAPI 后端依赖…')
    const hasPip = spawnSync(python, ['-m', 'pip', '--version'], { stdio: 'ignore' }).status === 0
    if (!hasPip && !selected) throw new Error('请安装 Python 的 pip 和 venv 支持。')
    const [exe, ...prefix] = hasPip ? [python] : selected
    const target = hasPip ? [] : ['--python', python]
    if (await launch(exe, [...prefix, '-m', 'pip', ...target, 'install', '-r', requirements], 'pip') || stopping) return stop(1)
    writeFileSync(stamp, hash)
  }

  const services = [
    ['FastAPI', python, ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '7646']],
    ['Vite', process.execPath, ['node_modules/vite/bin/vite.js', '--strictPort']],
  ]
  await Promise.all(services.map(async ([name, command, args]) => {
    const code = await launch(command, args, name)
    if (!stopping) console.log(`${name} 已退出，正在关闭另一项服务。`)
    stop(code)
  }))
}

start().catch((error) => {
  console.error(error.message)
  stop(1)
})

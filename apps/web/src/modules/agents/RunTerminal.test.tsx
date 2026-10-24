import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { RunTerminal } from './RunTerminal'

const terminal = vi.hoisted(() => ({
  reset: vi.fn(), write: vi.fn(), loadAddon: vi.fn(), open: vi.fn(), dispose: vi.fn(),
  onData: vi.fn<(cb: (data: string) => void) => { dispose: () => void }>(),
  attachCustomKeyEventHandler: vi.fn(), cols: 80, rows: 24,
}))
terminal.onData.mockReturnValue({ dispose: () => {} })
vi.mock('@xterm/xterm', () => ({ Terminal: class { constructor() { return terminal } } }))
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }))
class Socket {
  static OPEN = 1
  static instances: Socket[] = []
  readyState = 1
  binaryType = ''
  onopen?: () => void
  onmessage?: (event: {data: unknown}) => void
  onclose?: (event: {code: number; reason: string; wasClean: boolean}) => void
  onerror?: () => void
  send = vi.fn()
  close = vi.fn()
  url: string
  constructor(url: string) { this.url = url; Socket.instances.push(this) }
}
const fetchMock = vi.fn()
beforeEach(() => {
  vi.clearAllMocks(); Socket.instances = []
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockResolvedValue({ok: true, json: async () => ({websocket_url: '/ws/runs/run-1/terminal?existing=1'})})
})
afterEach(() => vi.unstubAllGlobals())

it('recovers an existing Run and resets the screen before each full replay', async () => {
  render(<RunTerminal runId="run-1" />)
  await waitFor(() => expect(Socket.instances).toHaveLength(1))
  act(() => Socket.instances[0].onopen?.())
  expect(terminal.reset).toHaveBeenCalledTimes(1)
  act(() => Socket.instances[0].onclose?.({code: 1006, reason: '', wasClean: false}))
  fireEvent.click(screen.getByRole('button', {name: 'Reconectar'}))
  await waitFor(() => expect(Socket.instances).toHaveLength(2))
  act(() => Socket.instances[1].onopen?.())
  expect(terminal.reset).toHaveBeenCalledTimes(2)
  expect(fetchMock).toHaveBeenLastCalledWith('/api/runs/run-1/terminal/reconnect', {method: 'POST'})
})

it('automatically reconnects after a lost connection without create', async () => {
  render(<RunTerminal runId="run-1" />)
  await waitFor(() => expect(Socket.instances).toHaveLength(1))
  act(() => Socket.instances[0].onclose?.({code: 1006, reason: '', wasClean: false}))
  await waitFor(() => expect(Socket.instances).toHaveLength(2), {timeout: 2500})
  expect(fetchMock.mock.calls.every(([url]) => url.endsWith('/reconnect'))).toBe(true)
})

it('represents a closed terminal without starting another process', async () => {
  fetchMock.mockResolvedValue({ok: false, status: 409, json: async () => ({detail: {state: 'CLOSED'}})})
  render(<RunTerminal runId="run-1" />)
  expect(await screen.findByText('Encerrado')).toBeInTheDocument()
  expect(Socket.instances).toHaveLength(0)
  expect(screen.queryByRole('button', {name: 'Criar terminal'})).not.toBeInTheDocument()
})

function statusMessage(instance: Socket, role: string) {
  act(() => instance.onmessage?.({data: JSON.stringify({type: 'status', state: 'RUNNING', role})}))
}

it('represents observer role, blocks local input and offers takeover', async () => {
  render(<RunTerminal runId="run-1" />)
  await waitFor(() => expect(Socket.instances).toHaveLength(1))
  act(() => Socket.instances[0].onopen?.())
  statusMessage(Socket.instances[0], 'observer')
  expect(await screen.findByText('Observador')).toBeInTheDocument()
  const onData = terminal.onData.mock.calls[0][0] as (data: string) => void
  onData('pwd\n')
  expect(Socket.instances[0].send).not.toHaveBeenCalled()
})

it('assumir controle reabre o socket pedindo writer com takeover', async () => {
  render(<RunTerminal runId="run-1" />)
  await waitFor(() => expect(Socket.instances).toHaveLength(1))
  act(() => Socket.instances[0].onopen?.())
  statusMessage(Socket.instances[0], 'observer')
  fireEvent.click(await screen.findByRole('button', {name: 'Assumir controle'}))
  await waitFor(() => expect(Socket.instances).toHaveLength(2))
  expect(Socket.instances[1].url).toContain('role=writer')
  expect(Socket.instances[1].url).toContain('takeover=1')
  expect(fetchMock).toHaveBeenLastCalledWith('/api/runs/run-1/terminal/reconnect', {method: 'POST'})
})

it('writer envia input normalmente e exibe Conectado', async () => {
  render(<RunTerminal runId="run-1" />)
  await waitFor(() => expect(Socket.instances).toHaveLength(1))
  act(() => Socket.instances[0].onopen?.())
  statusMessage(Socket.instances[0], 'writer')
  expect(await screen.findByText('Conectado')).toBeInTheDocument()
  expect(screen.queryByRole('button', {name: 'Assumir controle'})).not.toBeInTheDocument()
  const onData = terminal.onData.mock.calls[0][0] as (data: string) => void
  onData('ls\n')
  expect(Socket.instances[0].send).toHaveBeenCalledWith(JSON.stringify({type: 'input', data: 'ls\n'}))
})

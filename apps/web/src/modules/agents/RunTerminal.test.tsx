import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { RunTerminal } from './RunTerminal'

const terminal = vi.hoisted(() => ({
  reset: vi.fn(), write: vi.fn(), loadAddon: vi.fn(), open: vi.fn(), dispose: vi.fn(),
  onData: vi.fn(() => ({ dispose: vi.fn() })), attachCustomKeyEventHandler: vi.fn(), cols: 80, rows: 24,
}))
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

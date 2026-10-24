import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RuntimeControls } from './RuntimeControls'

const { setAgentConnection } = vi.hoisted(() => ({ setAgentConnection: vi.fn() }))
vi.mock('@/services/handoff.service', () => ({ setAgentConnection }))

beforeEach(() => vi.clearAllMocks())

describe('RuntimeControls', () => {
  it('separa WAITING_INPUT de BUSY e mostra STOPPING até confirmação física', () => {
    const { rerender } = render(<RuntimeControls agent="codex" runtimeState="ONLINE" activityState="WAITING_INPUT" />)
    expect(screen.getByText('WAITING_INPUT')).toBeInTheDocument()
    expect(screen.queryByText('BUSY')).not.toBeInTheDocument()
    rerender(<RuntimeControls agent="codex" runtimeState="STOPPING" activityState="IDLE" />)
    expect(screen.getByText('STOPPING')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ligar' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Desligar' })).toBeDisabled()
  })

  it('delegação idempotente não assume ONLINE ao clicar ou terminar a requisição', async () => {
    let finish!: () => void
    setAgentConnection.mockReturnValue(new Promise<void>(resolve => { finish = resolve }))
    render(<RuntimeControls agent="codex" runtimeState="OFFLINE" />)
    fireEvent.click(screen.getByRole('button', { name: 'Ligar' }))
    fireEvent.click(screen.getByRole('button', { name: 'Ligar' }))
    expect(setAgentConnection).toHaveBeenCalledTimes(1)
    expect(setAgentConnection).toHaveBeenCalledWith('codex', true)
    expect(screen.queryByText('ONLINE')).not.toBeInTheDocument()
    await act(async () => finish())
    expect(screen.getByText('OFFLINE')).toBeInTheDocument()
  })

  it('desconecta pelo lifecycle e expõe falha como ERROR', async () => {
    setAgentConnection.mockRejectedValue(new Error('runtime inconsistente'))
    const { rerender } = render(<RuntimeControls agent="codex" runtimeState="ONLINE" checkedAt="first" />)
    fireEvent.click(screen.getByRole('button', { name: 'Desligar' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('runtime inconsistente'))
    expect(setAgentConnection).toHaveBeenCalledWith('codex', false)
    expect(screen.getByText('ERROR')).toBeInTheDocument()
    rerender(<RuntimeControls agent="codex" runtimeState="ONLINE" checkedAt="next" />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('ONLINE')).toBeInTheDocument()
  })

  it('parada forçada refletida pelo snapshot muda ONLINE para OFFLINE', () => {
    const { rerender } = render(<RuntimeControls agent="codex" runtimeState="ONLINE" activityState="BUSY" />)
    expect(screen.getByText('ONLINE')).toBeInTheDocument()
    rerender(<RuntimeControls agent="codex" runtimeState="OFFLINE" activityState="IDLE" />)
    expect(screen.getByText('OFFLINE')).toBeInTheDocument()
    expect(screen.queryByText('ONLINE')).not.toBeInTheDocument()
  })

  it('mostra falha recebida após o snapshot avançar durante um stop lento', async () => {
    let reject!: (error: Error) => void
    setAgentConnection.mockReturnValue(new Promise((_resolve, fail) => { reject = fail }))
    const { rerender } = render(<RuntimeControls agent="codex" runtimeState="ONLINE" checkedAt="first" />)
    fireEvent.click(screen.getByRole('button', { name: 'Desligar' }))
    rerender(<RuntimeControls agent="codex" runtimeState="ONLINE" checkedAt="during-stop" />)
    await act(async () => reject(new Error('identity_not_durable')))
    expect(screen.getByRole('alert')).toHaveTextContent('identity_not_durable')
    expect(screen.getByText('ERROR')).toBeInTheDocument()
    rerender(<RuntimeControls agent="codex" runtimeState="ONLINE" checkedAt="after-failure" />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('cadastro sem snapshot não implica disponibilidade e GPU oferece controles do endpoint', () => {
    render(<RuntimeControls agent="gpu-runpod" persistent={false} />)
    expect(screen.getByText('ERROR')).toBeInTheDocument()
    expect(screen.getByText('Sob demanda')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ligar' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Atualizar' })).toBeEnabled()
  })
})

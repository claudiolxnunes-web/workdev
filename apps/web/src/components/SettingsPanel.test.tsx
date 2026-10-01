import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { vi, describe, it, beforeEach, expect } from 'vitest';
import SettingsPanel from './SettingsPanel';

const fetchMock = vi.fn();

vi.stubGlobal('fetch', fetchMock);

function jsonResponse(data: unknown): Response {
  return {
    ok: true,
    json: async () => data,
  } as unknown as Response;
}

const healthPayload = { service: 'WorkDev API', version: '0.7.0', status: 'online' };

describe('SettingsPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(jsonResponse(healthPayload));
  });

  it('renders the tab bar with all four sections', () => {
    render(<SettingsPanel />);

    expect(screen.getByRole('button', { name: /sistema/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ai providers/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /engineering graph/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /preferências/i })).toBeInTheDocument();
  });

  it('shows the Sistema tab by default with real health data', async () => {
    render(<SettingsPanel />);

    await waitFor(() => {
      expect(screen.getByText('WorkDev API')).toBeInTheDocument();
      expect(screen.getByText('0.7.0')).toBeInTheDocument();
    });
  });

  it('shows migration status from /api/system/migrations', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === '/api/system/migrations') {
        return Promise.resolve(
          jsonResponse({ current: 'abc123', head: 'def456', up_to_date: false })
        );
      }
      return Promise.resolve(jsonResponse(healthPayload));
    });

    render(<SettingsPanel />);

    await waitFor(() => {
      expect(screen.getByText(/pendente/i)).toBeInTheDocument();
      expect(screen.getByText('abc123')).toBeInTheDocument();
      expect(screen.getByText('def456')).toBeInTheDocument();
    });
  });

  it('manages provider keys without rendering their values', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === '/api/ai/providers') {
        return Promise.resolve(jsonResponse({
          providers: [{ provider: 'openai', label: 'OpenAI', connected: false }],
          connected: 0,
          total: 1,
        }));
      }
      return Promise.resolve(jsonResponse(healthPayload));
    });

    render(<SettingsPanel />);
    fireEvent.click(screen.getByRole('button', { name: /ai providers/i }));
    fireEvent.click(await screen.findByRole('button', { name: /configurar/i }));

    const input = screen.getByLabelText(/nova chave para openai/i);
    expect(input).toHaveAttribute('type', 'password');
    fireEvent.change(input, { target: { value: 'chave-ultrassecreta' } });
    fireEvent.click(screen.getByRole('button', { name: /salvar/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/ai/providers/openai/key',
      expect.objectContaining({ method: 'PUT' }),
    ));
    expect(screen.queryByText('chave-ultrassecreta')).not.toBeInTheDocument();
  });

  it('separates stored credentials from the physical state of agents', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === '/api/ai/providers') return Promise.resolve(jsonResponse({
        providers: [{ provider: 'moonshot', label: 'Moonshot', connected: true }],
        connected: 1, total: 1,
      }));
      if (url === '/api/agents/status') return Promise.resolve(jsonResponse({ agents: [
        { agent: 'kimi', runtime_state: 'OFFLINE', activity_state: 'IDLE', checked_at: '2026-09-30T04:00:00Z' },
        { agent: 'codex', runtime_state: 'ERROR', activity_state: 'IDLE', checked_at: '2026-09-30T04:00:00Z', health_reason: 'runtime_inconsistent' },
        { agent: 'local-code', runtime_state: 'ERROR', activity_state: 'IDLE', checked_at: '2026-09-30T04:00:00Z' },
      ] }));
      return Promise.resolve(jsonResponse(healthPayload));
    });
    render(<SettingsPanel />);
    fireEvent.click(screen.getByRole('button', { name: /ai providers/i }));
    expect(await screen.findByText('Chave cadastrada')).toBeInTheDocument();
    const agents = await screen.findByRole('list', { name: 'Estado real dos agentes' });
    expect(agents).toHaveTextContent('Kimi');
    expect(agents).toHaveTextContent('Desligado');
    expect(agents).toHaveTextContent('Codex');
    expect(agents).not.toHaveTextContent('Local Code');
    expect(agents).not.toHaveTextContent('local-code');
    expect(agents).toHaveTextContent('sessão do agente não está ativa');
  });
});

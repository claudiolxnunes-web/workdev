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
});

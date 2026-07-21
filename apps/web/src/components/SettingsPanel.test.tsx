import { render, screen, waitFor } from '@testing-library/react';
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
});

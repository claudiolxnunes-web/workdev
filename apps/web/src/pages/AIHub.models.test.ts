import { describe, expect, it } from "vitest";

import { DEFAULT_MODELO_LABEL, MODELOS } from "./AIHub";

describe("prioridade dos modelos do AI Hub", () => {
  it("prioriza Gemini, Kimi e GPT-OSS 120B", () => {
    expect(MODELOS.slice(0, 3).map(({ label }) => label)).toEqual([
      "Gemini 3.5 Flash",
      "Kimi K2.7 Code",
      "GPT-OSS 120B (Ollama Cloud)",
    ]);
    expect(DEFAULT_MODELO_LABEL).toBe(MODELOS[0].label);
  });
});

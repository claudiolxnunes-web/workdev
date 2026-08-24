import { describe, expect, it } from "vitest";

import { DEFAULT_MODELO_LABEL, MODELOS } from "./AIHub";

describe("prioridade dos modelos do AI Hub", () => {
  it("prioriza Gemini e depois GPT-OSS", () => {
    expect(MODELOS.slice(0, 2).map(({ label }) => label)).toEqual([
      "Gemini 3.5 Flash",
      "GPT-OSS 20B (Ollama Cloud)",
    ]);
    expect(DEFAULT_MODELO_LABEL).toBe(MODELOS[0].label);
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADRMarkdown } from "./ADRMarkdown";

describe("ADRMarkdown", () => {
  it("renders GFM content with readable semantic elements", () => {
    const { container } = render(
      <ADRMarkdown
        content={`## Arquitetura

Primeira linha
segunda linha com **ênfase** e [documentação](https://example.com/docs).

- item um
- item dois

| Camada | Estado |
| --- | --- |
| RAG | ativo |

\`\`\`ts
const enabled = true
\`\`\``}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Arquitetura", level: 2 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "documentação" })).toHaveAttribute(
      "href",
      "https://example.com/docs",
    );
    expect(container.querySelector("pre code")).toHaveTextContent(
      "const enabled = true",
    );
    expect(screen.getByText("ênfase").tagName).toBe("STRONG");
  });

  it("does not execute or inject raw HTML and unsafe links", () => {
    const onError = () => {
      throw new Error("conteúdo malicioso executado");
    };
    window.addEventListener("error", onError);

    const { container } = render(
      <ADRMarkdown
        content={`<script>window.__adrCompromised = true</script>

<img src=x onerror="window.__adrCompromised = true">

[link inseguro](javascript:window.__adrCompromised=true)`}
      />,
    );

    expect(container.querySelector("script")).not.toBeInTheDocument();
    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(screen.getByText("link inseguro")).not.toHaveAttribute("href");
    expect(
      (window as Window & { __adrCompromised?: boolean }).__adrCompromised,
    ).toBeUndefined();

    window.removeEventListener("error", onError);
  });
});

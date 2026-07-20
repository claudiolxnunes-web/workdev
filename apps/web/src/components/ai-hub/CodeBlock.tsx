import { useState } from "react";
import PrismLight from "react-syntax-highlighter/dist/esm/prism-light";
import oneDark from "react-syntax-highlighter/dist/esm/styles/prism/one-dark";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import c from "react-syntax-highlighter/dist/esm/languages/prism/c";
import cpp from "react-syntax-highlighter/dist/esm/languages/prism/cpp";
import csharp from "react-syntax-highlighter/dist/esm/languages/prism/csharp";
import css from "react-syntax-highlighter/dist/esm/languages/prism/css";
import diff from "react-syntax-highlighter/dist/esm/languages/prism/diff";
import go from "react-syntax-highlighter/dist/esm/languages/prism/go";
import java from "react-syntax-highlighter/dist/esm/languages/prism/java";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import jsx from "react-syntax-highlighter/dist/esm/languages/prism/jsx";
import markdown from "react-syntax-highlighter/dist/esm/languages/prism/markdown";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup";
import php from "react-syntax-highlighter/dist/esm/languages/prism/php";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import ruby from "react-syntax-highlighter/dist/esm/languages/prism/ruby";
import rust from "react-syntax-highlighter/dist/esm/languages/prism/rust";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";
import { Check, Copy } from "lucide-react";

PrismLight.registerLanguage("bash", bash);
PrismLight.registerLanguage("sh", bash);
PrismLight.registerLanguage("shell", bash);
PrismLight.registerLanguage("c", c);
PrismLight.registerLanguage("cpp", cpp);
PrismLight.registerLanguage("csharp", csharp);
PrismLight.registerLanguage("css", css);
PrismLight.registerLanguage("diff", diff);
PrismLight.registerLanguage("go", go);
PrismLight.registerLanguage("java", java);
PrismLight.registerLanguage("javascript", javascript);
PrismLight.registerLanguage("js", javascript);
PrismLight.registerLanguage("json", json);
PrismLight.registerLanguage("jsx", jsx);
PrismLight.registerLanguage("markdown", markdown);
PrismLight.registerLanguage("md", markdown);
PrismLight.registerLanguage("markup", markup);
PrismLight.registerLanguage("html", markup);
PrismLight.registerLanguage("xml", markup);
PrismLight.registerLanguage("php", php);
PrismLight.registerLanguage("python", python);
PrismLight.registerLanguage("py", python);
PrismLight.registerLanguage("ruby", ruby);
PrismLight.registerLanguage("rust", rust);
PrismLight.registerLanguage("sql", sql);
PrismLight.registerLanguage("tsx", tsx);
PrismLight.registerLanguage("typescript", typescript);
PrismLight.registerLanguage("ts", typescript);
PrismLight.registerLanguage("yaml", yaml);
PrismLight.registerLanguage("yml", yaml);

const SyntaxHighlighter = PrismLight;

function getCodeString(children: unknown): string {
  const raw = Array.isArray(children) ? children.join("") : String(children ?? "");
  return raw.replace(/\n$/, "");
}

export function CodeBlock({ className, children }: { className?: string; children?: unknown }) {
  const [copied, setCopied] = useState(false);
  const code = getCodeString(children);
  const lang = /language-(\w+)/.exec(className || "")?.[1];

  async function handleCopy() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="my-2 min-w-0 overflow-hidden rounded-lg border border-slate-700 bg-[#282c34]">
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-800/80 text-[11px] text-slate-400">
        <span>{lang || "texto"}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 hover:text-white transition-colors"
        >
          {copied ? (
            <>
              <Check className="w-3 h-3" /> Copiado
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" /> Copiar
            </>
          )}
        </button>
      </div>
      <div className="overflow-x-auto">
        <SyntaxHighlighter
          language={lang}
          style={oneDark}
          customStyle={{
            margin: 0,
            padding: "0.75rem 1rem",
            background: "transparent",
            fontSize: "0.8rem",
          }}
        >
          {code}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}

export function InlineCode({ children }: { children?: unknown }) {
  return (
    <code className="bg-slate-800 text-pink-300 rounded px-1.5 py-0.5 text-[0.85em] break-words">
      {children as React.ReactNode}
    </code>
  );
}

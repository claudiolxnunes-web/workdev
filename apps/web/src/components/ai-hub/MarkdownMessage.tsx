import ReactMarkdown from "react-markdown";
import { CodeBlock, InlineCode } from "./CodeBlock";

export function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="min-w-0 text-sm leading-relaxed break-words">
      <ReactMarkdown
        components={{
          pre({ children }) {
            return <>{children}</>;
          },
          code({ className, children }) {
            const raw = Array.isArray(children) ? children.join("") : String(children ?? "");
            const isBlock = /language-/.test(className || "") || raw.includes("\n");
            return isBlock ? (
              <CodeBlock className={className}>{children}</CodeBlock>
            ) : (
              <InlineCode>{children}</InlineCode>
            );
          },
          a({ href, children }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noreferrer"
                className="text-blue-400 underline hover:text-blue-300"
              >
                {children}
              </a>
            );
          },
          p({ children }) {
            return <p className="mb-2 last:mb-0">{children}</p>;
          },
          ul({ children }) {
            return <ul className="list-disc pl-5 space-y-1 my-1">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="list-decimal pl-5 space-y-1 my-1">{children}</ol>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

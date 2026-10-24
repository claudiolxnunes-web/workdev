import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function ADRMarkdown({ content }: { content: string }) {
  return (
    <div className="min-w-0 break-words text-sm leading-7 text-slate-300">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="mb-3 mt-6 text-xl font-bold text-slate-100 first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-3 mt-6 text-lg font-semibold text-slate-100 first:mt-0">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-2 mt-5 font-semibold text-slate-100 first:mt-0">
              {children}
            </h3>
          ),
          p: ({ children }) => (
            <p className="mb-3 whitespace-pre-wrap last:mb-0">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="mb-3 list-disc space-y-1 pl-6 last:mb-0">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-3 list-decimal space-y-1 pl-6 last:mb-0">{children}</ol>
          ),
          a: ({ href, children }) => {
            // O react-markdown já neutraliza esquemas perigosos (javascript:,
            // data:) reduzindo o href a string vazia. Nesse caso omitimos o
            // atributo de vez: um <a href=""> continua clicável e recarrega a
            // página. Sem href o link vira texto inerte, que é a intenção.
            const seguro = href && href.trim() !== "";
            return (
              <a
                {...(seguro ? { href, target: "_blank", rel: "noreferrer" } : {})}
                className="text-blue-400 underline decoration-blue-500/60 underline-offset-2 hover:text-blue-300"
              >
                {children}
              </a>
            );
          },
          blockquote: ({ children }) => (
            <blockquote className="mb-3 border-l-4 border-slate-600 pl-4 italic text-slate-400">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="mb-4 max-w-full overflow-x-auto rounded-lg border border-slate-700">
              <table className="w-full min-w-max border-collapse text-left text-sm">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border-b border-slate-700 bg-slate-800 px-3 py-2 font-semibold text-slate-100">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-b border-slate-800 px-3 py-2 align-top last:border-b-0">
              {children}
            </td>
          ),
          pre: ({ children }) => (
            <pre className="mb-4 max-w-full overflow-x-auto rounded-lg border border-slate-700 bg-slate-950 p-4 text-xs leading-6 text-slate-200">
              {children}
            </pre>
          ),
          code: ({ className, children }) =>
            className ? (
              <code className={className}>{children}</code>
            ) : (
              <code className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-cyan-300">
                {children}
              </code>
            ),
          hr: () => <hr className="my-5 border-slate-700" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

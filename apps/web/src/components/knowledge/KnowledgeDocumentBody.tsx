import { createElement, useState, type HTMLAttributes } from "react";
import Markdown, { type Components, type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";
import type { KnowledgeContent } from "../../api/knowledgeContent.ts";

type Highlight = KnowledgeContent["highlight"];
type PositionedProps = HTMLAttributes<HTMLElement> & ExtraProps;
const CITATION_BLOCKS = new Set(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "pre", "blockquote"]);

function overlaps(node: ExtraProps["node"], highlight: NonNullable<Highlight>): boolean {
  const start = node?.position?.start.line;
  const end = node?.position?.end.line;
  return start !== undefined && end !== undefined && start <= highlight.lineEnd && end >= highlight.lineStart;
}

function containsCitedBlock(node: NonNullable<ExtraProps["node"]>, highlight: NonNullable<Highlight>): boolean {
  return node.children.some(child => child.type === "element" && (
    (CITATION_BLOCKS.has(child.tagName) && overlaps(child, highlight)) || containsCitedBlock(child, highlight)
  ));
}

function position(node: ExtraProps["node"], highlight: Highlight) {
  const start = node?.position?.start.line;
  const end = node?.position?.end.line;
  return {
    "data-line-start": start, "data-line-end": end,
    "data-citation-hit": node !== undefined && CITATION_BLOCKS.has(node.tagName) && highlight !== null &&
      overlaps(node, highlight) && !containsCitedBlock(node, highlight) ? "true" : undefined,
  };
}

function Code({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  async function copy() {
    try { await navigator.clipboard.writeText(code); setCopied(true); setFailed(false); }
    catch { setCopied(false); setFailed(true); }
  }
  return <>
    <div className="knowledge-code-toolbar"><span>{language || "代码"}</span>
      <button type="button" aria-label="复制代码" onClick={() => void copy()}>
        {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
        {copied ? "已复制" : "复制"}</button></div>
    <code>{code}</code>
    {failed ? <span role="status">复制失败，请选中代码手动复制。</span> : null}
  </>;
}

export function KnowledgeDocumentBody({ content, format, highlight }: {
  content: string; format: KnowledgeContent["format"]; highlight: Highlight;
}) {
  if (format === "text") {
    const lines = content.split("\n");
    return <pre className="knowledge-document-text">{lines.map((line, index) =>
      <span key={index} data-line-start={index + 1} data-line-end={index + 1}
        data-citation-hit={highlight !== null && index + 1 >= highlight.lineStart && index + 1 <= highlight.lineEnd ? "true" : undefined}>
        {line}{index < lines.length - 1 ? "\n" : ""}</span>)}</pre>;
  }
  const components: Components = {};
  const positioned: Record<string, (props: PositionedProps) => React.ReactElement> = {};
  for (const tag of ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "ul", "ol", "blockquote", "table", "tr", "td", "th", "pre"]) {
    positioned[tag] = ({ node, children, ...props }: PositionedProps) =>
      createElement(tag, { ...props, ...position(node, highlight) }, children);
  }
  Object.assign(components, positioned);
  components.img = ({ alt }) => <span className="knowledge-document-media">{alt ? `图片：${alt}（预览不加载）` : "图片（预览不加载）"}</span>;
  components.a = ({ href, children }) => href ?
    <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>;
  components.code = ({ node, children, className }) => {
    if (node?.position?.start.line !== node?.position?.end.line || className !== undefined) {
      return <Code code={String(children)} language={className?.replace("language-", "") ?? ""} />;
    }
    return <code>{children}</code>;
  };
  return <div className="knowledge-document-markdown"><Markdown
    remarkPlugins={[remarkGfm]} components={components} skipHtml
    urlTransform={(url) => /^(https?:\/\/|mailto:|#)/i.test(url) ? url : ""}
  >{content}</Markdown></div>;
}

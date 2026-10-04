import { Check, Copy } from 'lucide-react';
import { useState } from 'react';

/** Render bounded plain text. No HTML, link expansion, or remote media. */
export function KnowledgeText({ text }: { text: string }) {
  const blocks = text.split(/(```[^\n]*\n[\s\S]*?```)/g).filter(Boolean);
  return <div className='knowledge-text'>{blocks.map((block, index) => {
    if (block.startsWith('```') && block.endsWith('```')) {
      const newline = block.indexOf('\n');
      return <CodeBlock key={index} code={block.slice(newline + 1, -3).replace(/\n$/, '')} language={block.slice(3, newline).trim()} />;
    }
    return block.split(/\n\s*\n/).filter(part => part.trim()).map((part, paragraph) => {
      const heading = part.match(/^(#{1,3})\s+([^\n]+)$/);
      return heading ? <h3 key={`${index}:${paragraph}`}>{heading[2]}</h3> : <p key={`${index}:${paragraph}`}>{part}</p>;
    });
  })}</div>;
}
function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  async function copy() {
    try { await navigator.clipboard.writeText(code); setCopied(true); setFailed(false); }
    catch { setCopied(false); setFailed(true); }
  }
  return <div className='knowledge-code-block'>
    <div className='knowledge-code-toolbar'><span>{language || '代码'}</span><button type='button' aria-label='复制代码' onClick={() => void copy()}>{copied ? <Check size={16} aria-hidden='true' /> : <Copy size={16} aria-hidden='true' />}{copied ? '已复制' : '复制'}</button></div>
    <pre><code>{code}</code></pre>
    {failed ? <p role='status'>复制失败，请选中代码手动复制。</p> : null}
  </div>;
}

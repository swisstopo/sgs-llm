import { marked } from 'marked';
import DOMPurify from 'dompurify';

let hooksInstalled = false;

function installHooks(): void {
  if (hooksInstalled) {
    return;
  }
  // Open links from chat answers in a new tab, safely.
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName === 'A') {
      node.setAttribute('target', '_blank');
      node.setAttribute('rel', 'noopener noreferrer');
    }
  });
  hooksInstalled = true;
}

/** Renders agent markdown to sanitized HTML (GFM, no raw HTML passthrough). */
export function renderMarkdown(markdown: string): string {
  installHooks();
  const html = marked.parse(markdown, { async: false, gfm: true, breaks: true });
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'iframe', 'form', 'input'],
  });
}

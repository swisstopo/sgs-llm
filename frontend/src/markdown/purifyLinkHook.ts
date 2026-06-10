import DOMPurify from 'dompurify';

let installed = false;

/**
 * Forces sanitized anchors to open in a new tab, safely. Shared by the chat
 * markdown renderer and the legend sanitizer; idempotent because DOMPurify
 * hooks are global.
 */
export function ensureExternalLinkHook(): void {
  if (installed) {
    return;
  }
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName === 'A') {
      node.setAttribute('target', '_blank');
      node.setAttribute('rel', 'noopener noreferrer');
    }
  });
  installed = true;
}

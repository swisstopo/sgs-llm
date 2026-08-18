import { marked } from 'marked';
import DOMPurify from 'dompurify';
import type { CatalogLayerRef } from '../protocol/v1';
import { ensureExternalLinkHook } from './purifyLinkHook';

const INLINE_LAYER_CLASS = 'inline-catalog-layer';

function layerButton(layer: CatalogLayerRef & { name: string }): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = INLINE_LAYER_CLASS;
  button.dataset.catalogLayerId = layer.id;
  button.textContent = layer.name;
  return button;
}

/** Official layers whose exact display names occur in the answer. */
export function mentionedCatalogLayers(
  markdown: string,
  layers: readonly CatalogLayerRef[] = [],
): CatalogLayerRef[] {
  return layers.filter((layer) => Boolean(layer.name) && markdown.includes(layer.name!));
}

/**
 * Turns exact official-layer titles into safe inline controls after Markdown sanitation.
 *
 * Layer metadata comes from the structured protocol field, not model-authored HTML. That
 * keeps arbitrary tags and attributes out of the trust boundary while allowing the layer
 * name in the prose itself to open the map action.
 */
function linkCatalogLayerMentions(html: string, layers: readonly CatalogLayerRef[]): string {
  const named = layers
    .filter((layer): layer is CatalogLayerRef & { name: string } => Boolean(layer.name))
    .sort((a, b) => b.name.length - a.name.length);
  if (named.length === 0) {
    return html;
  }

  const template = document.createElement('template');
  template.innerHTML = html;

  // Models occasionally turn a layer title into `[title](ch.layer.id)`. It is still a
  // validated structured layer mention, not a trustworthy URL: replace the whole anchor
  // with the same inline control plain text would receive.
  for (const anchor of template.content.querySelectorAll('a')) {
    const label = anchor.textContent?.trim();
    const layer = named.find((candidate) => candidate.name === label);
    if (layer) {
      anchor.replaceWith(layerButton(layer));
    }
  }

  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT);
  const textNodes: Text[] = [];
  let current: Node | null;
  while ((current = walker.nextNode())) {
    const parent = current.parentElement;
    if (parent && !parent.closest('a, button, code, pre')) {
      textNodes.push(current as Text);
    }
  }

  for (const textNode of textNodes) {
    const value = textNode.data;
    const matches: Array<{ start: number; end: number; layer: (typeof named)[number] }> = [];
    for (const layer of named) {
      let start = value.indexOf(layer.name);
      while (start !== -1) {
        matches.push({ start, end: start + layer.name.length, layer });
        start = value.indexOf(layer.name, start + layer.name.length);
      }
    }
    matches.sort((a, b) => a.start - b.start || b.end - a.end);

    const fragment = document.createDocumentFragment();
    let cursor = 0;
    for (const match of matches) {
      if (match.start < cursor) {
        continue;
      }
      fragment.append(value.slice(cursor, match.start));
      fragment.append(layerButton(match.layer));
      cursor = match.end;
    }
    if (cursor > 0) {
      fragment.append(value.slice(cursor));
      textNode.replaceWith(fragment);
    }
  }
  return template.innerHTML;
}

/** Renders agent markdown to sanitized HTML (GFM, no raw HTML passthrough). */
export function renderMarkdown(
  markdown: string,
  catalogLayers: readonly CatalogLayerRef[] = [],
): string {
  ensureExternalLinkHook();
  const html = marked.parse(markdown, { async: false, gfm: true, breaks: true });
  const sanitized = DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'iframe', 'form', 'input'],
  });
  return linkCatalogLayerMentions(sanitized, catalogLayers);
}

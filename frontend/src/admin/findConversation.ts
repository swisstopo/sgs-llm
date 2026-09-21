import { adminFetch } from './auth';
import type { AdminRecord, RecordPage } from './types';

/** The existing API returns threads within a date range, paginated as whole records. */
export async function findConversation(
  conversationId: string,
  from: string,
  to: string,
  signal: AbortSignal,
): Promise<AdminRecord | undefined> {
  const query = new URLSearchParams({ from, to, limit: '50' });
  const seenCursors = new Set<string>();
  while (true) {
    const response = await adminFetch(`/records/conversations?${query}`, { signal });
    if (!response.ok) throw new Error(`Conversation lookup failed: ${response.status}`);
    const page = (await response.json()) as RecordPage;
    const match = page.items.find((record) => record.conversation_id === conversationId);
    if (match) return match;
    if (!page.next_cursor) return undefined;
    if (seenCursors.has(page.next_cursor)) throw new Error('Repeated conversation page');
    seenCursors.add(page.next_cursor);
    query.set('cursor', page.next_cursor);
  }
}

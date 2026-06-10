export const FEEDBACK_CATEGORIES = ['bug', 'feature', 'improvement', 'question', 'other'] as const;

export type FeedbackCategory = (typeof FEEDBACK_CATEGORIES)[number];

export interface FeedbackPayload {
  category: FeedbackCategory;
  message: string;
  email?: string;
  lang: string;
}

/** Submits feedback as JSON to the configured endpoint; throws on failure. */
export async function submitFeedback(
  url: string,
  payload: FeedbackPayload,
  fetchFn: typeof fetch = fetch,
): Promise<void> {
  const response = await fetchFn(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`feedback request failed: ${response.status}`);
  }
}

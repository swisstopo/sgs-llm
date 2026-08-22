export const USER_GROUPS = [
  'private_individual',
  'public_administration',
  'research_education',
  'private_sector',
  'nonprofit_other',
] as const;

export const GEODATA_EXPERIENCE_LEVELS = ['new', 'occasional', 'advanced'] as const;

export const INTENDED_USES = [
  'find_data',
  'answer_question',
  'create_map',
  'professional_analysis',
  'learning_other',
] as const;

export type UserGroup = (typeof USER_GROUPS)[number];
export type GeodataExperience = (typeof GEODATA_EXPERIENCE_LEVELS)[number];
export type IntendedUse = (typeof INTENDED_USES)[number];

/**
 * Consent is the only gate; the three survey answers are optional and are left out of
 * the payload entirely when the user does not answer (never sent as empty strings).
 */
export interface OnboardingPayload {
  type: 'onboarding';
  user_group?: UserGroup;
  geodata_experience?: GeodataExperience;
  intended_use?: IntendedUse;
  consent_version: string;
  lang: string;
}

/** Persists onboarding through the existing submission endpoint. */
export async function submitOnboarding(
  url: string,
  payload: OnboardingPayload,
  fetchFn: typeof fetch = fetch,
): Promise<void> {
  const response = await fetchFn(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`onboarding request failed: ${response.status}`);
  }
}

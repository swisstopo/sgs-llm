import { t } from '../../i18n/i18n';
import type { CatalogTopic } from '../../swisstopo/catalogApi';

/** Translated topic name; unknown topics fall back to the raw id. */
export function topicLabel(id: string): string {
  return t(`geocatalog.topics.${id}`, { defaultValue: id });
}

/** Pins 'ech' (the main geocatalog) first, keeps API order for the rest. */
export function orderTopics(topics: CatalogTopic[]): CatalogTopic[] {
  return [...topics].sort((a, b) => (a.id === 'ech' ? -1 : b.id === 'ech' ? 1 : 0));
}

import { describe, expect, it } from 'vitest';
import { orderTopics } from './topicLabels';

describe('orderTopics', () => {
  it('pins ech first and keeps API order for the rest', () => {
    const topics = [{ id: 'are' }, { id: 'bafu' }, { id: 'ech' }, { id: 'swisstopo' }];
    expect(orderTopics(topics).map((topic) => topic.id)).toEqual([
      'ech',
      'are',
      'bafu',
      'swisstopo',
    ]);
  });

  it('is a no-op without ech and does not mutate the input', () => {
    const topics = [{ id: 'bafu' }, { id: 'are' }];
    const ordered = orderTopics(topics);
    expect(ordered.map((topic) => topic.id)).toEqual(['bafu', 'are']);
    expect(ordered).not.toBe(topics);
    expect(topics.map((topic) => topic.id)).toEqual(['bafu', 'are']);
  });
});

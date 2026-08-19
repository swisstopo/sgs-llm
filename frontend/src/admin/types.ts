export interface DailyMetric {
  date: string;
  messages: number;
  conversations: number;
  onboarding: number;
  feedback: number;
  errors: number;
}

export interface AdminMetrics {
  from: string;
  to: string;
  daily: DailyMetric[];
  totals: Record<string, number>;
  breakdowns: Record<string, Record<string, number>>;
}

export type AdminRecordValue = string | number | boolean | string[] | AdminRecord[] | undefined;

export type AdminRecord = Record<string, AdminRecordValue>;

export interface RecordPage {
  items: AdminRecord[];
  next_cursor: string | null;
}

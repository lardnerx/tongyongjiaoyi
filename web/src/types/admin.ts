/** 规则项。 */
export interface RuleItem {
  rule_key: string;
  rule_value: unknown;
  description: string | null;
  category: string;
  version: number;
  updated_by: string | null;
  updated_at: string | null;
  is_default: boolean;
}

/** 规则变更历史项。 */
export interface RuleHistoryItem {
  history_id: number;
  rule_key: string;
  old_value: unknown;
  new_value: unknown;
  changed_by: string | null;
  changed_at: string;
  change_reason: string | null;
}

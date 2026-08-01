/** 统一响应信封（成功）。 */
export interface Envelope<T> {
  code: number;
  data: T | null;
  message: string;
}

/** 统一错误信封。 */
export interface ErrorEnvelope {
  code: number;
  message: string;
  details: unknown | null;
}

/** Token 响应。 */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

/** 用户信息。 */
export interface UserInfo {
  user_id: string;
  name: string;
  roles: string[];
  active_role: string | null;
}

/** 登录请求。 */
export interface LoginRequest {
  credential_type: string;
  token: string;
}

/** 刷新令牌请求。 */
export interface RefreshRequest {
  refresh_token: string;
}

/** WebSocket 推送消息。 */
export interface WSMessage {
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

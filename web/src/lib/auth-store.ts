import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserInfo } from "@/types/api";
import { wsClient } from "@/lib/ws-client";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: UserInfo | null;
  isAuthenticated: boolean;
  activeRole: string | null;
  setTokens: (accessToken: string, refreshToken: string) => void;
  setUser: (user: UserInfo) => void;
  setActiveRole: (role: string) => void;
  logout: () => void;
}

const secure = () => (process.env.NODE_ENV === "production" ? "; secure" : "");

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
      activeRole: null,
      setTokens: (accessToken, refreshToken) => {
        set({ accessToken, refreshToken, isAuthenticated: true });
        document.cookie = `auth-token=${accessToken}; path=/; max-age=3600; samesite=lax${secure()}`;
        // 初始化 WebSocket 连接
        const wsUrl = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/api/v1/ws/events";
        wsClient.init(wsUrl, accessToken);
      },
      setUser: (user) => {
        set({ user, activeRole: user.active_role });
        if (user.active_role) {
          document.cookie = `active-role=${user.active_role}; path=/; max-age=3600; samesite=lax${secure()}`;
        }
      },
      setActiveRole: (role) => {
        set({ activeRole: role });
        document.cookie = `active-role=${role}; path=/; max-age=3600; samesite=lax${secure()}`;
      },
      logout: () => {
        set({
          accessToken: null,
          refreshToken: null,
          user: null,
          isAuthenticated: false,
          activeRole: null,
        });
        document.cookie = "auth-token=; path=/; max-age=0";
        document.cookie = "active-role=; path=/; max-age=0";
        wsClient.disconnect();
      },
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        activeRole: state.activeRole,
      }),
      onRehydrateStorage: () => (state) => {
        // 页面刷新后，从持久化恢复时初始化 WebSocket
        if (state?.accessToken) {
          const wsUrl = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/api/v1/ws/events";
          wsClient.init(wsUrl, state.accessToken);
        }
      },
    }
  )
);

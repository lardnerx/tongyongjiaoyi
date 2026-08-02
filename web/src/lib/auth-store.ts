import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserInfo } from "@/types/api";

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
      },
      setUser: (user) =>
        set({ user, activeRole: user.active_role }),
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
    }
  )
);

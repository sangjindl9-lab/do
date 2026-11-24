import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { clearSession, hasRefresh, post, refresh, setSessionListener } from "./api";

type Ctx = { user: any | null; ready: boolean; logout: () => Promise<void>; setUser: (u: any) => void };
const AuthCtx = createContext<Ctx>({ user: null, ready: false, logout: async () => {}, setUser: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<any | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setSessionListener(setUser);
    const boot = async () => {
      // 일시 오류로 갱신에 실패하면 잠시 뒤 한 번 더 시도한다
      if (hasRefresh() && !(await refresh()) && hasRefresh()) { await new Promise((r) => setTimeout(r, 1500)); await refresh(); }
      setReady(true);
    };
    boot();
  }, []);
  const logout = async () => {
    const token = localStorage.getItem("gat.refresh");
    if (token) await post("/auth/logout", { refresh_token: token }).catch(() => {});
    clearSession();
  };
  return <AuthCtx.Provider value={{ user, ready, logout, setUser }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

export function Guard({ staff, children }: { staff?: boolean; children: ReactNode }) {
  const { user, ready } = useAuth();
  const loc = useLocation();
  if (!ready) return <div className="p-8 text-mute">불러오는 중</div>;
  if (!user) return <Navigate to={`${staff ? "/admin/login" : "/login"}?next=${encodeURIComponent(loc.pathname)}`} replace />;
  if (staff && !user.is_staff) return <Navigate to="/dashboard" replace />;
  if (!staff && user.is_staff) return <Navigate to="/admin" replace />;
  return <>{children}</>;
}

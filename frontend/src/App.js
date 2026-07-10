import { useState, useEffect, createContext, useContext, useCallback } from "react";
import { useLocation } from "react-router-dom";

import "@/App.css";
import { ThemeProvider } from "@/context/ThemeContext";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import api from "@/lib/api";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import PPPoEUsersPage from "@/pages/PPPoEUsersPage";
import HotspotUsersPage from "@/pages/HotspotUsersPage";
import ReportsPage from "@/pages/ReportsPage";
import DevicesPage from "@/pages/DevicesPage";
import AdminPage from "@/pages/AdminPage";
import SettingsPage from "@/pages/SettingsPage";
import NotificationsPage from "@/pages/NotificationsPage";
import BackupsPage from "@/pages/BackupsPage";
import SyslogPage from "@/pages/SyslogPage";
import RoutingPage from "@/pages/RoutingPage";
import GenieACSPage from "@/pages/GenieACSPage";
import BillingPage from "@/pages/BillingPage";
import BillingGuidePage from "@/pages/BillingGuidePage";
import HotspotBillingPage from "@/pages/HotspotBillingPage";
import RadiusSettingsPage from "@/pages/RadiusSettingsPage";
import WallDisplayPage from "@/pages/WallDisplayPage";
import SLAPage from "@/pages/SLAPage";
import IncidentsPage from "@/pages/IncidentsPage";
import AuditLogPage from "@/pages/AuditLogPage";
import TopologyPage from "@/pages/TopologyPage";
import UpdatePage from "@/pages/UpdatePage";
import SchedulerPage from "@/pages/SchedulerPage";
import PeeringEyePage from "@/pages/PeeringEyePage";

import LicensePage from "@/pages/LicensePage";
import IntegrationSettingsPage from "@/pages/IntegrationSettingsPage";
import SDWANPage from "@/pages/SDWANPage";
import FinanceReportPage from "@/pages/FinanceReportPage";
import WACustomerServicePage from "@/pages/WACustomerServicePage";
import PingToolPage from "@/pages/PingToolPage";
import QRISHubPage from "@/pages/QRISHubPage";
import ClientLogin from './pages/ClientPortal/ClientLogin';
import ClientDashboard from './pages/ClientPortal/ClientDashboard';
import { Capacitor } from '@capacitor/core';
import { Preferences } from '@capacitor/preferences';


import Layout from "@/components/Layout";
import { Toaster } from "@/components/ui/sonner";

const AuthContext = createContext(null);
const EditionContext = createContext({ edition: "pro", features: { billing: false, finance_report: false } });

export function useAuth() {
  return useContext(AuthContext);
}

export function useEdition() {
  return useContext(EditionContext);
}

function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem("noc_token"));
  const [loading, setLoading] = useState(true);


  const fetchUser = useCallback(async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      const res = await api.get("/auth/me");
      setUser(res.data);
    } catch {
      localStorage.removeItem("noc_token");
      localStorage.removeItem("noc_user");
      setToken(null);
      setUser(null);
    }
    setLoading(false);
  }, [token]);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = async (username, password) => {
    const res = await api.post("/auth/login", { username, password });
    const { token: t, user: u } = res.data;
    localStorage.setItem("noc_token", t);
    localStorage.setItem("noc_user", JSON.stringify(u));
    setToken(t);
    setUser(u);
    return u;
  };

  const logout = () => {
    localStorage.removeItem("noc_token");
    localStorage.removeItem("noc_user");
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

function EditionProvider({ children }) {
  const [editionData, setEditionData] = useState({
    edition: "pro",
    edition_name: "NOC-Sentinel Pro",
    is_enterprise: false,
    is_pro: true,
    billing_enabled: false,
    features: { billing: false, customers: false, finance_report: false, n8n_integration: false, genieacs: true },
    disabled_features: [],
    loading: true,
  });

  useEffect(() => {
    api.get("/edition")
      .then(res => setEditionData({ ...res.data, loading: false }))
      .catch(() => {
        // Fallback: coba /system/info
        api.get("/system/info")
          .then(res => setEditionData({ ...res.data, loading: false }))
          .catch(() => setEditionData(prev => ({ ...prev, loading: false })));
      });
  }, []);

  return (
    <EditionContext.Provider value={editionData}>
      {children}
    </EditionContext.Provider>
  );
}


// Cek apakah user memiliki service tertentu dalam allowed_services kustom
function userHasService(user, serviceKey) {
  if (!user) return false;
  const role = user.role;
  // Admin selalu punya akses penuh
  if (role === "administrator" || role === "super_admin") return true;
  // Jika ada allowed_services kustom, cek di sana
  const explicit = user.allowed_services;
  if (Array.isArray(explicit)) return explicit.includes(serviceKey);
  return false;
}

function ProtectedRoute({ children, allowedRoles, serviceKey }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="flex items-center justify-center min-h-screen bg-background"><div className="text-muted-foreground">Loading...</div></div>;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;

  // Jika role cocok, langsung izinkan
  if (allowedRoles && allowedRoles.includes(user.role)) return children;

  // Jika role TIDAK cocok, cek apakah ada custom service grant
  if (allowedRoles) {
    // Jika serviceKey ada, cek allowed_services
    if (serviceKey && userHasService(user, serviceKey)) return children;
    // Jika tidak ada serviceKey tapi user adalah admin, izinkan
    if (!serviceKey && (user.role === "administrator" || user.role === "super_admin")) return children;
    // Tidak ada izin sama sekali, redirect ke dashboard
    return <Navigate to="/" />;
  }

  return children;
}

// BillingRoute: redirect ke dashboard jika edisi Pro ATAU user tidak punya akses billing
function BillingRoute({ page }) {
  const { features, loading } = useEdition();
  const { user } = useAuth();
  if (loading) return <div className="flex items-center justify-center min-h-screen bg-background"><div className="text-muted-foreground">Loading...</div></div>;
  if (!features?.billing) return <Navigate to="/" />;
  // Billing diizinkan untuk: administrator, super_admin, billing_staff, ATAU user dengan custom billing services
  const BILLING_ROLES = ["administrator", "super_admin", "billing_staff"];
  const hasBillingAccess = user && (
    BILLING_ROLES.includes(user.role) ||
    userHasService(user, "billing") ||
    userHasService(user, "hotspot_billing") ||
    userHasService(user, "finance_report")
  );
  if (!hasBillingAccess) return <Navigate to="/" />;
  return page || <BillingPage />;
}

// Helper: deteksi apakah running di domain client ATAU sebagai APK Capacitor
function isClientPortalContext() {
  // 1. Native Capacitor APK — hostname adalah 'localhost' saat di-bundle
  if (Capacitor.isNativePlatform()) return true;
  // 2. Browser dengan domain client.* atau pelanggan.*
  const h = window.location.hostname;
  return h.startsWith('client') || h.startsWith('pelanggan');
}

// Fitur Kesadaran Domain (Multi-Tenant Auto-Routing)
function AdminOrClientRoot() {
  const isClient = isClientPortalContext();
  const [clientRedirect, setClientRedirect] = useState(null);

  useEffect(() => {
    if (!isClient) return;
    // Pengecekan aman Double-Layer (Preferences + localStorage)
    const checkTokenSession = async () => {
      let tokenValue = null;
      try {
        const { value } = await Preferences.get({ key: 'clientToken' });
        tokenValue = value;
      } catch (err) {
        console.warn('Gagal memuat Capacitor Preferences:', err);
      }
      
      // Jika nilainya null di Native, coba ambil dari Browser Webview bawaannya
      if (!tokenValue) {
        tokenValue = localStorage.getItem('clientToken');
      }

      setClientRedirect(tokenValue ? '/client/dashboard' : '/client/login');
    };
    checkTokenSession();
  }, [isClient]);

  if (isClient) {
    // Sementara cek token, tampilkan loading
    if (!clientRedirect) {
      return (
        <div className="min-h-screen bg-black flex items-center justify-center">
          <div className="w-10 h-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        </div>
      );
    }
    return <Navigate to={clientRedirect} replace />;
  }
  return (
    <ProtectedRoute>
      <Layout />
    </ProtectedRoute>
  );
}

function LoginRouter() {
  const isClient = isClientPortalContext();
  if (isClient) {
    return <ClientLogin />;
  }
  return <LoginPage />;
}



const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
        <EditionProvider>
        <AuthProvider>
          <Toaster
            theme="dark"
            toastOptions={{
              classNames: {
                toast: "bg-card border-border text-foreground",
                description: "text-muted-foreground",
              },
            }}
          />
          <Routes>
            <Route path="/login" element={<LoginRouter />} />
            <Route path="/client/login" element={<ClientLogin />} />
            <Route path="/client/dashboard" element={<ClientDashboard />} />
            <Route path="/wall-display" element={<ProtectedRoute><WallDisplayPage /></ProtectedRoute>} />
            <Route path="/" element={<AdminOrClientRoot />}>
              <Route index element={<DashboardPage />} />
              <Route path="pppoe" element={<PPPoEUsersPage />} />
              <Route path="hotspot" element={<HotspotUsersPage />} />
              <Route path="reports" element={<ReportsPage />} />
              <Route path="devices" element={<DevicesPage />} />
              <Route path="settings" element={<ProtectedRoute allowedRoles={["administrator", "super_admin"]} serviceKey="settings"><SettingsPage /></ProtectedRoute>} />
              <Route path="notifications" element={<ProtectedRoute allowedRoles={["administrator", "super_admin"]} serviceKey="notifications"><NotificationsPage /></ProtectedRoute>} />
              <Route path="backups" element={<ProtectedRoute allowedRoles={["administrator", "super_admin", "noc_engineer"]} serviceKey="backups"><BackupsPage /></ProtectedRoute>} />
              <Route path="syslog" element={<ProtectedRoute allowedRoles={["administrator", "super_admin", "noc_engineer"]} serviceKey="syslog"><SyslogPage /></ProtectedRoute>} />
              <Route path="admin" element={<ProtectedRoute allowedRoles={["administrator", "super_admin"]} serviceKey="settings"><AdminPage /></ProtectedRoute>} />

              <Route path="routing" element={<ProtectedRoute allowedRoles={["administrator", "super_admin", "noc_engineer"]} serviceKey="routing"><RoutingPage /></ProtectedRoute>} />
              <Route path="genieacs" element={<ProtectedRoute allowedRoles={["administrator", "super_admin", "noc_engineer"]} serviceKey="genieacs"><GenieACSPage /></ProtectedRoute>} />
              <Route path="billing" element={<BillingRoute />} />
              <Route path="billing-guide" element={<BillingRoute page={<BillingGuidePage />} />} />
              <Route path="hotspot-billing" element={<BillingRoute page={<HotspotBillingPage />} />} />
              <Route path="finance-report" element={<BillingRoute page={<FinanceReportPage />} />} />
              {/* v3 New Features */}
              <Route path="sla" element={<SLAPage />} />
              <Route path="incidents" element={<IncidentsPage />} />
              <Route path="audit" element={<ProtectedRoute allowedRoles={["administrator", "super_admin", "noc_engineer"]} serviceKey="audit"><AuditLogPage /></ProtectedRoute>} />
              <Route path="topology" element={<TopologyPage />} />
              <Route path="update" element={<ProtectedRoute allowedRoles={["administrator", "super_admin"]} serviceKey="update"><UpdatePage /></ProtectedRoute>} />
              <Route path="scheduler" element={<ProtectedRoute allowedRoles={["administrator", "super_admin", "noc_engineer"]} serviceKey="scheduler"><SchedulerPage /></ProtectedRoute>} />
              {/* SD-WAN & Load Balance */}
              <Route path="sdwan" element={<ProtectedRoute allowedRoles={["administrator", "super_admin", "noc_engineer"]} serviceKey="sdwan"><SDWANPage /></ProtectedRoute>} />
              {/* Peering-Eye */}
              <Route path="peering-eye" element={<PeeringEyePage />} />

              <Route path="ping" element={<PingToolPage />} />

              {/* License Management */}
              <Route path="admin/license" element={<ProtectedRoute allowedRoles={["administrator", "super_admin"]} serviceKey="license"><LicensePage /></ProtectedRoute>} />
              {/* Integration & Automation */}
              <Route path="integration-settings" element={<ProtectedRoute allowedRoles={["administrator", "super_admin"]} serviceKey="integration_settings"><IntegrationSettingsPage /></ProtectedRoute>} />
              <Route path="radius-server" element={<ProtectedRoute allowedRoles={["administrator", "super_admin"]} serviceKey="radius_server"><RadiusSettingsPage /></ProtectedRoute>} />
              {/* WA Customer Service */}
              <Route path="wa-customer-service" element={<ProtectedRoute allowedRoles={["administrator", "super_admin", "billing_staff"]} serviceKey="wa_customer_service"><WACustomerServicePage /></ProtectedRoute>} />
              <Route path="qris-hub" element={<ProtectedRoute allowedRoles={["administrator", "super_admin", "billing_staff"]} serviceKey="license"><QRISHubPage /></ProtectedRoute>} />
            </Route>
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </AuthProvider>
        </EditionProvider>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;


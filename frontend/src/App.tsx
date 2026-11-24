import { Navigate, Route, Routes } from "react-router-dom";
import { Guard } from "./lib/auth";
import * as A from "./pages/admin";
import * as D from "./pages/dash";
import * as P from "./pages/public";

export default function App() {
  return (
    <Routes>
      <Route element={<P.PublicLayout />}>
        <Route path="/" element={<P.Home />} />
        <Route path="/service" element={<P.Service />} />
        <Route path="/how-it-works" element={<P.HowTo />} />
        <Route path="/pricing" element={<P.Pricing />} />
        <Route path="/devices" element={<P.Devices />} />
        <Route path="/faq" element={<P.FaqPage />} />
        <Route path="/notices" element={<P.Notices />} />
        <Route path="/legal/:key" element={<P.Legal />} />
        <Route path="/login" element={<P.Login />} />
        <Route path="/admin/login" element={<P.Login admin />} />
        <Route path="/register" element={<P.Register />} />
        <Route path="/forgot" element={<P.Forgot />} />
        <Route path="/reset-password" element={<P.Reset />} />
        <Route path="/verify-email" element={<P.VerifyEmail />} />
        <Route path="/oauth-complete" element={<P.OAuthComplete />} />
      </Route>
      <Route element={<Guard><D.DashLayout /></Guard>}>
        <Route path="/dashboard" element={<D.Overview />} />
        <Route path="/dashboard/apps" element={<D.Apps />} />
        <Route path="/dashboard/apps/:id" element={<D.AppDetail />} />
        <Route path="/dashboard/new-test" element={<D.NewTest />} />
        <Route path="/dashboard/pay/:id" element={<D.Pay />} />
        <Route path="/pay/success" element={<D.PaySuccess />} />
        <Route path="/pay/fail" element={<D.PayFail />} />
        <Route path="/dashboard/orders" element={<D.Orders />} />
        <Route path="/dashboard/orders/:id" element={<D.OrderDetail />} />
        <Route path="/dashboard/results" element={<D.Orders resultsMode />} />
        <Route path="/dashboard/reports" element={<D.Reports />} />
        <Route path="/dashboard/scenarios" element={<D.Scenarios />} />
        <Route path="/dashboard/payments" element={<D.Payments />} />
        <Route path="/dashboard/support" element={<D.Support />} />
        <Route path="/dashboard/support/:id" element={<D.SupportDetail />} />
        <Route path="/dashboard/notifications" element={<D.NotificationsPage />} />
        <Route path="/dashboard/account" element={<D.Account />} />
      </Route>
      <Route element={<Guard staff><A.AdminLayout /></Guard>}>
        <Route path="/admin" element={<A.AdminHome />} />
        <Route path="/admin/customers" element={<A.Customers />} />
        <Route path="/admin/users" element={<A.UsersPage />} />
        <Route path="/admin/apps" element={<A.AdminApps />} />
        <Route path="/admin/orders" element={<A.AdminOrders />} />
        <Route path="/admin/products" element={<A.Products />} />
        <Route path="/admin/coupons" element={<A.Coupons />} />
        <Route path="/admin/payments" element={<A.AdminPayments />} />
        <Route path="/admin/revenue" element={<A.Revenue />} />
        <Route path="/admin/refunds" element={<A.Refunds />} />
        <Route path="/admin/pg" element={<A.PgSettings />} />
        <Route path="/admin/devices" element={<A.DevicesPage />} />
        <Route path="/admin/device-groups" element={<A.DeviceGroups />} />
        <Route path="/admin/agents" element={<A.Agents />} />
        <Route path="/admin/incidents" element={<A.Incidents />} />
        <Route path="/admin/live" element={<A.Live />} />
        <Route path="/admin/jobs" element={<A.Jobs />} />
        <Route path="/admin/plans" element={<A.Plans />} />
        <Route path="/admin/scenarios" element={<A.AdminScenarios />} />
        <Route path="/admin/results" element={<A.Results />} />
        <Route path="/admin/crashes" element={<A.Crashes />} />
        <Route path="/admin/screenshots" element={<A.Screenshots />} />
        <Route path="/admin/reports" element={<A.AdminReports />} />
        <Route path="/admin/tickets" element={<A.Tickets />} />
        <Route path="/admin/tickets/:id" element={<A.TicketDetail />} />
        <Route path="/admin/announcements" element={<A.Announcements />} />
        <Route path="/admin/faqs" element={<A.Faqs />} />
        <Route path="/admin/legal" element={<A.LegalAdmin />} />
        <Route path="/admin/settings" element={<A.SettingsPage />} />
        <Route path="/admin/status" element={<A.StatusPage />} />
        <Route path="/admin/emails" element={<A.Emails />} />
        <Route path="/admin/templates" element={<A.Templates />} />
        <Route path="/admin/audit" element={<A.Audit />} />
        <Route path="/admin/logs" element={<A.Logs />} />
        <Route path="/admin/backups" element={<A.Backups />} />
        <Route path="/admin/account" element={<D.Account />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

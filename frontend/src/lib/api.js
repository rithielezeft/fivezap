import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API,
  headers: { "Content-Type": "application/json" },
});

// Auto-inject auth token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("wf_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Redirect to /login on 401
api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401 && !window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/teste") && !window.location.pathname.startsWith("/pay/")) {
      localStorage.removeItem("wf_token");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export const authApi = {
  login: (password) => api.post("/auth/login", { password }).then((r) => r.data),
  me: () => api.get("/auth/me").then((r) => r.data),
  changePassword: (data) => api.post("/auth/change-password", data).then((r) => r.data),
};

export const uploadsApi = {
  upload: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post("/uploads", fd, {
      headers: { "Content-Type": "multipart/form-data" },
    }).then((r) => r.data);
  },
};

// Convenience wrappers
export const dashboardApi = {
  stats: () => api.get("/dashboard/stats").then((r) => r.data),
  activity: () => api.get("/dashboard/activity").then((r) => r.data),
  attribution: (days = 30) => api.get("/dashboard/attribution", { params: { days } }).then((r) => r.data),
  revenueByDay: (days = 14) => api.get("/dashboard/revenue-by-day", { params: { days } }).then((r) => r.data),
  balances: () => api.get("/dashboard/balances", { timeout: 15000 }).then((r) => r.data),
};

export const customersApi = {
  list: (params) => api.get("/customers", { params }).then((r) => r.data),
  get: (id) => api.get(`/customers/${id}`).then((r) => r.data),
  create: (data) => api.post("/customers", data).then((r) => r.data),
  update: (id, data) => api.put(`/customers/${id}`, data).then((r) => r.data),
  remove: (id) => api.delete(`/customers/${id}`).then((r) => r.data),
  setWhatsappByPainel: (data) => api.post("/customers/set-whatsapp-by-painel", data).then((r) => r.data),
};

export const trialsApi = {
  list: () => api.get("/trials").then((r) => r.data),
  create: (data) => api.post("/trials", data).then((r) => r.data),
  testLogin: () => api.post("/trials/test-login").then((r) => r.data),
};

export const templatesApi = {
  list: () => api.get("/templates").then((r) => r.data),
  create: (data) => api.post("/templates", data).then((r) => r.data),
  update: (id, data) => api.put(`/templates/${id}`, data).then((r) => r.data),
  remove: (id) => api.delete(`/templates/${id}`).then((r) => r.data),
};

export const whatsappApi = {
  status: () => api.get("/whatsapp/status").then((r) => r.data),
  qr: () => api.get("/whatsapp/qr").then((r) => r.data),
  send: (data) => api.post("/whatsapp/send", data).then((r) => r.data),
  logout: () => api.post("/whatsapp/logout").then((r) => r.data),
  restart: () => api.post("/whatsapp/restart", null, { timeout: 30000 }).then((r) => r.data),
  pairingCode: (phone) =>
    api.post("/whatsapp/pairing-code", { phone }, { timeout: 20000 }).then((r) => r.data),
};

export const messagesApi = {
  list: (params) => api.get("/messages", { params }).then((r) => r.data),
  conversations: () => api.get("/messages/conversations").then((r) => r.data),
};

export const paymentsApi = {
  list: () => api.get("/payments").then((r) => r.data),
  create: (data) => api.post("/payments", data).then((r) => r.data),
  customerInfo: (id) => api.get(`/payments/customer/${id}`).then((r) => r.data),
  testLink: () => api.post("/payments/test-link", null, { timeout: 45000 }).then((r) => r.data),
  checkStatus: (customerId, body = {}) =>
    api.post(`/payments/check-status/${customerId}`, body).then((r) => r.data),
  reprocess: (paymentId) =>
    api.post(`/payments/reprocess/${paymentId}`, {}).then((r) => r.data),
  resendNotification: (paymentId) =>
    api.post(`/payments/resend-notification/${paymentId}`, {}).then((r) => r.data),
  diagnostics: () => api.get("/payments/diagnostics").then((r) => r.data),
  painelLink: (customerId) =>
    api.get(`/payments/painel-link/${customerId}`).then((r) => r.data),
};

export const settingsApi = {
  get: () => api.get("/settings").then((r) => r.data),
  update: (data) => api.put("/settings", data).then((r) => r.data),
  listDiscounts: () => api.get("/settings/discounts").then((r) => r.data),
  updateDiscount: (event_key, data) => api.put(`/settings/discounts/${event_key}`, data).then((r) => r.data),
};

export const analyticsApi = {
  geography: (scope = "all") =>
    api.get("/analytics/geography", { params: { scope } }).then((r) => r.data),
};

export const systemApi = {
  update: (password) => api.post("/system/update", { password }).then((r) => r.data),
  updateStatus: (tail_lines = 80) =>
    api.get("/system/update-status", { params: { tail_lines } }).then((r) => r.data),
};

export const publicApi = {
  requestTrial: (data) => api.post("/public/trial", data).then((r) => r.data),
};

export const couponsApi = {
  list: () => api.get("/coupons").then((r) => r.data),
  create: (data) => api.post("/coupons", data).then((r) => r.data),
  update: (id, data) => api.put(`/coupons/${id}`, data).then((r) => r.data),
  remove: (id) => api.delete(`/coupons/${id}`).then((r) => r.data),
  bulkDelete: (ids) => api.post("/coupons/bulk-delete", { ids }).then((r) => r.data),
  usages: (id) => api.get(`/coupons/${id}/usages`).then((r) => r.data),
  recentUsages: (limit = 50) =>
    api.get("/coupons/usages/recent", { params: { limit } }).then((r) => r.data),
  // PUBLIC — no auth needed (endpoint is whitelisted server-side).
  validate: (code, customer_id) =>
    api.post("/coupons/validate", { code, customer_id }).then((r) => r.data),
};

export const notificationsApi = {
  list: () => api.get("/notifications").then((r) => r.data),
  get: (event_key) => api.get(`/notifications/${event_key}`).then((r) => r.data),
  update: (event_key, data) => api.put(`/notifications/${event_key}`, data).then((r) => r.data),
  restoreDefault: (event_key) => api.post(`/notifications/${event_key}/restore-defaults`).then((r) => r.data),
  listDeliveries: (params) => api.get("/notifications/deliveries", { params }).then((r) => r.data),
  listDedupLog: (params) => api.get("/notifications/dedup-log", { params }).then((r) => r.data),
  retryDelivery: (id) => api.post(`/notifications/deliveries/${id}/retry`).then((r) => r.data),
};

export const painelApi = {
  listUsers: (params) => api.get("/painel/users", { params }).then((r) => r.data),
  refresh: () => api.post("/painel/users/refresh").then((r) => r.data),
  status: () => api.get("/painel/status").then((r) => r.data),
  testConnection: () => api.get("/painel/test-connection", { timeout: 120000 }).then((r) => r.data),
  renew: (data) => api.post("/painel/renew", data).then((r) => r.data),
  packageIds: () => api.get("/painel/package-ids").then((r) => r.data),
  expiring: () => api.get("/painel/expiring").then((r) => r.data),
  notifyNow: () => api.post("/painel/notify-now", null, { timeout: 120000 }).then((r) => r.data),
  debugSample: () => api.get("/painel/debug-sample").then((r) => r.data),
  listExpired: () => api.get("/painel/expired").then((r) => r.data),
  notifyExpired: (user_ids, force) => api.post("/painel/notify-expired", { user_ids: user_ids || [], force: !!force }, { timeout: 180000 }).then((r) => r.data),
};

export function formatMoney(cents) {
  return (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

// In-memory cache of the admin-selected timezone. Populated once at startup
// by App.jsx via `setDisplayTimezone`. Defaults to Brasília.
let _displayTz = "America/Sao_Paulo";

export function setDisplayTimezone(tz) {
  if (tz && typeof tz === "string") _displayTz = tz;
}

export function getDisplayTimezone() {
  return _displayTz;
}

export function formatDateBR(iso) {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "-";
    return d.toLocaleString("pt-BR", { timeZone: _displayTz });
  } catch {
    return iso;
  }
}

// Compact date formatter: "08-08-26 às 23:08h" — used in cards where the
// verbose "08/08/2026, 23:08:36" from `formatDateBR` is too noisy.
export function formatDateShort(iso) {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "-";
    const parts = new Intl.DateTimeFormat("pt-BR", {
      timeZone: _displayTz,
      day: "2-digit", month: "2-digit", year: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).formatToParts(d);
    const get = (t) => (parts.find((p) => p.type === t) || {}).value || "";
    return `${get("day")}-${get("month")}-${get("year")} às ${get("hour")}:${get("minute")}h`;
  } catch {
    return iso;
  }
}

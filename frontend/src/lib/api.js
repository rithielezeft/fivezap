import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API,
  headers: { "Content-Type": "application/json" },
});

// Convenience wrappers
export const dashboardApi = {
  stats: () => api.get("/dashboard/stats").then((r) => r.data),
  activity: () => api.get("/dashboard/activity").then((r) => r.data),
};

export const customersApi = {
  list: (params) => api.get("/customers", { params }).then((r) => r.data),
  get: (id) => api.get(`/customers/${id}`).then((r) => r.data),
  create: (data) => api.post("/customers", data).then((r) => r.data),
  update: (id, data) => api.put(`/customers/${id}`, data).then((r) => r.data),
  remove: (id) => api.delete(`/customers/${id}`).then((r) => r.data),
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
};

export const messagesApi = {
  list: (params) => api.get("/messages", { params }).then((r) => r.data),
  conversations: () => api.get("/messages/conversations").then((r) => r.data),
};

export const paymentsApi = {
  list: () => api.get("/payments").then((r) => r.data),
  create: (data) => api.post("/payments", data).then((r) => r.data),
  customerInfo: (id) => api.get(`/payments/customer/${id}`).then((r) => r.data),
};

export const settingsApi = {
  get: () => api.get("/settings").then((r) => r.data),
  update: (data) => api.put("/settings", data).then((r) => r.data),
};

export const publicApi = {
  requestTrial: (data) => api.post("/public/trial", data).then((r) => r.data),
};

export function formatMoney(cents) {
  return (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export function formatDateBR(iso) {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return iso;
  }
}

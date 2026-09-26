import axios from "axios";

// In dev, Vite proxies "/api" to the backend (see vite.config.js). In a
// production build you can bake in an absolute backend URL at build time
// with VITE_API_URL (e.g. https://api.yourdomain.com/api); otherwise it
// falls back to the relative "/api" path (works when both are served
// behind the same reverse proxy / domain).
const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || "/api" });

export const health = () => api.get("/health").then((r) => r.data);

export const listProjects = () => api.get("/projects").then((r) => r.data);
export const createProject = (name, description = "") =>
  api.post("/projects", { name, description }).then((r) => r.data);
export const getProject = (id) => api.get(`/projects/${id}`).then((r) => r.data);
export const deleteProject = (id) => api.delete(`/projects/${id}`).then((r) => r.data);

export const generatePrimitive = (id, shape, dims, divisions) =>
  api
    .post(`/projects/${id}/mesh/primitive`, { shape, dims, divisions })
    .then((r) => r.data);

export const setMaterial = (id, material) =>
  api.put(`/projects/${id}/material`, material).then((r) => r.data);

export const addBC = (id, bc) => api.post(`/projects/${id}/bcs`, bc).then((r) => r.data);
export const deleteBC = (id, bcId) =>
  api.delete(`/projects/${id}/bcs/${bcId}`).then((r) => r.data);

export const addLoad = (id, load) =>
  api.post(`/projects/${id}/loads`, load).then((r) => r.data);
export const deleteLoad = (id, loadId) =>
  api.delete(`/projects/${id}/loads/${loadId}`).then((r) => r.data);

export const solve = (id) => api.post(`/projects/${id}/solve`).then((r) => r.data);
export const getJob = (jobId) => api.get(`/jobs/${jobId}`).then((r) => r.data);
export const listJobs = (id) => api.get(`/projects/${id}/jobs`).then((r) => r.data);

export default api;

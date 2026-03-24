// API base URL — set VITE_API_URL in your environment for production.
// In development the Vite proxy rewrites /api → localhost:8000, so API_BASE is empty.
export const API_BASE = import.meta.env.VITE_API_URL || '';

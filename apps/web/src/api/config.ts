export const apiOrigins = Object.freeze({
  identity: import.meta.env.VITE_IDENTITY_API_URL ?? "http://localhost:8080",
  mock: import.meta.env.VITE_MOCK_API_URL ?? "http://localhost:8787",
});

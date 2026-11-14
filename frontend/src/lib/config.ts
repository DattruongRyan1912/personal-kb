// NEXT_PUBLIC_* values are inlined at build time: reference each one literally.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
export const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
// the API's POST /api/v1/dev/token, for development without a Supabase project (DEV_LOGIN on the API)
export const DEV_LOGIN = process.env.NEXT_PUBLIC_DEV_LOGIN === "1";

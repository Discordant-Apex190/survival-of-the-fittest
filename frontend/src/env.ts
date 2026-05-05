// Env validation — fails fast on missing vars at startup.
// envsafe v2 uses process.env by default; Vite exposes vars via import.meta.env.
// We bridge the two by reading import.meta.env directly.

const raw = {
  VITE_API_URL: import.meta.env.VITE_API_URL as string | undefined,
  VITE_WS_URL:  import.meta.env.VITE_WS_URL  as string | undefined,
};

function required(key: keyof typeof raw, fallback?: string): string {
  const val = raw[key] ?? fallback;
  if (!val) throw new Error(`Missing env var: ${key}`);
  return val;
}

export const env = {
  VITE_API_URL: required('VITE_API_URL', 'http://localhost:8000'),
  VITE_WS_URL:  required('VITE_WS_URL',  'ws://localhost:8000/ws'),
} as const;

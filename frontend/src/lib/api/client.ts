import { ok, err, type Result } from 'neverthrow';
import type { z } from 'zod';
import { env } from '../../env';

const base = env.VITE_API_URL;

export async function get<T>(
  path: string,
  schema: z.ZodType<T>,
): Promise<Result<T, Error>> {
  try {
    const res = await fetch(`${base}${path}`);
    if (!res.ok) return err(new Error(`HTTP ${res.status}: ${path}`));
    const raw: unknown = await res.json();
    const parsed = schema.safeParse(raw);
    return parsed.success ? ok(parsed.data) : err(new Error(parsed.error.message));
  } catch (e) {
    return err(e instanceof Error ? e : new Error(String(e)));
  }
}

export async function post<T>(
  path: string,
  body: unknown,
  schema: z.ZodType<T>,
): Promise<Result<T, Error>> {
  try {
    const res = await fetch(`${base}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) return err(new Error(`HTTP ${res.status}: ${path}`));
    const raw: unknown = await res.json();
    const parsed = schema.safeParse(raw);
    return parsed.success ? ok(parsed.data) : err(new Error(parsed.error.message));
  } catch (e) {
    return err(e instanceof Error ? e : new Error(String(e)));
  }
}

export const C = {
  bg: '#0d0e12', card: '#13151e', border: '#252836', borderHi: '#363a50',
  text: '#e8eaf0', textMid: '#8a8fa8', textDim: '#4a4f63',
  fire: '#f05a28', void: '#9b59d4', nature: '#2ecc71', ice: '#4fc3f7', electric: '#f5c518',
  common: '#6b7280', uncommon: '#4fc3f7', rare: '#b56cf5', legendary: '#f5c518',
  pass: '#22c55e', fail: '#ef4444', retry: '#f5c518',
} as const;

export type ThemeColor = (typeof C)[keyof typeof C];

const ELEMENT_COLORS: Record<string, string> = {
  fire: C.fire, void: C.void, nature: C.nature, ice: C.ice, electric: C.electric,
};

const TIER_COLORS: Record<string, string> = {
  common: C.common, uncommon: C.uncommon, rare: C.rare, legendary: C.legendary,
};

export const elementColor = (el: string): string => ELEMENT_COLORS[el] ?? C.textMid;
export const tierColor     = (tier: string): string => TIER_COLORS[tier]  ?? C.textMid;

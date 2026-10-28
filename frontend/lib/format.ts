export const money = (v: unknown, digits = 2) => v == null ? '—' : Number(v).toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits});
export const pct = (v: unknown) => v == null ? '—' : `${(Number(v) * 100).toFixed(2)}%`;
export const stamp = (v: string | null | undefined) => v ? new Date(v).toLocaleString(undefined, {timeZone: 'UTC', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) + ' UTC' : 'Not yet available';

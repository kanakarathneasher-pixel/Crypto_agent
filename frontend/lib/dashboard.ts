export type Row = Record<string, any>;
export type Dashboard = {
  market:Row; agent:Row; model:Row; portfolio:Row; performance:Row;
  settings:Row; trades:Row[]; decisions:Row[]; research:Row;
};

export const DASHBOARD_REFRESH_MS = 15000;

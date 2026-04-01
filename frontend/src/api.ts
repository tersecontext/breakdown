import type { RepoInfo, RefreshResponse, TaskCreate, TaskListItem, TaskOut, TaskResubmit, TokenResponse, User } from './types';

// In-memory only — never written to localStorage
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

let isRefreshing = false;
let refreshQueue: Array<(token: string | null) => void> = [];

async function tryRefresh(): Promise<string | null> {
  if (isRefreshing) {
    return new Promise((resolve) => refreshQueue.push(resolve));
  }
  isRefreshing = true;
  let newToken: string | null = null;
  try {
    const res = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
    if (res.ok) {
      const data: RefreshResponse = await res.json();
      accessToken = data.access_token;
      newToken = data.access_token;
    }
  } finally {
    isRefreshing = false;
    refreshQueue.forEach(cb => cb(newToken));
    refreshQueue = [];
  }
  return newToken;
}

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const doFetch = (token: string | null) =>
    fetch(path, {
      ...options,
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers ?? {}),
      },
    });

  let res = await doFetch(accessToken);

  if (res.status === 401 && path !== '/api/auth/refresh') {
    const newToken = await tryRefresh();
    if (!newToken) {
      // Refresh failed — redirect to login
      accessToken = null;
      window.location.href = '/login';
      throw new Error('Session expired');
    }
    res = await doFetch(newToken);
  }

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const login = (username: string, password: string): Promise<TokenResponse> =>
  apiFetch('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });

// Call fetch directly — avoids the apiFetch 401 interceptor redirecting
// to /login during the RequireAuth page-load session restore attempt.
export async function refreshSession(): Promise<RefreshResponse> {
  const res = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export const logout = (): Promise<void> =>
  apiFetch('/api/auth/logout', { method: 'POST' });

export const getMe = (): Promise<User> => apiFetch('/api/auth/me');

export const listRepos = (): Promise<RepoInfo[]> => apiFetch('/api/repos');

export const getBranches = (repo: string): Promise<string[]> =>
  apiFetch(`/api/repos/${encodeURIComponent(repo)}/branches`);

export const indexRepo = (repo: string): Promise<{ queued: boolean }> =>
  apiFetch(`/api/repos/${encodeURIComponent(repo)}/index`, { method: 'POST' });

export const listTasks = (): Promise<TaskListItem[]> => apiFetch('/api/tasks');

export const getTask = (id: string): Promise<TaskOut> => apiFetch(`/api/tasks/${id}`);

export const createTask = (body: TaskCreate): Promise<TaskOut> =>
  apiFetch('/api/tasks', { method: 'POST', body: JSON.stringify(body) });

export const retryTask = (id: string): Promise<TaskOut> =>
  apiFetch(`/api/tasks/${id}/retry`, { method: 'POST' });

export const approveTask = (id: string): Promise<TaskOut> =>
  apiFetch(`/api/tasks/${id}/approve`, { method: 'POST' });

export const rejectTask = (id: string, reason?: string): Promise<TaskOut> =>
  apiFetch(`/api/tasks/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason: reason ?? null }),
  });

export const resubmitTask = (id: string, fields: TaskResubmit): Promise<TaskOut> =>
  apiFetch(`/api/tasks/${id}/resubmit`, {
    method: 'POST',
    body: JSON.stringify(fields),
  });

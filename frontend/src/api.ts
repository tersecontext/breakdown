// frontend/src/api.ts

import type { RepoInfo, TaskCreate, TaskListItem, TaskOut, User } from './types';

const getUser = () => localStorage.getItem('username') ?? '';

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-User': getUser(),
      ...(options.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const login = (username: string): Promise<User> =>
  apiFetch('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username }),
  });

export const getMe = (): Promise<User> => apiFetch('/api/auth/me');

export const listRepos = (): Promise<RepoInfo[]> => apiFetch('/api/repos');

export const getBranches = (repo: string): Promise<string[]> =>
  apiFetch(`/api/repos/${encodeURIComponent(repo)}/branches`);

export const listTasks = (): Promise<TaskListItem[]> => apiFetch('/api/tasks');

export const getTask = (id: string): Promise<TaskOut> => apiFetch(`/api/tasks/${id}`);

export const createTask = (body: TaskCreate): Promise<TaskOut> =>
  apiFetch('/api/tasks', { method: 'POST', body: JSON.stringify(body) });

export const approveTask = (id: string): Promise<TaskOut> =>
  apiFetch(`/api/tasks/${id}/approve`, { method: 'POST' });

export const rejectTask = (id: string, reason?: string): Promise<TaskOut> =>
  apiFetch(`/api/tasks/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason: reason ?? null }),
  });

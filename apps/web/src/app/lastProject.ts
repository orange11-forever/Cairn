const storageKey = (organizationId: string) => `cairn-last-project:${organizationId}`;

export function readLastProject(storage: Pick<Storage, "getItem">, organizationId: string): string | null {
  try {
    return storage.getItem(storageKey(organizationId));
  } catch {
    return null;
  }
}

export function writeLastProject(storage: Pick<Storage, "setItem">, organizationId: string, projectId: string): void {
  try {
    storage.setItem(storageKey(organizationId), projectId);
  } catch {
    return;
  }
}

export function clearLastProject(storage: Pick<Storage, "removeItem">, organizationId: string): void {
  try {
    storage.removeItem(storageKey(organizationId));
  } catch {
    return;
  }
}

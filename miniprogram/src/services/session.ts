export interface AuthSessionSnapshot {
  token: string | null
  isMockLogin: boolean
}

let snapshot: AuthSessionSnapshot = {
  token: null,
  isMockLogin: false
}

export function setAuthSession(
  token: string | null,
  isMockLogin: boolean
): void {
  snapshot = { token, isMockLogin }
}

export function getAuthSession(): AuthSessionSnapshot {
  return snapshot
}

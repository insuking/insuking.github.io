/**
 * Client-side auth state (P21) - `user_id` lives in `localStorage`, set
 * once a real Kakao login redirect completes (`pages/KakaoCallbackPage.tsx`,
 * backed by `app/api/auth.py`), and sent back as the `X-User-Id` header on
 * approval requests (see `api/client.ts`). No server-side session cookie -
 * see `app/api/approvals.py`'s module docstring for why this design was
 * kept rather than replaced.
 */

const STORAGE_KEY = "userId";

export function currentUserId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setUserId(userId: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, userId);
  } catch {
    // Storage unavailable (private browsing, quota) - the user will be
    // prompted to log in again rather than silently failing later.
  }
}

import { useEffect, useState } from "react";
import { submitKakaoCallback } from "../api/client";
import { setUserId } from "../auth";

type Status = "pending" | "success" | "error";

/** Handles the Kakao OAuth redirect (`?code=...&state=...`) - exchanges it
 * via `app/api/auth.py`'s callback endpoint and stores the resulting
 * `user_id` (see `auth.ts`), then sends the browser back to the home tab.
 * Rendered when App.tsx matches the configured Kakao redirect path. */
export function KakaoCallbackPage() {
  const [status, setStatus] = useState<Status>("pending");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      setStatus("error");
      return;
    }

    let cancelled = false;
    submitKakaoCallback(code, state)
      .then(({ user_id }) => {
        if (cancelled) return;
        setUserId(user_id);
        setStatus("success");
        window.location.replace("#/radar");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="page">
      <section className="card">
        {status === "pending" && <p className="muted">로그인 처리 중...</p>}
        {status === "success" && <p className="muted">로그인 완료. 이동 중...</p>}
        {status === "error" && <p className="muted">로그인에 실패했습니다. 다시 시도해주세요.</p>}
      </section>
    </main>
  );
}

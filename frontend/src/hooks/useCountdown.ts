import { useEffect, useState } from "react";

function secondsUntil(expiresAtIso: string): number {
  return Math.max(0, Math.floor((new Date(expiresAtIso).getTime() - Date.now()) / 1000));
}

/** Seconds remaining until `expiresAtIso`, updated once per second, floored at 0. */
export function useCountdown(expiresAtIso: string): number {
  const [remainingSeconds, setRemainingSeconds] = useState(() => secondsUntil(expiresAtIso));

  useEffect(() => {
    // Recompute immediately on mount/prop-change rather than waiting up to
    // 1s for the first tick; the lazy useState initializer only covers the
    // very first render, not a later `expiresAtIso` change. oxlint flags
    // this as "set-state-in-effect" - correct pattern here, not a bug.
    setRemainingSeconds(secondsUntil(expiresAtIso));
    const interval = setInterval(() => {
      setRemainingSeconds(secondsUntil(expiresAtIso));
    }, 1000);
    return () => clearInterval(interval);
  }, [expiresAtIso]);

  return remainingSeconds;
}

export function formatCountdown(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

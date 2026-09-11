import { useCallback, useRef, useState, type CSSProperties } from "react";
import "./HoldToConfirmButton.css";

interface HoldToConfirmButtonProps {
  label: string;
  holdingLabel?: string;
  busyLabel?: string;
  onConfirm: () => void | Promise<void>;
  disabled?: boolean;
  durationMs?: number;
  variant?: "default" | "danger";
  className?: string;
}

const DEFAULT_DURATION_MS = 1800;

/**
 * Press-and-hold confirmation control (P46) - the functional equivalent of
 * the SmartCoin mockups' "n초간 눌러 확인" slider for destructive/
 * real-money actions (즉시 청산, 긴급정지 활성화/해제). A press-and-hold
 * button gives the same "can't fire on an accidental tap" friction a drag
 * slider does, without hand-rolling pointer-drag physics for what is
 * ultimately a single boolean outcome - the simplest control that
 * delivers the same real safety property, same reasoning
 * `SafetyCheckPage`'s plain disabled-button gate already uses over a
 * fancier widget. Releasing early cancels - nothing fires until the hold
 * genuinely completes.
 */
export function HoldToConfirmButton({
  label,
  holdingLabel,
  busyLabel,
  onConfirm,
  disabled = false,
  durationMs = DEFAULT_DURATION_MS,
  variant = "default",
  className,
}: HoldToConfirmButtonProps) {
  const [holding, setHolding] = useState(false);
  const [busy, setBusy] = useState(false);
  const timerRef = useRef<number | null>(null);

  const cancelHold = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setHolding(false);
  }, []);

  const startHold = useCallback(() => {
    if (disabled || busy || timerRef.current !== null) return;
    setHolding(true);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setHolding(false);
      setBusy(true);
      void Promise.resolve(onConfirm()).finally(() => setBusy(false));
    }, durationMs);
  }, [disabled, busy, durationMs, onConfirm]);

  const fillStyle: CSSProperties | undefined = holding
    ? { transitionDuration: `${durationMs}ms` }
    : undefined;

  return (
    <button
      type="button"
      className={`hold-confirm-button hold-confirm-button--${variant}${holding ? " hold-confirm-button--holding" : ""}${className ? ` ${className}` : ""}`}
      disabled={disabled || busy}
      onMouseDown={startHold}
      onMouseUp={cancelHold}
      onMouseLeave={cancelHold}
      onTouchStart={startHold}
      onTouchEnd={cancelHold}
      onTouchCancel={cancelHold}
    >
      <span className="hold-confirm-button__fill" style={fillStyle} aria-hidden="true" />
      <span className="hold-confirm-button__label">
        {busy ? (busyLabel ?? "처리 중...") : holding ? (holdingLabel ?? "계속 누르고 있으세요...") : label}
      </span>
    </button>
  );
}

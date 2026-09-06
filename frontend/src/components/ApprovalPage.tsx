import { useEffect, useState } from "react";
import { ApprovalApiError, decideApproval, fetchApproval } from "../api/client";
import { formatCountdown, useCountdown } from "../hooks/useCountdown";
import type { ApprovalDecisionType, ApprovalDetail } from "../types/approval";
import "./ApprovalPage.css";

interface ApprovalPageProps {
  token: string;
  userId: string | null;
}

const TERMINAL_STATES = new Set([
  "APPROVED",
  "REJECTED",
  "EXPIRED",
  "INVALIDATED",
  "EXECUTED",
  "BLOCKED_BY_RISK",
]);

const STATE_LABEL_KO: Record<string, string> = {
  CREATED: "확인 대기",
  NOTIFIED: "확인 대기",
  OPENED: "확인 대기",
  APPROVED: "승인 완료",
  REJECTED: "거절됨",
  EXPIRED: "만료됨",
  INVALIDATED: "무효화됨 (시장 조건 변경)",
  EXECUTED: "주문 완료",
  BLOCKED_BY_RISK: "위험관리에 의해 차단됨",
};

const numberFormatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

function formatWon(value: number): string {
  return `₩${numberFormatter.format(Math.round(value))}`;
}

type PendingAction = "APPROVE" | "APPROVE_WITH_AMOUNT_CHANGE" | null;

export function ApprovalPage({ token, userId }: ApprovalPageProps) {
  const [detail, setDetail] = useState<ApprovalDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;

    fetchApproval(token, userId)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(err instanceof ApprovalApiError ? err.detail : "승인 정보를 불러오지 못했습니다");
      });

    return () => {
      cancelled = true;
    };
  }, [token, userId]);

  if (!userId) {
    return (
      <main className="approval-page">
        <p className="approval-page__notice">카카오 로그인이 필요합니다.</p>
      </main>
    );
  }

  if (loadError) {
    return (
      <main className="approval-page">
        <p className="approval-page__notice approval-page__notice--error">{loadError}</p>
      </main>
    );
  }

  if (!detail) {
    return (
      <main className="approval-page">
        <p className="approval-page__notice">불러오는 중...</p>
      </main>
    );
  }

  // A separate component so its `useCountdown` mounts fresh - once, exactly
  // when real `detail` first exists - rather than starting from a
  // placeholder "now" timestamp in the parent and correcting a render
  // later. That one-render-late correction is invisible to a human but
  // race-prone in tests (and in real fast interactions): a click
  // immediately after data loads could still see the stale disabled state.
  return <ApprovalDetailView token={token} userId={userId} initialDetail={detail} />;
}

interface ApprovalDetailViewProps {
  token: string;
  userId: string;
  initialDetail: ApprovalDetail;
}

function ApprovalDetailView({ token, userId, initialDetail }: ApprovalDetailViewProps) {
  const [detail, setDetail] = useState(initialDetail);
  const [expiresAtIso] = useState(() => new Date(Date.now() + initialDetail.remaining_seconds * 1000).toISOString());
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [pin, setPin] = useState("");
  const [overrideAmount, setOverrideAmount] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const remainingSeconds = useCountdown(expiresAtIso);
  const isTerminal = TERMINAL_STATES.has(detail.approval_state);
  const isExpiredByCountdown = remainingSeconds <= 0 && !isTerminal;
  const decisionsDisabled = isTerminal || isExpiredByCountdown || submitting;

  async function submitDecision(decision: ApprovalDecisionType) {
    setSubmitting(true);
    setActionError(null);
    try {
      const body =
        decision === "APPROVE_WITH_AMOUNT_CHANGE"
          ? { decision, pin, override_amount: Number(overrideAmount) }
          : decision === "APPROVE"
            ? { decision, pin }
            : { decision };
      const result = await decideApproval(token, userId, body);
      setDetail((prev) => ({ ...prev, approval_state: result.approval_state }));
      setPendingAction(null);
      setPin("");
    } catch (err) {
      setActionError(err instanceof ApprovalApiError ? err.detail : "요청을 처리하지 못했습니다");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="approval-page" data-testid="approval-page">
      <header className="approval-page__header">
        <span className="approval-page__symbol">{detail.symbol}</span>
        <span className="approval-page__badge">{STATE_LABEL_KO[detail.approval_state] ?? detail.approval_state}</span>
      </header>

      <p className="approval-page__countdown">
        {isTerminal ? "" : isExpiredByCountdown ? "만료됨" : `남은 시간 ${formatCountdown(remainingSeconds)}`}
      </p>

      <div className="approval-page__grid">
        <div className="approval-page__cell">
          <span className="approval-page__label">진입</span>
          <span className="approval-page__value">
            {formatWon(detail.entry_low)} ~ {formatWon(detail.entry_high)}
          </span>
        </div>
        <div className="approval-page__cell">
          <span className="approval-page__label">손절</span>
          <span className="approval-page__value">{formatWon(detail.stop_price)}</span>
        </div>
        <div className="approval-page__cell">
          <span className="approval-page__label">T1 ({detail.t1_percent}%)</span>
          <span className="approval-page__value">{formatWon(detail.t1_price)}</span>
        </div>
        <div className="approval-page__cell">
          <span className="approval-page__label">T2 ({detail.t2_percent}%)</span>
          <span className="approval-page__value">{formatWon(detail.t2_price)}</span>
        </div>
        <div className="approval-page__cell">
          <span className="approval-page__label">Runner</span>
          <span className="approval-page__value">{detail.runner_percent}%</span>
        </div>
        <div className="approval-page__cell">
          <span className="approval-page__label">최대 예상손실</span>
          <span className="approval-page__value">{formatWon(detail.expected_max_loss)}</span>
        </div>
        <div className="approval-page__cell">
          <span className="approval-page__label">점수 / 신뢰도</span>
          <span className="approval-page__value">
            {Math.round(detail.score)} / {detail.confidence}
          </span>
        </div>
        <div className="approval-page__cell">
          <span className="approval-page__label">R:R</span>
          <span className="approval-page__value">{detail.risk_reward.toFixed(1)}R</span>
        </div>
      </div>

      <div className="approval-page__details">
        <div>
          <p className="approval-page__details-title">왜 추천?</p>
          <ul>
            {detail.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
        <div>
          <p className="approval-page__details-title">위험요인</p>
          <ul>
            {detail.risks.map((risk) => (
              <li key={risk}>{risk}</li>
            ))}
          </ul>
        </div>
      </div>

      {actionError && <p className="approval-page__notice approval-page__notice--error">{actionError}</p>}

      {pendingAction && !decisionsDisabled && (
        <div className="approval-page__pin-box">
          {pendingAction === "APPROVE_WITH_AMOUNT_CHANGE" && (
            <input
              type="number"
              inputMode="numeric"
              placeholder="변경할 금액"
              value={overrideAmount}
              onChange={(e) => setOverrideAmount(e.target.value)}
              className="approval-page__input"
            />
          )}
          <input
            type="password"
            inputMode="numeric"
            placeholder="PIN"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            className="approval-page__input"
          />
          <button
            type="button"
            className="approval-page__cta"
            disabled={submitting}
            onClick={() => submitDecision(pendingAction)}
          >
            확인
          </button>
        </div>
      )}

      <div className="approval-page__actions">
        <button
          type="button"
          className="approval-page__cta approval-page__cta--primary"
          disabled={decisionsDisabled}
          onClick={() => setPendingAction("APPROVE")}
        >
          승인
        </button>
        <button
          type="button"
          className="approval-page__cta"
          disabled={decisionsDisabled}
          onClick={() => setPendingAction("APPROVE_WITH_AMOUNT_CHANGE")}
        >
          금액변경 후 승인
        </button>
        <button
          type="button"
          className="approval-page__cta"
          disabled={decisionsDisabled}
          onClick={() => submitDecision("HOLD")}
        >
          보류
        </button>
        <button
          type="button"
          className="approval-page__cta approval-page__cta--danger"
          disabled={decisionsDisabled}
          onClick={() => submitDecision("REJECT")}
        >
          거절
        </button>
      </div>
    </main>
  );
}

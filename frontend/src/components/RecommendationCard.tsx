import { useState } from "react";
import { formatCountdown, useCountdown } from "../hooks/useCountdown";
import type { Recommendation } from "../types/domain";
import "./RecommendationCard.css";

interface RecommendationCardProps {
  recommendation: Recommendation;
  onApprove?: () => void;
}

const numberFormatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

function formatWon(value: number): string {
  return `₩${numberFormatter.format(Math.round(value))}`;
}

export function RecommendationCard({ recommendation, onApprove }: RecommendationCardProps) {
  const [expanded, setExpanded] = useState(false);
  const remainingSeconds = useCountdown(recommendation.expires_at);
  const expired = remainingSeconds <= 0;

  const riskPerUnit = recommendation.entry_low - recommendation.stop_price;
  const quantity = riskPerUnit > 0 ? recommendation.expected_max_loss / riskPerUnit : 0;
  const recommendedAmount = quantity * recommendation.entry_low;

  return (
    <article className="rec-card" data-testid="recommendation-card">
      <header className="rec-card__header">
        <div>
          <span className="rec-card__symbol">{recommendation.symbol}</span>
          <span className="rec-card__state">{recommendation.state}</span>
        </div>
        <span className="rec-card__score">Score {Math.round(recommendation.score)}</span>
      </header>

      <div className="rec-card__grid">
        <div className="rec-card__cell">
          <span className="rec-card__label">진입</span>
          <span className="rec-card__value">
            {formatWon(recommendation.entry_low)} ~ {formatWon(recommendation.entry_high)}
          </span>
        </div>
        <div className="rec-card__cell">
          <span className="rec-card__label">손절</span>
          <span className="rec-card__value">{formatWon(recommendation.stop_price)}</span>
        </div>
        <div className="rec-card__cell">
          <span className="rec-card__label">T1 ({recommendation.t1_percent}%)</span>
          <span className="rec-card__value">{formatWon(recommendation.t1_price)}</span>
        </div>
        <div className="rec-card__cell">
          <span className="rec-card__label">T2 ({recommendation.t2_percent}%)</span>
          <span className="rec-card__value">{formatWon(recommendation.t2_price)}</span>
        </div>
        <div className="rec-card__cell rec-card__cell--wide">
          <span className="rec-card__label">Runner</span>
          <span className="rec-card__value">{recommendation.runner_percent}%</span>
        </div>
      </div>

      <div className="rec-card__summary">
        <div>
          <span className="rec-card__label">최대 예상손실</span>
          <span className="rec-card__value">{formatWon(recommendation.expected_max_loss)}</span>
        </div>
        <div>
          <span className="rec-card__label">추천금액</span>
          <span className="rec-card__value">{formatWon(recommendedAmount)}</span>
        </div>
        <div>
          <span className="rec-card__label">R:R</span>
          <span className="rec-card__value">{recommendation.risk_reward.toFixed(1)}R</span>
        </div>
      </div>

      <button
        type="button"
        className="rec-card__toggle"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        {expanded ? "접기" : "왜 추천? / 위험요인"}
      </button>

      {expanded && (
        <div className="rec-card__details">
          <div>
            <p className="rec-card__details-title">왜 추천?</p>
            <ul>
              {recommendation.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
          <div>
            <p className="rec-card__details-title">위험요인</p>
            <ul>
              {recommendation.risks.map((risk) => (
                <li key={risk}>{risk}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <footer className="rec-card__footer">
        <span className="rec-card__countdown" data-testid="countdown">
          {expired ? "만료됨" : `추천 유효시간 ${formatCountdown(remainingSeconds)}`}
        </span>
        <button
          type="button"
          className="rec-card__cta"
          disabled={expired}
          onClick={onApprove}
        >
          승인하기
        </button>
      </footer>
    </article>
  );
}

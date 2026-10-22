/**
 * Kakao Login HTTP API types (P21) - mirror backend/app/api/auth.py's
 * response models.
 */

export interface LoginUrlResponse {
  authorize_url: string;
}

export interface CallbackResponse {
  user_id: string;
}

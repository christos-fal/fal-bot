from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Set


class RateLimiter:
    """
    Rate limiter for Discord bot commands with model-specific limits.
    - Default: 50 generations per user per day
    - Veo 3.1: 5 generations per user per day
    - 1 concurrent generation per user (across all models)
    """

    def __init__(self):
        # Track daily usage per model: {user_id: {model: [timestamp1, timestamp2, ...]}}
        self.daily_usage: Dict[int, Dict[str, list]] = defaultdict(lambda: defaultdict(list))

        # Track concurrent generations: {user_id}
        self.active_users: Set[int] = set()

        # Model-specific limits
        self.MODEL_LIMITS = {
            "veo": 5,      # Veo 3.1 gets 5/day
            "default": 50,  # All other models get 50/day
        }
        
        self.CONCURRENT_LIMIT = 1

    def _get_model_limit(self, model: str = "default") -> int:
        """Get the daily limit for a specific model"""
        return self.MODEL_LIMITS.get(model, self.MODEL_LIMITS["default"])

    def _clean_old_timestamps(self, user_id: int, model: str = "default"):
        """Remove timestamps older than 24 hours for a specific model"""
        now = datetime.now()
        cutoff = now - timedelta(days=1)

        if user_id in self.daily_usage and model in self.daily_usage[user_id]:
            self.daily_usage[user_id][model] = [
                ts for ts in self.daily_usage[user_id][model] if ts > cutoff
            ]

    def get_remaining_generations(self, user_id: int, model: str = "default") -> int:
        """Get how many generations the user has left today for a specific model"""
        self._clean_old_timestamps(user_id, model)
        limit = self._get_model_limit(model)
        used = len(self.daily_usage.get(user_id, {}).get(model, []))
        return max(0, limit - used)

    def get_reset_time(self, user_id: int, model: str = "default") -> datetime:
        """Get when the user's oldest generation will expire for a specific model"""
        self._clean_old_timestamps(user_id, model)

        if (
            user_id not in self.daily_usage
            or model not in self.daily_usage[user_id]
            or not self.daily_usage[user_id][model]
        ):
            return datetime.now()

        oldest = min(self.daily_usage[user_id][model])
        return oldest + timedelta(days=1)

    def can_generate(self, user_id: int, model: str = "default") -> tuple[bool, str]:
        """
        Check if user can generate for a specific model.

        Args:
            user_id: Discord user ID
            model: Model identifier ("veo" for Veo 3.1, "default" for others)

        Returns:
            tuple[bool, str]: (can_generate, reason_if_not)
        """
        # Check concurrent limit (applies across all models)
        if user_id in self.active_users:
            return (
                False,
                "You already have a generation in progress. Please wait for it to complete.",
            )

        # Check model-specific daily limit
        self._clean_old_timestamps(user_id, model)
        limit = self._get_model_limit(model)
        used = len(self.daily_usage.get(user_id, {}).get(model, []))

        if used >= limit:
            reset_time = self.get_reset_time(user_id, model)
            time_until_reset = reset_time - datetime.now()
            hours = int(time_until_reset.total_seconds() // 3600)
            minutes = int((time_until_reset.total_seconds() % 3600) // 60)

            model_name = "Veo 3.1" if model == "veo" else "this model"
            return (
                False,
                f"Daily limit reached for {model_name} ({limit} generations/day). Resets in {hours}h {minutes}m.",
            )

        return True, ""

    async def acquire(self, user_id: int, model: str = "default") -> bool:
        """
        Try to acquire a generation slot for the user.

        Args:
            user_id: Discord user ID
            model: Model identifier ("veo" for Veo 3.1, "default" for others)

        Returns:
            bool: True if acquired, False if rate limited
        """
        can_gen, _ = self.can_generate(user_id, model)

        if not can_gen:
            return False

        # Mark user as active
        self.active_users.add(user_id)

        # Record the generation for this specific model
        self.daily_usage[user_id][model].append(datetime.now())

        return True

    def release(self, user_id: int):
        """Release the generation slot for the user"""
        self.active_users.discard(user_id)

    def get_stats(self, user_id: int, model: str = "default") -> dict:
        """Get user's rate limit stats for a specific model"""
        self._clean_old_timestamps(user_id, model)

        limit = self._get_model_limit(model)
        used = len(self.daily_usage.get(user_id, {}).get(model, []))
        remaining = limit - used
        is_active = user_id in self.active_users

        return {
            "used": used,
            "remaining": remaining,
            "daily_limit": limit,
            "is_generating": is_active,
            "reset_time": self.get_reset_time(user_id, model) if used > 0 else None,
        }


# Global rate limiter instance
rate_limiter = RateLimiter()
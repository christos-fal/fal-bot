from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Set


class RateLimiter:
    """
    Rate limiter for Discord bot commands.
    - 10 generations per user per day
    - 1 concurrent generation per user
    """

    def __init__(self):
        # Track daily usage: {user_id: [(timestamp1, timestamp2, ...)]}
        self.daily_usage: Dict[int, list] = defaultdict(list)

        # Track concurrent generations: {user_id}
        self.active_users: Set[int] = set()

        # Limits
        self.DAILY_LIMIT = 100
        self.CONCURRENT_LIMIT = 1

    def _clean_old_timestamps(self, user_id: int):
        """Remove timestamps older than 24 hours"""
        now = datetime.now()
        cutoff = now - timedelta(days=1)

        if user_id in self.daily_usage:
            self.daily_usage[user_id] = [
                ts for ts in self.daily_usage[user_id] if ts > cutoff
            ]

    def get_remaining_generations(self, user_id: int) -> int:
        """Get how many generations the user has left today"""
        self._clean_old_timestamps(user_id)
        used = len(self.daily_usage.get(user_id, []))
        return max(0, self.DAILY_LIMIT - used)

    def get_reset_time(self, user_id: int) -> datetime:
        """Get when the user's oldest generation will expire"""
        self._clean_old_timestamps(user_id)

        if user_id not in self.daily_usage or not self.daily_usage[user_id]:
            return datetime.now()

        oldest = min(self.daily_usage[user_id])
        return oldest + timedelta(days=1)

    def can_generate(self, user_id: int) -> tuple[bool, str]:
        """
        Check if user can generate.

        Returns:
            tuple[bool, str]: (can_generate, reason_if_not)
        """
        # Check concurrent limit
        if user_id in self.active_users:
            return (
                False,
                "You already have a generation in progress. Please wait for it to complete.",
            )

        # Check daily limit
        self._clean_old_timestamps(user_id)
        used = len(self.daily_usage.get(user_id, []))

        if used >= self.DAILY_LIMIT:
            reset_time = self.get_reset_time(user_id)
            time_until_reset = reset_time - datetime.now()
            hours = int(time_until_reset.total_seconds() // 3600)
            minutes = int((time_until_reset.total_seconds() % 3600) // 60)

            return (
                False,
                f"Daily limit reached ({self.DAILY_LIMIT} generations/day). Resets in {hours}h {minutes}m.",
            )

        return True, ""

    async def acquire(self, user_id: int) -> bool:
        """
        Try to acquire a generation slot for the user.

        Returns:
            bool: True if acquired, False if rate limited
        """
        can_gen, _ = self.can_generate(user_id)

        if not can_gen:
            return False

        # Mark user as active
        self.active_users.add(user_id)

        # Record the generation
        self.daily_usage[user_id].append(datetime.now())

        return True

    def release(self, user_id: int):
        """Release the generation slot for the user"""
        self.active_users.discard(user_id)

    def get_stats(self, user_id: int) -> dict:
        """Get user's rate limit stats"""
        self._clean_old_timestamps(user_id)

        used = len(self.daily_usage.get(user_id, []))
        remaining = self.DAILY_LIMIT - used
        is_active = user_id in self.active_users

        return {
            "used": used,
            "remaining": remaining,
            "daily_limit": self.DAILY_LIMIT,
            "is_generating": is_active,
            "reset_time": self.get_reset_time(user_id) if used > 0 else None,
        }


# Global rate limiter instance
rate_limiter = RateLimiter()

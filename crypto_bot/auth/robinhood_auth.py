from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)

try:
    import robin_stocks.robinhood as rh
    RH_AVAILABLE = True
except ImportError:
    RH_AVAILABLE = False


class RobinhoodAuth:
    def __init__(self):
        self._logged_in = False

    def login(self) -> bool:
        if not RH_AVAILABLE:
            logger.error("robin_stocks not installed")
            return False
        try:
            u = os.getenv("ROBINHOOD_USERNAME", "")
            p = os.getenv("ROBINHOOD_PASSWORD", "")
            if not u or not p:
                logger.error("Missing ROBINHOOD_USERNAME or ROBINHOOD_PASSWORD")
                return False
            rh.login(u, p, store_session=True)
            self._logged_in = True
            logger.info("Crypto bot: Robinhood login successful")
            return True
        except Exception as e:
            logger.error(f"Crypto bot login failed: {e}")
            return False

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    def refresh_session(self) -> bool:
        if self._logged_in:
            try:
                rh.login(os.getenv("ROBINHOOD_USERNAME", ""), os.getenv("ROBINHOOD_PASSWORD", ""), store_session=True)
                return True
            except Exception:
                self._logged_in = False
                return False
        return self.login()

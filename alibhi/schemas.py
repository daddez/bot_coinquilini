from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple


@dataclass
class PendingPurchase:
    items: List[Dict]
    cost: Optional[Decimal] = None
    receipt_paths: List[str] = None
    receipt_meta: List[Tuple[str, int]] = None  # (unique_id, file_size)
    stage: str = "await_cost"
    start_time: Optional[dt.datetime] = None

    def __post_init__(self):
        if self.receipt_paths is None:
            self.receipt_paths = []
        if self.receipt_meta is None:
            self.receipt_meta = []


PENDING: Dict[int, PendingPurchase] = {}
PENDING_LOCK = threading.Lock()


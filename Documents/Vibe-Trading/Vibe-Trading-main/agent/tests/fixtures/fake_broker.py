from __future__ import annotations


class FakeBroker:
    """KIS-like adapter that never touches a real account."""

    def __init__(self) -> None:
        self.orders: list[dict] = []
        self.cancelled: list[str] = []
        self.positions: dict[str, int] = {}
        self._seq = 0

    def place_order_cash(
        self,
        symbol: str,
        side: str,
        *,
        qty: int,
        price: float,
        order_type: str,
        excg_id: str = "KRX",
        env_dv: str = "demo",
        dry_run: bool = False,
        ord_dvsn_override=None,
    ) -> dict:
        self._seq += 1
        order_no = f"MOCK{self._seq:05d}"
        self.orders.append({
            "order_no": order_no,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "order_type": order_type,
            "excg_id": excg_id,
            "env_dv": env_dv,
            "dry_run": dry_run,
            "ord_dvsn_override": ord_dvsn_override,
        })
        return {"status": "ok", "order_no": order_no, "krx_org_no": f"K{self._seq:05d}"}

    def cancel_order(self, *, order_no: str, symbol: str, qty: int, **kwargs) -> dict:
        self.cancelled.append(order_no)
        return {"status": "ok", "order_no": order_no, "symbol": symbol, "qty": qty}

    def apply_fill(self, symbol: str, side: str, qty: int) -> None:
        if side == "buy":
            self.positions[symbol] = self.positions.get(symbol, 0) + qty
        else:
            self.positions[symbol] = max(0, self.positions.get(symbol, 0) - qty)

    def fetch_positions(self) -> dict[str, int]:
        return dict(self.positions)


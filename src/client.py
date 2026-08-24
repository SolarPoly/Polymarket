import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

class PolymarketEngine:
    def __init__(self):
        self.host = "https://clob.polymarket.com"
        self.chain_id = 137
        self.pk = os.getenv("POLYGON_PRIVATE_KEY")
        self.builder_code = os.getenv("BUILDER_CODE", "")

        if not self.pk:
            raise ValueError("Erreur : POLYGON_PRIVATE_KEY non défini dans le fichier .env")

        self.client = ClobClient(
            host=self.host,
            key=self.pk,
            chain_id=self.chain_id
        )

    def get_sampling_markets(self):
        """Récupère les marchés actifs directement via le SDK CLOB."""
        return self.client.get_sampling_markets()

    def get_order_book(self, token_id: str):
        """Récupère le carnet d'ordres pour un asset donné."""
        return self.client.get_order_book(token_id)

    def place_limit_order(self, token_id: str, price: float, size: float, side: str = "BUY"):
        order_side = BUY if side.upper() == "BUY" else SELL
        order_args = OrderArgs(price=price, size=size, side=order_side, token_id=token_id)
        signed_order = self.client.create_order(order_args)
        return self.client.post_order(signed_order, OrderType.GTC)

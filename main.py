import os
import sys
from dotenv import load_dotenv

load_dotenv()

from src.client import PolymarketEngine
from src.market import GammaMarketScanner

def run_demo():
    print("=== PolyTrade Engine CLI ===")
    print("1. Initialisation du moteur CLOB...")
    try:
        engine = PolymarketEngine()
        print("[OK] Client Polymarket CLOB initialisé avec succès.")
    except Exception as e:
        print(f"[ERREUR] Échec de l'initialisation : {e}")
        sys.exit(1)

    print("\n2. Scan des marchés chauds via Gamma API...")
    try:
        markets = GammaMarketScanner.get_active_markets(limit=5)
        if not markets:
            print("Aucun marché retourné.")
            return

        for i, m in enumerate(markets):
            vol = float(m.get('volume24hr', 0) or 0)
            print(f"[{i+1}] {m.get('question')} (Vol 24h: ${vol:,.0f})")
    except Exception as e:
        print(f"[ERREUR] Scan Gamma : {e}")
        return

    choice = input("\nEntrez le numéro du marché pour inspecter les tokens (ou Entrée pour quitter) : ")
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(markets):
        print("Fin du script.")
        return

    selected = markets[int(choice) - 1]
    tokens = GammaMarketScanner.get_market_tokens(selected)
    print(f"\nMarché : {selected.get('question')}")
    print(f"Token YES ID : {tokens.get('YES')}")
    print(f"Token NO ID  : {tokens.get('NO')}")
    print("\n[SUCCÈS] Pipeline d'agrégation Gamma & CLOB validé avec succès !")

if __name__ == "__main__":
    run_demo()

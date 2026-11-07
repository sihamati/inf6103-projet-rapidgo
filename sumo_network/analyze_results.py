"""
Analyse les resultats d'une simulation (baseline ou attaque) et calcule les
KPI definis dans la proposition de projet :
  - Temps de trajet moyen de la flotte RapidGo (bout en bout sur le corridor)
  - Temps de trajet moyen du trafic general sur le corridor
  - Longueur moyenne et maximale des files d'attente sur les voies transversales
  - Temps d'arret moyen par vehicule (usagers normaux, hors corridor)

Usage (dans PowerShell, venv active, depuis le dossier sumo_network) :
    python analyze_results.py tripinfo_baseline.xml results_baseline_queues.csv
    python analyze_results.py tripinfo_attack1.xml  results_attack1_queues.csv
"""

import sys
import xml.etree.ElementTree as ET
import pandas as pd


CROSS_EDGES = ["E5", "-E5", "E6", "-E6", "E3", "-E3", "E4", "-E4"]
CORRIDOR_EDGES = ["E0", "E1", "E2"]


def load_tripinfo(path):
    """Parse le fichier tripinfo.xml genere par SUMO en DataFrame pandas."""
    tree = ET.parse(path)
    root = tree.getroot()

    rows = []
    for trip in root.findall("tripinfo"):
        departLane = trip.get("departLane", "")
        arrivalLane = trip.get("arrivalLane", "")
        rows.append({
            "id": trip.get("id"),
            "vType": trip.get("vType"),
            "depart": float(trip.get("depart")),
            "arrival": float(trip.get("arrival")),
            "duration": float(trip.get("duration")),       # temps de trajet total (s)
            "routeLength": float(trip.get("routeLength")),
            "waitingTime": float(trip.get("waitingTime")),  # temps totalement a l'arret (s)
            "timeLoss": float(trip.get("timeLoss")),        # perte de temps vs trajet ideal (s)
            "departEdge": departLane.rsplit("_", 1)[0] if departLane else "",
            "arrivalEdge": arrivalLane.rsplit("_", 1)[0] if arrivalLane else "",
        })
    return pd.DataFrame(rows)


def load_queues(path):
    return pd.read_csv(path)


def main():
    if len(sys.argv) != 3:
        print("Usage : python analyze_results.py <tripinfo.xml> <queues.csv>")
        sys.exit(1)

    tripinfo_path = sys.argv[1]
    queues_path = sys.argv[2]

    trips = load_tripinfo(tripinfo_path)
    queues = load_queues(queues_path)

    print("=" * 60)
    print(f"ANALYSE : {tripinfo_path}")
    print("=" * 60)

    # --- KPI 1 : Rentabilite operationnelle (temps de trajet RapidGo) ---
    rapidgo = trips[trips["vType"] == "rapidgo"]

    # Pour isoler dans le trafic "normal" uniquement les vehicules qui font le
    # MEME trajet que RapidGo (meme origine E0, meme destination E2), on
    # filtre directement par voie de depart/arrivee plutot que par une
    # estimation de distance (plus fiable : la longueur totale inclut les
    # segments internes des intersections, difficiles a estimer a l'avance).
    normal_all = trips[(trips["vType"] == "normal")]
    normal_corridor = normal_all[
        (normal_all["departEdge"] == "E0") & (normal_all["arrivalEdge"] == "E2")
    ]

    print("\n--- KPI 1 : Temps de trajet (corridor complet J0->J3) ---")
    if len(rapidgo) > 0:
        print(f"RapidGo              : n={len(rapidgo):4d}  "
              f"temps moyen={rapidgo['duration'].mean():.1f}s  "
              f"min={rapidgo['duration'].min():.1f}s  "
              f"max={rapidgo['duration'].max():.1f}s")
    else:
        print("RapidGo              : aucun vehicule arrive a destination")

    if len(normal_corridor) > 0:
        print(f"Trafic gen. (meme trajet): n={len(normal_corridor):4d}  "
              f"temps moyen={normal_corridor['duration'].mean():.1f}s")

    print(f"\n(Pour reference, TOUT le trafic 'normal' (incl. trajets transversaux "
          f"plus courts) : n={len(normal_all):4d}  "
          f"temps moyen={normal_all['duration'].mean():.1f}s)")

    # --- KPI 2 : Degradation du service public (files d'attente) ---
    print("\n--- KPI 2 : Files d'attente sur voies transversales ---")
    for edge in CROSS_EDGES:
        col = f"halting_{edge}"
        if col in queues.columns:
            print(f"{edge:6s} : moyenne={queues[col].mean():.2f}  "
                  f"maximum={queues[col].max()}")

    # --- KPI 3 : Temps d'arret par vehicule (usagers normaux) ---
    print("\n--- KPI 3 : Temps d'arret moyen (tous vehicules) ---")
    print(f"Tous vehicules : waitingTime moyen={trips['waitingTime'].mean():.1f}s  "
          f"timeLoss moyen={trips['timeLoss'].mean():.1f}s")
    if len(rapidgo) > 0:
        print(f"RapidGo seul   : waitingTime moyen={rapidgo['waitingTime'].mean():.1f}s")
    if len(normal_corridor) > 0:
        print(f"Normal corridor: waitingTime moyen={normal_corridor['waitingTime'].mean():.1f}s")

    # --- Sauvegarde d'un resume CSV pour le rapport ---
    summary = {
        "source_tripinfo": tripinfo_path,
        "rapidgo_n": len(rapidgo),
        "rapidgo_avg_duration_s": rapidgo["duration"].mean() if len(rapidgo) else None,
        "rapidgo_avg_waitingTime_s": rapidgo["waitingTime"].mean() if len(rapidgo) else None,
        "normal_corridor_n": len(normal_corridor),
        "normal_corridor_avg_duration_s": normal_corridor["duration"].mean() if len(normal_corridor) else None,
        "normal_corridor_avg_waitingTime_s": normal_corridor["waitingTime"].mean() if len(normal_corridor) else None,
        "all_avg_waitingTime_s": trips["waitingTime"].mean(),
        "all_avg_timeLoss_s": trips["timeLoss"].mean(),
    }
    for edge in CROSS_EDGES:
        col = f"halting_{edge}"
        if col in queues.columns:
            summary[f"queue_avg_{edge}"] = queues[col].mean()
            summary[f"queue_max_{edge}"] = queues[col].max()

    out_name = tripinfo_path.replace(".xml", "_summary.csv")
    pd.DataFrame([summary]).to_csv(out_name, index=False)
    print(f"\nResume sauvegarde dans {out_name}")


if __name__ == "__main__":
    main()
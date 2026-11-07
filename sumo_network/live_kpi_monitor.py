"""
Calcule les KPI EN TEMPS REEL pendant que la simulation tourne, en
surveillant le fichier CSV que bridge_modbus_traci.py ecrit EN CONTINU
(ligne par ligne, au fur et a mesure). Ce script est independant de TraCI
(il ne fait que lire un fichier texte qui grossit) -- il peut donc tourner
dans un terminal separe, EN PARALLELE du pont et de l'attaquant, sans
conflit (TraCI n'accepte qu'une seule connexion a la fois, donc cette
approche par fichier est la facon correcte d'obtenir un "2e point de vue"
en direct).

A chaque nouvelle ligne detectee dans le CSV, le script recalcule et
affiche :
  - la moyenne et le maximum des files d'attente transversales, separement
    pour la periode BASELINE et la periode ATTAQUE (colonne attack_active)
  - la vitesse moyenne du corridor, separement baseline/attaque
  - le ratio d'augmentation de la file d'attente (attaque vs baseline)

Usage (dans PowerShell, venv active, depuis le dossier sumo_network,
PENDANT que bridge_modbus_traci.py tourne dans un autre terminal) :
    python live_kpi_monitor.py results_live_queues.csv
"""

import sys
import time
import csv

CROSS_EDGES = ["E5", "-E5", "E6", "-E6", "E3", "-E3", "E4", "-E4"]
REFRESH_INTERVAL_SECONDS = 5  # a quelle frequence (temps reel, pas simule) on recalcule l'affichage


def read_all_rows(path):
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except (FileNotFoundError, PermissionError):
        return []


def compute_kpis(rows):
    baseline_rows = [r for r in rows if r.get("attack_active") == "0"]
    attack_rows = [r for r in rows if r.get("attack_active") == "1"]

    def avg_queue(subset):
        if not subset:
            return 0.0, 0
        totals = []
        maxes = []
        for r in subset:
            vals = [int(r[f"halting_{e}"]) for e in CROSS_EDGES if f"halting_{e}" in r]
            if vals:
                totals.append(sum(vals) / len(vals))
                maxes.append(max(vals))
        return (sum(totals) / len(totals) if totals else 0.0,
                max(maxes) if maxes else 0)

    def avg_numeric(subset, column):
        values = []
        for r in subset:
            val = r.get(column, "")
            if val not in ("", None):
                try:
                    values.append(float(val))
                except ValueError:
                    pass
        return sum(values) / len(values) if values else None

    base_avg_q, base_max_q = avg_queue(baseline_rows)
    atk_avg_q, atk_max_q = avg_queue(attack_rows)

    return {
        "n_baseline": len(baseline_rows),
        "n_attack": len(attack_rows),
        "baseline_avg_queue": base_avg_q,
        "baseline_max_queue": base_max_q,
        "baseline_rapidgo_wait": avg_numeric(baseline_rows, "rapidgo_wait_avg"),
        "baseline_normal_wait": avg_numeric(baseline_rows, "normal_wait_avg"),
        "attack_avg_queue": atk_avg_q,
        "attack_max_queue": atk_max_q,
        "attack_rapidgo_wait": avg_numeric(attack_rows, "rapidgo_wait_avg"),
        "attack_normal_wait": avg_numeric(attack_rows, "normal_wait_avg"),
    }


def main():
    if len(sys.argv) != 2:
        print("Usage : python live_kpi_monitor.py <results_queues.csv>")
        sys.exit(1)

    csv_path = sys.argv[1]
    print(f"=== Moniteur de KPI en temps reel -- surveille {csv_path} ===")
    print("(Ctrl+C pour arreter. N'affecte pas la simulation en cours.)\n")

    last_row_count = -1

    try:
        while True:
            rows = read_all_rows(csv_path)

            if len(rows) != last_row_count:
                kpis = compute_kpis(rows)

                def fmt(v):
                    return f"{v:.2f}s" if v is not None else "n/a"

                print(f"--- t_reel={time.strftime('%H:%M:%S')} | "
                      f"{len(rows)} pas de temps simules lus ---")
                print(f"  BASELINE (n={kpis['n_baseline']:5d}) : "
                      f"file moy={kpis['baseline_avg_queue']:.2f}  "
                      f"file max={kpis['baseline_max_queue']}  "
                      f"attente RapidGo={fmt(kpis['baseline_rapidgo_wait'])}   "
                      f"attente Normal={fmt(kpis['baseline_normal_wait'])}")
                print(f"  ATTAQUE  (n={kpis['n_attack']:5d}) : "
                      f"file moy={kpis['attack_avg_queue']:.2f}  "
                      f"file max={kpis['attack_max_queue']}  "
                      f"attente RapidGo={fmt(kpis['attack_rapidgo_wait'])}   "
                      f"attente Normal={fmt(kpis['attack_normal_wait'])}")

                if kpis["n_attack"] > 0 and kpis["baseline_avg_queue"] > 0:
                    ratio = kpis["attack_avg_queue"] / kpis["baseline_avg_queue"]
                    print(f"  >>> Augmentation de la file moyenne sous attaque : "
                          f"x{ratio:.2f}")
                if (kpis["baseline_rapidgo_wait"] not in (None, 0)
                        and kpis["attack_rapidgo_wait"] is not None):
                    reduction = (1 - kpis["attack_rapidgo_wait"] / kpis["baseline_rapidgo_wait"]) * 100
                    print(f"  >>> Reduction du temps d'attente RapidGo sous attaque : {reduction:+.1f}%")
                if (kpis["baseline_normal_wait"] not in (None, 0)
                        and kpis["attack_normal_wait"] is not None):
                    change_normal = (kpis["attack_normal_wait"] / kpis["baseline_normal_wait"] - 1) * 100
                    print(f"  >>> Variation du temps d'attente Normal sous attaque : {change_normal:+.1f}%")
                print()
                last_row_count = len(rows)

            time.sleep(REFRESH_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nMoniteur arrete.")


if __name__ == "__main__":
    main()
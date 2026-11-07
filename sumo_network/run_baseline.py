"""
Lance la simulation SUMO baseline (programme legitime, sans attaque) et
enregistre deux choses :
  1. tripinfo_baseline.xml -> genere nativement par SUMO : duree de trajet,
     temps d'arret, perte de temps, etc. pour CHAQUE vehicule.
  2. results_baseline_queues.csv -> genere via TraCI, nombre de vehicules a
     l'arret sur chaque branche transversale, a CHAQUE pas de temps.

Usage (dans PowerShell, venv active, depuis le dossier sumo_network) :
    python run_baseline.py
"""

import os
import sys
import csv

# --- Verification que SUMO_HOME est bien configure pour trouver traci ---
if "SUMO_HOME" in os.environ:
    tools = os.path.join(os.environ["SUMO_HOME"], "tools")
    sys.path.append(tools)
else:
    sys.exit("Erreur : la variable d'environnement SUMO_HOME n'est pas definie.")

import traci  # noqa: E402

# --- Configuration ---
SUMO_BINARY = "sumo"  # pas d'interface graphique -> execution rapide. Mettre "sumo-gui" pour observer.
CONFIG_FILE = "simulation.sumocfg"
TRIPINFO_OUTPUT = "tripinfo_baseline.xml"
QUEUE_OUTPUT_CSV = "results_baseline_queues.csv"

# Branches transversales (trafic non privilegie) a surveiller
CROSS_EDGES = ["E5", "-E5", "E6", "-E6", "E3", "-E3", "E4", "-E4"]
# Corridor principal (flotte RapidGo + trafic general)
CORRIDOR_EDGES = ["E0", "E1", "E2"]


def run():
    sumo_cmd = [
        SUMO_BINARY,
        "-c", CONFIG_FILE,
        "--tripinfo-output", TRIPINFO_OUTPUT,
        "--no-step-log", "true",
        "--duration-log.statistics", "true",
    ]

    print("Demarrage de la simulation baseline...")
    traci.start(sumo_cmd)

    queue_rows = []
    step = 0

    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()

        row = {"time": step}
        for edge in CROSS_EDGES:
            row[f"halting_{edge}"] = traci.edge.getLastStepHaltingNumber(edge)
        for edge in CORRIDOR_EDGES:
            row[f"halting_{edge}"] = traci.edge.getLastStepHaltingNumber(edge)

        queue_rows.append(row)
        step += 1

    traci.close()
    print(f"Simulation terminee apres {step} pas de temps.")

    # --- Sauvegarde du CSV des files d'attente ---
    if queue_rows:
        fieldnames = list(queue_rows[0].keys())
        with open(QUEUE_OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(queue_rows)
        print(f"Donnees de files d'attente sauvegardees dans {QUEUE_OUTPUT_CSV}")

    print(f"Donnees detaillees par vehicule sauvegardees dans {TRIPINFO_OUTPUT}")
    print("\nProchaine etape : lancez 'python analyze_results.py' pour calculer les KPI.")


if __name__ == "__main__":
    run()
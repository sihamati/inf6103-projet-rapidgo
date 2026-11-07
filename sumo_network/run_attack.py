"""
Lance une simulation avec un fichier .net.xml donne (baseline OU attaque) en
reutilisant le meme fichier de routes (routes.rou.xml). Enregistre les
memes KPI que run_baseline.py : tripinfo XML + CSV des files d'attente.

Usage (dans PowerShell, venv active, depuis le dossier sumo_network) :
    python run_attack.py reseau_attack1_program.net.xml tripinfo_attack1.xml results_attack1_queues.csv
    python run_attack.py reseau_attack2_param.net.xml   tripinfo_attack2.xml results_attack2_queues.csv
"""

import os
import sys
import csv

if "SUMO_HOME" in os.environ:
    tools = os.path.join(os.environ["SUMO_HOME"], "tools")
    sys.path.append(tools)
else:
    sys.exit("Erreur : la variable d'environnement SUMO_HOME n'est pas definie.")

import traci  # noqa: E402

SUMO_BINARY = "sumo"
ROUTE_FILE = "routes.rou.xml"

CROSS_EDGES = ["E5", "-E5", "E6", "-E6", "E3", "-E3", "E4", "-E4"]
CORRIDOR_EDGES = ["E0", "E1", "E2"]


def run(net_file, tripinfo_output, queue_output_csv):
    sumo_cmd = [
        SUMO_BINARY,
        "--net-file", net_file,
        "--route-files", ROUTE_FILE,
        "--tripinfo-output", tripinfo_output,
        "--no-step-log", "true",
        "--duration-log.statistics", "true",
        "--begin", "0",
        "--end", "3600",
    ]

    print(f"Demarrage de la simulation avec le reseau : {net_file}")
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

    if queue_rows:
        fieldnames = list(queue_rows[0].keys())
        with open(queue_output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(queue_rows)
        print(f"Donnees de files d'attente sauvegardees dans {queue_output_csv}")

    print(f"Donnees detaillees par vehicule sauvegardees dans {tripinfo_output}")
    print(f"\nProchaine etape : python analyze_results.py {tripinfo_output} {queue_output_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage : python run_attack.py <net_file.xml> <tripinfo_output.xml> <queue_output.csv>")
        sys.exit(1)

    run(sys.argv[1], sys.argv[2], sys.argv[3])
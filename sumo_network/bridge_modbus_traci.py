"""
Pont Modbus <-> TraCI. Fait le lien en temps reel entre le "serveur PLC"
(plc_server.py, qui expose les durees de phase via Modbus TCP) et la
simulation SUMO (via TraCI). A chaque intervalle de verification, le pont
relit les registres Modbus et reconstruit le programme de feu reel dans
SUMO avec les valeurs courantes -- donc si quelqu'un modifie les registres
pendant que la simulation tourne (voir attacker_client.py), le changement
se repercute en direct sur le trafic simule.

IMPORTANT : lancez d'abord plc_server.py dans un AUTRE terminal, et
laissez-le tourner, avant de lancer ce script.

Usage (dans PowerShell, venv active, depuis le dossier sumo_network,
APRES avoir demarre plc_server.py dans un autre terminal) :
    python bridge_modbus_traci.py tripinfo_live.xml results_live_queues.csv
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
from pymodbus.client import ModbusTcpClient  # noqa: E402

# --- Configuration ---
SUMO_BINARY = "sumo-gui"  # mettre "sumo" (sans -gui) pour aller plus vite sans affichage
NET_FILE = "reseau.net.xml"
ROUTE_FILE = "routes.rou.xml"

MODBUS_HOST = "127.0.0.1"
MODBUS_PORT = 5020

POLL_INTERVAL_STEPS = 50  # relit les registres Modbus toutes les 50 secondes simulees

CROSS_EDGES = ["E5", "-E5", "E6", "-E6", "E3", "-E3", "E4", "-E4"]
CORRIDOR_EDGES = ["E0", "E1", "E2"]

# Index des phases CORRIDOR dans le programme tlLogic genere par netedit
# (determine en inspectant reseau.net.xml -- voir create_attack_nets.py)
J1_PHASE_INDEX = {"corridor": 4, "autreA": 0, "autreB": 2}
J2_PHASE_INDEX = {"corridor": 2, "autre": 0}


def read_plc_registers(client):
    """Lit les 5 registres du PLC. Retourne None en cas d'echec de lecture."""
    # Le nom du parametre d'identifiant d'esclave Modbus a change selon les
    # versions de pymodbus ("slave" -> "device_id" dans les versions
    # recentes). On essaie les deux pour rester compatible.
    # Note d'adressage : ModbusSequentialDataBlock(1, ...) cote serveur utilise
    # une adresse "humaine" 1-based, mais stocke les valeurs a partir de
    # l'index interne 0. Le client doit donc lire a l'adresse 0 (convention
    # Modbus PDU standard, 0-based) pour obtenir le premier registre.
    try:
        result = client.read_holding_registers(address=0, count=5, device_id=1)
    except TypeError:
        try:
            result = client.read_holding_registers(address=0, count=5, slave=1)
        except Exception as e:
            print(f"[Pont] Erreur de lecture Modbus : {e}")
            return None
    except Exception as e:
        print(f"[Pont] Erreur de lecture Modbus : {e}")
        return None

    if result.isError():
        print(f"[Pont] Reponse Modbus invalide : {result}")
        return None

    return result.registers  # [J1_corridor, J1_autreA, J1_autreB, J2_corridor, J2_autre]


def apply_durations_to_tls(tls_id, phase_index_map, new_values):
    """Reconstruit le programme de feu de tls_id avec les nouvelles durees,
    en conservant les etats (state strings) d'origine -- seule la duree
    change, exactement comme le ferait un PLC qui applique une nouvelle
    configuration recue par Modbus."""
    logics = traci.trafficlight.getAllProgramLogics(tls_id)
    logic = logics[0]  # un seul programme (programID "0") pour nos feux

    new_phases = []
    for idx, phase in enumerate(logic.phases):
        duration = phase.duration
        for key, phase_idx in phase_index_map.items():
            if idx == phase_idx:
                duration = new_values[key]
        new_phases.append(
            traci.trafficlight.Phase(duration, phase.state, phase.minDur, phase.maxDur)
        )

    new_logic = traci.trafficlight.Logic(
        logic.programID, logic.type, logic.currentPhaseIndex, new_phases
    )
    traci.trafficlight.setProgramLogic(tls_id, new_logic)


def run(tripinfo_output, queue_output_csv):
    # --- Connexion au "PLC" ---
    client = ModbusTcpClient(MODBUS_HOST, port=MODBUS_PORT)
    if not client.connect():
        sys.exit(f"Impossible de se connecter au serveur PLC sur {MODBUS_HOST}:{MODBUS_PORT}.\n"
                  f"Avez-vous bien lance plc_server.py dans un autre terminal ?")
    print(f"[Pont] Connecte au serveur PLC sur {MODBUS_HOST}:{MODBUS_PORT}")

    # --- Demarrage de SUMO ---
    sumo_cmd = [
        SUMO_BINARY,
        "--net-file", NET_FILE,
        "--route-files", ROUTE_FILE,
        "--tripinfo-output", tripinfo_output,
        "--no-step-log", "true",
        "--begin", "0",
        "--end", "3600",
    ]
    traci.start(sumo_cmd)
    print("[Pont] Simulation SUMO demarree.")

    queue_rows = []
    step = 0
    last_values = None

    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()

        if step % POLL_INTERVAL_STEPS == 0:
            registers = read_plc_registers(client)
            if registers and registers != last_values:
                print(f"[Pont] t={step}s -- Nouvelles valeurs recues du PLC : {registers}")
                j1_values = {
                    "corridor": registers[0],
                    "autreA": registers[1],
                    "autreB": registers[2],
                }
                j2_values = {"corridor": registers[3], "autre": registers[4]}
                apply_durations_to_tls("J1", J1_PHASE_INDEX, j1_values)
                apply_durations_to_tls("J2", J2_PHASE_INDEX, j2_values)
                last_values = registers

        row = {"time": step}
        for edge in CROSS_EDGES:
            row[f"halting_{edge}"] = traci.edge.getLastStepHaltingNumber(edge)
        for edge in CORRIDOR_EDGES:
            row[f"halting_{edge}"] = traci.edge.getLastStepHaltingNumber(edge)
        queue_rows.append(row)

        step += 1

    traci.close()
    client.close()
    print(f"[Pont] Simulation terminee apres {step} pas de temps.")

    if queue_rows:
        fieldnames = list(queue_rows[0].keys())
        with open(queue_output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(queue_rows)
        print(f"[Pont] Donnees de files d'attente sauvegardees dans {queue_output_csv}")

    print(f"[Pont] Donnees detaillees par vehicule sauvegardees dans {tripinfo_output}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage : python bridge_modbus_traci.py <tripinfo_output.xml> <queue_output.csv>")
        sys.exit(1)

    run(sys.argv[1], sys.argv[2])
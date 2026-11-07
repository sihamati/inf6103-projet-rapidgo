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

POLL_INTERVAL_STEPS = 10  # relit les registres Modbus toutes les 10 secondes simulees
LIVE_STATS_INTERVAL_STEPS = 10  # affiche un tableau de bord -- MEME intervalle que POLL_INTERVAL_STEPS,
                                  # pour que le tableau de bord n'affiche jamais une valeur perimee

BASELINE_VALUES = [27, 27, 27, 42, 42]

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


REGISTER_LABELS = ["J1 CORRIDOR", "J1 autreA", "J1 autreB", "J2 CORRIDOR", "J2 autre"]


def print_register_status(step, last_values):
    """Affiche uniquement l'etat des registres Modbus du PLC (pas de KPI de
    trafic ici -- voir live_kpi_monitor.py, lance dans un terminal separe,
    pour le suivi des KPI en temps reel)."""
    etat = "BASELINE (programme legitime)"
    if last_values is not None and list(last_values) != BASELINE_VALUES:
        etat = "*** ATTAQUE ACTIVE ***"

    valeurs = ", ".join(f"{label}={val}" for label, val in zip(REGISTER_LABELS, last_values or []))
    print(f"[Registres] t={step:5d}s | {etat} | {valeurs}")


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

    # Avertissement : le serveur PLC tourne en continu (Terminal A) et garde
    # en memoire la DERNIERE valeur ecrite par une attaque precedente, meme
    # apres le redemarrage du pont. Si les valeurs lues au demarrage ne sont
    # pas le baseline [27, 27, 27, 42, 42], ce n'est pas un bug -- c'est
    # l'etat reel et persistant du PLC. Pour repartir d'un vrai baseline,
    # executez "python attacker_client.py restore" AVANT de relancer ce pont.
    initial_registers = read_plc_registers(client)
    if initial_registers is not None and list(initial_registers) != BASELINE_VALUES:
        print(f"[Pont] ATTENTION : le PLC ne contient PAS les valeurs baseline actuellement.")
        print(f"[Pont]            Valeurs actuelles du PLC : {initial_registers}")
        print(f"[Pont]            (Pour repartir du baseline, lancez dans un autre terminal : "
              f"python attacker_client.py restore, PUIS relancez ce script.)")

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

    # Supprime un ancien fichier de meme nom pour repartir sur un CSV propre
    # (sinon l'ecriture incrementale ci-dessous s'ajouterait a un fichier
    # d'une execution precedente, potentiellement avec des colonnes differentes).
    if os.path.exists(queue_output_csv):
        os.remove(queue_output_csv)

    step = 0
    last_values = None

    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()

        if step % POLL_INTERVAL_STEPS == 0:
            # Lecture FRAICHE des registres a chaque intervalle -- cette
            # meme valeur sert A LA FOIS a appliquer un changement eventuel
            # ET a l'affichage du tableau de bord juste en dessous, pour
            # garantir qu'on affiche toujours l'etat REEL et actuel du PLC,
            # jamais une valeur en retard (perimee).
            registers = read_plc_registers(client)
            if registers is not None:
                if registers != last_values:
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

            print_register_status(step, last_values)

        row = {"time": step}
        for edge in CROSS_EDGES:
            row[f"halting_{edge}"] = traci.edge.getLastStepHaltingNumber(edge)
        for edge in CORRIDOR_EDGES:
            row[f"halting_{edge}"] = traci.edge.getLastStepHaltingNumber(edge)
        corridor_speeds = [traci.edge.getLastStepMeanSpeed(e) for e in CORRIDOR_EDGES]
        row["corridor_speed_avg"] = sum(corridor_speeds) / len(corridor_speeds) if corridor_speeds else 0

        # Temps d'attente moyen SEPARE par type de vehicule (rapidgo vs
        # normal), uniquement sur le corridor (seul axe emprunte par
        # RapidGo), pour comparer leur attente respective avant/apres
        # l'attaque. getWaitingTime() donne le temps (s) depuis lequel le
        # vehicule roule a moins de 0.1 m/s (donc "arrete dans la file").
        # On doit faire ce calcul ici (dans le pont) car seule la connexion
        # TraCI active a acces au type de chaque vehicule individuel.
        rapidgo_waits = []
        normal_waits = []
        for edge in CORRIDOR_EDGES:
            for veh_id in traci.edge.getLastStepVehicleIDs(edge):
                v_type = traci.vehicle.getTypeID(veh_id)
                v_wait = traci.vehicle.getWaitingTime(veh_id)
                if v_type == "rapidgo":
                    rapidgo_waits.append(v_wait)
                elif v_type == "normal":
                    normal_waits.append(v_wait)

        row["rapidgo_wait_avg"] = sum(rapidgo_waits) / len(rapidgo_waits) if rapidgo_waits else ""
        row["normal_wait_avg"] = sum(normal_waits) / len(normal_waits) if normal_waits else ""
        # Marqueur simple pour qu'un script externe (ex. live_kpi_monitor.py)
        # puisse distinguer baseline vs attaque directement depuis le CSV,
        # sans avoir besoin d'une 2e connexion TraCI (non supportee par
        # defaut -- un seul client TraCI a la fois).
        row["attack_active"] = 0 if (last_values is None or list(last_values) == BASELINE_VALUES) else 1

        # Ecriture incrementale du CSV (append) pour qu'un script externe
        # puisse le lire EN DIRECT pendant que la simulation tourne, plutot
        # que d'attendre la fin (ou tout le fichier n'est ecrit qu'a la fin).
        write_header = not os.path.exists(queue_output_csv)
        with open(queue_output_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            if write_header:
                writer.writeheader()
            writer.writerow(row)

        step += 1

    traci.close()
    client.close()
    print(f"[Pont] Simulation terminee apres {step} pas de temps.")
    print(f"[Pont] Donnees de files d'attente (ecrites en continu) dans {queue_output_csv}")
    print(f"[Pont] Donnees detaillees par vehicule sauvegardees dans {tripinfo_output}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage : python bridge_modbus_traci.py <tripinfo_output.xml> <queue_output.csv>")
        sys.exit(1)

    run(sys.argv[1], sys.argv[2])
"""
Simule le controleur PLC (automate programmable) qui gere les feux de
circulation, via un serveur Modbus TCP (Pymodbus). C'est la cible de
l'attaque : en conditions normales, son programme legitime applique les
durees de phase de reference (baseline). Un attaquant qui ecrit dans ses
registres peut modifier ces durees sans authentification -- exactement la
vulnerabilite decrite dans la proposition de projet (protocole Modbus en
texte clair, sans authentification).

Table des registres (holding registers, fonction Modbus 03/06/16) :
    Registre 0 : duree de la phase CORRIDOR a J1 (secondes)
    Registre 1 : duree de la phase "autre A" a J1 (secondes)
    Registre 2 : duree de la phase "autre B" a J1 (secondes)
    Registre 3 : duree de la phase CORRIDOR a J2 (secondes)
    Registre 4 : duree de la phase "autre" a J2 (secondes)

Usage (dans PowerShell, venv active, depuis le dossier sumo_network) :
    python plc_server.py
Laissez cette fenetre ouverte -- c'est le "serveur PLC" qui tourne en
continu. Ouvrez un AUTRE terminal pour lancer le pont TraCI ou l'attaquant.
"""

import logging
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext

# Pymodbus a renomme ModbusSlaveContext en ModbusDeviceContext dans les
# versions recentes (3.8+). On gere les deux pour compatibilite.
try:
    from pymodbus.datastore import ModbusDeviceContext as ModbusSlaveContext
except ImportError:
    from pymodbus.datastore import ModbusSlaveContext

logging.basicConfig(level=logging.INFO)

# --- Valeurs de reference (programme legitime / baseline) ---
# [J1_corridor, J1_autreA, J1_autreB, J2_corridor, J2_autre]
BASELINE_VALUES = [27, 27, 27, 42, 42]

HOST = "127.0.0.1"
PORT = 5020  # port Modbus TCP non-privilegie (le port standard 502 exige des droits admin sous Windows)


def build_context():
    # Pymodbus 3.16+ exige une adresse de depart >= 1 pour
    # ModbusSequentialDataBlock (indexation a partir de 1). On utilise donc
    # l'adresse 1 comme premier registre, de facon coherente avec le pont
    # et le client attaquant (voir bridge_modbus_traci.py / attacker_client.py).
    holding_registers = ModbusSequentialDataBlock(1, BASELINE_VALUES)
    slave_context = ModbusSlaveContext(hr=holding_registers)
    # Le parametre a aussi ete renomme "slaves" -> "devices" dans les
    # versions recentes de pymodbus. On essaie les deux.
    try:
        return ModbusServerContext(devices=slave_context, single=True)
    except TypeError:
        return ModbusServerContext(slaves=slave_context, single=True)


def main():
    context = build_context()
    print(f"=== Serveur PLC (Modbus TCP) demarre sur {HOST}:{PORT} ===")
    print(f"Valeurs initiales (programme legitime) : {BASELINE_VALUES}")
    print("    Registre 0 = J1 CORRIDOR, 1 = J1 autreA, 2 = J1 autreB, "
          "3 = J2 CORRIDOR, 4 = J2 autre")
    print("Ce serveur tourne en continu. Fermez cette fenetre (Ctrl+C) pour l'arreter.")
    print()

    StartTcpServer(context=context, address=(HOST, PORT))


if __name__ == "__main__":
    main()
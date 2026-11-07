"""
Genere les 2 reseaux altere a partir du reseau baseline (reseau.net.xml) :

  1. reseau_attack2_param.net.xml  (Experience 2 - T0836, Modify Parameter)
     Les phases de feu restent les memes (meme nombre, meme ordre), seules
     les DUREES changent : plus de vert pour le corridor RapidGo (E0->E1 a
     J1, E1->E2 a J2), moins de vert pour les mouvements transversaux.

  2. reseau_attack1_program.net.xml (Experience 1 - T0889, Modify Program)
     La LOGIQUE elle-meme est modifiee : en plus d'augmenter le vert du
     corridor, on SUPPRIME une phase complete (vert + jaune) dediee a un
     mouvement transversal a l'intersection J1. Ce n'est plus seulement un
     ajustement de parametre, mais un changement structurel du programme.

Usage (dans PowerShell, venv active, depuis le dossier sumo_network) :
    python create_attack_nets.py
"""

import xml.etree.ElementTree as ET
import copy

SOURCE_NET = "reseau.net.xml"


def load_net(path):
    tree = ET.parse(path)
    return tree, tree.getroot()


def find_tllogic(root, tl_id):
    for tl in root.findall("tlLogic"):
        if tl.get("id") == tl_id:
            return tl
    raise ValueError(f"tlLogic '{tl_id}' introuvable dans {SOURCE_NET}")


def set_phase_duration(tllogic, phase_index, new_duration):
    """phase_index : position 0-based dans la liste des <phase> de ce tlLogic."""
    phases = tllogic.findall("phase")
    phases[phase_index].set("duration", str(new_duration))


def build_parameter_attack():
    """Experience 2 (T0836) : seules les durees changent."""
    tree, root = load_net(SOURCE_NET)

    # --- J1 : phases [0]=autre A (27s), [2]=autre B (27s), [4]=CORRIDOR (27s) ---
    j1 = find_tllogic(root, "J1")
    set_phase_duration(j1, 0, 12)   # autre A : 27 -> 12
    set_phase_duration(j1, 2, 12)   # autre B : 27 -> 12
    set_phase_duration(j1, 4, 55)   # CORRIDOR : 27 -> 55

    # --- J2 : phases [0]=autre (42s), [2]=CORRIDOR (42s) ---
    j2 = find_tllogic(root, "J2")
    set_phase_duration(j2, 0, 18)   # autre : 42 -> 18
    set_phase_duration(j2, 2, 70)   # CORRIDOR : 42 -> 70

    out_path = "reseau_attack2_param.net.xml"
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)
    print(f"[T0836] Reseau genere : {out_path}")
    print("        J1 : autre A=12s, autre B=12s, CORRIDOR=55s (vs 27/27/27 baseline)")
    print("        J2 : autre=18s, CORRIDOR=70s (vs 42/42 baseline)")


def build_program_attack():
    """Experience 1 (T0889) : la logique elle-meme change (suppression
    d'une phase complete a J1), en plus d'augmenter le vert du corridor."""
    tree, root = load_net(SOURCE_NET)

    j1 = find_tllogic(root, "J1")
    phases = j1.findall("phase")

    # On garde une trace du nombre de phases avant modification
    n_before = len(phases)

    # Supprime la toute premiere paire vert+jaune (phases 0 et 1), qui
    # desservait un mouvement transversal. C'est un changement de la
    # STRUCTURE du programme (le nombre et l'ordre des phases change),
    # pas seulement un parametre numerique.
    j1.remove(phases[0])  # vert "autre A"
    # Apres suppression du 1er element, le jaune qui suivait est maintenant
    # a l'index 0 de la liste restante
    phases_apres = j1.findall("phase")
    j1.remove(phases_apres[0])  # jaune correspondant

    n_after = len(j1.findall("phase"))
    print(f"[T0889] J1 : {n_before} phases -> {n_after} phases "
          f"(suppression complete d'un mouvement transversal)")

    # On augmente aussi fortement le vert du corridor restant (qui est
    # maintenant a un index different puisque 2 phases ont ete retirees)
    phases_restantes = j1.findall("phase")
    # Les phases restantes, dans l'ordre original, etaient :
    #   [2]=autre B (27s), [3]=jaune, [4]=CORRIDOR (27s), [5]=jaune
    # Apres suppression de [0] et [1], elles deviennent les index [0..3]
    set_phase_duration(j1, 0, 15)   # autre B : 27 -> 15 (reste en place)
    set_phase_duration(j1, 2, 60)   # CORRIDOR : 27 -> 60

    # J2 : on applique le meme changement de parametres que l'experience 2
    # (le scenario pourrait aussi modifier le programme de J2, mais pour
    # rester lisible on se concentre la structure sur J1 uniquement et on
    # ajuste J2 par parametre, ce qui est documente comme tel dans le rapport)
    j2 = find_tllogic(root, "J2")
    set_phase_duration(j2, 0, 18)
    set_phase_duration(j2, 2, 70)

    out_path = "reseau_attack1_program.net.xml"
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)
    print(f"[T0889] Reseau genere : {out_path}")


if __name__ == "__main__":
    build_parameter_attack()
    print()
    build_program_attack()
    print("\nTermine. Deux nouveaux fichiers .net.xml sont prets pour les simulations d'attaque.")
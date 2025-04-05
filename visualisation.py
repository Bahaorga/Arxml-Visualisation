from graphviz import Digraph
import requests
import json
from collections import defaultdict


def fetch_arxml_data(file_path):
    """Télécharge et traite le fichier ARXML via l'API"""
    with open(file_path, 'rb') as f:
        files = {'file': f}
        response = requests.post(API_URL, files=files)
        return response.json()


def create_autosar_graph(data):
    """Crée un graphique AUTOSAR avancé avec les spécifications fournies"""
    graph = Digraph('G', filename='autosar_advanced.gv',
                    engine='dot',
                    node_attr={'fontname': 'Arial', 'fontsize': '10'})

    # Configuration globale
    graph.attr(compound='true', rankdir='TB', splines='ortho')
    graph.attr(label='<<b>Composition AUTOSAR - HvDisE</b>>', labelloc='t', fontsize='16')

    # Styles prédéfinis
    styles = {
        'composition': {'shape': 'rectangle', 'style': 'filled,dashed', 'fillcolor': 'lightgrey'},
        'swc': {'shape': 'rectangle', 'style': 'filled,rounded', 'fillcolor': 'lightblue'},
        'p_port': {'shape': 'triangle', 'color': 'darkgreen', 'fillcolor': 'green', 'style': 'filled'},
        'r_port': {'shape': 'invtriangle', 'color': 'darkred', 'fillcolor': 'red', 'style': 'filled'},
        'interface_sr': {'shape': 'ellipse', 'color': 'orange', 'fillcolor': 'moccasin'},
        'interface_cs': {'shape': 'ellipse', 'color': 'purple', 'fillcolor': 'thistle'},
        'delegation': {'style': 'dashed', 'color': 'blue', 'arrowhead': 'open'}
    }

    # 1. Créer la composition parente
    with graph.subgraph(name='cluster_composition') as comp:
        comp.attr(**styles['composition'])
        comp.attr(label='XYZ_CPS_HvDisE (Composition)')

        # 2. Ajouter les SWCs
        swc_clusters = {}
        for swc_name, swc_data in data['swcs'].items():
            with comp.subgraph(name=f'cluster_{swc_name}') as swc_cluster:
                swc_cluster.attr(**styles['swc'])
                swc_cluster.attr(label=f'{swc_name}\nType: {swc_data["type"]}')

                # Ports P à droite, Ports R à gauche
                with swc_cluster.subgraph(name=f'ports_{swc_name}') as ports:
                    ports.attr(rank='same')

                    # P-Ports (droite)
                    for port_name, port_data in swc_data['ports'].items():
                        if port_data['type'] == 'P-Port':
                            ports.node(f'{swc_name}:{port_name}', port_name,
                                       **styles['p_port'], xlabel='P-Port')

                    # R-Ports (gauche)
                    for port_name, port_data in swc_data['ports'].items():
                        if port_data['type'] == 'R-Port':
                            ports.node(f'{swc_name}:{port_name}', port_name,
                                       **styles['r_port'], xlabel='R-Port')

                swc_clusters[swc_name] = swc_cluster

        # 3. Gérer les connecteurs (connexions entre SWCs)
        interface_nodes = set()
        for swc_name, swc_data in data['swcs'].items():
            for port_name, port_data in swc_data['ports'].items():
                full_port_name = f'{swc_name}:{port_name}'

                for conn in port_data['connections']:
                    target_port = f'{conn["target_swc"]}:{conn["target_port"]}'
                    source_port = f'{conn["source_swc"]}:{conn["source_port"]}' if 'source_swc' in conn else None

                    if port_data['type'] == 'P-Port':
                        # Vérifier si une interface est impliquée
                        if port_data.get('interface_type'):
                            interface_name = f'int_{port_name}_{conn["target_port"]}'
                            interface_style = styles['interface_sr'] if port_data[
                                                                            'interface_type'] == 'Sender-Receiver' else \
                            styles['interface_cs']

                            graph.node(interface_name,
                                       label=f'{port_data["interface_type"]}\n{port_name}',
                                       **interface_style)

                            graph.edge(full_port_name, interface_name)
                            graph.edge(interface_name, target_port)
                            interface_nodes.add(interface_name)
                        else:
                            # Connexion directe P-Port vers R-Port
                            graph.edge(full_port_name, target_port)

        # 4. Gérer les délégations
        delegation_ports = set()
        for swc_name, swc_data in data['swcs'].items():
            for delegation in swc_data['delegations']:
                inner_port = f'{swc_name}:{delegation["inner_port"]}'
                outer_port = delegation['outer_port']

                # Créer le port de délégation externe
                graph.node(outer_port, outer_port,
                           shape='diamond' if delegation['type'] == 'P-Port' else 'invdiamond',
                           color='blue', style='filled', fillcolor='lightblue')

                # Connecter avec style de délégation
                if delegation['type'] == 'P-Port':
                    graph.edge(inner_port, outer_port,
                               label=f"Délégation P-Port\n({delegation['composition']})",
                               **styles['delegation'])
                else:
                    graph.edge(outer_port, inner_port,
                               label=f"Délégation R-Port\n({delegation['composition']})",
                               **styles['delegation'])

                delegation_ports.add(outer_port)

    # 5. Organisation du layout
    # - Les ports de délégation en haut
    # - La composition au centre
    # - Les interfaces entre les composants
    if delegation_ports:
        with graph.subgraph(name='cluster_delegations') as del_cluster:
            del_cluster.attr(label='Ports de Délégation', style='dashed')
            for port in delegation_ports:
                del_cluster.node(port)

    if interface_nodes:
        with graph.subgraph(name='cluster_interfaces') as int_cluster:
            int_cluster.attr(label='Interfaces', style='dotted')
            for interface in interface_nodes:
                int_cluster.node(interface)

    # 6. Ajouter une légende détaillée
    with graph.subgraph(name='cluster_legend') as legend:
        legend.attr(label='<<b>Légende</b>>', style='filled', color='lightgray', fontsize='12')

        # Composants
        legend.node('legend_comp', 'Composition', **styles['composition'])
        legend.node('legend_swc', 'SWC', **styles['swc'])

        # Ports
        legend.node('legend_pport', 'P-Port', **styles['p_port'])
        legend.node('legend_rport', 'R-Port', **styles['r_port'])

        # Interfaces
        legend.node('legend_sr', 'Sender-Receiver', **styles['interface_sr'])
        legend.node('legend_cs', 'Client-Server', **styles['interface_cs'])

        # Délégations
        legend.node('legend_deleg', 'Port délégué', shape='diamond', color='blue')
        legend.edge('legend_pport', 'legend_deleg', label='Délégation', **styles['delegation'])

        # Organisation en colonnes
        legend.attr(rank='same')
        legend.attr(nodesep='0.5')

    return graph


# Exemple d'utilisation
if __name__ == "__main__":
    API_URL = "http://localhost:8000/upload/"  # Ajustez selon votre configuration

    # Option 1: Utiliser l'API avec un vrai fichier
    # arxml_data = fetch_arxml_data("XYZ_CPS_HvDisE_component.arxml")

    # Option 2: Utiliser les données d'exemple
    with open('response_example.json') as f:
        arxml_data = json.load(f)

    graph = create_autosar_graph(arxml_data)

    # Paramètres de rendu
    graph.format = 'png'
    graph.render('autosar_visualization_advanced', view=True, cleanup=True)

    print("Visualisation générée avec succès!")
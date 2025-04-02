import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import dash_cytoscape as cyto
import requests
import base64
import io
from fastapi.testclient import TestClient
from main import app

# Initialisation de l'application Dash
dash_app = dash.Dash(__name__)

# Configuration du layout
dash_app.layout = html.Div([
    html.H1("Visualisation des composants AUTOSAR", style={'textAlign': 'center'}),

    dcc.Upload(
        id='upload-arxml',
        children=html.Div([
            'Glissez-déposez ou ',
            html.A('sélectionnez un fichier ARXML')
        ]),
        style={
            'width': '50%',
            'height': '60px',
            'lineHeight': '60px',
            'borderWidth': '1px',
            'borderStyle': 'dashed',
            'borderRadius': '5px',
            'textAlign': 'center',
            'margin': '10px auto'
        },
        multiple=False
    ),

    html.Div(id='output-filename'),

    cyto.Cytoscape(
        id='arxml-graph',
        layout={'name': 'preset', 'animate': True},
        style={'width': '100%', 'height': '800px'},
        stylesheet=[
            # Style des nœuds SWC
            {
                'selector': '.swc',
                'style': {
                    'label': 'data(label)',
                    'width': 180,
                    'height': 120,
                    'shape': 'rectangle',
                    'background-color': '#4682B4',
                    'border-color': '#2A4E6C',
                    'border-width': '2px',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'color': 'white',
                    'font-size': '14px',
                    'text-wrap': 'wrap',
                    'text-margin-y': 8
                }
            },
            # Style des ports P-Port (à droite)
            {
                'selector': '.p-port',
                'style': {
                    'label': 'data(label)',
                    'width': 100,
                    'height': 30,
                    'shape': 'round-rectangle',
                    'background-color': '#32CD32',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'color': 'black',
                    'font-size': '10px',
                    'text-wrap': 'wrap'
                }
            },
            # Style des ports R-Port (à gauche)
            {
                'selector': '.r-port',
                'style': {
                    'label': 'data(label)',
                    'width': 100,
                    'height': 30,
                    'shape': 'round-rectangle',
                    'background-color': '#FF6347',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'color': 'black',
                    'font-size': '10px',
                    'text-wrap': 'wrap'
                }
            },
            # Style des interfaces
            {
                'selector': '.interface',
                'style': {
                    'label': 'data(label)',
                    'width': 120,
                    'height': 40,
                    'shape': 'diamond',
                    'background-color': '#9370DB',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'color': 'white',
                    'font-size': '10px'
                }
            },
            # Style des connexions
            {
                'selector': 'edge',
                'style': {
                    'curve-style': 'straight',
                    'target-arrow-shape': 'triangle',
                    'arrow-scale': 1,
                    'line-color': '#666',
                    'target-arrow-color': '#666',
                    'width': 2
                }
            }
        ]
    ),

    html.Div(id='selected-node-info', style={'margin': '20px'})
])


def process_uploaded_file(contents):
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)

    client = TestClient(app)
    response = client.post(
        "/upload-arxml/",
        files={"file": ("uploaded.arxml", io.BytesIO(decoded), "application/arxml")}
    )

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Erreur API: {response.status_code} - {response.text}")


@dash_app.callback(
    [Output('arxml-graph', 'elements'),
     Output('output-filename', 'children')],
    [Input('upload-arxml', 'contents')],
    [State('upload-arxml', 'filename')]
)
def update_graph(contents, filename):
    if contents is None:
        return [], "Aucun fichier sélectionné"

    try:
        data = process_uploaded_file(contents)
        elements = []

        # Calcul des positions pour les SWC (alignés horizontalement)
        positions = {
            swc_name: {'x': i * 300, 'y': 0}
            for i, swc_name in enumerate(data['composition']['swcs'].keys())
        }

        # Ajouter les nœuds SWC
        for swc_name, swc_data in data['composition']['swcs'].items():
            elements.append({
                'data': {'id': swc_name, 'label': f"{swc_name}\n({swc_data['type']})"},
                'classes': 'swc',
                'position': positions[swc_name]
            })

            # Ajouter les ports P-Port à droite
            p_ports = [p for p in swc_data['ports'].items() if p[1]['type'] == 'P-Port']
            for i, (port_name, port_data) in enumerate(p_ports):
                port_id = f"{swc_name}_{port_name}"
                elements.append({
                    'data': {'id': port_id, 'label': port_name},
                    'classes': 'p-port',
                    'position': {
                        'x': positions[swc_name]['x'] + 150,
                        'y': positions[swc_name]['y'] - 40 + i * 40
                    }
                })

            # Ajouter les ports R-Port à gauche
            r_ports = [p for p in swc_data['ports'].items() if p[1]['type'] == 'R-Port']
            for i, (port_name, port_data) in enumerate(r_ports):
                port_id = f"{swc_name}_{port_name}"
                elements.append({
                    'data': {'id': port_id, 'label': port_name},
                    'classes': 'r-port',
                    'position': {
                        'x': positions[swc_name]['x'] - 150,
                        'y': positions[swc_name]['y'] - 40 + i * 40
                    }
                })

        # Ajouter les interfaces et connexions
        interface_counter = 1
        for conn in data['composition']['connections']:
            source_swc, source_port = conn['source'].split('.')
            target_swc, target_port = conn['target'].split('.')

            # Créer un nœud interface
            interface_id = f"interface_{interface_counter}"
            interface_counter += 1

            # Positionner l'interface entre les deux composants
            interface_x = (positions[source_swc]['x'] + positions[target_swc]['x']) / 2
            interface_y = -100

            elements.append({
                'data': {'id': interface_id, 'label': f"Interface\n{conn['direction'].split(' -> ')[-1]}"},
                'classes': 'interface',
                'position': {'x': interface_x, 'y': interface_y}
            })

            # Connecter le P-Port à l'interface
            elements.append({
                'data': {
                    'source': f"{source_swc}_{source_port}",
                    'target': interface_id
                }
            })

            # Connecter l'interface au R-Port
            elements.append({
                'data': {
                    'source': interface_id,
                    'target': f"{target_swc}_{target_port}"
                }
            })

        return elements, f"Fichier chargé: {filename}"

    except Exception as e:
        return [], f"Erreur: {str(e)}"


@dash_app.callback(
    Output('selected-node-info', 'children'),
    [Input('arxml-graph', 'tapNodeData')]
)
def display_node_data(data):
    if data is None:
        return "Cliquez sur un nœud pour voir ses détails"

    return html.Div([
        html.H3(f"Détails du nœud: {data.get('label', '')}"),
        html.P(f"ID: {data.get('id', '')}"),
        html.P(f"Classe: {data.get('classes', '')}")
    ])


if __name__ == '__main__':
    dash_app.run(debug=True)
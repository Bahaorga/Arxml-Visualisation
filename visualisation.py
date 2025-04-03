import dash
from dash import dcc, html
import dash_cytoscape as cyto
import requests
import json

app = dash.Dash(__name__)

# Récupérer les données de l'API FastAPI
try:
    response = requests.get("http://127.0.0.1:8000/get_arxml_data")
    data = response.json()
    swcs = data.get("swcs", [])
    connections = data.get("connections", [])
except requests.exceptions.RequestException as e:
    print(f"Erreur lors de la récupération des données: {e}")
    swcs = []
    connections = []

# Création des nœuds pour Cytoscape
elements = []
position_y = 50
for idx, swc in enumerate(swcs):
    swc_id = swc["name"]
    elements.append({"data": {"id": swc_id, "label": swc_id}, "position": {"x": 100 * (idx + 1), "y": position_y}})

    # Ajouter les ports associés
    for port in swc.get("ports", []):
        port_id = f"{swc_id}_{port}"
        elements.append({"data": {"id": port_id, "label": port, "parent": swc_id},
                         "position": {"x": 100 * (idx + 1), "y": position_y + 50}})

# Création des connexions entre les SWCs
target_x = 500
for conn in connections:
    src = conn["source"]
    dest = conn["destination"]
    elements.append({"data": {"source": src, "target": dest}})

# Mise en page de l'application Dash
app.layout = html.Div([
    html.H1("Visualisation ARXML - SWCs et Connexions"),
    cyto.Cytoscape(
        id='cytoscape',
        elements=elements,
        layout={"name": "breadthfirst"},
        style={"width": "100%", "height": "600px"},
        stylesheet=[
            {
                "selector": "node",
                "style": {
                    "content": "data(label)",
                    "text-valign": "center",
                    "background-color": "#0074D9",
                    "color": "white",
                    "width": "50px",
                    "height": "50px",
                    "font-size": "12px"
                }
            },
            {
                "selector": "edge",
                "style": {
                    "curve-style": "bezier",
                    "target-arrow-shape": "triangle",
                    "line-color": "#999",
                    "target-arrow-color": "#999"
                }
            }
        ]
    )
])

if __name__ == "__main__":
    app.run(debug=True)

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from lxml import etree
from io import BytesIO
import logging

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Création de l'application FastAPI
app = FastAPI()

# Configuration des CORS pour autoriser toutes les origines
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Espace de noms AUTOSAR
AUTOSAR_NS = {"ns": "http://autosar.org/schema/r4.0"}


# --- Fonctions utilitaires ---

def get_swc_type_name(swc_type_ref):
    """Extrait le nom du type SWC à partir de la référence"""
    if swc_type_ref is None:
        return "UNKNOWN"
    return swc_type_ref.text.split('/')[-1]


def extract_swcs(root):
    """Extrait les composants logiciels (SWCs)"""
    swcs = {}
    composition = root.find(".//ns:COMPOSITION-SW-COMPONENT-TYPE", AUTOSAR_NS)
    if composition is None:
        return swcs

    for swc in composition.findall(".//ns:COMPONENTS/ns:SW-COMPONENT-PROTOTYPE", AUTOSAR_NS):
        swc_name = swc.find("ns:SHORT-NAME", AUTOSAR_NS)
        swc_type_ref = swc.find("ns:TYPE-TREF", AUTOSAR_NS)

        if swc_name is not None:
            swcs[swc_name.text] = {
                "id": swc_name.text,
                "type": get_swc_type_name(swc_type_ref),
                "ports": {},
                "connectors": [],
                "delegations": []
            }
    return swcs


def extract_interfaces(root):
    """Extrait les interfaces (Sender-Receiver et Client-Server)"""
    interfaces = {}

    for interface in root.findall(".//ns:SENDER-RECEIVER-INTERFACE", AUTOSAR_NS):
        name = interface.find("ns:SHORT-NAME", AUTOSAR_NS)
        if name is not None:
            interfaces[name.text] = {
                "type": "Sender-Receiver",
                "data_elements": []
            }
            for data in interface.findall(".//ns:DATA-ELEMENT-PROTOTYPE", AUTOSAR_NS):
                data_name = data.find("ns:SHORT-NAME", AUTOSAR_NS)
                if data_name is not None:
                    interfaces[name.text]["data_elements"].append(data_name.text)

    for interface in root.findall(".//ns:CLIENT-SERVER-INTERFACE", AUTOSAR_NS):
        name = interface.find("ns:SHORT-NAME", AUTOSAR_NS)
        if name is not None:
            interfaces[name.text] = {
                "type": "Client-Server",
                "operations": []
            }
            for operation in interface.findall(".//ns:OPERATION-PROTOTYPE", AUTOSAR_NS):
                op_name = operation.find("ns:SHORT-NAME", AUTOSAR_NS)
                if op_name is not None:
                    interfaces[name.text]["operations"].append(op_name.text)

    return interfaces


def extract_port_metadata(root, swcs, interfaces):
    """Extrait les métadonnées des ports : type d'interface, data elements ou opérations"""
    for swc in swcs.values():
        for port_name, port_data in swc["ports"].items():
            port_data["interface_type"] = "Unknown"
            port_data["data_elements"] = []

            port = root.find(f".//ns:PORTS/*[ns:SHORT-NAME='{port_name}']", AUTOSAR_NS)
            if port is None:
                continue

            if "NvM" in port_name:
                port_data["interface_type"] = "NvM-Interface"
                continue

            if port_data["type"] == "P-Port":
                interface_ref = port.find("ns:PROVIDED-INTERFACE-TREF", AUTOSAR_NS)
            else:
                interface_ref = port.find("ns:REQUIRED-INTERFACE-TREF", AUTOSAR_NS)

            if interface_ref is None:
                continue

            interface_name = interface_ref.text.split('/')[-1]

            if interface_name in interfaces:
                port_data["interface_type"] = interfaces[interface_name]["type"]
                if port_data["interface_type"] == "Sender-Receiver":
                    port_data["data_elements"] = interfaces[interface_name]["data_elements"]
                else:
                    port_data["operations"] = interfaces[interface_name]["operations"]

            com_spec = None
            if port_data["type"] == "P-Port":
                com_spec = port.find(".//ns:NONQUEUED-SENDER-COM-SPEC", AUTOSAR_NS)
            else:
                com_spec = port.find(".//ns:NONQUEUED-RECEIVER-COM-SPEC", AUTOSAR_NS)

            if com_spec is not None:
                data_ref = com_spec.find("ns:DATA-ELEMENT-REF", AUTOSAR_NS)
                if data_ref is not None:
                    port_data["data_elements"].append(data_ref.text.split('/')[-1])


def extract_connections(root, swcs):
    """Extrait les connexions entre les ports des SWCs"""
    for connector in root.findall(".//ns:CONNECTORS/ns:ASSEMBLY-SW-CONNECTOR", AUTOSAR_NS):
        provider = connector.find("ns:PROVIDER-IREF", AUTOSAR_NS)
        requester = connector.find("ns:REQUESTER-IREF", AUTOSAR_NS)

        if provider is None or requester is None:
            continue

        provider_comp = provider.find("ns:CONTEXT-COMPONENT-REF", AUTOSAR_NS)
        provider_port = provider.find("ns:TARGET-P-PORT-REF", AUTOSAR_NS)
        requester_comp = requester.find("ns:CONTEXT-COMPONENT-REF", AUTOSAR_NS)
        requester_port = requester.find("ns:TARGET-R-PORT-REF", AUTOSAR_NS)

        if None in [provider_comp, provider_port, requester_comp, requester_port]:
            continue

        provider_swc = provider_comp.text.split('/')[-1]
        provider_port_name = provider_port.text.split('/')[-1]
        requester_swc = requester_comp.text.split('/')[-1]
        requester_port_name = requester_port.text.split('/')[-1]

        if provider_port_name not in swcs[provider_swc]["ports"]:
            swcs[provider_swc]["ports"][provider_port_name] = {
                "type": "P-Port",
                "connections": [],
                "interface_type": "Unknown",
                "data_elements": []
            }

        if requester_port_name not in swcs[requester_swc]["ports"]:
            swcs[requester_swc]["ports"][requester_port_name] = {
                "type": "R-Port",
                "connections": [],
                "interface_type": "Unknown",
                "data_elements": []
            }

        swcs[provider_swc]["ports"][provider_port_name]["connections"].append({
            "target_swc": requester_swc,
            "target_port": requester_port_name
        })

        swcs[requester_swc]["ports"][requester_port_name]["connections"].append({
            "source_swc": provider_swc,
            "source_port": provider_port_name
        })


def extract_delegations(root, swcs):
    """Extrait les délégations de ports dans la composition"""
    composition_name = root.find(".//ns:COMPOSITION-SW-COMPONENT-TYPE/ns:SHORT-NAME", AUTOSAR_NS)
    comp_name = composition_name.text if composition_name is not None else "UNKNOWN_COMPOSITION"

    for delegation in root.findall(".//ns:CONNECTORS/ns:DELEGATION-SW-CONNECTOR", AUTOSAR_NS):
        inner_port = delegation.find("ns:INNER-PORT-IREF", AUTOSAR_NS)
        outer_port = delegation.find("ns:OUTER-PORT-REF", AUTOSAR_NS)

        if inner_port is None or outer_port is None:
            continue

        p_port_ref = inner_port.find(".//ns:TARGET-P-PORT-REF", AUTOSAR_NS)
        r_port_ref = inner_port.find(".//ns:TARGET-R-PORT-REF", AUTOSAR_NS)
        port_ref = p_port_ref if p_port_ref is not None else r_port_ref

        if port_ref is None:
            continue

        path = port_ref.text.split('/')
        if len(path) < 2:
            continue

        swc_name = path[-2]
        port_name = path[-1]
        outer_port_name = outer_port.text.split('/')[-1]

        if swc_name in swcs:
            swcs[swc_name]["delegations"].append({
                "inner_port": port_name,
                "outer_port": outer_port_name,
                "type": "P-Port" if p_port_ref is not None else "R-Port",
                "composition": comp_name
            })


# --- Points d'entrée de l'API ---

@app.post("/upload/")
async def upload(file: UploadFile = File(...)):
    """Route pour traiter le fichier ARXML"""
    try:
        xml_data = await file.read()
        root = etree.parse(BytesIO(xml_data)).getroot()

        swcs = extract_swcs(root)
        interfaces = extract_interfaces(root)
        extract_port_metadata(root, swcs, interfaces)
        extract_connections(root, swcs)
        extract_delegations(root, swcs)

        # Structure de la réponse JSON
        response_data = {
            "swcs": swcs,
            "interfaces": interfaces
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"Erreur dans le traitement du fichier: {e}")
        raise HTTPException(status_code=400, detail="Fichier ARXML invalide ou traitement échoué.")
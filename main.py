from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from lxml import etree
from io import BytesIO
import logging

# Configuration de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Namespace AUTOSAR
AUTOSAR_NS = {"ns": "http://autosar.org/schema/r4.0"}


def get_swc_type_name(swc_type_ref):
    """Extrait le nom du type SWC depuis la référence"""
    if swc_type_ref is None:
        return "UNKNOWN"
    return swc_type_ref.text.split('/')[-1]


def extract_swcs(root):
    """Extrait les SWCs avec leurs métadonnées"""
    swcs = {}
    composition = root.find(".//ns:COMPOSITION-SW-COMPONENT-TYPE", AUTOSAR_NS)
    if composition is None:
        return swcs

    for swc in composition.findall(".//ns:COMPONENTS/ns:SW-COMPONENT-PROTOTYPE", AUTOSAR_NS):
        swc_name = swc.find("ns:SHORT-NAME", AUTOSAR_NS)
        swc_type_ref = swc.find("ns:TYPE-TREF", AUTOSAR_NS)

        if swc_name is not None:
            swcs[swc_name.text] = {
                "name": swc_name.text,
                "type": get_swc_type_name(swc_type_ref),
                "ports": {},
                "connectors": [],
                "delegations": []
            }
    return swcs


def extract_connections(root, swcs):
    """Extrait les connexions entre les SWCs"""
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

        # Ajouter le port si absent
        if provider_port_name not in swcs[provider_swc]["ports"]:
            swcs[provider_swc]["ports"][provider_port_name] = {
                "type": "P-Port",
                "connections": []
            }

        if requester_port_name not in swcs[requester_swc]["ports"]:
            swcs[requester_swc]["ports"][requester_port_name] = {
                "type": "R-Port",
                "connections": []
            }

        # Ajouter la connexion
        connection = {
            "target_swc": requester_swc,
            "target_port": requester_port_name
        }

        swcs[provider_swc]["ports"][provider_port_name]["connections"].append(connection)
        swcs[requester_swc]["ports"][requester_port_name]["connections"].append({
            "source_swc": provider_swc,
            "source_port": provider_port_name
        })


def extract_delegations(root, swcs):
    """Extrait les délégations de ports"""
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

        port_path = port_ref.text.split('/')
        if len(port_path) < 2:
            continue

        swc_name = port_path[-2]
        port_name = port_path[-1]
        outer_port_name = outer_port.text.split('/')[-1]

        if swc_name in swcs:
            swcs[swc_name]["delegations"].append({
                "inner_port": port_name,
                "outer_port": outer_port_name,
                "type": "P-Port" if p_port_ref is not None else "R-Port"
            })


def parse_arxml(file_content: bytes):
    """Analyse un fichier ARXML et extrait la structure SWC"""
    try:
        tree = etree.parse(BytesIO(file_content))
        root = tree.getroot()

        # Extraction des SWCs
        swcs = extract_swcs(root)

        # Extraction des connexions et délégations
        extract_connections(root, swcs)
        extract_delegations(root, swcs)

        # Génération du résultat
        composition_name = root.find(".//ns:COMPOSITION-SW-COMPONENT-TYPE/ns:SHORT-NAME", AUTOSAR_NS)
        result = {
            "composition": {
                "name": composition_name.text if composition_name is not None else "UNKNOWN_COMPOSITION",
                "swcs": swcs
            }
        }

        return result

    except Exception as e:
        logger.error(f"Erreur lors de l'analyse du fichier ARXML : {e}")
        raise HTTPException(status_code=400, detail="Erreur lors de l'analyse du fichier")


@app.post("/upload-arxml/")
async def upload_arxml(file: UploadFile = File(...)):
    """Endpoint pour uploader et analyser un fichier ARXML"""
    try:
        content = await file.read()
        parsed_data = parse_arxml(content)
        return JSONResponse(content=parsed_data, status_code=200)
    except HTTPException as e:
        return JSONResponse(content={"error": str(e.detail)}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

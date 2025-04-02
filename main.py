from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from lxml import etree
from io import BytesIO
import logging

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# AUTOSAR namespace
AUTOSAR_NS = {"ns": "http://autosar.org/schema/r4.0"}


def get_swc_type_name(swc_type_ref):
    """Extracts the SWC type name from the reference"""
    if swc_type_ref is None:
        return "UNKNOWN"
    return swc_type_ref.text.split('/')[-1]


def extract_swcs(root):
    """Extracts SWC components from the composition"""
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
                "ports": [],
                "connectors": [],
                "delegations": []
            }
    return swcs


def extract_ports_from_connectors(root, swcs):
    """Extracts ports from SWCs based on connectors"""
    for connector in root.findall(".//ns:CONNECTORS/ns:ASSEMBLY-SW-CONNECTOR", AUTOSAR_NS):
        # Provider port (P-Port)
        provider_iref = connector.find("ns:PROVIDER-IREF", AUTOSAR_NS)
        if provider_iref is not None:
            provider_comp = provider_iref.find("ns:CONTEXT-COMPONENT-REF", AUTOSAR_NS)
            provider_port = provider_iref.find("ns:TARGET-P-PORT-REF", AUTOSAR_NS)

            if provider_comp is not None and provider_port is not None:
                swc_name = provider_comp.text.split('/')[-1]
                port_name = provider_port.text.split('/')[-1]

                if swc_name in swcs:
                    port_exists = any(p['name'] == port_name for p in swcs[swc_name]['ports'])
                    if not port_exists:
                        swcs[swc_name]['ports'].append({
                            'name': port_name,
                            'type': 'P-Port',
                            'direction': 'provided'
                        })

        # Requester port (R-Port)
        requester_iref = connector.find("ns:REQUESTER-IREF", AUTOSAR_NS)
        if requester_iref is not None:
            requester_comp = requester_iref.find("ns:CONTEXT-COMPONENT-REF", AUTOSAR_NS)
            requester_port = requester_iref.find("ns:TARGET-R-PORT-REF", AUTOSAR_NS)

            if requester_comp is not None and requester_port is not None:
                swc_name = requester_comp.text.split('/')[-1]
                port_name = requester_port.text.split('/')[-1]

                if swc_name in swcs:
                    port_exists = any(p['name'] == port_name for p in swcs[swc_name]['ports'])
                    if not port_exists:
                        swcs[swc_name]['ports'].append({
                            'name': port_name,
                            'type': 'R-Port',
                            'direction': 'required'
                        })


def extract_connectors(root, swcs):
    """Extracts connectors between SWCs"""
    connectors = []
    composition = root.find(".//ns:COMPOSITION-SW-COMPONENT-TYPE", AUTOSAR_NS)
    if composition is None:
        return connectors

    for connector in composition.findall(".//ns:CONNECTORS/ns:ASSEMBLY-SW-CONNECTOR", AUTOSAR_NS):
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

        connector_data = {
            "source": f"{provider_swc}.{provider_port_name}",
            "target": f"{requester_swc}.{requester_port_name}",
            "direction": f"{provider_swc} -> {requester_swc}"
        }

        connectors.append(connector_data)

        if provider_swc in swcs:
            swcs[provider_swc]["connectors"].append(connector_data)
        if requester_swc in swcs:
            swcs[requester_swc]["connectors"].append(connector_data)

    return connectors


def extract_delegations(root, swcs):
    """Extracts port delegations"""
    composition = root.find(".//ns:COMPOSITION-SW-COMPONENT-TYPE", AUTOSAR_NS)
    if composition is None:
        return

    for delegation in composition.findall(".//ns:CONNECTORS/ns:DELEGATION-SW-CONNECTOR", AUTOSAR_NS):
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
            delegation_data = {
                "inner_port": port_name,
                "outer_port": outer_port_name,
                "type": "P-Port" if p_port_ref is not None else "R-Port"
            }
            swcs[swc_name]["delegations"].append(delegation_data)


def parse_arxml(file_content: bytes):
    """Parses an ARXML file and extracts the SWC structure"""
    try:
        tree = etree.parse(BytesIO(file_content))
        root = tree.getroot()

        # Extract SWCs from composition
        swcs = extract_swcs(root)

        result = {
            "composition": {
                "name": "",
                "swcs": {},
                "connections": []
            }
        }

        composition_name = root.find(".//ns:COMPOSITION-SW-COMPONENT-TYPE/ns:SHORT-NAME", AUTOSAR_NS)
        result["composition"]["name"] = composition_name.text if composition_name is not None else "UNKNOWN_COMPOSITION"

        # Extract ports and connectors
        extract_ports_from_connectors(root, swcs)
        connections = extract_connectors(root, swcs)
        result["composition"]["connections"] = connections

        # Extract delegations
        extract_delegations(root, swcs)

        # Convert SWC structure
        for swc_name, swc_data in swcs.items():
            result["composition"]["swcs"][swc_name] = {
                "type": swc_data["type"],
                "ports": {},
                "delegations": swc_data["delegations"]
            }

            # Organize ports
            for port in swc_data["ports"]:
                port_info = {
                    "type": port["type"],
                    "direction": port["direction"],
                    "connections": []
                }

                result["composition"]["swcs"][swc_name]["ports"][port["name"]] = port_info

        # Fill connections
        for connector in result["composition"]["connections"]:
            source_swc, source_port = connector["source"].split('.')
            target_swc, target_port = connector["target"].split('.')

            if source_swc in result["composition"]["swcs"] and source_port in result["composition"]["swcs"][source_swc]["ports"]:
                result["composition"]["swcs"][source_swc]["ports"][source_port]["connections"].append(connector["target"])

            if target_swc in result["composition"]["swcs"] and target_port in result["composition"]["swcs"][target_swc]["ports"]:
                result["composition"]["swcs"][target_swc]["ports"][target_port]["connections"].append(connector["source"])

        return result

    except Exception as e:
        logger.error(f"ARXML parsing error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"ARXML parsing error: {str(e)}")


@app.post("/upload-arxml/")
async def upload_arxml(file: UploadFile = File(...)):
    """Endpoint to analyze an ARXML file"""
    if not file.filename.endswith(".arxml"):
        raise HTTPException(status_code=400, detail="Only .arxml files are allowed")

    file_content = await file.read()
    try:
        parsed_data = parse_arxml(file_content)
        return JSONResponse(content=parsed_data, status_code=200)
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
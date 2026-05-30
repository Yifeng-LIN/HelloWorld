from __future__ import annotations
import math
import time
from datetime import datetime
from pathlib import Path
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.root
import ifcopenshell.api.unit
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.aggregate
import ifcopenshell.api.spatial
from bridge_modeler.models.irg import BridgeIRG

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def _create_ifc_model() -> ifcopenshell.file:
    model = ifcopenshell.file(schema="IFC4X3")
    return model


def export_to_ifc(irg: BridgeIRG) -> str:
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"bridge_{timestamp}.ifc"

    model = ifcopenshell.file(schema="IFC4X3")

    # --- Owner / Application history ---
    person = model.create_entity("IfcPerson", FamilyName="BridgeModeler")
    org = model.create_entity("IfcOrganization", Name="BridgeModelerSaaS")
    person_org = model.create_entity("IfcPersonAndOrganization", ThePerson=person, TheOrganization=org)
    app = model.create_entity(
        "IfcApplication",
        ApplicationDeveloper=org,
        Version="1.0",
        ApplicationFullName="BridgeModelerSaaS",
        ApplicationIdentifier="BMS",
    )
    owner_history = model.create_entity(
        "IfcOwnerHistory",
        OwningUser=person_org,
        OwningApplication=app,
        ChangeAction="ADDED",
        CreationDate=int(time.time()),
    )

    # --- Units ---
    length_unit = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    unit_assign = model.create_entity("IfcUnitAssignment", Units=[length_unit])

    # --- Geometry context ---
    world_coord = model.create_entity(
        "IfcAxis2Placement3D",
        Location=model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
    )
    geom_ctx = model.create_entity(
        "IfcGeometricRepresentationContext",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1e-5,
        WorldCoordinateSystem=world_coord,
    )

    # --- Project ---
    project = model.create_entity(
        "IfcProject",
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=owner_history,
        Name="BridgeProject",
        UnitsInContext=unit_assign,
        RepresentationContexts=[geom_ctx],
    )

    # --- Site ---
    site_placement = model.create_entity(
        "IfcLocalPlacement",
        RelativePlacement=model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
        ),
    )
    site = model.create_entity(
        "IfcSite",
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=owner_history,
        Name="BridgeSite",
        ObjectPlacement=site_placement,
        CompositionType="ELEMENT",
    )
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=owner_history,
        RelatingObject=project,
        RelatedObjects=[site],
    )

    # --- Bridge (IfcFacility / IfcBridge) ---
    bridge_placement = model.create_entity(
        "IfcLocalPlacement",
        PlacementRelTo=site_placement,
        RelativePlacement=model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
        ),
    )
    bridge = model.create_entity(
        "IfcBridge",
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=owner_history,
        Name=f"Bridge_{irg.bridge_type.value}",
        ObjectPlacement=bridge_placement,
        CompositionType="ELEMENT",
    )
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=owner_history,
        RelatingObject=site,
        RelatedObjects=[bridge],
    )

    # --- Material ---
    material = model.create_entity("IfcMaterial", Name=irg.material)

    # --- Deck height approximation based on bridge type ---
    deck_h_map = {"box_girder": 2.5, "t_beam": 1.5, "solid_slab": 0.6}
    deck_h = deck_h_map.get(irg.bridge_type.value, 1.5)

    elements: list = []
    x_offset = 0.0

    for i, span in enumerate(irg.span_lengths_m):
        # Beam geometry: rectangular swept solid
        profile = model.create_entity(
            "IfcRectangleProfileDef",
            ProfileType="AREA",
            ProfileName=f"DeckProfile_Span{i+1}",
            XDim=irg.deck_width_m,
            YDim=deck_h,
        )
        extrude_dir = model.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))
        extrude_origin = model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
        )
        solid = model.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=profile,
            Position=extrude_origin,
            ExtrudedDirection=extrude_dir,
            Depth=span,
        )
        shape_rep = model.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=geom_ctx,
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=[solid],
        )
        prod_def = model.create_entity("IfcProductDefinitionShape", Representations=[shape_rep])

        beam_placement = model.create_entity(
            "IfcLocalPlacement",
            PlacementRelTo=bridge_placement,
            RelativePlacement=model.create_entity(
                "IfcAxis2Placement3D",
                Location=model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, irg.pier_height_m)),
                Axis=model.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
                RefDirection=model.create_entity("IfcDirection", DirectionRatios=(1.0, 0.0, 0.0)),
            ),
        )
        beam = model.create_entity(
            "IfcBeam",
            GlobalId=ifcopenshell.guid.new(),
            OwnerHistory=owner_history,
            Name=f"Beam_Span{i+1}",
            ObjectPlacement=beam_placement,
            Representation=prod_def,
        )
        elements.append(beam)

        # Associate material to beam
        model.create_entity(
            "IfcRelAssociatesMaterial",
            GlobalId=ifcopenshell.guid.new(),
            OwnerHistory=owner_history,
            RelatedObjects=[beam],
            RelatingMaterial=material,
        )

        # Pier between spans (not after last span)
        if i < len(irg.span_lengths_m) - 1:
            pier_profile = model.create_entity(
                "IfcRectangleProfileDef",
                ProfileType="AREA",
                ProfileName=f"PierProfile_{i+1}",
                XDim=1.5,
                YDim=1.5,
            )
            pier_extrude_dir = model.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))
            pier_origin = model.create_entity(
                "IfcAxis2Placement3D",
                Location=model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
            )
            pier_solid = model.create_entity(
                "IfcExtrudedAreaSolid",
                SweptArea=pier_profile,
                Position=pier_origin,
                ExtrudedDirection=pier_extrude_dir,
                Depth=irg.pier_height_m,
            )
            pier_shape_rep = model.create_entity(
                "IfcShapeRepresentation",
                ContextOfItems=geom_ctx,
                RepresentationIdentifier="Body",
                RepresentationType="SweptSolid",
                Items=[pier_solid],
            )
            pier_prod_def = model.create_entity(
                "IfcProductDefinitionShape", Representations=[pier_shape_rep]
            )
            pier_x = x_offset + span
            pier_placement = model.create_entity(
                "IfcLocalPlacement",
                PlacementRelTo=bridge_placement,
                RelativePlacement=model.create_entity(
                    "IfcAxis2Placement3D",
                    Location=model.create_entity(
                        "IfcCartesianPoint", Coordinates=(pier_x, 0.0, 0.0)
                    ),
                ),
            )
            pier = model.create_entity(
                "IfcColumn",
                GlobalId=ifcopenshell.guid.new(),
                OwnerHistory=owner_history,
                Name=f"Pier_{i+1}",
                ObjectPlacement=pier_placement,
                Representation=pier_prod_def,
            )
            elements.append(pier)
            model.create_entity(
                "IfcRelAssociatesMaterial",
                GlobalId=ifcopenshell.guid.new(),
                OwnerHistory=owner_history,
                RelatedObjects=[pier],
                RelatingMaterial=material,
            )

        x_offset += span

    # Aggregate all elements into bridge
    if elements:
        model.create_entity(
            "IfcRelContainedInSpatialStructure",
            GlobalId=ifcopenshell.guid.new(),
            OwnerHistory=owner_history,
            RelatingStructure=bridge,
            RelatedElements=elements,
        )

    model.write(str(out_path))
    return str(out_path)

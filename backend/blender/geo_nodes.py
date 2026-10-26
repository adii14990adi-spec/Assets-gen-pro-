"""Reusable Blender 4.2 LTS Geometry Nodes procedural builders.

Used selectively by Architecture and Environment generators for procedural point
scattering (rocks, shrubs, scree) and linear parapet/battlement instancing, then
realized and baked cleanly to exportable meshes for glTF 2.0 / Godot 4.
"""

from __future__ import annotations

from typing import Any


def apply_surface_scatter_geonodes(
    host_obj: Any,
    instance_obj: Any,
    density: float,
    seed: int,
    scale_min: float = 0.65,
    scale_max: float = 1.35,
) -> bool:
    """Attach, evaluate, and apply a Geometry Nodes surface scatter modifier on `host_obj`."""
    import bpy  # type: ignore[import-not-found]

    if density <= 0.001:
        return False

    tree = bpy.data.node_groups.new(f"GN_Scatter_{host_obj.name}", "GeometryNodeTree")
    tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    nodes = tree.nodes
    links = tree.links

    n_in = nodes.new("NodeGroupInput")
    n_out = nodes.new("NodeGroupOutput")
    n_join = nodes.new("GeometryNodeJoinGeometry")

    n_dist = nodes.new("GeometryNodeDistributePointsOnFaces")
    n_dist.distribute_method = "POISSON"
    n_dist.inputs["Distance Min"].default_value = 1.35
    n_dist.inputs["Density Max"].default_value = float(density)
    n_dist.inputs["Seed"].default_value = int(seed)

    n_obj = nodes.new("GeometryNodeObjectInfo")
    n_obj.transform_space = "ORIGINAL"
    n_obj.inputs["Object"].default_value = instance_obj

    n_rand_scale = nodes.new("FunctionNodeRandomValue")
    n_rand_scale.data_type = "FLOAT"
    n_rand_scale.inputs["Min"].default_value = float(scale_min)
    n_rand_scale.inputs["Max"].default_value = float(scale_max)
    n_rand_scale.inputs["Seed"].default_value = int(seed + 17)

    n_rand_rot = nodes.new("FunctionNodeRandomValue")
    n_rand_rot.data_type = "FLOAT_VECTOR"
    n_rand_rot.inputs["Min"].default_value = (-0.12, -0.12, 0.0)
    n_rand_rot.inputs["Max"].default_value = (0.12, 0.12, 6.28318)
    n_rand_rot.inputs["Seed"].default_value = int(seed + 43)

    n_inst = nodes.new("GeometryNodeInstanceOnPoints")
    n_realize = nodes.new("GeometryNodeRealizeInstances")

    links.new(n_in.outputs["Geometry"], n_dist.inputs["Mesh"])
    links.new(n_dist.outputs["Points"], n_inst.inputs["Points"])
    links.new(n_obj.outputs["Geometry"], n_inst.inputs["Instance"])
    links.new(n_rand_scale.outputs["Value"], n_inst.inputs["Scale"])
    links.new(n_rand_rot.outputs["Value"], n_inst.inputs["Rotation"])
    links.new(n_inst.outputs["Instances"], n_realize.inputs["Geometry"])
    links.new(n_in.outputs["Geometry"], n_join.inputs["Geometry"])
    links.new(n_realize.outputs["Geometry"], n_join.inputs["Geometry"])
    links.new(n_join.outputs["Geometry"], n_out.inputs["Geometry"])

    # Ensure host_obj has all materials present on instance_obj so realized faces keep materials
    existing_mat_names = {m.name for m in host_obj.data.materials if m is not None}
    for inst_mat in instance_obj.data.materials:
        if inst_mat is not None and inst_mat.name not in existing_mat_names:
            host_obj.data.materials.append(inst_mat)
            existing_mat_names.add(inst_mat.name)

    mod = host_obj.modifiers.new(name="ProceduralScatterGN", type="NODES")
    mod.node_group = tree

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = host_obj.evaluated_get(depsgraph)
    baked_mesh = bpy.data.meshes.new_from_object(eval_obj, preserve_all_data_layers=True, depsgraph=depsgraph)
    old_mesh = host_obj.data
    host_obj.modifiers.remove(mod)
    host_obj.data = baked_mesh
    bpy.data.meshes.remove(old_mesh)
    bpy.data.node_groups.remove(tree)
    return True


def apply_linear_instancer_geonodes(
    instance_obj: Any,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    count: int,
    output_name: str,
    rotation_euler: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Any | None:
    """Create a realized array of `instance_obj` along a line segment via Geometry Nodes."""
    import bpy  # type: ignore[import-not-found]

    if count < 1:
        return None

    carrier_mesh = bpy.data.meshes.new(f"{output_name}_Carrier")
    carrier_obj = bpy.data.objects.new(output_name, carrier_mesh)
    bpy.context.collection.objects.link(carrier_obj)
    for mat in instance_obj.data.materials:
        if mat is not None:
            carrier_obj.data.materials.append(mat)

    tree = bpy.data.node_groups.new(f"GN_Line_{output_name}", "GeometryNodeTree")
    tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    nodes = tree.nodes
    links = tree.links

    n_out = nodes.new("NodeGroupOutput")
    n_line = nodes.new("GeometryNodeMeshLine")
    n_line.mode = "END_POINTS"
    n_line.inputs["Count"].default_value = int(count)
    n_line.inputs["Start Location"].default_value = start
    n_line.inputs["Offset"].default_value = end

    n_obj = nodes.new("GeometryNodeObjectInfo")
    n_obj.transform_space = "ORIGINAL"
    n_obj.inputs["Object"].default_value = instance_obj

    n_inst = nodes.new("GeometryNodeInstanceOnPoints")
    n_inst.inputs["Rotation"].default_value = rotation_euler
    n_realize = nodes.new("GeometryNodeRealizeInstances")

    links.new(n_line.outputs["Mesh"], n_inst.inputs["Points"])
    links.new(n_obj.outputs["Geometry"], n_inst.inputs["Instance"])
    links.new(n_inst.outputs["Instances"], n_realize.inputs["Geometry"])
    links.new(n_realize.outputs["Geometry"], n_out.inputs["Geometry"])

    mod = carrier_obj.modifiers.new(name="LinearArrayGN", type="NODES")
    mod.node_group = tree

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = carrier_obj.evaluated_get(depsgraph)
    baked_mesh = bpy.data.meshes.new_from_object(eval_obj, preserve_all_data_layers=True, depsgraph=depsgraph)
    carrier_obj.modifiers.remove(mod)
    carrier_obj.data = baked_mesh
    bpy.data.meshes.remove(carrier_mesh)
    bpy.data.node_groups.remove(tree)
    return carrier_obj

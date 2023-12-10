#
# Copyright (C) 2023, Inria
# GRAPHDECO research group, https://team.inria.fr/graphdeco
# All rights reserved.
#
# This software is free for non-commercial, research and evaluation use 
# under the terms of the LICENSE.md file.
#
# For inquiries contact  george.drettakis@inria.fr
#

import torch
import math
from diff_gaussian_rasterization import GaussianRasterizationSettings, GaussianRasterizer
from scene.gaussian_model import GaussianModel
from utils.sh_utils import eval_sh
import numpy as np
 # Example function to convert a tensor to a numpy array and handle None values
def tensor_to_numpy(tensor):
  if tensor is not None:
    return tensor.detach().cpu().numpy() 
  else:
    return None
def write_data_to_file(filename, *args):
    with open(filename, 'w') as file:
        for label, data in args:
            if data is not None:
                # Write the label to the file
                file.write(f'{label}:\n')
                # Flatten the array if it is 3D
                if data.ndim == 3:
                    data = data.reshape(-1, data.shape[-1])
                np.savetxt(file, data, fmt='%f')
                file.write('\n')

def render(viewpoint_camera, pc : GaussianModel, pipe, bg_color : torch.Tensor, scaling_modifier = 1.0, override_color = None):
    """
    Render the scene. 
    
    Background tensor (bg_color) must be on GPU!
    """
 
    # Create zero tensor. We will use it to make pytorch return gradients of the 2D (screen-space) means
    screenspace_points = torch.zeros_like(pc.get_xyz, dtype=pc.get_xyz.dtype, requires_grad=True, device="cuda") + 0
    try:
        screenspace_points.retain_grad()
    except:
        pass

    # Set up rasterization configuration
    tanfovx = math.tan(viewpoint_camera.FoVx * 0.5)
    tanfovy = math.tan(viewpoint_camera.FoVy * 0.5)

    raster_settings = GaussianRasterizationSettings(
        image_height=int(viewpoint_camera.image_height),
        image_width=int(viewpoint_camera.image_width),
        tanfovx=tanfovx,
        tanfovy=tanfovy,
        bg=bg_color,
        scale_modifier=scaling_modifier,
        viewmatrix=viewpoint_camera.world_view_transform,
        projmatrix=viewpoint_camera.full_proj_transform,
        sh_degree=pc.active_sh_degree,
        campos=viewpoint_camera.camera_center,
        prefiltered=False,
        debug=pipe.debug
    )

    rasterizer = GaussianRasterizer(raster_settings=raster_settings)

    max_gaussians = 2000
    means3D = pc.get_xyz[:max_gaussians]
    means2D = screenspace_points[:max_gaussians]
    opacity = pc.get_opacity[:max_gaussians]

    scales = pc.get_scaling[:max_gaussians] if pc.get_scaling is not None else None
    rotations = pc.get_rotation[:max_gaussians] if pc.get_rotation is not None else None
    cov3D_precomp = pc.get_covariance(scaling_modifier)[:max_gaussians] if pipe.compute_cov3D_python else None

    if override_color is None:
        if pipe.convert_SHs_python:
            shs_view = pc.get_features.transpose(1, 2).view(-1, 3, (pc.max_sh_degree + 1) ** 2)[:max_gaussians]
            dir_pp = (means3D - viewpoint_camera.camera_center.repeat(means3D.shape[0], 1))
            dir_pp_normalized = dir_pp / dir_pp.norm(dim=1, keepdim=True)
            sh2rgb = eval_sh(pc.active_sh_degree, shs_view, dir_pp_normalized)
            colors_precomp = torch.clamp_min(sh2rgb + 0.5, 0.0)
        else:
            shs = pc.get_features[:max_gaussians]
    else:
        colors_precomp = override_color
    


    # Rasterize visible Gaussians to image, obtain their radii (on screen). 
    rendered_image, radii = rasterizer(
        means3D = means3D,
        means2D = means2D,
        shs = shs,
        colors_precomp = colors_precomp,
        opacities = opacity,
        scales = scales,
        rotations = rotations,
        cov3D_precomp = cov3D_precomp)
        # Convert all data to numpy arrays

    # means3D_np = tensor_to_numpy(means3D)
    # means2D_np = tensor_to_numpy(means2D)
    # shs_np = tensor_to_numpy(shs)
    # colors_precomp_np = tensor_to_numpy(colors_precomp)
    # opacity_np = tensor_to_numpy(opacity)
    # scales_np = tensor_to_numpy(scales)
    # rotations_np = tensor_to_numpy(rotations)
    # cov3D_precomp_np = tensor_to_numpy(cov3D_precomp)
    # write_data_to_file(
    # '/content/gaussian_data.txt',
    # ('means3D', means3D_np),
    # ('means2D', means2D_np),
    # ('spherical harmonics (shs)', shs_np),
    # ('precomputed colors', colors_precomp_np),
    # ('opacity', opacity_np),
    # ('scales', scales_np),
    # ('rotations', rotations_np),
    # ('precomputed 3D covariance', cov3D_precomp_np)
    # )
    
    # Those Gaussians that were frustum culled or had a radius of 0 were not visible.
    # They will be excluded from value updates used in the splitting criteria.
    return {"render": rendered_image,
            "viewspace_points": screenspace_points,
            "visibility_filter" : radii > 0,
            "radii": radii}

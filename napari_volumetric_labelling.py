import nrrd
import napari
import os
import numpy as np
import zarr
import blosc2
from helper import *
from gui_components import VesuviusGUI
from napari.layers import Image
from scipy.ndimage import binary_dilation, binary_erosion, binary_closing
from qtpy.QtWidgets import QSizePolicy,QMessageBox,QPushButton, QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QScrollArea
from qtpy.QtCore import QTimer, Qt
from magicgui import magicgui
from magicgui.widgets import Container
from napari.qt.threading import thread_worker
from napari.utils.notifications import show_info
from napari.utils.interactions import mouse_press_callbacks, mouse_move_callbacks, mouse_release_callbacks
import yaml
from pathlib import Path
import sys

def read_hotkey_config(config_path='napari_config.yaml'):
    config_path = Path(config_path)
    if config_path.exists():
        with open(config_path, 'r') as file:
            config = yaml.safe_load(file)
            return config.get('customizable_hotkeys', {})
    return {}

config = read_hotkey_config()

# Data location and size parameters
scroll_name = 's1'
z = 7632
y = 2768
x = 5072
chunk_size = 256
pad_amount = 100
current_directory = os.getcwd()
pad_state = False
padded_raw_data = []

#nrrd zyx coord cubes
nrrd_cube_path = os.path.join(current_directory, 'data/nrrd_cubes') #Change to the path of the folder containing the nrrd cubes
raw_data, _ = nrrd.read(nrrd_cube_path+f'/volume_{z}_{y}_{x}.nrrd')
original_label_data, _ = nrrd.read(nrrd_cube_path+f'/mask_{z}_{y}_{x}.nrrd')
padded_raw_data = get_padded_nrrd_data(nrrd_cube_path, (z, y, x), pad_amount)

label_data = original_label_data
data = raw_data

# # #---Multi Res Zarr specific code, comment out if not using---
# zarr_path = "/Volumes/16TB_RAID_0/Scroll1/Scroll1.zarr" #Change this to the path of the zarr file if using zarr
# # zarr_path = "/Volumes/16TB_RAID_0/Scroll2/Scroll2.zarr"
# zarr_multi_res = zarr.open(zarr_path, mode='r')
# zarr = zarr_multi_res[0]

# raw_data = zarr[z:z+chunk_size, y:y+chunk_size, x:x+chunk_size]

# #Note: will crash if out of bounds and not checking at the moment
# padded_raw_data = zarr[z-pad_amount:z+chunk_size+pad_amount, y-pad_amount:y+chunk_size+pad_amount, x-pad_amount:x+chunk_size+pad_amount]
# data = raw_data

# # Jordi's gross volumetric labels from blosc2
# file_path = os.path.join(current_directory, 'data/s1_gross_labels.b2nd') #Change this to the path of the blosc2 file if using blosc2 labels
# blosc2_full_array = blosc2.open(file_path, mode='r')

# label_data = blosc2_full_array[z:z+chunk_size, y:y+chunk_size, x:x+chunk_size]
# label_data = label_data * np.logical_not(bright_spot_mask(data))


#If padded raw data isnt setup, just set it to raw_data
if len(padded_raw_data) == 0:
    padded_raw_data = raw_data

# removes bright spots from the data, brightest 0.5% of the data
bright_spot_masking = False
if bright_spot_masking:
    bright_spot_mask_arr = bright_spot_mask(data)
    print(f'bright spot mask shape: {bright_spot_mask_arr.shape}')
    print(np.max(bright_spot_mask_arr  ))
    label_data[bright_spot_mask_arr] = 0

# Initialize the Napari viewer
viewer = napari.Viewer()

#layer name variables
label_name = 'Labels'
data_name = 'Data'
compressed_name = 'Compressed Regions'
ff_name = 'flood_fill_layer'
label_3d_name = '3D Label Edit Layer'
compressed_class = 254
pad_state = False
erase_mode = False
cut_side = True
eraser_size = 4

global erase_slice_width
erase_slice_width = 30

# Add the 3D data to the viewer
image_layer =  viewer.add_image(data, colormap='gray', name=data_name)
labels_layer = viewer.add_labels(label_data, name=label_name)

#load saved labels and compressed labels if they exist
file_path = f'output/volumetric_labels_{scroll_name}/'
label_path = os.path.join(current_directory, file_path, f"{z}_{y}_{x}_zyx_{chunk_size}_chunk_{scroll_name}_vol_label.nrrd")
if os.path.exists(label_path):
    label_data, _ = nrrd.read(label_path)
    if bright_spot_masking:
        label_data = label_data * np.logical_not(bright_spot_mask(data))
    # label_data = np.pad(label_data, pad_width=1, mode='constant', constant_values=0)
    labels_layer.data = label_data

padded_labels = np.pad(label_data, pad_width=pad_amount, mode='constant', constant_values=0)

compressed_path = os.path.join(current_directory, file_path, f"{z}_{y}_{x}_zyx_{chunk_size}_chunk_{scroll_name}_vol_compressed_regions.nrrd")
if os.path.exists(compressed_path):
    data, _ = nrrd.read(compressed_path)
    viewer.add_labels(data, name=compressed_name)

#keybind l to switch to the data layer as the active layer
#@viewer.bind_key('l')
def switch_to_data_layer(viewer):
    viewer.layers[data_name].visible = True
    viewer.layers.selection.active = viewer.layers[data_name]
    
#keybind v to toggle settings to draw the compressed region class brush
#@viewer.bind_key('v')
def draw_compressed_class(viewer):
    msg = 'draw compressed class'
    viewer.status = msg
    print(msg)
    labels_layer.selected_label = compressed_class
    labels_layer.mode = 'paint'

#keybind r to toggle the labels layer visibility
#@viewer.bind_key('r')
def toggle_labels_visibility(viewer):
    msg = 'toggle labels visibility'
    viewer.status = msg
    print(msg)
    if viewer.dims.ndisplay == 3 and label_3d_name in viewer.layers:
        viewer.layers[label_3d_name].visible = not viewer.layers[label_3d_name].visible
    else:
        labels_layer.visible = not labels_layer.visible

#keybind / alt to toggle the labels layer visibility
# viewer.bind_key('/', toggle_labels_visibility)

#keybind . to toggle the data visibility
#@viewer.bind_key('.')
def toggle_data_visibility(viewer):
    msg = 'toggle data visibility'
    viewer.status = msg
    print(msg)
    image_layer.visible = not image_layer.visible
    if label_3d_name in viewer.layers and not image_layer.visible:
        viewer.layers[label_3d_name].blending = 'minimum'
    elif label_3d_name in viewer.layers and image_layer.visible:
        viewer.layers[label_3d_name].blending = 'opaque'

#keybind t alt to toggle the data layer visibility
# viewer.bind_key('t', toggle_data_visibility)

#keybind q to decrease the brush size of the labels layer
#@viewer.bind_key('q')
def decrease_brush_size(viewer):
    msg = 'decrease brush size'
    viewer.status = msg
    print(msg)
    labels_layer.brush_size = labels_layer.brush_size - 1

#keybind e to increase the brush size of the labels layer
#@viewer.bind_key('e')
def increase_brush_size(viewer):
    msg = 'increase brush size'
    viewer.status = msg
    print(msg)
    labels_layer.brush_size = labels_layer.brush_size + 1

#keybind s to toggle the show selected label only mode
#@viewer.bind_key('s')
def toggle_show_selected_label(viewer):
    msg = 'toggle show selected label'
    viewer.status = msg
    print(msg)
    labels_layer.show_selected_label = not labels_layer.show_selected_label
    if label_3d_name in viewer.layers:
        viewer.layers[label_3d_name].show_selected_label = not viewer.layers[label_3d_name].show_selected_label

# Function to capture cursor information when 'w' is pressed
def capture_cursor_info(event):
    # Get cursor position in world coordinates
    position = viewer.cursor.position

    # Convert world coordinates to data indices
    indices = tuple(int(np.round(coord)) for coord in position)

    # Get the value of the label under the cursor
    label_value = labels_layer.data[indices]

    # Print the cursor position and label value
    print(f"Cursor Position: {indices}, Label Value: {label_value}")
    labels_layer.selected_label = label_value

# keybind w to capture cursor info and select the label under the cursor
# 4 and the color picker also works for this
#@viewer.bind_key('w')
def label_picker(event):
    capture_cursor_info(event)

#keybind x to run the new compressed label interpolation function
#@viewer.bind_key('x')
def interpolate_borders(viewer):
    msg = "Are you sure you want to interpolate the compressed region class? This operation cannot be undone and removes the undo queue. It may also take a few seconds to minutes."
    response = confirm_popup(msg)
    if response != QMessageBox.Yes:
            return 
    msg = 'interpolating borders'
    viewer.status = msg
    print(msg)
    interpolated_borders = interpolate_slices(labels_layer.data, compressed_class)
    if compressed_name in viewer.layers:
        viewer.layers[compressed_name].data = interpolated_borders
    else:
        viewer.add_labels(interpolated_borders, name=compressed_name)

# Add an empty labels layer for the flood fill result
flood_fill_layer = viewer.add_labels(np.zeros_like(data), name=ff_name)

#keybind f to run the flood fill function with a distance of 20
#@viewer.bind_key('f')
def flood_fill(viewer, distance=20):
    msg = 'flood fill'
    viewer.status = msg
    print(msg)
    # Get the cursor position in data coordinates
    cursor_position = viewer.cursor.position
    cursor_position = tuple(int(np.round(coord)) for coord in cursor_position)

    # Get the current labels layer
    labels_layer = viewer.layers[label_name]

    # Get the current labels
    labels = labels_layer.data

    # Perform the flood fill operation
    flood_fill_result = limited_bfs_flood_fill(labels, cursor_position, distance)

    # Update the flood fill layer with the result
    flood_fill_layer.data = flood_fill_result

#keybind g to run the flood fill function with a distance of 100
#@viewer.bind_key('g')
def large_flood_fill(viewer):
    flood_fill(viewer, 100)

# Variable to store the previous oblique plane information
prev_plane_info_var = None

# Persistent variables to store the previous state and mask
previous_label_3d_data = None
manual_changes_mask = None

def process_value(value, data, erode, erosion_iterations, dilation_iterations, original_label_data):
    structure_mask = data == value
    result = np.zeros_like(data, dtype=np.uint8)
    
    if erode:
        padded_structure = np.pad(structure_mask, pad_width=erosion_iterations, mode='constant', constant_values=value)
        eroded_padded_structure = binary_erosion(padded_structure, iterations=erosion_iterations)
        eroded_structure = eroded_padded_structure[
            erosion_iterations:-erosion_iterations,
            erosion_iterations:-erosion_iterations,
            erosion_iterations:-erosion_iterations
        ]
        if eroded_structure.shape != structure_mask.shape:
            eroded_structure = np.zeros_like(structure_mask)
        result[eroded_structure] = value
    else:
        if dilation_iterations > 0:
            # Create a mask of all other values
            other_values_mask = (data != 0) & (data != value)
            
            # Dilate the structure
            # dilated_structure = binary_dilation(structure_mask, iterations=dilation_iterations)
            
            dilated_structure = numba_dilation_3d_labels(structure_mask, dilation_iterations)
            # Remove areas where dilation intersects with other values
            final_dilated_structure = dilated_structure & ~other_values_mask
            
            # Ensure dilation doesn't exceed the original label data boundaries
            final_dilated_structure = final_dilated_structure & (original_label_data != 0)
            
            # Apply the result
            result[final_dilated_structure] = value
        else:
            result[structure_mask] = value
    
    return result

@thread_worker
def erode_dilate_labels_worker(data, erode=True, erosion_iterations=1, dilation_iterations=1, original_label_data=original_label_data):
    unique_values = np.unique(data[(data > 0) & (data < 254)])
    result = np.zeros_like(data, dtype=np.uint8)
    
    total_values = len(unique_values)
    for i, value in enumerate(unique_values):
        partial_result = process_value(value, data, erode, erosion_iterations, dilation_iterations, original_label_data)
        result = np.maximum(result, partial_result)
        yield i / total_values  # This will update the progress bar
    
    return result

# Function to call from your Napari UI
def erode_dilate_labels(viewer, data, erode=True, erosion_iterations=1, dilation_iterations=1):
    worker = erode_dilate_labels_worker(data, erode, erosion_iterations, dilation_iterations)
    
    def update_progress(progress):
        show_info(f"Processing: {progress:.0%}")
    
    def on_complete(result):
        viewer.layers[label_name].data = result
        show_info("Processing complete!")
    
    worker.yielded.connect(update_progress)
    worker.returned.connect(on_complete)
    worker.start()

def shift_plane(layer, direction, padding_mode=False, padding=50):
    if isinstance(layer, Image) and viewer.dims.ndisplay == 3 and layer.depiction == 'plane':
        # Get the current position and normal of the plane
        current_position = np.array(layer.plane.position)
        normal_vector = np.array(layer.plane.normal)
        
        # Normalize the normal vector
        normal_vector /= np.linalg.norm(normal_vector)
        
        if padding_mode:
            # Create the padding vector
            padding_vector = np.array([-padding, -padding, -padding])
            
            # Calculate the new position considering padding
            new_position = current_position - padding_vector
        else:
            # Simple shift without considering padding
            new_position = current_position + direction * normal_vector
        
        # Update the plane position
        layer.plane.position = tuple(new_position)
        print(f"Shifted plane to: new position = {new_position}")
    elif viewer.dims.ndisplay == 2:
        # If in 2D mode, shift the slice by 1
        current_step = viewer.dims.current_step[0]
        new_step = current_step + direction
        viewer.dims.set_current_step(0, new_step)
        print(f"Shifted 2D slice to: {new_step}")
    else:
        print("Cannot shift: not in plane mode or 2D view")

#keybind b to switch to full label 3d view
#@viewer.bind_key('b', overwrite=True)
def full_label_view(viewer):
    if viewer.dims.ndisplay == 2:
        viewer.dims.ndisplay = 3
        for layer in viewer.layers:
            if layer.name != label_name:
                viewer.layers[layer.name].visible = False
            else:
                viewer.layers[layer.name].visible = True
                viewer.layers[layer.name].blending = 'opaque'
                
    else:
        viewer.dims.ndisplay = 2
        for layer in viewer.layers:
            if layer.name != label_3d_name:
                viewer.layers[layer.name].visible = True
            else:
                viewer.layers[layer.name].visible = False
            if layer.name == label_name:
                viewer.layers[layer.name].blending = 'translucent'
        viewer.layers.selection.active = viewer.layers[label_name]
        viewer.layers[label_name].contour = 1
            


#keybind \ to setup the 3d viewing mode conviniently with custom vesuvius layers
#@viewer.bind_key('\\')
def switch_to_plane(viewer):
   # Switch to 3D mode
    if viewer.dims.ndisplay == 3:
        viewer.dims.ndisplay = 2
        for layer in viewer.layers:
            if layer.name != label_3d_name:
                viewer.layers[layer.name].visible = True
            else:
                viewer.layers[layer.name].visible = False
            if layer.name == label_name:
                viewer.layers[layer.name].blending = 'translucent'
        viewer.layers.selection.active = viewer.layers[label_name]
        viewer.layers[label_name].contour = 1

    else:
        step_val = viewer.dims.current_step
        # print(f"Current step: {step_val}")
        viewer.dims.ndisplay = 3
    
        # Prep layers visibility and blending
        for layer in viewer.layers:
            
            if layer.name != data_name and layer.name != ff_name and layer.name != label_name and layer.name != label_3d_name:
                viewer.layers[layer.name].visible = False
            elif layer.name == label_name:
                if label_3d_name in viewer.layers:
                    viewer.layers[label_3d_name].visible = True
                    viewer.layers[label_3d_name].blending = 'opaque'
                    viewer.layers[layer.name].visible = False
                else:
                    viewer.layers[layer.name].visible = True
                    viewer.layers[layer.name].blending = 'opaque'
            elif layer.name == data_name:
                # Change the depiction of `data_name` layer from volume to plane
                viewer.layers[layer.name].visible = True
                viewer.layers[layer.name].depiction = 'plane'
                viewer.layers[layer.name].plane.position = (step_val[0], 0, 0)
                viewer.layers[layer.name].affine = np.eye(3)  # Ensure the affine transform is identity for proper rendering
                viewer.layers[layer.name].blending = 'opaque'
                viewer.layers.selection.active = viewer.layers[layer.name]

def cut_label_at_plane(viewer, erase_mode=False, cut_side=True, prev_plane_info=None):
    global previous_label_3d_data, manual_changes_mask, prev_plane_info_var, erase_slice_width

    data_plane = viewer.layers[data_name]
    if data_plane.depiction != 'plane':
        print("Please switch to plane mode by pressing '\\' key.")
        return

    active_mode = viewer.layers.selection.active.mode
    if prev_plane_info is not None:
        position = prev_plane_info['position']
        normal = prev_plane_info['normal']
    else:
        position = np.array(data_plane.plane.position)
        normal = np.array(data_plane.plane.normal)
        prev_plane_info_var = {'position': position, 'normal': normal}
    viewer.layers[data_name].blending = 'opaque'

    # Create a meshgrid for the label data coordinates
    z, y, x = np.meshgrid(np.arange(viewer.layers[label_name].data.shape[0]),
                          np.arange(viewer.layers[label_name].data.shape[1]),
                          np.arange(viewer.layers[label_name].data.shape[2]),
                          indexing='ij')

    # Calculate the distance of each voxel from the plane
    distances = (x - position[2]) * normal[2] + (y - position[1]) * normal[1] + (z - position[0]) * normal[0]
    labels_layer = viewer.layers[label_name]

    # Check if the label_3d_name layer already exists
    if label_3d_name in viewer.layers:
        existing_layer = viewer.layers[label_3d_name]
        if isinstance(existing_layer, napari.layers.Labels):
            # Calculate the manual changes mask
            if previous_label_3d_data is not None and previous_label_3d_data.shape == existing_layer.data.shape:
                manual_changes_mask = existing_layer.data != previous_label_3d_data
            else:
                manual_changes_mask = np.zeros_like(existing_layer.data, dtype=bool)
            
            # Apply the manual changes to the label_name layer
            labels_layer.data[manual_changes_mask] = existing_layer.data[manual_changes_mask]

    # Create a copy of the label data and set all voxels between the viewer and the plane to 0
    new_label_data = labels_layer.data.copy()
    print(f"Cutting label data at plane: position = {position}, normal = {normal}, erase_mode = {erase_mode}, cut_side = {cut_side}")
    if cut_side:
        new_label_data[distances > 1.5] = 0
        if erase_mode:
            new_label_data[distances < -erase_slice_width + 0.5] = 0
    else:
        new_label_data[distances < -1.5] = 0
        if erase_mode:
            new_label_data[distances > erase_slice_width + 0.5] = 0

    # Remove the old label_3d_name layer if it exists
    visible_state = True
    if label_3d_name in viewer.layers:
        visible_state = viewer.layers[label_3d_name].visible
        
        viewer.layers.remove(viewer.layers[label_3d_name])
    
    # Add a new label layer with the updated data
    viewer.add_labels(new_label_data, name=label_3d_name)
    viewer.layers[label_3d_name].colormap = get_direct_label_colormap()
    
    new_label_layer = viewer.layers[label_3d_name]
    new_label_layer.visible = visible_state
    new_label_layer.blending = 'opaque'
    new_label_layer.mode = active_mode

    # Store the current state of the label_3d_name layer for future comparison
    previous_label_3d_data = new_label_data.copy()

    # Refresh the viewer to immediately show the changes
    viewer.layers[label_name].refresh()
    viewer.layers[label_3d_name].refresh()

def plane_3d_erase_mode_shift_left(viewer):
    global erase_mode
    if erase_mode:
        shift_plane(viewer.layers[data_name], -erase_slice_width)
        if viewer.dims.ndisplay == 3 and label_3d_name in viewer.layers and viewer.layers[label_3d_name].visible:
            cut_label_at_plane(viewer, erase_mode=erase_mode, cut_side=cut_side)

def plane_3d_erase_mode_shift_right(viewer):
    global erase_mode
    if erase_mode:
        shift_plane(viewer.layers[data_name], erase_slice_width)
        if viewer.dims.ndisplay == 3 and label_3d_name in viewer.layers and viewer.layers[label_3d_name].visible:
            cut_label_at_plane(viewer, erase_mode=erase_mode, cut_side=cut_side)

#keybind Left arrow  to shift the plane along the normal vector in 3d viewing mode
#@viewer.bind_key('Left', overwrite=True)
def shift_data_left_and_recut_3d_label(viewer):
    global erase_mode, cut_side
    shift_plane(viewer.layers[data_name], -1)
    if viewer.dims.ndisplay == 3 and label_3d_name in viewer.layers and viewer.layers[label_3d_name].visible:
        cut_label_at_plane(viewer, erase_mode=erase_mode, cut_side=cut_side)

#@viewer.bind_key('Shift-Left', overwrite=True)
def shift_data_left_fast_and_recut_3d_label(viewer):
    global erase_mode, cut_side, erase_slice_width
    if erase_mode:
        shift_plane(viewer.layers[data_name], -erase_slice_width)
    else:
        shift_plane(viewer.layers[data_name], -20)
    if viewer.dims.ndisplay == 3 and label_3d_name in viewer.layers and viewer.layers[label_3d_name].visible:
        cut_label_at_plane(viewer, erase_mode=erase_mode, cut_side=cut_side)

#keybind Right arrow to shift the plane along the normal vector in 3d viewing mode
#@viewer.bind_key('Right', overwrite=True)
def shift_data_right_and_recut_3d_label(viewer):
    global erase_mode, cut_side
    shift_plane(viewer.layers[data_name], 1)
    if viewer.dims.ndisplay == 3 and label_3d_name in viewer.layers and viewer.layers[label_3d_name].visible:
        cut_label_at_plane(viewer, erase_mode=erase_mode, cut_side=cut_side)

#keybind Right arrow + shift to shift the plane along the normal vector 20 in 3d viewing mode
#@viewer.bind_key('Shift-Right', overwrite=True)
def shift_data_right_fast_and_recut_3d_label(viewer):
    global erase_mode, cut_side, erase_slice_width
    if erase_mode:
        shift_plane(viewer.layers[data_name], erase_slice_width)
    else:
        shift_plane(viewer.layers[data_name], 20)
    if viewer.dims.ndisplay == 3 and label_3d_name in viewer.layers and viewer.layers[label_3d_name].visible:
        cut_label_at_plane(viewer, erase_mode=erase_mode, cut_side=cut_side)

# Define the functions to move left and right
def move_left(viewer, distance=1):
    # viewer.window._qt_viewer.viewer.dims._increment_dims_left()
    shift_plane(viewer.layers[data_name], -distance)

def move_right(viewer, distance=1):
    # viewer.window._qt_viewer.viewer.dims._increment_dims_right()
    shift_plane(viewer.layers[data_name], distance)

# Create timers for holding keys
left_timer = QTimer()
right_timer = QTimer()

# Connect the timers to the move functions
left_timer.timeout.connect(lambda: move_left(viewer))
right_timer.timeout.connect(lambda: move_right(viewer))

# Define the key press events
#@viewer.bind_key('a', overwrite=True)
def shift_data_left(viewer):
    move_left(viewer)  # Move immediately on key press
    if not left_timer.isActive():
        left_timer.start(50)  # Adjust the interval as needed

#@viewer.bind_key('d', overwrite=True)
def shift_data_right(viewer):
    move_right(viewer)  # Move immediately on key press
    if not right_timer.isActive():
        right_timer.start(50)  # Adjust the interval as needed

def shift_data_left_fast(viewer):
    move_left(viewer, 20)  # Move immediately on key press

def shift_data_right_fast(viewer):
    move_right(viewer, 20)  # Move immediately on key press



# Function to stop timers when keys are released
def stop_timers(event):
    if event.key == 'a' and left_timer.isActive():
        left_timer.stop()
    elif event.key == 'd' and right_timer.isActive():
        right_timer.stop()

# Connect the key release event to the function
viewer.window._qt_viewer.canvas.events.key_release.connect(stop_timers)

#keybind ' to switch to eraser on the 3d label layer
#@viewer.bind_key('\'')
def erase_mode(viewer):
    global eraser_size
    if viewer.dims.ndisplay == 3 and label_3d_name in viewer.layers and viewer.layers[label_3d_name].visible:
        viewer.layers[label_3d_name].mode = 'erase'
        viewer.layers.selection.active = viewer.layers[label_3d_name]
    elif viewer.dims.ndisplay == 3:
        viewer.layers[label_name].mode = 'erase'
        viewer.layers.selection.active = viewer.layers[label_name]
    elif viewer.dims.ndisplay == 2:
        viewer.layers[label_name].mode = 'erase'
        viewer.layers.selection.active = viewer.layers[label_name]

#keybind , to enable the 3d slice erase mode
#@viewer.bind_key(',')
def plane_erase_3d_mode(viewer, switch=True):
    global erase_mode, cut_side
    if not erase_mode:
        switch = False
        erase_mode = True
    if switch:
        cut_side = not cut_side
    if viewer.dims.ndisplay == 3 and viewer.layers[data_name].depiction == 'plane':
        cut_label_at_plane(viewer, erase_mode=erase_mode, cut_side=cut_side)
        viewer.layers[label_name].visible = False

#keybind ; to enable 3d pan_zoom/move mode
#@viewer.bind_key(';')
def move_mode(viewer):
    if viewer.dims.ndisplay == 3 and label_3d_name in viewer.layers and viewer.layers[label_3d_name].visible:
        viewer.layers[label_3d_name].mode = 'pan_zoom'
    else:
        viewer.layers[label_name].mode = 'pan_zoom'

# keybind k to cut the label layer at the oblique plane, also called by left and right arrow
#@viewer.bind_key('k', overwrite=True)
def cut_label_at_oblique_plane(viewer, switch=True, prev_plane_info=None):
    global erase_mode, cut_side
    if erase_mode:
        switch = False
        erase_mode = False
    if switch:
        cut_side = not cut_side
    if viewer.dims.ndisplay == 3 and viewer.layers[data_name].depiction == 'plane':
        cut_label_at_plane(viewer, erase_mode=False, cut_side=cut_side, prev_plane_info=prev_plane_info)
        
        viewer.layers[label_3d_name].visible = True
        viewer.layers[label_3d_name].blending = 'opaque'
        viewer.layers[label_3d_name].refresh()
        viewer.layers[label_name].visible = False

#run connected components on the labels layer to get instance segmentations
#@viewer.bind_key('c')
def connected_components(viewer):
    msg = 'connected components'
    viewer.status = msg
    print(msg)
    msg = "DANGER Are you sure you want to run connected components? This operation cannot be undone and removes the undo queue. Consider saving first. \n\nIF YOU HAVE DILATED SEPERATED LABELS AND THEY NOW TOUCH, THEY WILL BE COMBINED."
    response = confirm_popup(msg)
    if response != QMessageBox.Yes:
            return 

    #mask for the compressed class from the labels layer
    mask = (labels_layer.data == compressed_class)
    old_borders = np.zeros_like(labels_layer.data)
    old_borders[labels_layer.data == compressed_class] = compressed_class

    #new borders from the compressed layer and labels layer
    if compressed_name in viewer.layers:
        compressed_label = viewer.layers[compressed_name].data
        new_borders = compressed_label  | old_borders
        new_borders[new_borders > 0] = compressed_class
        
        mask_2 = (compressed_label  == compressed_class)
        mask = mask | mask_2
        
        viewer.layers[compressed_name].data = new_borders
    else:
        new_borders = old_borders
        viewer.add_labels(new_borders, name=compressed_name)

    #apply any changes to the layer_3d_name layer to the labels layer
    if label_3d_name in viewer.layers:
        if prev_plane_info_var is not None:
            cut_label_at_oblique_plane(viewer, switch=False, prev_plane_info=prev_plane_info_var)
        else:
            cut_label_at_oblique_plane(viewer, switch=False)

    #connected components data with both layer's borders removed
    cc_data = labels_layer.data.copy()
    cc_data[mask] = 0

    labels_layer.data = label_foreground_structures_napari(cc_data, compressed_class=compressed_class, min_size=1000)
    if label_3d_name in viewer.layers:
        if prev_plane_info_var is not None:
            cut_label_at_oblique_plane(viewer, switch=False, prev_plane_info=prev_plane_info_var)
        else:
            cut_label_at_oblique_plane(viewer, switch=False)
    msg = 'connected components finished'
    viewer.status = msg
    print(msg)

#keybind j to add context padding to the data layer
pad_key = 'j'
#@viewer.bind_key(pad_key)
def add_padding_contextual_data(viewer):
    global pad_state, previous_label_3d_data, manual_changes_mask

    if pad_state:
        data = raw_data
        viewer.layers[data_name].data = data
        
        # Remove padding from the layers
        slices = tuple(slice(pad_amount, -pad_amount) if dim > 2 * pad_amount else slice(None) for dim in data.shape)
        for layer in viewer.layers:
            if layer.name is not data_name:
                original_data = layer.data.copy()
                layer.data = original_data[slices]
        if previous_label_3d_data is not None:
            previous_label_3d_data = previous_label_3d_data[slices]
        if manual_changes_mask is not None:
            manual_changes_mask = manual_changes_mask[slices]
        shift_plane(viewer.layers[data_name], 0, padding_mode=True, padding=-pad_amount)
        pad_state = False
    else:
        data = padded_raw_data
        viewer.layers[data_name].data = data
        # if label_3d_name in viewer.layers:
        #     viewer.layers.remove(viewer.layers[label_3d_name])

        # Add padding to the layers
        pad_width = ((pad_amount, pad_amount), (pad_amount, pad_amount), (pad_amount, pad_amount))
        for layer in viewer.layers:
            if layer.name is not data_name:
                print(layer.name)
                original_data = layer.data.copy()
                layer.data = np.pad(original_data, pad_width=pad_width, mode='constant', constant_values=0)
        if previous_label_3d_data is not None:
            previous_label_3d_data = np.pad(previous_label_3d_data, pad_width=pad_width, mode='constant', constant_values=0)
        if manual_changes_mask is not None:
            manual_changes_mask = np.pad(manual_changes_mask, pad_width=pad_width, mode='constant', constant_values=0)
        shift_plane(viewer.layers[data_name], 0, padding_mode=True, padding=pad_amount)
        pad_state = True

#keybind i to erode the labels layer
#@viewer.bind_key('i')
def erode_labels(viewer):
    global pad_state
    msg = 'eroding labels'
    viewer.status = msg
    print(msg) 
    if not pad_state:
        msg = "Are you sure you want to erode the labels? This operation cannot be undone."
        response = confirm_popup(msg)
        if response != QMessageBox.Yes:
            print('eroding labels cancelled')
            return 
        erode_dilate_labels(viewer, labels_layer.data)
        labels_layer.refresh()

        #update 3d label layer if it is visible
        if viewer.dims.ndisplay == 3 and label_3d_name in viewer.layers and viewer.layers[label_3d_name].visible:
            cut_label_at_oblique_plane(viewer, switch=False)
    else:
        msg = f'please remove contextual padding with {pad_key} before eroding labels'
        show_popup(msg)
        viewer.status = msg
        print(msg)
        return
    msg = 'eroding labels finished'
    viewer.status = msg
    print(msg)

#keybind u to dilate the labels layer
#@viewer.bind_key('u')
def dilate_labels(viewer):
    global pad_state
    msg = 'dilating labels'
    viewer.status = msg
    print(msg)
    if not pad_state:
        msg = "Are you sure you want to dilate the labels? This operation cannot be undone. It will only dilate up to the borders of the original mask file."
        response = confirm_popup(msg)
        if response != QMessageBox.Yes:
            print('dilating labels cancelled')
            return 
        erode_dilate_labels(viewer, labels_layer.data, erode=False)
        labels_layer.refresh()

        #update 3d label layer if it is visible
        if viewer.dims.ndisplay == 3 and label_3d_name in viewer.layers and viewer.layers[label_3d_name].visible:
            cut_label_at_oblique_plane(viewer, switch=False)
    else:
        msg = f'please remove contextual padding with {pad_key} before dilating labels'
        show_popup(msg)
        viewer.status = msg
        print(msg)
        return
    msg = 'dilating labels finished'
    viewer.status = msg
    print(msg)

#Keybind h to save the labels, raw and compressed class layer
#@viewer.bind_key('h')
def save_labels(viewer):
    msg = 'save labels'
    viewer.status = msg
    print(msg)
    current_directory = os.getcwd()
    file_path = f'output/volumetric_labels_{scroll_name}/'
    output_path = os.path.join(current_directory, file_path)
    if not os.path.exists(output_path):
        os.makedirs(output_path)
    print(labels_layer.data.shape, labels_layer.data.dtype)
    if label_3d_name in viewer.layers:
        if prev_plane_info_var is not None:
            cut_label_at_oblique_plane(viewer, switch=False, prev_plane_info=prev_plane_info_var)
        else:
            cut_label_at_oblique_plane(viewer, switch=False)
    
    nrrd.write(os.path.join(output_path,f"{z}_{y}_{x}_zyx_{chunk_size}_chunk_{scroll_name}_vol_label.nrrd"), labels_layer.data)
    nrrd.write(os.path.join(output_path,f"{z}_{y}_{x}_zyx_{chunk_size}_chunk_{scroll_name}_vol_raw.nrrd"), viewer.layers[data_name].data)
    if compressed_name in viewer.layers:
        nrrd.write(os.path.join(output_path,f"{z}_{y}_{x}_zyx_{chunk_size}_chunk_{scroll_name}_vol_compressed_regions.nrrd"), viewer.layers[compressed_name].data)
    msg = f"Layers saved to {output_path}"
    show_popup(msg)

# UI functions for the buttons
# def dilate_labels_gui():
#     dilate_labels(viewer, viewer.layers[label_name].data, erode=False)

# def erode_labels_gui():
#     erode_labels(viewer)

# def toggle_full_label_view():
#     full_label_view(viewer)

# def toggle_3D_plane_cut_view():
#     switch_to_plane(viewer)

# def toggle_padding_context():
#     add_padding_contextual_data(viewer)

# def cut_label_at_plane_gui():
#     cut_label_at_oblique_plane(viewer)

# def run_connected_components():
#     connected_components(viewer)

# def save_labels_button():
#     save_labels(viewer)

# Create a dictionary of functions to pass to the GUI
functions_dict = {
    'erode_labels': erode_labels,
    'dilate_labels': dilate_labels,
    'full_label_view': full_label_view,
    'switch_to_plane': switch_to_plane,
    'add_padding_contextual_data': add_padding_contextual_data,
    'cut_label_at_oblique_plane': cut_label_at_oblique_plane,
    'connected_components': connected_components,
    'save_labels': save_labels,
}

def update_global_erase_slice_width(value):
    global erase_slice_width
    erase_slice_width = value
    print(f"Global erase width updated to: {erase_slice_width}")

# Create the GUI
gui = VesuviusGUI(viewer, functions_dict, update_global_erase_slice_width, config)
gui.setup_napari_defaults()

def bind_hotkeys(viewer, config, module=None, overwrite=True):
    if module is None:
        module = sys.modules['__main__']  # Get the main module
    
    for func_name, keys in config.items():
        # Skip if keys is None, an empty string, or an empty list
        if keys is None or keys == "" or (isinstance(keys, list) and len(keys) == 0):
            print(f"Warning: No key binding specified for function '{func_name}'. Skipping.")
            continue

        # First, try to find the function in the viewer
        if hasattr(viewer, func_name):
            func = getattr(viewer, func_name)
        # If not in viewer, try to find it in the main module
        elif hasattr(module, func_name):
            func = getattr(module, func_name)
        else:
            print(f"Warning: Function '{func_name}' not found. Skipping.")
            continue

        if isinstance(keys, list):
            for key in keys:
                if key:  # Only bind if key is not an empty string
                    try:
                        viewer.bind_key(key, func, overwrite=overwrite)
                    except (ValueError, TypeError) as e:
                        print(f"Error binding key '{key}' to function '{func_name}': {str(e)}")
        elif keys:  # Only bind if keys is not an empty string
            try:
                viewer.bind_key(keys, func, overwrite=overwrite)
            except (ValueError, TypeError) as e:
                print(f"Error binding key '{keys}' to function '{func_name}': {str(e)}")

bind_hotkeys(viewer, config)

# Start the Napari event loop
napari.run()



# --------------------------------------------------------
#    mmqgis_library - mmqgis operation functions
#
#    begin		: 10 May 2010
#    copyright		: (c) 2010 - 2026 by Michael Minn
#    email		: See michaelminn.com
#
#   MMQGIS is free software and is offered without guarantee
#   or warranty. You can redistribute it and/or modify it 
#   under the terms of version 2 of the GNU General Public 
#   License (GPL v2) as published by the Free Software 
#   Foundation (www.gnu.org).
# --------------------------------------------------------

import io
import re
import csv
import sys
import ssl
import time
import json
import math
import locale
import random
import os.path
import operator
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree

from qgis.core import *
from qgis.PyQt.QtCore import *
from qgis.PyQt.QtGui import *

# from PyQt6.QtCore import *
# from PyQt6.QtGui import *

# Used instead of "import math" so math functions can be used without "math." prefix
from math import *


# --------------------------------------------------------
#    mmqgis_animate_lines
# --------------------------------------------------------

def mmqgis_animate_lines(print_layout, input_layer, fixed_speed, frame_count, frame_directory, status_callback = None):

	# Error Checks

	if not print_layout:
		return "Invalid print layout"

	exporter = QgsLayoutExporter(print_layout)
	if not exporter:
		return "No exporter found for print layout " + print_layout.name()

	if not input_layer:
		return "Invalid map layer"

	if (input_layer.wkbType() in [QgsWkbTypes.LineString25D, QgsWkbTypes.MultiLineString25D]):
		return "2.5-D not supported. Modify -> Convert Geometry Type to line to animate"
	
	if (input_layer.type() != QgsMapLayer.VectorLayer) or\
	   (input_layer.wkbType() not in [QgsWkbTypes.LineString, QgsWkbTypes.LineString25D, \
				QgsWkbTypes.MultiLineString, QgsWkbTypes.MultiLineString25D]):
		return "Input needs to be a line layer"
	
	if frame_count <= 0:
		return "Invalid number of frames specified: " + str(frame_count)

	if not os.path.isdir(frame_directory):
		return "Invalid output directory: " + str(frame_directory)


	# Convert features to lists of points
	points = []
	length = []
	for feature_index, feature in enumerate(input_layer.getFeatures()):

		# This doesn't actually work for 2.5D geometries = waiting for API to support them 2/22/2017

		fpoints = []
		if (feature.geometry().wkbType() == QgsWkbTypes.LineString) or \
		   (feature.geometry().wkbType() == QgsWkbTypes.LineString25D):
			fpoints = feature.geometry().asPolyline()

		elif (feature.geometry().wkbType() == QgsWkbTypes.MultiLineString) or \
		     (feature.geometry().wkbType() == QgsWkbTypes.MultiLineString25D):
			for line in feature.geometry().asMultiPolyline():
				fpoints.extend(line)

		else:
			return "Invalid geometry type " + str(feature.geometry().wkbType())

		points.append(fpoints)

		#print str(feature_index) + " = " + str(len(points)) + " = " + str(len(fpoints)) + \
		#	" = " + str(feature.geometry().wkbType()) + " = " + str(type(points))

		# Calculate total shape length 
		# Can't use length() function because it does not consider circuity
		flength = 0
		for point in range(0,len(fpoints) - 1):
			flength = flength + \
				sqrt(pow(fpoints[point].x() - fpoints[point + 1].x(), 2) + \
				pow(fpoints[point].y() - fpoints[point + 1].y(), 2))

		length.append(flength)

	if len(length) <= 0:
		return "No features in layer to animate"

	max_length = max(length)

	# Iterate Frames
	for frame in range(frame_count + 1):
		if status_callback:
			if status_callback(100 * frame / frame_count, "Rendering frame " + str(frame)):
				return "Animate lines cancelled on frame " + str(frame)

		input_layer.startEditing()

		for feature_index, feature in enumerate(input_layer.getFeatures()):

			fpoints = points[feature_index]
			if (len(fpoints) <= 0):
				continue

			if fixed_speed:
				visible_length = min([length[feature_index], max_length * frame / frame_count])
			else:
				visible_length = length[feature_index] * frame / frame_count


			total_length = 0
			visible = [fpoints[0], fpoints[0]]
			for z in range(1, len(fpoints)):
				segment_length = pow(pow(fpoints[z].x() - fpoints[z - 1].x(), 2) + \
					pow(fpoints[z].y() - fpoints[z - 1].y(), 2), 0.5)

				# print "   " + str(total_length) + " + " + str(segment_length)

				if (total_length >= visible_length):
					break

				elif (total_length + segment_length) <= visible_length:
					visible.append(fpoints[z])
					total_length = total_length + segment_length

				else: # only display part of line segment
					fraction = (visible_length - total_length) / segment_length
					x = fpoints[z - 1].x() + ((fpoints[z].x() - fpoints[z - 1].x()) * fraction)
					y = fpoints[z - 1].y() + ((fpoints[z].y() - fpoints[z - 1].y()) * fraction)
					visible.append(QgsPointXY(x, y))
					break

			# print str(visible_length) + ", " + str(len(visible)) + ", " + \
			#	str(total_length) + ", " + str(max_length)

			# This doesn't actually work for 2.5D geometries = waiting for API to support them 2/22/2017
			input_layer.changeGeometry(feature.id(), QgsGeometry.fromPolylineXY(visible))

		# Write Frame

		framefile = frame_directory + "/frame" + format(frame, "06d") + ".png"

		exporter.exportToImage(framefile, QgsLayoutExporter.ImageExportSettings())

		# Clean up: Constantly starting and stopping editing is slow, 
		# but leaving editing open and accumulating successive changes
		# seems to be even slower

		input_layer.rollBack()

	if status_callback:
		status_callback(100, str(frame_count) + " frames exported")

	return None

# ----------------------------------------------------------------------------------------------------
#    mmqgis_animate_location - Animate with linear interpolation from source to destination locations
# ----------------------------------------------------------------------------------------------------

def mmqgis_animate_location(print_layout, source_layer, source_key_field, \
			destination_layer, destination_key_field, frame_count, \
			frame_directory, status_callback = None):

	# Error Checks
	if not print_layout:
		return "Invalid print layout"

	exporter = QgsLayoutExporter(print_layout)
	if not exporter:
		return "No exporter found for print layout " + print_layout.name()

	if (not source_layer) or (source_layer.type() != QgsMapLayer.VectorLayer) or (source_layer.featureCount() <= 0):
		return "Invalid source layer"

	if (not destination_layer) or (destination_layer.type() != QgsMapLayer.VectorLayer) or \
	   (destination_layer.featureCount() <= 0):
		return "Invalid destination layer"

	source_key_index = source_layer.dataProvider().fieldNameIndex(source_key_field)
	if (source_key_index < 0):
		return "Invalid source key field: " + str(long_col)

	destination_key_index = destination_layer.dataProvider().fieldNameIndex(destination_key_field)
	if (destination_key_index < 0):
		return "Invalid destination key field: " + str(long_col)

	if frame_count <= 0:
		return "Invalid number of frames specified: " + str(frame_count)

	if not os.path.isdir(frame_directory):
		return "Invalid output directory: " + str(frame_directory)


	transform = QgsCoordinateTransform(destination_layer.crs(), source_layer.crs(), QgsProject.instance())

	# Find each feature's differential change with each frame
	xdifferential = {}
	ydifferential = {}
	animated_features = 0

	for feature in source_layer.getFeatures():
		x_start = feature.geometry().centroid().asPoint().x()
		y_start = feature.geometry().centroid().asPoint().y()
		
		source_key = str(feature.attributes()[source_key_index])
		expression = "\"" + str(destination_key_field) + "\" = '" + source_key + "'"

		for destination in destination_layer.getFeatures(expression):
			geometry = destination.geometry()
			geometry.transform(transform)
			x_end = geometry.centroid().asPoint().x()
			y_end = geometry.centroid().asPoint().y()

			xdifferential[feature.id()] = (x_end - x_start) / frame_count
			ydifferential[feature.id()] = (y_end - y_start) / frame_count

			#print("Feature " + str(feature.id()) + " " + str(feature.attributes()[2]) + \
			#	": " + str(xdifferential[feature.id()]) + ", " + str(ydifferential[feature.id()]))

			animated_features = animated_features + 1
			break

	# Iterate Frames

	for frame in range(frame_count + 1):
		if status_callback:
			if status_callback(100 * frame / frame_count, 
				str(animated_features) + " features, frame " + str(frame) + " of " + str(frame_count)):
				return "Animate columns cancelled on frame " + str(frame)

		# Translate (move) shapes

		source_layer.startEditing()

		for feature in source_layer.getFeatures():
			if feature.id() in xdifferential:
				x_shift = xdifferential[feature.id()] * frame
				y_shift = ydifferential[feature.id()] * frame

				#print(str(feature.id()) + ": " + str(x_shift) + ", " + str(y_shift))
				
				source_layer.translateFeature(feature.id(), x_shift, y_shift)

		# Write Frame

		frame_file = frame_directory + "/frame" + format(frame, "06d") + ".png"
		exporter.exportToImage(frame_file, QgsLayoutExporter.ImageExportSettings())

		# Clean up: Constantly starting and stopping editing is slow, 
		# but leaving editing open and accumulating successive changes
		# seems to be even slower (6/5/2014)

		source_layer.rollBack()

	if status_callback:
		status_callback(100, str(animated_features) + " features, " + str(frame_count) + " frames")

	return None


# ----------------------------------------------------------------------------
#    mmqgis_animate_sequence - Create animations by displaying successive rows
# ----------------------------------------------------------------------------

def mmqgis_animate_sequence(print_layout, layers, cumulative, frame_directory, status_callback = None):

	# Error Checks

	if not print_layout:
		return "Invalid print layout"

	exporter = QgsLayoutExporter(print_layout)
	if not exporter:
		return "No exporter found for print layout " + print_layout.name()

	frame_count = 0
	for layer in layers:
		if frame_count < layer.featureCount():
			frame_count = layer.featureCount()

		if not layer.startEditing():
			return "A layer must be editable to animate"

		layer.rollBack()

	if frame_count <= 1:
		return "At least one animated layer must have more than one feature"

	if not os.path.isdir(frame_directory):
		return "Invalid output directory: " + str(frame_directory)


	# Store geometries in a list and delete them from features

	geometries = [[] * len(layers)]
	feature_ids = [None] * len(layers)
	for layer_index, layer in enumerate(layers):
		layer.startEditing()
		feature_ids[layer_index] = layer.allFeatureIds()
		for feature_index, feature in enumerate(layer.getFeatures()):
			geometries[layer_index].append(QgsGeometry(feature.geometry()))
			layer.changeGeometry(feature_ids[layer_index][feature_index], QgsGeometry())
			#feature.setGeometry(QgsGeometry(QgsGeometry.fromPoint(QgsPoint(0,0))))


	# Iterate frames

	# qgis.mapCanvas().renderComplete.connect(temp_render_complete)
	#qgis.mapCanvas().setParallelRenderingEnabled(False)
	#qgis.mapCanvas().setCachingEnabled(False)

	for frame in range(int(frame_count + 1)):
		if status_callback:
			if status_callback(100 * frame / frame_count, "Rendering frame " + str(frame)):
				return "Animate rows cancelled on frame " + str(frame)

		for layer_index, layer in enumerate(layers):
			if frame < len(geometries[layer_index]):
				layer.changeGeometry(feature_ids[layer_index][frame], \
					QgsGeometry(geometries[layer_index][frame]))
				if (frame > 0) and (not cumulative):
					layer.changeGeometry(feature_ids[layer_index][frame - 1], QgsGeometry())

		# qgis.mapCanvas().refresh()

		#pixmap = QPixmap(qgis.mapCanvas().mapSettings().outputSize().width(), 
		#	qgis.mapCanvas().mapSettings().outputSize().height())

		framefile = frame_directory + "/frame" + format(frame, "06d") + ".png"

		# qgis.mapCanvas().saveAsImage(framefile, pixmap)

		exporter.exportToImage(framefile, QgsLayoutExporter.ImageExportSettings())

		# print("Saved " + str(frame))

		# return


	# Restore geometries

	for layer_index, layer in enumerate(layers):
		for frame in range(int(frame_count + 1)):
			if frame < len(geometries[layer_index]):
				layer.changeGeometry(feature_ids[layer_index][frame], \
					QgsGeometry(geometries[layer_index][frame]))
		layer.rollBack()

	if status_callback:
		status_callback(100, str(frame_count) + " frames exported")

	return None

# ----------------------------------------------------------------------------
#    mmqgis_animate_zoom - Create animations by zoomin into or out of a map
# ----------------------------------------------------------------------------

def mmqgis_animate_zoom(print_layout, start_lat, start_long, start_zoom, \
		end_lat, end_long, end_zoom, frame_count, frame_directory, status_callback = None):

	# Error checks
	if (not print_layout) or (type(print_layout) != QgsPrintLayout):
		return "Invalid print layout"

	if (type(start_lat) not in [int, float]) or (start_lat < -90) or (start_lat > 90) or \
	   (type(start_long) not in [int, float]) or (start_long < -180) or (start_long > 180):
		return "Start location out of range"

	if (type(end_lat) not in [int, float]) or (end_lat < -90) or (end_lat > 90) or \
	   (type(end_long) not in [int, float]) or (end_long < -180) or (end_long > 180):
		return "End location out of range"

	if (type(start_zoom) not in [int, float]) or (start_zoom < 1) or (start_zoom > 20):
		return "Start zoom out of range"

	if (type(end_zoom) not in [int, float]) or (end_zoom < 1) or (end_zoom > 20):
		return "End zoom out of range"

	if (type(frame_count) != int) or (frame_count <= 0):
		return "Frame count must be positive"

	if (not frame_directory) or (not os.path.isdir(frame_directory)):
		return "Invalid frame directory"

	map_item_count = 0
	for page_number in range(print_layout.pageCollection().pageCount()):
		for item in print_layout.pageCollection().itemsOnPage(page_number):
			if item.type() == QgsLayoutItemRegistry.LayoutMap:
				map_item_count = map_item_count + 1

	if not map_item_count:
		return "No map items in the print layout"

	wgs84 = QgsCoordinateReferenceSystem("PROJ4:+proj=longlat +datum=WGS84 +no_defs")

	# Export frame images

	exporter = QgsLayoutExporter(print_layout)

	for frame in range(frame_count + 1):
		if status_callback:
			if status_callback(100 * frame / float(frame_count), "Frame " + str(frame)):
				return "Cancelled at frame " + str(frame) + " of " + str(frame_count)

		# Calculate the smoothed zoom, latitude, and longitude
		ratio = (1 - math.cos((frame / frame_count) * math.pi)) / 2
		zoom = start_zoom + ((end_zoom - start_zoom) * ratio)
		degree_height = 360 * math.pow(0.5, zoom)
		center_lat = start_lat + (ratio * (end_lat - start_lat))
		center_long = start_long + (ratio * (end_long - start_long))
		# print("Ratio " + str(ratio) + " = " + str(zoom) + " = " + str(degree_height) + " degrees")

		# Zoom in/out
		old_extents = []
		for page_number in range(print_layout.pageCollection().pageCount()):
			for item in print_layout.pageCollection().itemsOnPage(page_number):
				if item.type() == QgsLayoutItemRegistry.LayoutMap:
					# Save the old extent for restoration after printing the fram
					old_extent = item.extent()
					old_extents.append(old_extent)

					# Find the extent top/bottom based on zoom level and center
					top = QgsPointXY(center_long, center_lat + (degree_height / 2))
					bottom = QgsPointXY(center_long, center_lat - (degree_height / 2))

					transform = QgsCoordinateTransform(wgs84, item.crs(), QgsProject.instance())
					top = transform.transform(top)
					bottom = transform.transform(bottom)

					# Find the new width based on the aspect ratio of the old extent
					new_width = old_extent.width() * (top.x() - bottom.x()) / old_extent.height()
					new_extent = QgsRectangle(bottom.x() - (new_width / 2), bottom.y(),
							bottom.x() + (new_width / 2), top.y())

					# print(str(new_extent))

					item.zoomToExtent(new_extent)

		
		# Print the frame image
		file_name = frame_directory + "/frame%04d.png" % frame
		exporter.exportToImage(file_name, exporter.ImageExportSettings())

		# Restore old extents
		for page_number in range(print_layout.pageCollection().pageCount()):
			for item in print_layout.pageCollection().itemsOnPage(page_number):
				if item.type() == QgsLayoutItemRegistry.LayoutMap:
					if len(old_extents) > 0:
						item.zoomToExtent(old_extents[0])
						old_extents.remove(old_extents[0])
				
	if status_callback:
		status_callback(100, str(frame_count) + " frames exported")

	return None

# ----------------------------------------------------------
#    mmqgis_attribute_export - Export attributes to CSV file
# ----------------------------------------------------------

def mmqgis_attribute_export(input_layer, attribute_names, output_csv_name, \
		field_delimiter = ",", line_terminator = "\n", decimal_mark = ".", \
		status_callback = None):

	# Error checks

	if (not input_layer) or (input_layer.type() != QgsMapLayer.VectorLayer) or (input_layer.featureCount() <= 0):
		return "Invalid layer"

	if not attribute_names:
		return "No attributes specified for export"

	
	# CSV Options

	layer_options = []
	if line_terminator == "\r\n":
		layer_options.append("LINEFORMAT=CRLF")
	else:
		layer_options.append("LINEFORMAT=LF")

	if field_delimiter == ";":
		layer_options.append("SEPARATOR=SEMICOLON")
	elif field_delimiter == "\t":
		layer_options.append("SEPARATOR=TAB")
	elif field_delimiter == " ":
		layer_options.append("SEPARATOR=SPACE")
	else:
		layer_options.append("SEPARATOR=COMMA")
		
	if not decimal_mark:
		decimal_mark = "."


	# Build field list

	fields = QgsFields()
	attribute_indices = []

	for attribute in attribute_names:
		found = False
		for index, field in enumerate(input_layer.fields()):
			if field.name() == attribute:
				fields.append(field)
				attribute_indices.append(index)
				found = True
				break
		if not found:
			return "Invalid attribute name: " + attribute

	if not attribute_indices:
		return "No valid attributes specified"

	# Create file writer

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = 'CSV'
	save_options.fileEncoding = 'UTF-8'
	save_options.layerOptions = layer_options

	outfile = QgsVectorFileWriter.create(output_csv_name, fields, \
		QgsWkbTypes.Unknown, input_layer.crs(), \
		QgsProject.instance().transformContext(), \
		save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())

	# Iterate through each feature in the source layer
	for index, feature in enumerate(input_layer.getFeatures()):
		if ((index % 50) == 0) and status_callback:
			if status_callback(100 * index / input_layer.featureCount(), \
					"Exporting " + str(index) + " of " + str(input_layer.featureCount())):
				return "Export attributes cancelled on feature " + str(index)

		attributes = []
		for x in attribute_indices:
			attributes.append(feature.attributes()[x])

		newfeature = QgsFeature()
		newfeature.setAttributes(attributes)
		outfile.addFeature(newfeature)

	del outfile

	if status_callback:
		status_callback(100, str(input_layer.featureCount()) + " records exported")

	return None

# --------------------------------------------------------------------------
#    mmqgis_attribute_join - Join attributes from a CSV file to a shapefile
# --------------------------------------------------------------------------

def mmqgis_attribute_join(input_layer, input_layer_attribute, input_csv_name, input_csv_attribute, \
			output_file_name, status_callback = None):

	# Error checks
	try:
		if (input_layer.type() != QgsMapLayer.VectorLayer):
			return "Invalid layer type " + str(input_layer.type()) + " for attribute export"
	except Exception as e:
		return "Invalid layer: " + str(e)

	if (input_layer.wkbType() == None) or (input_layer.wkbType() == QgsWkbTypes.NoGeometry):
		return "Layer has no geometries"

	join_index = input_layer.dataProvider().fieldNameIndex(input_layer_attribute)
	if join_index < 0:
		return "Invalid CSV field name: " + str(input_layer_attribute)

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]


	# Open CSV file and read the header

	if not input_csv_name:
		return "No input CSV file name given"

	input_csv = QgsVectorLayer(input_csv_name)

	if (not input_csv) or (input_csv.featureCount() <= 0) or (len(input_csv.fields()) <= 0):
		return "Failure opening input file: " + str(input_csv_name)

	header = [x.name() for x in input_csv.fields()]


	# Read shapefile field names

	# 12/27/2016: Real numbers imported from shapefiles have a precision of
	# zero, which causes them to be written as integers, which causes
	# loss of decimal points and total loss of value when values exceed MAXINT.
	# This kludge sets the precision to an arbitrary value, which causes
	# the OGR writer to consider them floating point.

	newfields = QgsFields()
	for field in input_layer.fields():
		if field.type() == QVariant.Double:
			newfields.append(QgsField(field.name(), field.type(), field.typeName(), 12, 4))
		else:
			newfields.append(QgsField(field.name(), field.type(), field.typeName(), 
				field.length(), field.precision()))
		

	# Create a combined list of fields with shapefile-safe (<= 10 char) unique names
	csv_index = -1
	for index in range(0, len(header)):
		if header[index].strip().lower() == input_csv_attribute.strip().lower():
			csv_index = index

		else:
			# Shapefile-safe = 10 characters or less
			fieldname = header[index].strip()[0:10]

			# Rename fields that have duplicate names
			suffix = 1
			while (newfields.indexFromName(fieldname) >= 0):
				suffix = suffix + 1
				if (suffix <= 9):
					fieldname = fieldname[0:9] + str(suffix)
				else:
					fieldname = fieldname[0:8] + str(suffix)

			# 12/27/2016: String length of 254 is used to prevent a warning thrown 
			# when the default 255 exceeds the 254 char limit
			newfields.append(QgsField(fieldname, QVariant.String, "String", 254))

	if csv_index < 0:
		return "Field " + str(input_csv_attribute) + " not found in " + str(input_csv_name)

	# Create the output shapefile

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, newfields, \
		input_layer.wkbType(), input_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())


	# Iterate through each feature in the source layer
	matched_count = 0

	for feature_index, feature in enumerate(input_layer.getFeatures()):
		if status_callback and ((feature_index % 50) == 0):
			if status_callback(100 * feature_index / input_layer.featureCount(), \
				"Feature " + str(feature_index) + " of " + str(input_layer.featureCount()) + \
				" (" + str(matched_count) + " matched)"):
				return "Cancelled on feature " + str(feature.id()) + " of " + str(input_layer.featureCount())

		if feature.geometry() == None:
			return "No geometry in on feature " + str(feature_index)

		attributes = feature.attributes()

		key = attributes[join_index].lower().strip()

		for row_index, row in enumerate(input_csv.getFeatures()):
			if row.attribute(csv_index).strip().lower() == key:
				# print(key + " --------------")

				newattributes = []
				for value in attributes:
					newattributes.append(value)
					
				for combine_index in range(len(row.attributes())):
					if combine_index != csv_index:
						newattributes.append(row.attribute(combine_index))

				newfeature = QgsFeature()
				newfeature.setAttributes(newattributes)
				newfeature.setGeometry(feature.geometry())
				outfile.addFeature(newfeature)
				matched_count += 1

	del outfile

	if matched_count <= 0:
		return "No matching records found"

	if status_callback:
		status_callback(100, str(input_layer.featureCount()) + " layer + " \
			+ str(input_csv.featureCount()) + " CSV = " + str(matched_count) + " features")

	return None



# --------------------------------------------------------
#    mmqgis_buffers - Create buffers around shapes
# --------------------------------------------------------

def mmqgis_bearing(start, end):
	# Assumes points are WGS 84 lat/long
	# http://www.movable-type.co.uk/scripts/latlong.html

	start_lon = start.x() * pi / 180
	start_lat = start.y() * pi / 180
	end_lon = end.x() * pi / 180
	end_lat = end.y() * pi / 180

	return atan2(sin(end_lon - start_lon) * cos(end_lat), \
		(cos(start_lat) * sin(end_lat)) - \
		(sin(start_lat) * cos(end_lat) * cos(end_lon - start_lon))) \
		* 180 / pi

def mmqgis_endpoint(start, distance, degrees):
	# Assumes points are WGS 84 lat/long, distance in meters,
	# bearing in degrees with north = 0, east = 90, west = -90
	# Uses the haversine formula for calculation:
	# http://www.movable-type.co.uk/scripts/latlong.html
	radius = 6378137.0 # meters

	start_lon = start.x() * pi / 180
	start_lat = start.y() * pi / 180
	bearing = degrees * pi / 180

	end_lat = asin((sin(start_lat) * cos(distance / radius)) +
		(cos(start_lat) * sin(distance / radius) * cos(bearing)))
	end_lon = start_lon + atan2( \
		sin(bearing) * sin(distance / radius) * cos(start_lat),
		cos(distance / radius) - (sin(start_lat) * sin(end_lat)))

	return QgsPointXY(end_lon * 180 / pi, end_lat * 180 / pi)


def mmqgis_buffer_geometry(geometry, meters):
	if meters <= 0:
		return None

	# To approximate meaningful meter distances independent of the original CRS,
	# the geometry is transformed to an azimuthal equidistant projection
	# with the center of the polygon as the origin. After buffer creation,
	# the buffer is transformed to WGS 84 and returned. While this may introduce
	# some deviation from the original CRS, buffering is assumed in practice
	# to be a fairly inexact operation that can tolerate such deviation

	wgs84 = QgsCoordinateReferenceSystem("PROJ4:+proj=longlat +datum=WGS84 +no_defs")

	latitude = str(geometry.centroid().asPoint().y())
	longitude = str(geometry.centroid().asPoint().x())

	#proj4 = "+proj=aeqd +lat_0=" + str(geometry.centroid().asPoint().y()) + \
	#	" +lon_0=" + str(geometry.centroid().asPoint().x()) + \
	#	" +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

	# For some reason, Azimuthal Equidistant transformation noticed to not be
	# working on 10 July 2014. World Equidistant Conic works, but there may be errors.
	proj4 = "+proj=eqdc +lat_0=0 +lon_0=0 +lat_1=60 +lat_2=60 " + \
		"+x_0=0 +y_0=0 +ellps=WGS84 +datum=WGS84 +units=m +no_defs"

	azimuthal_equidistant = QgsCoordinateReferenceSystem()
	azimuthal_equidistant.createFromProj4(proj4)
	
	transform = QgsCoordinateTransform(wgs84, azimuthal_equidistant, QgsProject.instance())
	geometry.transform(transform)

	newgeometry = geometry.buffer(meters, 7)

	wgs84 = QgsCoordinateReferenceSystem()
	wgs84.createFromProj4("+proj=longlat +datum=WGS84 +no_defs")

	transform = QgsCoordinateTransform(azimuthal_equidistant, wgs84, QgsProject.instance())
	newgeometry.transform(transform)

	return newgeometry


def mmqgis_buffer_point(point, meters, edges, rotation_degrees):
	if (meters <= 0) or (edges < 3):
		return None

	# Points are treated separately from other geometries so that discrete
	# edges can be supplied for non-circular buffers that are not supported
	# by the QgsGeometry.buffer() function

	wgs84 = QgsCoordinateReferenceSystem()
	wgs84.createFromProj4("+proj=longlat +datum=WGS84 +no_defs")

	# print "Point " + str(point.x()) + ", " + str(point.y()) + " meters " + str(meters)

	polyline = []
	for edge in range(0, edges + 1):
		degrees = ((float(edge) * 360.0 / float(edges)) + rotation_degrees) % 360
		polyline.append(mmqgis_endpoint(QgsPointXY(point), meters, degrees))

	return QgsGeometry.fromPolygonXY([polyline])


def mmqgis_buffer_line_side(geometry, width, direction):
	# width in meters
	# direction should be 0 for north side, 90 for east, 180 for south, 270 for west

	# print "\nmmqgis_buffer_line_side(" + str(direction) + ")"

	if (geometry.wkbType() == QgsWkbTypes.MultiLineString) or \
	   (geometry.wkbType() == QgsWkbTypes.MultiLineString25D):
		multipolygon = None
		for line in geometry.asMultiPolyline():
			segment = mmqgis_buffer_line_side(QgsGeometry.fromPolylineXY(line), width, direction)
			if multipolygon == None:
				multipolygon = segment
			else:
				multipolygon = multipolygon.combine(segment)
			# print "  Build multipolygon " + str(multipolygon.isGeosValid())

		# Multiline always has multipolygon buffer even if buffers merge into one polygon
		if multipolygon.wkbType() == QgsWkbTypes.Polygon:
			multipolygon = QgsGeometry.fromMultiPolygonXY([multipolygon.asPolygon()])

		# print "Final Multipolygon " + str(multipolygon.isGeosValid())
		return multipolygon

	if (geometry.wkbType() != QgsWkbTypes.LineString) and \
	   (geometry.wkbType() != QgsWkbTypes.LineString25D):
		return geometry

	points = geometry.asPolyline()
	line_bearing = mmqgis_bearing(points[0], points[-1]) % 360

	# Determine side of line to buffer based on angle from start point to end point
	# "bearing" will be 90 for right side buffer, -90 for left side buffer
	direction = round((direction % 360) / 90) * 90
	if (direction == 0): # North
		if (line_bearing >= 180):
			bearing = 90 # Right
		else:
			bearing = -90 # Left

	elif (direction == 90): # East
		if (line_bearing >= 270) or (line_bearing < 90):
			bearing = 90 # Right
		else:
			bearing = -90 # Left

	elif (direction == 180): # South
		if (line_bearing < 180):
			bearing = 90 # Right
		else:
			bearing = -90 # Left

	else: # West
		if (line_bearing >= 90) and (line_bearing < 270):
			bearing = 90 # Right
		else:
			bearing = -90 # Left

	# Buffer individual segments
	polygon = None
	for z in range(0, len(points) - 1):
		b1 = mmqgis_bearing(points[z], points[z + 1]) % 360

		# Form rectangle beside line 
		# 2% offset mitigates topology floating-point errors
		linestring = [QgsPointXY(points[z])]
		if (z == 0):
			linestring.append(mmqgis_endpoint(points[z], width, b1 + bearing))
		else:
			linestring.append(mmqgis_endpoint(points[z], width, b1 + (1.02 * bearing)))
		linestring.append(mmqgis_endpoint(points[z + 1], width, b1 + bearing))

		# Determine if rounded convex elbow is needed
		if (z < (len(points) - 2)):
			b2 = mmqgis_bearing(points[z + 1], points[z + 2]) % 360
			elbow = b2 - b1
			if (elbow < -180):
				elbow = elbow + 360
			elif (elbow > 180):
				elbow = elbow - 360

			# print str(b1) + ", " + str(b2) + " = " + str(elbow)

			# 8-step interpolation of arc
			if (((bearing > 0) and (elbow < 0)) or \
			    ((bearing < 0) and (elbow > 0))): 
				for a in range(1,8):
					b = b1 + (elbow * a / 8.0) + bearing
					linestring.append(mmqgis_endpoint(points[z + 1], width, b))
					# print "  arc: " + str(b)

				linestring.append(mmqgis_endpoint(points[z + 1], width, b2 + bearing))

		# Close polygon
		linestring.append(QgsPointXY(points[z + 1]))
		linestring.append(QgsPointXY(points[z]))	
		segment = QgsGeometry.fromPolygonXY([linestring])
		# print linestring
		# print "  Line to polygon " + str(segment.isGeosValid())

		if (polygon == None):
			polygon = segment
		else:
			polygon = polygon.combine(segment)

		#print "  Polygon build " + str(polygon.isGeosValid())
		#if not polygon.isGeosValid():
		#	print polygon.asPolygon()

	# print "  Final polygon " + str(polygon.isGeosValid())

	return polygon


def mmqgis_buffers(input_layer, selected_only, radius_attribute, radius, radius_unit, \
	edge_attribute, edge_count, rotation_attribute, rotation_degrees, \
	output_file_name, status_callback = None):

	# Error checking

	try:
		if (input_layer.type() != QgsMapLayer.VectorLayer):
			return "Invalid layer type for buffering: " + str(input_layer.type())

	except Exception as e:
		return "Invalid layer: " + str(e)

	# Radius
	radius_attribute_index = -1
	if radius_attribute:
		radius_attribute_index = input_layer.dataProvider().fieldNameIndex(radius_attribute)

		if (radius_attribute_index < 0):
			return "Invalid radius attribute name: " + str(radius_attribute)

	else:
		try:
			radius = float(radius)

		except Exception as e:
			return "Invalid radius: " + str(radius)

		if (radius <= 0):
			return "Radius must be greater than zero (" + str(radius) + ")"

	# Edges
	edge_attribute_index = -1
	if (input_layer.wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D, \
			QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPointZ, QgsWkbTypes.MultiPoint25D]):
		if edge_attribute:
			edge_attribute_index = input_layer.dataProvider().fieldNameIndex(edge_attribute)

			if (edge_attribute_index < 0):
				return "Invalid edge attribute name: " + str(edge_attribute)

		else:
			try:
				edge_count = int(edge_count)
			except Exception as e:
				return "Invalid edge count: " + str(edge_count)

			if (edge_count <= 0):
				return "Number of edges must be greater than zero (" + str(edge_count) + ")"

	# Rotation
	rotation_attribute_index = -1
	if rotation_attribute:
		rotation_attribute_index = input_layer.dataProvider().fieldNameIndex(rotation_attribute)

		if (rotation_attribute_index < 0):
			return "Invalid rotation attribute name: " + str(rotation_attribute)

	else:
		try:
			rotation_degrees = float(rotation_degrees)
		except Exception as e:
			return "Invalid rotation degrees: " + str(rotation_degrees)
		

	# Create the output file

	wgs84 = QgsCoordinateReferenceSystem()
	wgs84.createFromProj4("+proj=longlat +datum=WGS84 +no_defs")
	transform = QgsCoordinateTransform(input_layer.crs(), wgs84, QgsProject.instance())
	# print layer.crs().toProj4() + " -> " + wgs84.toProj4()
	
	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, input_layer.fields(), \
		QgsWkbTypes.Polygon, wgs84, \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return str(outfile.errorMessage())

	# Create buffers for each feature
	buffercount = 0
	feature_count = input_layer.featureCount();
	if selected_only:
		feature_list = input_layer.selectedFeatures()
	else:
		feature_list = input_layer.getFeatures()

	for feature_index, feature in enumerate(feature_list):
		if status_callback:
			if status_callback(100 * feature.id() / feature_count, \
					"Feature " + str(feature.id()) + " of " + str(feature_count)):
				return "Buffering cancelled on feature " + str(feature.id()) + " of " + str(feature_count)

		if radius_attribute_index < 0:
			feature_radius = radius
		else:
			try:
				feature_radius = float(feature.attributes()[radius_attribute_index])
			except:
				feature_radius = 0.0

		if feature_radius <= 0:
			continue

		# Buffer radii are always in meters
		if radius_unit == "Kilometers":
			feature_radius = feature_radius * 1000

		elif radius_unit == "Feet":
			feature_radius = feature_radius / 3.2808399

		elif radius_unit == "Miles":
			feature_radius = feature_radius * 1609.344

		elif radius_unit == "Nautical Miles":
			feature_radius = feature_radius * 1852

		if feature_radius <= 0:
			continue

		if edge_attribute_index < 0:
			feature_edges = edge_count
		else:
			try:
				feature_edges = int(feature.attributes()[edge_attribute_index])
			except:
				feature_edges = 32 # default to circle

		if rotation_attribute_index < 0:
			feature_rotation = rotation_degrees
		else:
			try:
				feature_rotation = float(feature.attributes()[rotation_attribute_index])
			except:
				feature_rotation = 0.0

		geometry = feature.geometry()
		geometry.transform(transform) # Needs to be WGS 84 to use Haversine distance calculation
		# print "Transform " + str(x) + ": " + str(geometry.centroid().asPoint().x())

		if (geometry.wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D, \
				QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPointZ, QgsWkbTypes.MultiPoint25D]):

			newgeometry = mmqgis_buffer_point(geometry.asPoint(), feature_radius, feature_edges, feature_rotation)

		elif (geometry.wkbType() in [QgsWkbTypes.LineString, QgsWkbTypes.LineStringZ, \
				QgsWkbTypes.LineString25D, QgsWkbTypes.MultiLineString, \
				QgsWkbTypes.MultiLineStringZ, QgsWkbTypes.MultiLineString25D]):

			if (edge_attribute == "Flat End"):
				# newgeometry = mmqgis_buffer_line_flat_end(geometry, feature_radius)
				north = mmqgis_buffer_line_side(QgsGeometry(geometry), feature_radius, 0)
				south = mmqgis_buffer_line_side(QgsGeometry(geometry), feature_radius, 180)
				newgeometry = north.combine(south)

			elif (edge_attribute == "North Side"):
				newgeometry = mmqgis_buffer_line_side(geometry, feature_radius, 0)

			elif (edge_attribute == "East Side"):
				newgeometry = mmqgis_buffer_line_side(geometry, feature_radius, 90)

			elif (edge_attribute == "South Side"):
				newgeometry = mmqgis_buffer_line_side(geometry, feature_radius, 180)

			elif (edge_attribute == "West Side"):
				newgeometry = mmqgis_buffer_line_side(geometry, feature_radius, 270)

			else: # "Rounded"
				newgeometry = mmqgis_buffer_geometry(geometry, feature_radius)

		else:
			newgeometry = mmqgis_buffer_geometry(geometry, feature_radius)

		if newgeometry == None:
			return "Failure converting geometry for feature " + str(buffercount)

		else:
			newfeature = QgsFeature()
			newfeature.setGeometry(newgeometry)
			newfeature.setAttributes(feature.attributes())
			outfile.addFeature(newfeature)
	
		buffercount = buffercount + 1

	del outfile

	if status_callback:
		status_callback(100, str(buffercount) + " buffers created for " + str(feature_count) + " features")

	return None

# -----------------------------------------------------------------------------------------
#    mmqgis_change_projection - change a layer's projection (reproject)
# -----------------------------------------------------------------------------------------

def mmqgis_change_projection(input_layer, new_crs, output_file_name, status_callback = None):

	# Error checks

	if type(input_layer) not in [ QgsMapLayer, QgsVectorLayer ]:
		return "Invalid layer type for modification: " + str(type(input_layer))

	if type(new_crs) != QgsCoordinateReferenceSystem:
		return "Invalid CRS"

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, input_layer.fields(), \
		input_layer.wkbType(), new_crs, \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return str(outfile.errorMessage())

	transform = QgsCoordinateTransform(input_layer.crs(), new_crs, QgsProject.instance())

	for index, feature in enumerate(input_layer.getFeatures()):
		if status_callback and ((index % 50) == 0):
			if status_callback(100 * index / input_layer.featureCount(), "Feature " + str(index)):
				return "Cancelled on feature " + str(index) + " of " + str(input_layer.featureCount())

		new_feature = QgsFeature()
		new_feature.setAttributes(feature.attributes())

		new_geometry = feature.geometry()
		try:
			new_geometry.transform(transform)
		except Exception as e:
			return "Feature " + str(index) + " could not be transformed to the new projection: " + str(e)
		new_feature.setGeometry(new_geometry)
		
		outfile.addFeature(new_feature)
				
	if status_callback:
		status_callback(100, "Changed projection for " + str(input_layer.featureCount()) + " features")

	return None

# -----------------------------------------------------------------------------------------
#    mmqgis_delete_duplicate_geometries - Save to shaperile while removing duplicate shapes
# -----------------------------------------------------------------------------------------

def mmqgis_delete_duplicate_geometries(input_layer, output_file_name, status_callback = None):

	# Error checks

	try:
		if (input_layer.type() != QgsMapLayer.VectorLayer):
			return "Invalid layer type for modification: " + str(input_layer.type())

	except Exception as e:
		return "Invalid layer: " + str(e)

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, input_layer.fields(), \
		input_layer.wkbType(), input_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return str(outfile.errorMessage())

	# Read geometries into an array
	# Have to save as WKT because saving geometries causes segfault 
	# when they are used with equal() later
	geometries = []

	for feature in input_layer.getFeatures():
		geometries.append(feature.geometry().asWkt())

	# NULL duplicate geometries
	for x in range(0, len(geometries) - 1):
		if geometries[x] == None:
			continue

		if status_callback and ((x % 50) == 0):
			if status_callback(100 * x / len(geometries), "Feature " + str(x)):
				return "Cancelled on feature " + str(x) + " of " + str(len(geometries))

		for y in range(x + 1, len(geometries)):
			#print "Comparing " + str(x) + ", " + str(y)
			if geometries[x] == geometries[y]:
				#print "None " + str(x)
				geometries[y] = None

	writecount = 0
	for index, feature in enumerate(input_layer.getFeatures()):
		if geometries[index] != None:
			writecount += 1
			outfile.addFeature(feature)
				
	del outfile

	if status_callback:
		status_callback(100, str(writecount) + " unique of " + str(input_layer.featureCount()))

	return None

# ---------------------------------------------------------
#    mmqgis_float_to_text - String format numeric fields
# ---------------------------------------------------------

def mmqgis_float_to_text(input_layer, attributes, separator, \
			 decimals, multiplier, prefix, suffix, \
		 	 output_file_name, status_callback = None):

	# Error checks

	try:
		if input_layer.type() != QgsMapLayer.VectorLayer:
			return "Input layer must be a vector layer"
	except:
		return "Invalid input layer"

	if decimals < 0:
		return "Invalid number of decimals: " + str(decimals)

	if not multiplier:
		return "Invalid multiplier: " + str(multiplier)

	if not separator:
		separator = ""

	if not prefix:
		prefix = ""

	if not suffix:
		suffix = ""

	# Build dictionary of fields with selected fields for conversion to floating point
	changecount = 0
	fieldchanged = []
	destfields = QgsFields();
	for index, field in enumerate(input_layer.fields()):
		if field.name() in attributes:
			if not (field.type() in [QVariant.Double, QVariant.Int, QVariant.UInt, \
					QVariant.LongLong, QVariant.ULongLong]):
				return "Cannot convert non-numeric field: " + str(field.name())
		
			changecount += 1
			fieldchanged.append(True)
			destfields.append(QgsField (field.name(), QVariant.String, field.typeName(), \
				20, 0, field.comment()))
		else:
			fieldchanged.append(False)
			destfields.append(QgsField (field.name(), field.type(), field.typeName(), \
				field.length(), field.precision(), field.comment()))

	if (changecount <= 0):
		return "No numeric fields selected for conversion"

	# Create the output file

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, destfields, \
		input_layer.wkbType(), input_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return str(outfile.errorMessage())


	# Write the features with modified attributes
	feature_count = input_layer.featureCount();
	for feature_index, feature in enumerate(input_layer.getFeatures()):
		if status_callback and ((feature_index % 50) == 0):
			if status_callback(100 * feature_index / feature_count, \
					"Feature " + str(feature_index) + " of " + str(feature_count)):
				return "Cancelled on feature " + str(feature_index) + " of " + str(feature_count)

		attributes = feature.attributes()
		for index, field in enumerate(input_layer.fields()):
			if fieldchanged[index]:
				# floatvalue, test = attributes[index].toDouble()
				try:
					floatvalue = multiplier * float(attributes[index])
				except:
					floatvalue = 0

				value = ("{:,." + str(decimals) + "f}").format(floatvalue)
				if (separator == ' ') or (separator == '.'):
					# European-style numbers: 1.203.347,42
					value = value.replace(".", "dec")
					value = value.replace(",", separator)
					value = value.replace("dec", ",")
				elif separator == "":
					value = value.replace(",", "")
				else:
					value = value.replace(",", separator)

				attributes[index] = str(prefix) + str(value) + str(suffix)

		feature.setAttributes(attributes)
		outfile.addFeature(feature)

	del outfile

	if status_callback:
		status_callback(100, str(len(attributes)) + " fields, " + str(input_layer.featureCount()) + " features")

	return None


# ---------------------------------------------------------------------
#    mmqgis_geocode_reverse - Reverse geocode locations to addresses
# ---------------------------------------------------------------------

def mmqgis_proxy_settings():
	# Load proxy settings from qgis options settings
	try:
		settings = QSettings()
		proxyEnabled = settings.value("proxy/proxyEnabled", "")
		proxyType = settings.value("proxy/proxyType", "" )
		proxyHost = settings.value("proxy/proxyHost", "" )
		proxyPort = settings.value("proxy/proxyPort", "" )
		proxyUser = settings.value("proxy/proxyUser", "" )
		proxyPassword = settings.value("proxy/proxyPassword", "" )

		# http://stackoverflow.com/questions/1450132/proxy-with-urllib2
		if proxyEnabled == "true":
			if proxyUser:
				proxy = urllib.request.ProxyHandler({'http': 'http://' +  proxyUser + ':' + 
					proxyPassword + '@' + proxyHost + ':' + proxyPort})
			else:
				proxy = urllib.request.ProxyHandler({'http': 'http://' + proxyHost + ':' + proxyPort})

			opener = urllib.request.build_opener(proxy)
			urllib.request.install_opener(opener)
	except:
		pass

def mmqgis_geocode_reverse(input_layer, web_service, api_key, use_first, output_file_name, status_callback = None):

	# Error checks

	web_services = ["Google", "OpenStreetMap / Nominatim"]
	if web_service not in web_services:
		return "Invalid web service name: " + str(web_service)

	if (web_service == "Google") and (not api_key):
		return "A Google Maps API key is required\n" + \
			"https://developers.google.com/maps/documentation/javascript/get-api-key"


	# Create the output file

	try:
		fields = input_layer.fields()
	except:
		return "Invalid layer"

	if web_service == "Google":
		for field_name in ["result_num", "status", "formatted_address", "place_id", \
				   "location_type", "latlong"]:
			fields.append(QgsField (field_name, QVariant.String))

	elif web_service == "OpenStreetMap / Nominatim":
		for field_name in ["result_num", "osm_id", "display_name", "category", "type", "latlong"]:
			fields.append(QgsField (field_name, QVariant.String))

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, fields, \
		input_layer.wkbType(), input_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return str(outfile.errorMessage())


	# HTTP(S) proxy settings from qgis options settings
	mmqgis_proxy_settings()


	# Coordinates to the web services assumed to be WGS 84 latitude/longitude
	wgs84 = QgsCoordinateReferenceSystem()

	wgs84.createFromProj4("+proj=longlat +datum=WGS84 +no_defs")

	transform = QgsCoordinateTransform(input_layer.crs(), wgs84, QgsProject.instance())

	# Iterate through each feature in the source layer
	feature_count = input_layer.featureCount()
	result_count = 0

	for feature_index, feature in enumerate(input_layer.getFeatures()):
		if status_callback and ((feature_index % 3) == 0):
			if status_callback(100 * feature_index / feature_count, 
					"Feature " + str(feature_index) + " of " + str(feature_count)):
				return "Cancelled on feature " + str(feature_index)

		# Use the centroid as the latitude and longitude
		point = feature.geometry().centroid().asPoint()
		point = transform.transform(point)
		latitude = point.y()
		longitude = point.x()

		# API URL
		if web_service == "Google":
			url = "https://maps.googleapis.com/maps/api/geocode/json?latlng=" + \
				str(latitude) + "," + str(longitude) + "&key=" + api_key
		else:
			url = "https://nominatim.openstreetmap.org/reverse?&format=geojson&lat=" + \
				str(latitude) + "&lon=" + str(longitude)

		# Query the API
		max_attempts = 5
		for attempt in range(1, max_attempts + 1):
			try:
				# Avoids the dreaded SSL: CERTIFICATE_VERIFY_FAILED error
				# https://datumorphism.com/til/data/python-urllib-ssl/
				# Ignore SSL certificate errors
				request_context = ssl.create_default_context()
				request_context.check_hostname = False
				request_context.verify_mode = ssl.CERT_NONE

				# https://operations.osmfoundation.org/policies/nominatim/
				user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3)"
				request = urllib.request.Request(url, headers={'User-Agent': user_agent})
				json_string = urllib.request.urlopen(request, context=request_context).read()
				break

			except Exception as e:
				if (attempt >= max_attempts):
					return "Failure connecting to API: " + str(e)

				# Wait a second and try again
				time.sleep(1)

		new_feature = QgsFeature()
		new_feature.setGeometry(feature.geometry())

		try:
			json_array = json.loads(json_string.decode("utf-8"))

		except Exception as e:
			attributes = feature.attributes()
			attributes.append(str(-1))
			attributes.append(str(e))
			new_feature.setAttributes(feature.attributes())
			outfile.addFeature(new_feature)
			continue

		if web_service == "Google":

			# Check status
			# https://developers.google.com/maps/documentation/geocoding/intro#GeocodingRequests
			if "status" in json_array:
				status = json_array["status"]
			else:
				status = "No status"

			if "error_meessage" in json_array:
				error_messsage = json_array["error_message"]
			else:
				error_message = ""

			if (status == "REQUEST_DENIED") or (status == "OVER_QUERY_LIMIT"):
				return status + ": " + error_message

			if status != "OK":
				attributes = feature.attributes()
				attributes.append(str(-1))
				attributes.append(status)
				attributes.append(error_message)

				new_feature.setAttributes(attributes)
				outfile.addFeature(new_feature)
				continue
				
			# No results found (shouldn't happen?)

			if (not "results" in json_array) or (len(json_array["results"]) <= 0):
				attributes = feature.attributes()
				attributes.append(str(-1))
				attributes.append("No results")
				new_feature.setAttributes(attributes)
				outfile.addFeature(new_feature)
				continue


			# Iterate through results

			for result_num, result in enumerate(json_array['results']):

				# Collect attributes

				attributes = feature.attributes()
				attributes.append(str(result_num))
				attributes.append(status)

				if "formatted_address" in result:
					attributes.append(str(result["formatted_address"]))
				else:
					attributes.append("")

				if "place_id" in result:
					attributes.append(str(result["place_id"]))
				else:
					attributes.append("")

				try:
					latitude = float(result["geometry"]["location"]["lat"])
					longitude = float(result["geometry"]["location"]["lng"])

					attributes.append(str(result["geometry"]["location_type"]))
					attributes.append(str(latitude) + "," + str(longitude))
				except Exception as e:
					attributes.append("")
					attributes.append("")

					
				# Add feature

				new_feature.setAttributes(attributes)
				outfile.addFeature(new_feature)
				result_count = result_count + 1

				if use_first:
					break

		else: # OSM/Nominatim
			# https://nominatim.org/release-docs/develop/api/Reverse/
			if "error" in json_array:
				if "message" in json_array["error"]:
					error_message = json_array["error"]["message"]
				else:
					error_message = "Undefined Error"

				attributes = feature.attributes()
				attributes.append(str(-1))
				attributes.append(error_message)

				new_feature.setAttributes(attributes)
				outfile.addFeature(new_feature)
				continue

			if (not "features" in json_array) or (len(json_array["features"]) <= 0):
				attributes = feature.attributes()
				attributes.append(str(-1))
				attributes.append("No results")

				new_feature.setAttributes(attributes)
				outfile.addFeature(new_feature)
				continue

			for result_num, result in enumerate(json_array['features']):

				# Collect attributes
					
				attributes = feature.attributes()
				attributes.append(str(result_num))

				for property_name in ["osm_id", "display_name", "category", "type"]:
					if ("properties" in result) and (property_name in result["properties"]):
						attributes.append(str(result["properties"][property_name]))
					else:
						attributes.append("")
			
				try:
					latitude = float(result["geometry"]["coordinates"][1])
					longitude = float(result["geometry"]["coordinates"][0])
					attributes.append(str(latitude) + "," + str(longitude))

				except Exception as e:
					attributes.append("")


				# Add feature

				new_feature.setAttributes(attributes)
				outfile.addFeature(new_feature)
				result_count = result_count + 1

				if use_first:
					break

	del outfile

	if status_callback:
		status_callback(100, str(result_count) + " of " + str(input_layer.featureCount()) + " reverse geocoded")

	return None


# ---------------------------------------------------------------------------------------
#    mmqgis_geocode_street_layer - Geocode addresses from street address finder layer
# ---------------------------------------------------------------------------------------

# Use common address abbreviations to reduce naming discrepancies and improve hit ratio

def mmqgis_searchable_streetname(name):
	# print "searchable_name(" + str(name) + ")"
	if not name:
		return ""

	# name = str(name).strip().lower()
	name = name.strip().lower()

	name = name.replace(".", "")
	name = name.replace(" street", " st")
	name = name.replace(" avenue", " av")
	name = name.replace(" plaza", " plz")
	name = name.replace(" drive", " dr")
	name = name.replace("saint ", "st ")
	name = name.replace("fort ", "ft ")
	name = name.replace(" ave", " av")

	name = name.replace("east", "e")
	name = name.replace("west", "w")
	name = name.replace("north", "n")
	name = name.replace("south", "s")
	name = name.replace("1st", "1")
	name = name.replace("2nd", "2")
	name = name.replace("3rd", "3")
	name = name.replace("4th", "4")
	name = name.replace("5th", "5")
	name = name.replace("6th", "6")
	name = name.replace("7th", "7")
	name = name.replace("8th", "8")
	name = name.replace("9th", "9")
	name = name.replace("0th", "0")
	name = name.replace("1th", "1")
	name = name.replace("2th", "2")
	name = name.replace("3th", "3")

	name = name.replace("first", "1")
	name = name.replace("second", "2")
	name = name.replace("third", "3")
	name = name.replace("fourth", "4")
	name = name.replace("fifth", "5")
	name = name.replace("sixth", "6")
	name = name.replace("seventh", "7")
	name = name.replace("eighth", "8")
	name = name.replace("ninth", "9")
	name = name.replace("tenth", "10")

	return name

def mmqgis_geocode_street_layer(input_csv_name, number_column, street_name_column, zip_column, \
	input_layer, street_name_attr, left_from_attr, left_to_attr, left_zip_attr, \
	right_from_attr, right_to_attr, right_zip_attr, \
	from_x_attr, from_y_attr, to_x_attr, to_y_attr, setback, \
	output_file_name, not_found_file, status_callback = None):

	# Error checks

	try:
		input_layer.featureCount()
	except:
		return "Invalid input street layer"

	if (input_layer.wkbType() != QgsWkbTypes.LineString) and \
	   (input_layer.wkbType() != QgsWkbTypes.LineString25D) and \
	   (input_layer.wkbType() != QgsWkbTypes.MultiLineString) and \
	   (input_layer.wkbType() != QgsWkbTypes.MultiLineString25D):
		return "Street layer must be lines or multilines (WKB Type " + str(input_layer.wkbType()) + ")"

	if (not street_name_attr) or (input_layer.dataProvider().fieldNameIndex(str(street_name_attr)) < 0):
		return "Invalid street name attribute: " + str(street_name_attr)

	if (not left_from_attr) or (input_layer.dataProvider().fieldNameIndex(str(left_from_attr)) < 0):
		return "Invalid left from attribute: " + str(left_from_attr)

	if (not left_to_attr) or (input_layer.dataProvider().fieldNameIndex(str(left_to_attr)) < 0):
		return "Invalid left to attribute: " + str(left_to_attr)

	if left_zip_attr and (input_layer.dataProvider().fieldNameIndex(str(left_zip_attr)) < 0):
		return "Invalid left ZIP Code attribute: " + str(left_zip_attr)

	if (not right_from_attr) or (input_layer.dataProvider().fieldNameIndex(str(right_from_attr)) < 0):
		return "Invalid right from attribute: " + str(right_from_attr)

	if (not right_to_attr) or (input_layer.dataProvider().fieldNameIndex(str(right_to_attr)) < 0):
		return "Invalid right to attribute: " + str(right_to_attr)

	if right_zip_attr and (input_layer.dataProvider().fieldNameIndex(str(right_zip_attr)) < 0):
		return "Invalid right ZIP Code attribute: " + str(right_zip_attr)

	if from_x_attr and (input_layer.dataProvider().fieldNameIndex(str(from_x_attr)) < 0):
		return "Invalid from x attribute: " + str(from_x_attr)
	
	if from_y_attr and (input_layer.dataProvider().fieldNameIndey(str(from_y_attr)) < 0):
		return "Invalid from y attribute: " + str(from_y_attr)
	
	if to_x_attr and (input_layer.dataProvider().fieldNameIndex(str(to_x_attr)) < 0):
		return "Invalid to x attribute: " + str(to_x_attr)
	
	if to_y_attr and (input_layer.dataProvider().fieldNameIndey(str(to_y_attr)) < 0):
		return "Invalid to y attribute: " + str(to_y_attr)
	
	try:
		setback = float(setback)
	except Exception as e:
		return "Invalid setback value: " + str(e)

	
	# Open CSV file and validate fields
	if status_callback:
		status_callback(0, "Opening Files")

	if not input_csv_name:
		return "No input CSV file name given"

	input_csv = QgsVectorLayer(input_csv_name)

	if (not input_csv) or (input_csv.featureCount() <= 0) or (len(input_csv.fields()) <= 0):
		return "Failure opening input file: " + str(input_csv_name)

	if input_csv.dataProvider().fieldNameIndex(str(number_column)) < 0:
		return "Invalid CSV number column: " + str(number_column)

	if input_csv.dataProvider().fieldNameIndex(str(street_name_column)) < 0:
		return "Invalid CSV street name column: " + str(street_name_column)

	if zip_column and (input_csv.dataProvider().fieldNameIndex(str(zip_column)) < 0):
		return "Invalid CSV ZIP Code column: " + str(zip_column)


	# Create the not found file for addresses that were not valid or not found

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = 'CSV'
	save_options.fileEncoding = 'UTF-8'

	not_found = QgsVectorFileWriter.create(not_found_file, input_csv.fields(), \
		QgsWkbTypes.Unknown, input_layer.crs(), \
		QgsProject.instance().transformContext(), \
		save_options)

	if (not_found.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating not found CSV file: " + str(not_found.errorMessage())


	# Create the output shapefile
	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	new_fields = input_csv.fields()
	new_fields.append(QgsField("Longitude", QVariant.Double, "real", 24, 16))
	new_fields.append(QgsField("Latitude", QVariant.Double, "real", 24, 16))
	new_fields.append(QgsField("Side", QVariant.String))

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, new_fields, \
		QgsWkbTypes.Point, input_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())


	# Iterate through each CSV row
	matched_count = 0
	for address_index, address in enumerate(input_csv.getFeatures()):
		if status_callback and ((address_index % 2) == 0):
			if status_callback(100 * address_index / input_csv.featureCount(),
			   str(matched_count) + " of " + str(address_index) + " matched"):
				return "Cancelled geocode at address " + \
					str(address_index) + " of " + str(input_csv.featureCount())

		# Find parts of this address
		street = mmqgis_searchable_streetname(str(address.attribute(street_name_column)))
		if not street:
			new_feature = QgsFeature()
			new_feature.setAttributes(address.attributes())
			not_found.addFeature(new_feature)
			continue

		try:
			number = int(address.attribute(number_column))
		except:
			number = 0

		zip_code = None
		if zip_column:
			zip_code = str(address.attribute(zip_column))


		# Iterate through each feature in the street layer
		found = False
		for feature_index, feature in enumerate(input_layer.getFeatures()):

			# Compare street names
			feature_street = mmqgis_searchable_streetname(str(feature.attribute(street_name_attr)))
			if (not feature_street) or (feature_street != street):
				# Not on this street
				continue 

			# Compare street numbers and find distance along the side
			try:
				left_to_number = int(feature.attribute(left_to_attr))
				left_from_number = int(feature.attribute(left_from_attr))
				right_to_number = int(feature.attribute(right_to_attr))
				right_from_number = int(feature.attribute(right_from_attr))

			except:
				left_to_number = 0
				left_from_number = 0
				right_to_number = 0
				right_from_number = 0

			left_side = False
			right_side = False
			if ((left_from_number < left_to_number) and \
			    (number >= left_from_number) and (number <= left_to_number)) or \
			   ((number <= left_from_number) and (number >= left_to_number)):
				left_side = True
				if left_from_number == left_to_number:
					distance_ratio = 0
				else:
					distance_ratio = (number - left_from_number) / (left_to_number - left_from_number)

			if ((right_from_number < right_to_number) and \
			    (number >= right_from_number) and (number <= right_to_number)) or \
			   ((number <= right_from_number) and (number >= right_to_number)):
				# Check odd/even numbering match
				if (not left_side) or ((number % 2) == (right_from_number % 2)):
					left_side = False
					right_side = True
					if right_from_number == right_to_number:
						distance_ratio = 0
					else:
						distance_ratio = (number - right_from_number) / \
							(right_to_number - right_from_number)

			if (not left_side) and (not right_side):
				continue

			#print("Street match " + feature_street + " number " + \
			#	str(number) + " right " + str(right_from_number) + " - " + str(right_to_number) + \
			#	", left " + str(left_from_number) + " - " + str(left_to_number) + " = " + \
			#	str(left_side) + ", " + str(right_side))

			# Compare ZIP Codes
			# Exclusion condition to filter duplicate street/number addresses in different zip codes

			if zip_code:
				if left_zip_attr and (zip_code != str(feature.attribute(left_zip_attr))) and \
				   right_zip_attr and (zip_code != str(feature.attribute(right_zip_attr))):
					#print("ZIP exclude " + str(zip_code) + " <> " \
					#	+ str(feature.attribute(left_zip_attr)) \
					#	+ " <> " + str(feature.attribute(right_zip_attr)))
					continue

			# Find line start and end points
			geometry = feature.geometry()
			if (geometry.wkbType() == QgsWkbTypes.LineString) or \
			   (geometry.wkbType() == QgsWkbTypes.LineString25D):
				line = geometry.asPolyline()

			elif (geometry.wkbType() == QgsWkbTypes.MultiLineString) or \
			     (geometry.wkbType() == QgsWkbTypes.MultiLineString25D):
				line = []
				for polyline in geometry.asMultiPolyline():
					for point in polyline:
						line.append(point)

			else:
				continue # errant geometry type?!

			# Assume from/to x/y ignores input layer geometry
			if from_x_attr and feature.attributes(from_x_attr) and \
			   from_y_attr and feature.attributes(from_y_attr) and \
			   to_x_attr and feature.attributes(to_x_attr) and \
			   to_y_attr and feature.attributes(to_y_attr):
				try:
					polyline = [QgsPointXY(float(feature.attributes(from_x_attr)),
							float(feature.attributes(from_y_attr))),
						    QgsPointXY(float(feature.attributes(to_x_attr)),
							float(feature.attributes(to_y_attr)))]
					line = QgsGeometry.fromPolyline(polyline)
				except:
					line = line


			# Find total line length
			total_length = 0
			for z in range(len(line) - 1):
				x_diff = line[z + 1][0] - line[z][0]
				y_diff = line[z + 1][1] - line[z][1]
				total_length = total_length + pow(pow(x_diff, 2) + pow(y_diff, 2), 0.5)

			# Find the position along the street centerline
			x = line[0][0]
			y = line[0][1]

			start_distance = 0;
			distance_along_centerline = setback + (distance_ratio * (total_length - (2 * setback)))
			for z in range(len(line) - 1):
				x_diff = line[z + 1][0] - line[z][0]
				y_diff = line[z + 1][1] - line[z][1]
				segment_length = pow(pow(x_diff, 2) + pow(y_diff, 2), 0.5)
				end_distance = start_distance + segment_length

				if distance_along_centerline > end_distance:
					start_distance = end_distance
					continue

				segment_ratio = (distance_along_centerline - start_distance) / (end_distance - start_distance)
				x = line[z][0] + (segment_ratio * (line[z + 1][0] - line[z][0]))
				y = line[z][1] + (segment_ratio * (line[z + 1][1] - line[z][1]))

				# Setback from centerline
				bearing = atan2(y_diff, x_diff)

				# print("Number " + str(number) + ", segment " + str(z) \
				#	+ ", bearing, " + str(bearing) + ", left " \
				#	+ str(left_side) + ", right odd agreement " \
				#	+ str((not left_side) or ((number % 2) == (right_from_number % 2))))

				if right_side:
					x = x + (setback * sin(bearing))
					y = y - (setback * cos(bearing))
				else:
					x = x - (setback * sin(bearing))
					y = y + (setback * cos(bearing))
				break

			# Create the output feature
			new_attributes = address.attributes()
			new_attributes.append(x)
			new_attributes.append(y)
			if left_side:
				new_attributes.append("Left")
			else:
				new_attributes.append("Right")

			newfeature = QgsFeature()
			newfeature.setAttributes(new_attributes)
			newfeature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
			outfile.addFeature(newfeature)
			matched_count = matched_count + 1

			found = True
			break

		if not found:
			new_feature = QgsFeature()
			new_feature.setAttributes(address.attributes())
			not_found.addFeature(new_feature)

	# Done
	if status_callback:
		status_callback(100, str(matched_count) + " of " + str(input_csv.featureCount()) + " geocoded")

	return None


# ----------------------------------------------------------------------
#    mmqgis_geocode_web_service - Geocode CSV points from a web service
# ----------------------------------------------------------------------

def mmqgis_geocode_web_service(input_csv_name, parameter_attributes, web_service, api_key, use_first,
	output_file_name, not_found_file_name, status_callback = None):

	# Error checks
	supported_services = ["Google", "OpenStreetMap / Nominatim", "US Census Bureau", "ESRI Server", "NetToolKit"]

	if web_service not in supported_services:
		return "Invalid web service name: " + str(web_service)

	if (web_service in ["Google", "NetToolKit"]) and (not api_key):
		return "A " + web_service + " API key is required to use this service"

	if (web_service == "ESRI Server") and ((not api_key) or (api_key[0:5] != "https")):
		return "An ESRI server URL is required to use ESRI geocoding"

	# Load the CSV file

	if not input_csv_name:
		return "No input CSV file name given"

	input_csv = QgsVectorLayer(input_csv_name)

	if (not input_csv) or (input_csv.featureCount() <= 0) or (len(input_csv.fields()) <= 0):
		return "Failure opening input file: " + str(input_csv_name)


	# Dictionary of key indices into attributes
	if not parameter_attributes or (not len(parameter_attributes)):
		return "Invalid search parameters"

	parameter_indices = []
	for attribute in parameter_attributes:
		index = input_csv.fields().indexOf(attribute[1])

		if index < 0:
			return "Invalid parameter attribute: " + attribute[1]

		parameter_indices.append((attribute[0], index))

	
	# Create attributes from field names in header
	# Add fields for the <type> and <location_type> returned by Google
	# or the class and type returned by OSM

	fields = QgsFields()
	for field in input_csv.fields():
		fields.append(field)

	if web_service == "Google":
		for field_name in ["result_num", "status", "formatted_address", "place_id", "location_type", "latlong"]:
			fields.append(QgsField (field_name, QVariant.String))

	elif web_service == "OpenStreetMap / Nominatim":
		for field_name in ["result_num", "osm_id", "display_name", "category", "type", "latlong"]:
			fields.append(QgsField (field_name, QVariant.String))

	elif web_service == "ESRI Server":
		for field_name in ["result_num", "score", "address_match", "Loc_name", "Addr_type", "User_fld", "latlong"]:
			fields.append(QgsField (field_name, QVariant.String))

	elif web_service == "US Census Bureau":
		for field_name in ["result_num", "matchedAddress", "tigerLineId", "side", "latlong"]:
			fields.append(QgsField (field_name, QVariant.String))

	elif web_service == "NetToolKit":
		for field_name in ["result_num", "address", "provider", "latlong"]:
			fields.append(QgsField (field_name, QVariant.String))



	# Create the CSV file for ungeocoded records

	try:
		notfound = open(not_found_file_name, 'w')

	except Exception as e:
		return str(e)

	# Kludge to prevent writer from crashing in Windoze 
	# Opening in local encoding rather than UTF-8?
	# dialect.escapechar = '\\' 

	notwriter = csv.writer(notfound)

	notwriter.writerow([x.name() for x in input_csv.fields()])

	# Web geocoders use WGS 84 lat/long
	crs = QgsCoordinateReferenceSystem(4326, QgsCoordinateReferenceSystem.EpsgCrsId)

	# Create the output spatial file
	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", \
		".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = file_formats[os.path.splitext(output_file_name)[1]]
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, fields, \
			QgsWkbTypes.Point, crs, \
			QgsProject.instance().transformContext(), \
			save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())

	# Proxy settings from qgis options settings
	mmqgis_proxy_settings()


	# Geocode and import
	matched_count = 0
	for row_number, row in enumerate(input_csv.getFeatures()):

		if status_callback and ((row_number % 5) == 0):
			if status_callback(100 * row_number / input_csv.featureCount(), \
			   str(row_number) + " of " + str(input_csv.featureCount()) + " = " + str(matched_count) + " found"):
				return "Cancelled a row " + str(row_number) + " of " + str(input_csv.featureCount())

		# Build escaped search parameters
		parameters = []
		for index in parameter_indices:

			if index[1] < len(row.attributes()):
				value = row.attributes()[index[1]]
			else:
				value = ""
				
			try:
				# The str coversion throws an exception on non-utf-8 characters
				# However, urllib.quote() requires the encoded string or it throws an error
				# utf8_test = str(row[x], "utf-8").strip()
				# print utf8_test
				value = urllib.parse.quote(value.strip())
				value = value.replace(" ","+")
			except Exception as e:
				value = ""

			parameters.append((index[0], value))


		# Build composite address used by Google and Nominatim
		address = ""
		sorted_names = list
		for parameter in parameters:
			if len(address) > 0:
				address += "%2C"

			address += parameter[1]

		# Skip if no search keys
		if len(address) <= 0:
			notwriter.writerow(attributes)
			continue

		# Create API URL
		if web_service == "Google":
			url = "https://maps.googleapis.com/maps/api/geocode/json?sensor=false&address=" \
				+ address + "&key=" + api_key

		elif web_service == "OpenStreetMap / Nominatim":
			url = "http://nominatim.openstreetmap.org/search?format=geojson&q=" + address

		elif web_service == "ESRI Server":
			# api_key field is used as the server URL with ESRI servers
			url = api_key + "?SingleLine=" + address + \
				"&category=&outFields=*&maxLocations=&outSR=4326" + \
				"&searchExtent=&location=&distance=&magicKey=&f=json"

		elif web_service == "US Census Bureau":
			url = "https://geocoding.geo.census.gov/geocoder/locations/address?&benchmark=4&format=json"

			# street, city, state
			for parameter in parameters:
				if parameter[0].lower() == "address":
					url = url + "&street=" + str(parameter[1])
				else:
					url = url + "&" + str(parameter[0]).lower() + "=" + str(parameter[1])

		elif web_service == "NetToolKit":
			# API key is passed in the HTTP header below
			url = "https://api.nettoolkit.com/v1/geo/geocodes?address=" + address


		# Query the API
		max_attempts = 5
		for attempt in range(1, max_attempts + 1):
			try:
				# Avoids the dreaded SSL: CERTIFICATE_VERIFY_FAILED error
				# https://datumorphism.com/til/data/python-urllib-ssl/
				# Ignore SSL certificate errors
				request_context = ssl.create_default_context()
				request_context.check_hostname = False
				request_context.verify_mode = ssl.CERT_NONE

				# https://operations.osmfoundation.org/policies/nominatim/
				# 11/9/2024: Added referer to avoid 403 prohibited error

				headers = {'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0)",
					'Referer': 'https://plugins.qgis.org/plugins/mmqgis/' }

				# headers = {'User-Agent': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3)" }

				if web_service == "NetToolKit":
					headers['X-NTK-KEY'] = api_key

				# print(headers)

				request = urllib.request.Request(url, headers = headers)

				json_string = urllib.request.urlopen(request, context=request_context).read()

				# print(str(json_string) + "\n\n")

				break

			except Exception as e:
				if (attempt >= max_attempts):
					return "Failure connecting to API: " + str(e)

				# Wait a second and try again
				time.sleep(1)

		try:
			json_array = json.loads(json_string.decode("utf-8"))

		except Exception as e:
			continue

		# Interpret the response
		if web_service == "Google":
			# https://developers.google.com/maps/documentation/geocoding/intro#GeocodingRequests
			if (not "status" in json_array) or \
			   (not "results" in json_array) or \
			   (len(json_array['results']) <= 0):
				notwriter.writerow(row.attributes())
				continue
			
			if "error_meessage" in json_array:
				error_message = json_array["error_message"]
			else:
				error_message = ""

			if (json_array["status"] == "REQUEST_DENIED") or \
			   (json_array["status"] == "OVER_QUERY_LIMIT"):
				return str(json_array["status"]) + ": " + str(error_message)

			if json_array["status"] != "OK":
				notwriter.writerow(row.attributes())
				continue

			for result_num, result in enumerate(json_array["results"]):
				try:
					latitude = float(result["geometry"]["location"]["lat"])
					longitude = float(result["geometry"]["location"]["lng"])

				except Exception as e:
					# Invalid result
					notwriter.writerow(row.attributes())
					break

				# Collect attributes					
				attributes = row.attributes()
				attributes.append(str(result_num))
				attributes.append(str(json_array["status"]))

				if "formatted_address" in result:
					attributes.append(str(result["formatted_address"]))
				else:
					attributes.append("")

				if "place_id" in result:
					attributes.append(str(result["place_id"]))
				else:
					attributes.append("")

				if "location_type" in result["geometry"]:
					attributes.append(str(result["geometry"]["location_type"]))
				else:
					attributes.append("")

				latitude = float(result["geometry"]["location"]["lat"])
				longitude = float(result["geometry"]["location"]["lng"])
				attributes.append(str(latitude) + "," + str(longitude))

				# Add new feature
				newfeature = QgsFeature()
				newfeature.setAttributes(attributes)
				newfeature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(longitude, latitude)))
				outfile.addFeature(newfeature)
				matched_count += 1

				if use_first:
					break

		elif web_service == "OpenStreetMap / Nominatim":
			# https://nominatim.org/release-docs/develop/api/Search/
			
			if (not "features" in json_array) or (len(json_array["features"]) <= 0):
				notwriter.writerow(row.attributes())
				continue
			
			for result_num, result in enumerate(json_array["features"]):
				try:
					latitude = float(result["geometry"]["coordinates"][1])
					longitude = float(result["geometry"]["coordinates"][0])

				except Exception as e:
					# Invalid result
					notwriter.writerow(row.attributes())
					break

				# Collect attributes
					
				attributes = row.attributes()
				attributes.append(str(result_num))

				for property_name in ["osm_id", "display_name", "category", "type"]:
					if property_name in result["properties"]:
						attributes.append(str(result["properties"][property_name]))
					else:
						attributes.append("")
			
				attributes.append(str(latitude) + "," + str(longitude))


				# Create feture

				newfeature = QgsFeature()
				newfeature.setAttributes(attributes)
				newfeature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(longitude, latitude)))
				outfile.addFeature(newfeature)
				matched_count += 1

				if use_first:
					break
			
		elif web_service == "ESRI Server":
			if ("candidates" not in json_array) or (len(json_array["candidates"]) <= 0):
				notwriter.writerow(row.attributes())
				continue
			
			for result_num, result in enumerate(json_array["candidates"]):
				try:
					latitude = float(result["location"]["y"])
					longitude = float(result["location"]["x"])

				except Exception as e:
					notwriter.writerow(row.attributes())
					break


				# Collect attributes

				attributes = row.attributes()
				attributes.append(str(result_num))

				if "score" in result:
					attributes.append(str(result["score"]))
				else:
					attributes.append("")

				if "address" in result:
					attributes.append(str(result["address"]))
				else:
					attributes.append("")

				for attribute_name in ["Loc_name", "Addr_type", "User_fld"]:
					if attribute_name in result["attributes"]:
						attributes.append(str(result["attributes"][attribute_name]))
					else:
						attributes.append("")

				attributes.append(str(latitude) + "," + str(longitude))


				# Add feature

				newfeature = QgsFeature()
				newfeature.setAttributes(attributes)
				newfeature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(longitude, latitude)))
				outfile.addFeature(newfeature)
				matched_count += 1


				if use_first:
					break

		elif web_service == "US Census Bureau":
			if (not "result" in json_array) or \
			   (not "addressMatches" in json_array["result"]) or \
			   (len(json_array["result"]["addressMatches"]) <= 0):
				notwriter.writerow(row.attributes())
				continue
			
			for result_num, result in enumerate(json_array["result"]["addressMatches"]):
				try:
					latitude = float(result["coordinates"]["y"])
					longitude = float(result["coordinates"]["x"])
				except Exception as e:
					notwriter.writerow(row.attributes())
					break

				# Collect attributes

				attributes = row.attributes()
				attributes.append(str(result_num))

				if "matchedAddress" in result:
					attributes.append(str(result["matchedAddress"]))
				else:
					attributes.append("")

				if "tigerLine" in result:
					if "tigerLineId" in result["tigerLine"]:
						attributes.append(str(result["tigerLine"]["tigerLineId"]))
					else:
						attributes.append("")

					if "side" in result["tigerLine"]:
						attributes.append(str(result["tigerLine"]["side"]))
					else:
						attributes.append("")

				attributes.append(str(latitude) + "," + str(longitude))


				# Add feature

				newfeature = QgsFeature()
				newfeature.setAttributes(attributes)
				newfeature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(longitude, latitude)))
				outfile.addFeature(newfeature)
				matched_count += 1

				if use_first:
					break

		elif (web_service == "NetToolKit"):
			if not "results" in json_array:
				notwriter.writerow(row.attributes())
				continue
			
			for result_num, result in enumerate(json_array["results"]):
				try:
					latitude = float(result["latitude"])
					longitude = float(result["longitude"])

				except Exception as e:
					notwriter.writerow(row.attributes())
					break

				# Collect attributes

				attributes = row.attributes()

				attributes.append(str(result_num + 1))

				if "address" in result:
					attributes.append(str(result["address"]))
				else:
					attributes.append("")

				if "provider" in result:
					attributes.append(str(result["provider"]))
				else:
					attributes.append("")

				attributes.append(str(latitude) + "," + str(longitude))


				# Add feature

				newfeature = QgsFeature()
				newfeature.setAttributes(attributes)
				newfeature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(longitude, latitude)))
				outfile.addFeature(newfeature)
				matched_count += 1

				if use_first:
					break

		else:
			return "Invalid web service: " + web_service

	if status_callback:
		status_callback(100, "Geocoded " + str(matched_count) + " of " + str(input_csv.featureCount()))

	del outfile
	del input_csv
	notfound.close()

	return None


# -----------------------------------------------------------------
#    mmqgis_geometry_convert - Convert geometries to simpler types
# -----------------------------------------------------------------

def mmqgis_line_center(geometry, distance_percent):
	try:
		geometry_type = geometry.wkbType()
	except:
		return None

	# Find the list of node points
	# This function is only really meaningful for linestrings

	if (geometry_type in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D]):
		return geometry

	elif (geometry_type in [QgsWkbTypes.LineString, QgsWkbTypes.LineStringZ, QgsWkbTypes.LineString25D]):
		points = geometry.asPolyline()

	elif (geometry_type in [QgsWkbTypes.Polygon, QgsWkbTypes.PolygonZ, QgsWkbTypes.Polygon25D]):
		points = geometry.asPolygon()[0]

	elif (geometry_type in [QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPointZ, QgsWkbTypes.MultiPoint25D]):
		points = geometry.asMultiPoint()

	elif (geometry_type in [QgsWkbTypes.MultiLineString, QgsWkbTypes.MultiLineStringZ, QgsWkbTypes.MultiLineString25D]):
		points = geometry.asMultiPolyline()[0]

	elif (geometry_type in [QgsWkbTypes.MultiPolygon, QgsWkbTypes.MultiPolygonZ, QgsWkbTypes.MultiPolygon25D]):
		points = geometry.asMultiPolygon()[0][0]

	else:
		return None


	# Returns for invalid parameters

	if (len(points) <= 0):
		return None

	if (len(points) <= 1):
		return QgsGeometry.fromPointXY(points[0])

	if (distance_percent <= 0):
		return QgsGeometry.fromPointXY(points[0])

	if (distance_percent >= 100):
		return QgsGeometry.fromPointXY(points[len(points) - 1])


	# Find lengths of segments between nodes

	segment_length = []
	for index in range(0, len(points) - 1):
		point1 = points[index]
		point2 = points[index + 1]
		length = sqrt(((point1.x() - point2.x())**2) + ((point1.y() - point2.y())**2))
		segment_length = segment_length + [length]


	# Find the point on the appropriate segment line

	segment_start = 0
	distance = sum(segment_length) * distance_percent / 100.0
	for index in range(0, len(segment_length)):
		segment_end = segment_start + segment_length[index]

		if (distance >= segment_start) and (distance <= segment_end):
			if (segment_length[index] <= 0):
				ratio = 0
			else:
				ratio = (distance - segment_start) / segment_length[index]

			xdiff = points[index + 1].x() - points[index].x()
			ydiff = points[index + 1].y() - points[index].y()
			linex = points[index].x() + (xdiff * ratio)
			liney = points[index].y() + (ydiff * ratio)

			return QgsGeometry.fromPointXY(QgsPointXY(linex, liney))

		segment_start = segment_end


	# Graceful failure - Shouldn't ever get here

	return QgsGeometry.fromPointXY(points[0])





def mmqgis_geometry_convert(input_layer, new_geometry, output_file_name, status_callback = None):

	if (not input_layer) or (input_layer.type() != QgsMapLayer.VectorLayer):
		return "Vector layer required"

	# Create output file
	if (new_geometry == "Points") or (new_geometry == "Centroids") or \
	   (new_geometry == "Nodes") or (new_geometry == "Line Centers"):
		new_geometry_wkb = QgsWkbTypes.Point

	elif (new_geometry == "Lines"):
		new_geometry_wkb = QgsWkbTypes.LineString

	elif (new_geometry == "Polygons"):
		new_geometry_wkb = QgsWkbTypes.Polygon

	elif (new_geometry == "Multipoints"):
		new_geometry_wkb = QgsWkbTypes.MultiPoint

	elif (new_geometry == "Multilines"):
		new_geometry_wkb = QgsWkbTypes.MultiLineString

	elif (new_geometry == "Multipolygons"):
		new_geometry_wkb = QgsWkbTypes.MultiPolygon

	else:
		return "Invalid type for new geometry: " + str(new_geometry)

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, input_layer.fields(), \
		new_geometry_wkb, input_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return str(outfile.errorMessage())

	# Iterate through each feature in the source layer
	out_count = 0

	for feature_index, feature in enumerate(input_layer.getFeatures()):
		# shapeid = str(feature.id()).strip()

		if status_callback and ((feature_index % 10) == 0):
			if status_callback(100 * feature_index / input_layer.featureCount(), \
				"Feature " + str(feature_index) + " of " + str(input_layer.featureCount())):
				return "Canceled on feature " + str(feature_index) + " of" + str(input_layer.featureCount())

		if (feature.geometry().wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D]):

			if (new_geometry == "Points"):
				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(QgsGeometry.fromPointXY(feature.geometry().asPoint()))
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			else:
				return "Invalid Conversion: " + \
					QgsWkbTypes.displayString(feature.geometry().wkbType()) + \
					" to " + str(new_geometry)

		elif (feature.geometry().wkbType() == QgsWkbTypes.LineString) or \
		     (feature.geometry().wkbType() == QgsWkbTypes.LineString25D):

			if (new_geometry == "Nodes"):
				polyline = feature.geometry().asPolyline()
				for point in polyline:
					newfeature = QgsFeature()
					newfeature.setAttributes(feature.attributes())
					newfeature.setGeometry(QgsGeometry.fromPointXY(point))
					outfile.addFeature(newfeature)
					out_count = out_count + 1

			elif (new_geometry == "Centroids"):
				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(feature.geometry().centroid())
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			elif (new_geometry == "Line Centers"):
				point = mmqgis_line_center(feature.geometry(), 50.0)
				if (not point):
					continue

				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(point)
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			elif (new_geometry == "Lines"):
				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(feature.geometry())
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			elif (new_geometry == "Multilines"):
				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(QgsGeometry.fromMultiPolyline([feature.geometry().asPolyline()]))
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			else:
				return "Invalid Conversion: " + \
					QgsWkbTypes.displayString(feature.geometry().wkbType()) + \
					" to " + new_geometry

		elif (feature.geometry().wkbType() == QgsWkbTypes.Polygon) or \
		     (feature.geometry().wkbType() == QgsWkbTypes.Polygon25D):

			if (new_geometry == "Nodes"):
				polygon = feature.geometry().asPolygon()
				for polyline in polygon:
					for point in polyline:
						newfeature = QgsFeature()
						newfeature.setAttributes(feature.attributes())
						newfeature.setGeometry(QgsGeometry.fromPointXY(point))
						outfile.addFeature(newfeature)
						out_count = out_count + 1

			elif (new_geometry == "Centroids"):
				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(feature.geometry().centroid())
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			elif (new_geometry == "Lines"):
				polygon = feature.geometry().asPolygon()
				for polyline in polygon:
					newfeature = QgsFeature()
					newfeature.setAttributes(feature.attributes())
					newfeature.setGeometry(QgsGeometry.fromPolylineXY(polyline))
					outfile.addFeature(newfeature)
					out_count = out_count + 1

			elif (new_geometry == "Multilines"):
				linestrings = []
				polygon = feature.geometry().asPolygon()
				for polyline in polygon:
					linestrings.append(polyline)

				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(QgsGeometry.fromMultiPolyline(linestrings))
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			elif (new_geometry == "Polygons"):
				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(feature.geometry())
				outfile.addFeature(newfeature)
				out_count = out_count + 1
				
			else:
				return "Invalid Conversion: " + QgsWkbTypes.displayString(feature.geometry().wkbType()) + \
					" to " + new_geometry

		elif (feature.geometry().wkbType() in \
			[QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPointZ, QgsWkbTypes.MultiPoint25D]):

			if (new_geometry == "Points"):
				points = feature.geometry().asMultiPoint()
				for point in points:
					newfeature = QgsFeature()
					newfeature.setAttributes(feature.attributes())
					newfeature.setGeometry(QgsGeometry.fromPointXY(point))
					outfile.addFeature(newfeature)
					out_count = out_count + 1

			elif (new_geometry == "Centroids"):
				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(feature.geometry().centroid())
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			else:
				return "Invalid Conversion: " + QgsWkbTypes.displayString(feature.geometry().wkbType()) + \
					" to " + new_geometry


		elif (feature.geometry().wkbType() == QgsWkbTypes.MultiLineString) or \
		     (feature.geometry().wkbType() == QgsWkbTypes.MultiLineString25D):

			if (new_geometry == "Nodes"):
				polylines = feature.geometry().asMultiPolyline()
				for polyline in polylines:
					for point in polyline:
						newfeature = QgsFeature()
						newfeature.setAttributes(feature.attributes())
						newfeature.setGeometry(QgsGeometry.fromPointXY(point))
						outfile.addFeature(newfeature)
						out_count = out_count + 1

			elif (new_geometry == "Centroids"):
				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(feature.geometry().centroid())
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			elif (new_geometry == "Lines"):
				linestrings = feature.geometry().asMultiPolyline()
				for linestring in linestrings:
					newfeature = QgsFeature()
					newfeature.setAttributes(feature.attributes())
					newfeature.setGeometry(QgsGeometry.fromPolylineXY(linestring))
					outfile.addFeature(newfeature)
					out_count = out_count + 1

			elif (new_geometry == "Line Centers"):
				linestrings = feature.geometry().asMultiPolyline()
				for linestring in linestrings:
					line_center = mmqgis_line_center(QgsGeometry.fromPolylineXY(linestring), 50.0)
					newfeature = QgsFeature()
					newfeature.setAttributes(feature.attributes())
					newfeature.setGeometry(line_center)
					outfile.addFeature(newfeature)
					out_count = out_count + 1

			elif (new_geometry == "Multilines"):
				linestrings = feature.geometry().asMultiPolyline()
				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(QgsGeometry.fromMultiPolyline(linestrings))
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			else:
				return "Invalid Conversion: " + QgsWkbTypes.displayString(feature.geometry().wkbType()) + \
					" to " + new_geometry

		elif (feature.geometry().wkbType() == QgsWkbTypes.MultiPolygon) or \
		     (feature.geometry().wkbType() == QgsWkbTypes.MultiPolygon25D):

			if (new_geometry == "Nodes"):
				polygons = feature.geometry().asMultiPolygon()
				for polygon in polygons:
					for polyline in polygon:
						for point in polyline:
							newfeature = QgsFeature()
							newfeature.setAttributes(feature.attributes())
							newfeature.setGeometry(QgsGeometry.fromPointXY(point))
							outfile.addFeature(newfeature)
							out_count = out_count + 1
	
			elif (new_geometry == "Centroids"):
				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(feature.geometry().centroid())
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			elif (new_geometry == "Lines"):
				polygons = feature.geometry().asMultiPolygon()
				for polygon in polygons:
					for polyline in polygon:
						newfeature = QgsFeature()
						newfeature.setAttributes(feature.attributes())
						newfeature.setGeometry(QgsGeometry.fromPolylineXY(polyline))
						outfile.addFeature(newfeature)
						out_count = out_count + 1

			elif (new_geometry == "Polygons"):
				polygons = feature.geometry().asMultiPolygon()
				for polygon in polygons:
					newfeature = QgsFeature()
					newfeature.setAttributes(feature.attributes())
					newfeature.setGeometry(QgsGeometry.fromPolygonXY(polygon))
					outfile.addFeature(newfeature)
					out_count = out_count + 1

			elif (new_geometry == "Multilines") or (new_geometry == "Multipolygons"):
				polygons = feature.geometry().asMultiPolygon()
				newfeature = QgsFeature()
				newfeature.setAttributes(feature.attributes())
				newfeature.setGeometry(QgsGeometry.fromMultiPolygonXY(polygons))
				outfile.addFeature(newfeature)
				out_count = out_count + 1

			else:
				return "Invalid Conversion: " + QgsWkbTypes.displayString(feature.geometry().wkbType()) + \
					" to " + new_geometry

	del outfile

	if status_callback:
		status_callback(100, str(input_layer.featureCount()) + " features converted to " + str(out_count))

	return None

# -----------------------------------------------------------------------------
#    mmqgis_geometry_to_multipart - Convert singlepart to multipart geometries
# -----------------------------------------------------------------------------

def mmqgis_geometry_to_multipart(input_layer, merge_field, attribute_handling, output_file_name, status_callback = None):

	# Error checking
	if (not input_layer) or (input_layer.type() != QgsMapLayer.VectorLayer):
		return "Invalid Vector Layer"

	point_types = [ QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D,
		QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPointZ, QgsWkbTypes.MultiPoint25D ]

	line_types = [ QgsWkbTypes.LineString, QgsWkbTypes.LineStringZ, QgsWkbTypes.LineString25D, 
		QgsWkbTypes.MultiLineString, QgsWkbTypes.MultiLineStringZ, QgsWkbTypes.MultiLineString25D ]

	polygon_types = [ QgsWkbTypes.Polygon, QgsWkbTypes.PolygonZ, QgsWkbTypes.Polygon25D, 
		QgsWkbTypes.MultiPolygon, QgsWkbTypes.MultiPolygonZ, QgsWkbTypes.MultiPolygon25D ]

	if (input_layer.wkbType() in point_types):
		new_type = QgsWkbTypes.MultiPoint

	elif (input_layer.wkbType() in line_types):
		new_type = QgsWkbTypes.MultiLineString

	elif (input_layer.wkbType() in polygon_types):
		new_type = QgsWkbTypes.MultiPolygon

	else:
		return "Geometry is already multipart: " + QgsWkbTypes.displayString(input_layer.wkbType())

	merge_index = input_layer.dataProvider().fieldNameIndex(merge_field)
	if merge_index < 0:
		return "Invalid merge field: " + merge_field

	
	# Create output file
	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, input_layer.fields(), \
		new_type, input_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())


	# Get a list of all unique keys
	keys = []
	for feature in input_layer.getFeatures():
		attribute = feature.attributes()[merge_index]
		if not attribute in keys:
			keys.append(attribute)


	# Iterate through each key and each feature in the source layer
	merge_count = 0
	for index, key in enumerate(keys):

		new_geometry = []
		new_attributes = []
		
		if status_callback and ((index % 5) == 0):
			if status_callback(100 * index / len(keys),
				"Converting " + str(index) + " of " + str(len(keys))):
				return "Canceled on feature " + str(index) + " of " + str(len(keys))

		for feature in input_layer.getFeatures():

			if feature.attributes()[merge_index] != key:
				continue

			# Convert geometry
			if new_type == QgsWkbTypes.MultiPoint:
				if (feature.geometry().wkbType() in \
					[QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D]):
					new_geometry.append(feature.geometry().asPoint())

				elif (feature.geometry().wkbType() in \
					[QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPointZ, QgsWkbTypes.MultiPoint25D]):
					for point in feature.geometry().asMultiPoint():
						new_geometry.append(point)
				else:
					return "Invalid multipoint geometry type: " + str(feature.geometry().wkbType())

			elif new_type == QgsWkbTypes.MultiLineString:

				if (feature.geometry().wkbType() in \
					[ QgsWkbTypes.LineString, QgsWkbTypes.LineStringZ, QgsWkbTypes.LineString25D]):

					new_geometry.append(feature.geometry().asPolyline())

				elif (feature.geometry().wkbType() in \
					[QgsWkbTypes.MultiLineString, QgsWkbTypes.MultiLineStringZ, \
					 QgsWkbTypes.MultiLineString25D]):

					for polyline in feature.geometry().asMultiPolyline():
						new_geometry.append(polyline)

				else:
					return "Invalid multilinestring geometry type: " + \
						str(feature.geometry().wkbType())

			else: # new_type == QgsWkbTypes.MultiPolygon:

				if (feature.geometry().wkbType() in \
					[QgsWkbTypes.Polygon, QgsWkbTypes.PolygonZ, QgsWkbTypes.Polygon25D]):
					new_geometry.append(feature.geometry().asPolygon())

				elif (feature.geometry().wkbType() in \
					[QgsWkbTypes.MultiPolygon, QgsWkbTypes.MultiPolygonZ, QgsWkbTypes.MultiPolygon25D]):
					for polygon in feature.geometry().asMultiPolygon():
						new_geometry.append(polygon)

				else:
					return "Invalid multipolygon geometry type: " + \
						QgsWkbTypes.displayString(feature.geometry().wkbType())

			# Convert attributes
			if len(new_attributes) <= 0:
				new_attributes = feature.attributes()

			elif attribute_handling == "Sum":
				for zindex, zfield in enumerate(input_layer.fields()):
					zvalue = feature.attributes()[zindex]
					if (zfield.type() == QVariant.Int):
						#xval, test = attributes[zindex].toInt()
						#yval, test = features[y].attributes()[zindex].toInt()
						#attributes[zindex] = QVariant(xval + yval)
						try:
							xval = int(new_attributes[zindex])
							yval = int(zvalue)
							new_attributes[zindex] = xval + yval
						except:
							new_attributes[zindex] = 0

					elif (zfield.type() == QVariant.Double):
						# xval, test = attributes[zindex].toDouble()
						# yval, test = features[y].attributes()[zindex].toDouble()
						# attributes[zindex] = QVariant(xval + yval)
						try:
							xval = float(new_attributes[zindex])
							yval = float(zvalue)
							new_attributes[zindex] = xval + yval
						except:
							new_attributes[zindex] = 0

					# print "      Sum " + str(zindex) + ": " + \
					#	str(attributes[zindex].typeName())


			# print str(key) + ": " + str(type(newgeometry)) + ": " + str(len(newgeometry))

		new_feature = QgsFeature()
		new_feature.setAttributes(new_attributes)

		if new_type == QgsWkbTypes.MultiPoint:
			new_feature.setGeometry(QgsGeometry.fromMultiPointXY(new_geometry))

		elif new_type == QgsWkbTypes.MultiLineString:
			new_feature.setGeometry(QgsGeometry.fromMultiPolylineXY(new_geometry))

		else: # WKBMultiPolygon:
			new_feature.setGeometry(QgsGeometry.fromMultiPolygonXY(new_geometry))

		outfile.addFeature(new_feature)

	del outfile

	if status_callback:
		status_callback(100, str(input_layer.featureCount()) + " features merged to " + str(len(keys)))

	return None



# ----------------------------------------------------------
#    mmqgis_geometry_export_to_csv - Shape node dump to CSV
# ----------------------------------------------------------

def mmqgis_geometry_export_to_csv(input_layer, node_file_name, attribute_file_name, \
	field_delimiter = ",", line_terminator = "\n", status_callback = None):

	if (not input_layer) or (input_layer.type() != QgsMapLayer.VectorLayer):
		return "Invalid Vector Layer " + input_layername

	# CSV Options

	layer_options = []
	if line_terminator == "\r\n":
		layer_options.append("LINEFORMAT=CRLF")
	else:
		layer_options.append("LINEFORMAT=LF")

	if field_delimiter == ";":
		layer_options.append("SEPARATOR=SEMICOLON")
	elif field_delimiter == "\t":
		layer_options.append("SEPARATOR=TAB")
	elif field_delimiter == " ":
		layer_options.append("SEPARATOR=SPACE")
	else:
		layer_options.append("SEPARATOR=COMMA")
		

	# Build field list for CSV file

	node_fields = QgsFields()
	node_fields.append(QgsField("shapeid", QVariant.Int))
	node_fields.append(QgsField("partid", QVariant.Int))
	node_fields.append(QgsField("x", QVariant.Double))
	node_fields.append(QgsField("y", QVariant.Double))

	attribute_fields = QgsFields()
	attribute_fields.append(QgsField("shapeid", QVariant.Int))

	for field in input_layer.fields():
		if input_layer.wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D]:
			node_fields.append(field)
		else:
			attribute_fields.append(field)

	# Create file writers

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = 'CSV'
	save_options.fileEncoding = 'UTF-8'
	save_options.layerOptions = layer_options

	node_file = QgsVectorFileWriter.create(node_file_name, node_fields, \
		QgsWkbTypes.Point, input_layer.crs(), \
		QgsProject.instance().transformContext(), \
		save_options)

	# QgsMessageLog.logMessage("Node file: " + node_file_name)

	if (node_file.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output node file: " + str(node_file.errorMessage())

	attribute_file = None
	if not input_layer.wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D]:
		save_options = QgsVectorFileWriter.SaveVectorOptions()
		save_options.driverName = 'CSV'
		save_options.fileEncoding = 'UTF-8'
		save_options.layerOptions = layer_options

		attribute_file = QgsVectorFileWriter.create(attribute_file_name, attribute_fields, \
			QgsWkbTypes.Unknown, input_layer.crs(), \
			QgsProject.instance().transformContext(), \
			save_options)

		if (attribute_file.hasError() != QgsVectorFileWriter.NoError):
			return "Failure creating output attribute file: " + str(attribute_file.errorMessage())

	# Iterate through each feature in the source layer

	feature_type = ""
	feature_count = input_layer.featureCount()
	for shape_id, feature in enumerate(input_layer.getFeatures()):
		feature_type = str(QgsWkbTypes.displayString(feature.geometry().wkbType()))
		# shapeid = str(feature.id()).strip()
		# print "Feature " + str(feature_index) + " = " + feature_type

		if status_callback and ((shape_id % 10) == 0):
			if status_callback(100 * shape_id / input_layer.featureCount(), \
					"Exporting " + str(shape_id) + " of " + str(input_layer.featureCount())):
				return "Cancelled " + str(shape_id) + " of " + str(input_layer.featureCount())

		# Build attributes
		node = [ shape_id, None, None, None ] 
		attributes = [ shape_id ]

		for attribute in feature.attributes():
			node.append(attribute)
			attributes.append(attribute)

		# Write attributes
		if not feature.geometry().wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D]:
			new_feature = QgsFeature()
			new_feature.setAttributes(attributes)
			attribute_file.addFeature(new_feature)

		# Write nodes
		if (feature.geometry() == None):
			new_feature = QgsFeature()
			new_feature.setAttributes(node)
			node_file.addFeature(new_feature)

		elif feature.geometry().wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D]:
			point = feature.geometry().asPoint()
			node[2] = point.x()
			node[3] = point.y()

			new_feature = QgsFeature()
			new_feature.setAttributes(node)
			node_file.addFeature(new_feature)

		elif feature.geometry().wkbType() in \
			[QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPointZ, QgsWkbTypes.MultiPoint25D]:
			for part_id, point in enumerate(feature.geometry().asMultiPoint()):
				node[1] = part_id
				node[2] = point.x()
				node[3] = point.y()
				
				new_feature = QgsFeature()
				new_feature.setAttributes(node)
				node_file.addFeature(new_feature)

		elif feature.geometry().wkbType() in \
			[QgsWkbTypes.LineString, QgsWkbTypes.LineStringZ, QgsWkbTypes.LineString25D]:
			for point in feature.geometry().asPolyline():
				node[2] = point.x()
				node[3] = point.y()
				
				new_feature = QgsFeature()
				new_feature.setAttributes(node)
				node_file.addFeature(new_feature)

		elif feature.geometry().wkbType() in [QgsWkbTypes.MultiLineString, QgsWkbTypes.MultiLineString25D]:
			for part_id, polyline in enumerate(feature.geometry().asMultiPolyline()):
				for point in polyline:
					node[1] = part_id
					node[2] = point.x()
					node[3] = point.y()
					
					new_feature = QgsFeature()
					new_feature.setAttributes(node)
					node_file.addFeature(new_feature)

		elif feature.geometry().wkbType() in [QgsWkbTypes.Polygon, QgsWkbTypes.PolygonZ, QgsWkbTypes.Polygon25D]:
			# The first polyline in the polygon is the outer ring
			# Subsequent polylines (if any) are inner rings (holes)
			for part_id, polyline in enumerate(feature.geometry().asPolygon()):
				for point in polyline:
					node[1] = part_id
					node[2] = point.x()
					node[3] = point.y()
					
					new_feature = QgsFeature()
					new_feature.setAttributes(node)
					node_file.addFeature(new_feature)

					# Errant legacy code? 7/12/2025
					# row = [ shape_id, str(point.x()), str(point.y()) ]
					# node_file.writerow(row)

		elif feature.geometry().wkbType() in \
			[QgsWkbTypes.MultiPolygon, QgsWkbTypes.MultiPolygonZ, QgsWkbTypes.MultiPolygon25D]:
			# This needs to deal with multipolygon -> polygon -> ring/holes -> nodes
			for part_id, polygon in enumerate(feature.geometry().asMultiPolygon()):
				for polyline in polygon:
					for point in polyline:
						node[1] = part_id
						node[2] = point.x()
						node[3] = point.y()
						
						new_feature = QgsFeature()
						new_feature.setAttributes(node)
						node_file.addFeature(new_feature)

		else:
			return "Unsupported geometry: " + str(QgsWkbTypes.displayString(feature.geometry().wkbType()))

	# Close and return

	del node_file

	if attribute_file:
		del attribute_file

	if status_callback:
		status_callback(100, str(feature_count) + " " + feature_type + " exported")

	return None


# ----------------------------------------------------------------
#    mmqgis_geometry_import_from_csv - Shape node import from CSV
# ----------------------------------------------------------------

def mmqgis_geometry_import_from_csv(input_csv_name, shape_id_field, part_id_field, \
		geometry_type, latitude_field, longitude_field, \
		output_file_name, status_callback = None):

	# Parameter error checks and conversions
	input_csv = QgsVectorLayer(input_csv_name)
	if input_csv.featureCount() <= 0:
		return "Invalid CSV node file"

	if geometry_type != "Point":
		shape_id_index = input_csv.fields().indexFromName(shape_id_field)
		if shape_id_index < 0:
			return "Invalid shape ID field"
	else:
		shape_id_index = -1

	if geometry_type in ["MultiPoint", "MultiLineString", "MultiPolygon"]:
		part_id_index = input_csv.fields().indexFromName(part_id_field)
		if part_id_index < 0:
			return "Invalid part ID field"
	else:
		part_id_index = shape_id_index

	latitude_index = input_csv.fields().indexFromName(latitude_field)
	if latitude_index < 0:
		return "Invalid latitude field"

	longitude_index = input_csv.fields().indexFromName(longitude_field)
	if longitude_index < 0:
		return "Invalid longitude field"

	geometry_types = {
		"Point": QgsWkbTypes.Point,
		"LineString": QgsWkbTypes.LineString,
		"Polygon": QgsWkbTypes.Polygon,
		"MultiPoint": QgsWkbTypes.MultiPoint,
		"MultiLineString": QgsWkbTypes.MultiLineString,
		"MultiPolygon": QgsWkbTypes.MultiPolygon }

	if not geometry_type in geometry_types:
		return "Invalid geometry type: " + geometry_type
	else:
		wkb_type = geometry_types[geometry_type]


	# Create the output shapefile

	fields = QgsFields()
	if (geometry_type == "Point"):
		for field in input_csv.fields():
			fields.append(field)

	else:
		fields.append(input_csv.fields()[shape_id_index])

	# Assume WGS 84?
	crs = QgsCoordinateReferenceSystem(4326, QgsCoordinateReferenceSystem.EpsgCrsId)

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, fields, \
		wkb_type, crs, \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())

	multi = []
	polyline = []
	shape_count = 0
	current_part_id = False
	current_shape_id = False

	for row_number, row in enumerate(input_csv.getFeatures()):
		if status_callback and ((row_number % 10) == 0):
			if status_callback(100 * row_number / input_csv.featureCount(), 
					"Node " + str(row_number) + " of " + str(input_csv.featureCount())):
				return "Canceled at node " + str(row_number)

		if (latitude_index >= len(row.attributes())) or (latitude_index >= len(row.attributes())):
			return "Node file missing lat/long at row " + str(row_number + 1)
	
		point = QgsPointXY(float(row.attributes()[longitude_index]), float(row.attributes()[latitude_index]))

		# Each node is a separate feature in a point file
		if geometry_type == "Point":
			newfeature = QgsFeature()
			newfeature.setAttributes(row.attributes())
			geometry = QgsGeometry.fromPointXY(point)
			newfeature.setGeometry(geometry)
			outfile.addFeature(newfeature)
			shape_count += 1
			continue

		if shape_id_index >= len(row.attributes()):
			return "Node file missing shape ID at row " + str(row_number + 1)
		else:
			row_shape_id = row.attributes()[shape_id_index]
		
		if part_id_index >= len(row.attributes()):
			return "Node file missing part ID at row " + str(row_number + 1)
		else:
			row_part_id = row.attributes()[part_id_index]

		# First line starts the current feature
		if row_number <= 0: 
			current_part_id = row_part_id
			current_shape_id = row_shape_id

		#print("Shape " + str(row_shape_id) + ", Part " + str(row_part_id) + \
		#	", Current shape " + str(current_shape_id) + ", Current part " + str(current_part_id))

		if row_shape_id == current_shape_id:
			if geometry_type == "MultiPoint":
				polyline.append(point)

			elif row_part_id == current_part_id:
				polyline.append(point)

			else:
				multi.append(polyline)
				polyline = [point]
				current_part_id = row_part_id

			# If adding to an existing shape and not on the last row
			if row_number < (input_csv.featureCount() - 1):
				continue

		# Special case kludge = when the final feature when the last line is a new single point multipoint
		elif (geometry_type == "MultiPoint") and (row_number >= (input_csv.featureCount() - 1)):
			geometry = QgsGeometry.fromMultiPointXY([ point ])

			newfeature = QgsFeature()
			newfeature.setAttributes([ row_shape_id ])
			newfeature.setGeometry(geometry)
			outfile.addFeature(newfeature)
			shape_count += 1


		if geometry_type == "LineString":
			geometry = QgsGeometry.fromPolylineXY(polyline)

		elif geometry_type == "MultiPoint":
			geometry = QgsGeometry.fromMultiPointXY(polyline)

		elif geometry_type == "MultiLineString":
			if len(polyline) > 0:
				multi.append(polyline)

			geometry = QgsGeometry.fromMultiPolylineXY(multi)

		elif geometry_type == "MultiPolygon":
			if len(polyline) > 0:
				multi.append(polyline)

			geometry = QgsGeometry.fromMultiPolygonXY([ multi ])

		else: # Polygon
			if len(polyline) < 3:
				return "Polygon with less than 3 nodes at row " + str(index)

			geometry = QgsGeometry.fromPolygonXY([polyline])

		newfeature = QgsFeature()
		newfeature.setAttributes([ current_shape_id ])
		newfeature.setGeometry(geometry)
		outfile.addFeature(newfeature)
		shape_count += 1

		multi = []
		polyline = [ point ]
		current_shape_id = row_shape_id
		current_part_id = row_part_id

	del outfile

	if status_callback:
		status_callback(100, str(shape_count) + " shapes, " + str(input_csv.featureCount()) + " nodes")

	return None


# --------------------------------------------------------
#    mmqgis_grid - Grid shapefile creation
# --------------------------------------------------------

def mmqgis_grid(geometry_type, crs, x_spacing, y_spacing, x_left, y_bottom, x_right, y_top, \
	output_file_name, status_callback = None):

	# Error Checks

	if len(output_file_name) <= 0:
		return "No output filename given"

	if (x_spacing <= 0) or (y_spacing <= 0):
		return "Grid spacing must be positive: " + str(x_spacing) + " x " + str(y_spacing)

	if (x_left >= x_right):
		return "Invalid extent width: " + str(x_left) + " - " + str(x_right)
	
	if (y_bottom >= y_top):
		return "Invalid extent height: " + str(y_bottom) + " - " + str(y_top)
	
	if (x_spacing >= (x_right - x_left)):
		return "X spacing too wide for extent: " + str(x_spacing)

	if (y_spacing >= (y_top - y_bottom)):
		return "Y spacing too tall for extent: " + str(y_spacing)


	# Fields containing coordinates

	fields = QgsFields()
	fields.append(QgsField("left", QVariant.Double))
	fields.append(QgsField("bottom", QVariant.Double))
	fields.append(QgsField("right", QVariant.Double))
	fields.append(QgsField("top", QVariant.Double))


	# Determine shapefile type

	if (geometry_type == "Points") or (geometry_type == "Random Points"):
		geometry_wkb = QgsWkbTypes.Point
		
	elif geometry_type == "Lines":
		geometry_wkb = QgsWkbTypes.LineString

	elif (geometry_type == "Rectangles") or (geometry_type == "Diamonds") or (geometry_type == "Hexagons"):
		geometry_wkb = QgsWkbTypes.Polygon

	else:
		return "Invalid output shape type: " + str(geometry_type)


	# Create output file

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, fields, \
		geometry_wkb, crs, \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())


	# (column + 1) and (row + 1) calculation is used to maintain 
	# topology between adjacent shapes and avoid overlaps/holes 
	# due to rounding errors

	rows = int(ceil((y_top - y_bottom) / y_spacing))
	columns = int(ceil((x_right - x_left) / x_spacing))

	feature_count = 0
	if geometry_type == "Lines":

		for column in range(0, columns + 1):
			for row in range(0, rows + 1):

				x1 = x_left + (column * x_spacing)
				x2 = x_left + ((column + 1) * x_spacing)
				y1 = y_bottom + (row * y_spacing)
				y2 = y_bottom + ((row + 1) * y_spacing)

				# Horizontal line
				if (column < columns):
					line = QgsGeometry.fromPolylineXY([QgsPointXY(x1, y1), QgsPointXY(x2, y1)])
					feature = QgsFeature()
					feature.setGeometry(line)
					feature.setAttributes([x1, y1, x2, y1])
					outfile.addFeature(feature)
					feature_count = feature_count + 1

				# Vertical line
				if (row < rows):
					line = QgsGeometry.fromPolylineXY([QgsPointXY(x1, y1), QgsPointXY(x1, y2)])
					feature = QgsFeature()
					feature.setGeometry(line)
					feature.setAttributes([x1, y1, x1, y2])
					outfile.addFeature(feature)
					feature_count = feature_count + 1

	elif geometry_type == "Rectangles":

		for column in range(0, columns):
			for row in range(0, rows):

				x1 = x_left + (column * x_spacing)
				x2 = x_left + ((column + 1) * x_spacing)
				y1 = y_bottom + (row * y_spacing)
				y2 = y_bottom + ((row + 1) * y_spacing)

				polygon = QgsGeometry.fromPolygonXY([[QgsPointXY(x1, y1), QgsPointXY(x2, y1), \
					QgsPointXY(x2, y2), QgsPointXY(x1, y2), QgsPointXY(x1, y1)]])
				feature = QgsFeature()
				feature.setGeometry(polygon)
				feature.setAttributes([x1, y1, x2, y2])
				outfile.addFeature(feature)
				feature_count = feature_count + 1

	elif (geometry_type == "Points"):

		for column in range(0, columns + 1):
			for row in range(0, rows + 1):

				x = x_left + (column * x_spacing)
				y = y_bottom + (row * y_spacing)

				point = QgsGeometry.fromPointXY(QgsPointXY(x, y))

				feature = QgsFeature()
				feature.setGeometry(point)
				feature.setAttributes([x, y, x, y])
				outfile.addFeature(feature)
				feature_count = feature_count + 1


	elif (geometry_type == "Random Points"):

		for column in range(0, columns):
			for row in range(0, rows):

				x = x_left + (column * x_spacing) + (random.random() * x_spacing)
				y = y_bottom + (row * y_spacing) + (random.random() * y_spacing)

				point = QgsGeometry.fromPointXY(QgsPointXY(x, y))

				feature = QgsFeature()
				feature.setGeometry(point)
				feature.setAttributes([x, y, x, y])
				outfile.addFeature(feature)
				feature_count = feature_count + 1


	elif geometry_type == "Diamonds":

		for column in range(0, (columns * 2) - 1):
			x1 = x_left + ((column + 0) * (x_spacing / 2))
			x2 = x_left + ((column + 1) * (x_spacing / 2))
			x3 = x_left + ((column + 2) * (x_spacing / 2))

			for row in range(0, rows):
				if (column % 2) == 0:
					y1 = y_bottom + (((row * 2) + 0) * (y_spacing / 2))
					y2 = y_bottom + (((row * 2) + 1) * (y_spacing / 2))
					y3 = y_bottom + (((row * 2) + 2) * (y_spacing / 2))
				else:
					y1 = y_bottom + (((row * 2) + 1) * (y_spacing / 2))
					y2 = y_bottom + (((row * 2) + 2) * (y_spacing / 2))
					y3 = y_bottom + (((row * 2) + 3) * (y_spacing / 2))

				polygon = [[QgsPointXY(x1,  y2), QgsPointXY(x2,  y1), QgsPointXY(x3,  y2), \
					QgsPointXY(x2,  y3), QgsPointXY(x1,  y2)]]

				feature = QgsFeature()
				feature.setGeometry(QgsGeometry.fromPolygonXY(polygon))
				feature.setAttributes([ x1, y1, x3, y3 ])
				outfile.addFeature(feature)
				feature_count = feature_count + 1


	elif geometry_type == "Hexagons":
		# To preserve symmetry, hspacing is fixed relative to vspacing
		xvertexlo = 0.288675134594813 * y_spacing;
		xvertexhi = 0.577350269189626 * y_spacing;
		x_spacing = xvertexlo + xvertexhi

		for column in range(0, int(floor(float(x_right - x_left) / x_spacing))):
			# (column + 1) and (row + 1) calculation is used to maintain 
			# _topology between adjacent shapes and avoid overlaps/holes 
			# due to rounding errors

			x1 = x_left + (column * x_spacing)	# far _left
			x2 = x1 + (xvertexhi - xvertexlo)	# _left
			x3 = x_left + ((column + 1) * x_spacing)	# _right
			x4 = x3 + (xvertexhi - xvertexlo)	# far _right

			for row in range(0, int(floor(float(y_top - y_bottom) / y_spacing))):

				if (column % 2) == 0:
					y1 = y_bottom + (((row * 2) + 0) * (y_spacing / 2))	# hi
					y2 = y_bottom + (((row * 2) + 1) * (y_spacing / 2))	# mid
					y3 = y_bottom + (((row * 2) + 2) * (y_spacing / 2))	# lo
				else:
					y1 = y_bottom + (((row * 2) + 1) * (y_spacing / 2))	# hi
					y2 = y_bottom + (((row * 2) + 2) * (y_spacing / 2))	# mid
					y3 = y_bottom + (((row * 2) + 3) * (y_spacing / 2))	#lo

				polygon = [[QgsPointXY(x1, y2), QgsPointXY(x2, y1), QgsPointXY(x3, y1),
					QgsPointXY(x4, y2), QgsPointXY(x3, y3), QgsPointXY(x2, y3), QgsPointXY(x1, y2)]]

				feature = QgsFeature()
				feature.setGeometry(QgsGeometry.fromPolygonXY(polygon))
				feature.setAttributes([ x1, y1, x4, y3 ])
				outfile.addFeature(feature)
				feature_count = feature_count + 1

	del outfile

	if status_callback:
		status_callback(100, str(feature_count) + " feature grid")

	return None

# --------------------------------------------------------
#    mmqgis_gridify - Snap shape verticies to grid
# --------------------------------------------------------

def mmqgis_gridify_points(points, horizontal_spacing, vertical_spacing):
	# Align points to grid
	point_count = 0
	deleted_points = 0
	newpoints = []
	for point in points:
		point_count += 1
		newpoints.append(QgsPointXY(round(point.x() / horizontal_spacing, 0) * horizontal_spacing, \
				    round(point.y() / vertical_spacing, 0) * vertical_spacing))

	# Delete overlapping points
	z = 0
	while z < (len(newpoints) - 2):
		if newpoints[z] == newpoints[z + 1]:
			newpoints.pop(z + 1)
			deleted_points += 1
		else:
			z += 1

	# Delete line points that go out and return to the same place
	z = 0
	while z < (len(newpoints) - 3):
		if newpoints[z] == newpoints[z + 2]:
			newpoints.pop(z + 1)
			newpoints.pop(z + 1)
			deleted_points += 2
			# Step back to catch arcs
			if (z > 0):
				z -= 1
		else:
			z += 1

	# Delete overlapping start/end points
	while (len(newpoints) > 1) and (newpoints[0] == newpoints[len(newpoints) - 1]):
		newpoints.pop(len(newpoints) - 1)
		deleted_points += 2
				
	return newpoints, point_count, deleted_points

def mmqgis_gridify_layer(input_layer, horizontal_spacing, vertical_spacing, output_file_name, status_callback = None):

	# Error checks

	if (not input_layer) or (input_layer.type() != QgsMapLayer.VectorLayer):
		return "Invalid input layer"

	if (horizontal_spacing <= 0) or (vertical_spacing <= 0):
		return "Invalid grid spacing: " + str(horizontal_spacing) + "/" + str(vertical_spacing)

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, input_layer.fields(), \
		input_layer.wkbType(), input_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())

	point_count = 0
	deleted_points = 0

	for feature_index, feature in enumerate(input_layer.getFeatures()):
		if status_callback and ((feature_index % 10) == 0):
			if status_callback(100 * feature_index / input_layer.featureCount(),
				"Feature " + str(feature_index) + " of " + str(input_layer.featureCount())):
				return "Canceled on feature " + str(feature_index) + " of " + str(input_layer.featureCount())

		geometry = feature.geometry()
		if not geometry:
			continue;

		if geometry.wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D]:
			points, added, deleted = mmqgis_gridify_points([geometry.asPoint()], \
				horizontal_spacing, vertical_spacing)
			geometry = geometry.fromPointXY(points[0])
			point_count += added
			deleted_points += deleted

		elif geometry.wkbType() in [QgsWkbTypes.LineString, QgsWkbTypes.LineStringZ, QgsWkbTypes.LineString25D]:
			#print "LineString"
			polyline, added, deleted = mmqgis_gridify_points(geometry.asPolyline(), \
				horizontal_spacing, vertical_spacing)
			if len(polyline) < 2:
				geometry = None
			else:
				geometry = geometry.fromPolylineXY(polyline)
			point_count += added
			deleted_points += deleted

		elif geometry.wkbType() in [QgsWkbTypes.Polygon, QgsWkbTypes.PolygonZ, QgsWkbTypes.Polygon25D]:
			newpolygon = []
			for polyline in geometry.asPolygonXY():
				newpolyline, added, deleted = mmqgis_gridify_points(polyline, \
					horizontal_spacing, vertical_spacing)
				point_count += added
				deleted_points += deleted

				if len(newpolyline) > 1:
					newpolygon.append(newpolyline)

			if len(newpolygon) <= 0:
				geometry = None
			else:
				geometry = geometry.fromPolygonXY(newpolygon)

		elif geometry.wkbType() in [QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPointZ, QgsWkbTypes.MultiPoint25D]:
			newmultipoints = []
			for index, point in enumerate(geometry.asMultiPoint()):
				# print str(index) + ": " + str(type(point))
				gridded, added, deleted = mmqgis_gridify_points([ point ], \
					horizontal_spacing, vertical_spacing, [ point ])
				# append() causes fail in fromMultiPoint(), extend() doesn't
				newmultipoints.extend(gridded)
				point_count += added
				deleted_points += deleted

			geometry = geometry.fromMultiPointXY(newmultipoints)

		elif geometry.wkbType() in \
			[QgsWkbTypes.MultiLineString, QgsWkbTypes.MultiLineStringZ, QgsWkbTypes.MultiLineString25D]:
			#print "MultiLineString"
			newmultipolyline = []
			for polyline in geometry.asMultiPolyline():
				newpolyline, added, deleted = mmqgis_gridify_points(polyline, \
					horizontal_spacing, vertical_spacing)
				if len(newpolyline) > 1:
					newmultipolyline.append(newpolyline)
				point_count += added
				deleted_points += deleted

			if len(newmultipolyline) <= 0:
				geometry = None
			else:
				geometry = geometry.fromMultiPolylineXY(newmultipolyline)


		elif geometry.wkbType() in [QgsWkbTypes.MultiPolygon, QgsWkbTypes.MultiPolygonZ, QgsWkbTypes.MultiPolygon25D]:
			#print "MultiPolygon"
			newmultipolygon = []
			for polygon in geometry.asMultiPolygon():
				newpolygon = []
				for polyline in polygon:
					newpolyline, added, deleted = mmqgis_gridify_points(polyline, \
						horizontal_spacing, vertical_spacing)

					if len(newpolyline) > 2:
						newpolygon.append(newpolyline)

					point_count += added
					deleted_points += deleted

				if len(newpolygon) > 0:
					newmultipolygon.append(newpolygon)

			if len(newmultipolygon) <= 0:
				geometry = None
			else:
				geometry = geometry.fromMultiPolygonXY(newmultipolygon)

		else:
			return "Unknown geometry type " + QgsWkbTypes.displayString(geometry.wkbType()) + \
				" on feature " + str(feature_index)

		# print "Closing feature"
	
		if geometry:
			out_feature = QgsFeature()
			out_feature.setGeometry(geometry)
			out_feature.setAttributes(feature.attributes())
			outfile.addFeature(out_feature)

	del outfile

	if status_callback:
		status_callback(100, "Gridify deleted " + str(deleted_points) + " of " + str(point_count) + " points")

	return None


# ---------------------------------------------------------------------------------
#    mmqgis_hub_distance - Create layer of distances from points to nearest hub
# ---------------------------------------------------------------------------------

def mmqgis_distance(start, end):
	# Assumes points are WGS 84 lat/long
	# Returns great circle distance in meters
	radius = 6378137 # meters
	flattening = 1/298.257223563

	# Convert to radians with reduced latitudes to compensate
	# for flattening of the earth as in Lambert's formula
	start_lon = start.x() * pi / 180
	start_lat = atan2((1 - flattening) * sin(start.y() * pi / 180), cos(start.y() * pi / 180))
	end_lon = end.x() * pi / 180
	end_lat = atan2((1 - flattening) * sin(end.y() * pi / 180), cos(end.y() * pi / 180))

	# Haversine formula
	arc_distance = (sin((end_lat - start_lat) / 2) ** 2) + \
		(cos(start_lat) * cos(end_lat) * (sin((end_lon - start_lon) / 2) ** 2))

	return 2 * radius * atan2(sqrt(arc_distance), sqrt(1 - arc_distance))


def mmqgis_hub_lines(hub_layer, hub_name_field, spoke_layer, spoke_hub_name_field, \
	allocation_criteria, distance_unit, output_geometry, output_file_name, status_callback = None):

	# Error checks
	if (not spoke_layer) or (spoke_layer.type() != QgsMapLayer.VectorLayer):
		return "Invalid point layer"

	if (not hub_layer) or (hub_layer.type() != QgsMapLayer.VectorLayer):
		return "Invalid hub layer"

	if spoke_layer == hub_layer:
		return "Same layer given for both hubs and spokes"

	hub_name_index = hub_layer.dataProvider().fieldNameIndex(hub_name_field)
	if hub_name_index < 0:
		return "Invalid hub name field: " + hub_name_field

	if spoke_hub_name_field:
		spoke_hub_name_index = spoke_layer.dataProvider().fieldNameIndex(spoke_hub_name_field)
		if spoke_hub_name_index < 0:
			return "Invalid spoke hub name field: " + spoke_hub_name_field

	allocation_options = [ "Nearest Hub", "Hub Name in Spoke Layer", "Evenly Distribute" ]
	if not allocation_criteria in allocation_options:
		return "Invalid allocation criteria"

	# Create output file
	if not output_file_name:
		return "Invalid output filename given"

	outfields = spoke_layer.fields()
	outfields.append(QgsField("HubName", QVariant.String))
	outfields.append(QgsField("HubDist", QVariant.Double))

	wgs84 = QgsCoordinateReferenceSystem("PROJ4:+proj=longlat +datum=WGS84 +no_defs")

	if output_geometry == "Lines to Hubs":
		geometry_type = QgsWkbTypes.LineString
	elif output_geometry == "Points":
		geometry_type = QgsWkbTypes.Point
	else:
		return "Invalid allocation criteria"

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, outfields, \
		geometry_type, wgs84, \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())

	# Distance calculations using mmqgis_distance() need 
	# points in unprojected WGS 84 coordinates

	htransform = QgsCoordinateTransform(hub_layer.crs(), wgs84, QgsProject.instance())
	stransform = QgsCoordinateTransform(spoke_layer.crs(), wgs84, QgsProject.instance())


	# Create array of hubs in memory with WGS84 centroids and hub name
	hubs = [] # point, hub_name
	for index, feature in enumerate(hub_layer.getFeatures()):
		if status_callback and ((index % 100) == 0):
			if status_callback(20, "Reading hub " + str(feature.id())):
				return "Cancelled while reading hubs"

		if not feature.geometry():
			continue

		wgs84_hub = feature.geometry().centroid().asPoint()

		if distance_unit != "Layer Units":
			wgs84_hub = htransform.transform(wgs84_hub)
		
		hubs.append([wgs84_hub, feature.attributes()[hub_name_index]])


	# Create array of points in memory with WGS84 centroids and attributes
	spokes = [] # point, attributes
	for index, feature in enumerate(spoke_layer.getFeatures()):
		if status_callback and ((index % 100) == 0):
			if status_callback(40, "Reading point " + str(feature.id())):
				return "Canceled while reading spokes"

		if not feature.geometry():
			continue

		wgs84_point = feature.geometry().centroid().asPoint()

		if distance_unit != "Layer Units":
			wgs84_point = stransform.transform(wgs84_point)

		spokes.append([wgs84_point, feature.attributes()])


	lines = [] # source_point, hub_point, source_attributes, hub_name, hub_distance (meters)

	if allocation_criteria == "Hub Name in Spoke Layer":
		# Scan spoke spokes
		for spoke_index, spoke in enumerate(spokes):

			if status_callback and ((spoke_index % 5) == 0):
				if status_callback(100 * spoke_index / len(spokes),
						"Spoke " + str(spoke_index) + " of " + str(len(spokes))):
					return "Cancelled at spoke " + str(spoke_index)

			spokeid = str(spoke[1][spoke_hub_name_index])

			# Scan hub spokes to find first matching hub
			for hub in hubs:

				if hub[1] != spokeid:
					continue

				if distance_unit == "Layer Units":
					hub_distance = sqrt(pow(spoke[0].x() - hub[0].x(), 2.0) + \
						pow(spoke[0].y() - hub[0].y(), 2.0))
				else:
					hub_distance = mmqgis_distance(spoke[0], hub[0])

				lines.append([spoke[0], hub[0], spoke[1], hub[1], hub_distance])
				break

	elif allocation_criteria == "Evenly Distribute":
		# Sequentially assign spokes to hubs for even distribution
		for index in range(0, len(spokes)):
			lines.append([spokes[index][0], hubs[index % len(hubs)][0], 
				spokes[index][1], hubs[index % len(hubs)][1], 0])

		# Optimize distances by swapping hubs when distance would be shorter for both
		# Arbitrary loop limit of 100 to prevent infinite looping
		for optimizing in range(0, 100):
			swaps = 0
			for x in range(0, len(lines) - 1):
				if status_callback and ((x % 50) == 0):
					if status_callback(60, "Optimizing line " + \
							str(x) + " of " + str(len(spokes)) + \
							"(pass " + str(optimizing + 1) + ")"):
						return "Canceled while optimizing lines"

				for y in range(x + 1, len(lines)):
					# Calculate distances with possible point/hub combinations
					xx = sqrt(pow(lines[x][0].x() - lines[x][1].x(), 2) + \
						  pow(lines[x][0].y() - lines[x][1].y(), 2))
					yy = sqrt(pow(lines[y][0].x() - lines[y][1].x(), 2) + \
						  pow(lines[y][0].y() - lines[y][1].y(), 2))
					xy = sqrt(pow(lines[x][0].x() - lines[y][1].x(), 2) + \
						  pow(lines[x][0].y() - lines[y][1].y(), 2))
					yx = sqrt(pow(lines[y][0].x() - lines[x][1].x(), 2) + \
						  pow(lines[y][0].y() - lines[x][1].y(), 2))

					# Swap hubs if that would shorten both lines or overall length is less
					# if ((xy < xx) and (yx < yy)) or ((xy + yx) < (xx + yy)):
					if ((xy + yx) < (xx + yy)):
						hubx = lines[x][1]
						namex = lines[x][3]
						lines[x][1] = lines[y][1]
						lines[x][3] = lines[y][3]
						lines[y][1] = hubx
						lines[y][3] = namex
						swaps = swaps + 1

			# Keep repeating until minimal length has been reached
			if swaps <= 0:
				break

		# Calculate actual distance
		for x in range(0, len(lines)):
			if distance_unit == "Layer Units":
				lines[x][4] = sqrt(pow(lines[x][0].x() - lines[x][1].x(), 2.0) + \
					pow(lines[x][0].y() - lines[0][1].y(), 2.0))
			else:
				lines[x][4] = mmqgis_distance(lines[x][0], lines[x][1])

	else: # "Find Closest Hub"
		for spoke_index, spoke in enumerate(spokes):
			# Status message
			if status_callback and ((spoke_index % 50) == 0):
				if status_callback(80, "Creating line " + str(spoke_index) + " of " + str(len(spokes))):
					return "Canceled while assigning spokes to hubs"

			# Find closest hub
			closest_index = -1
			closest_distance = 0

			for hub_index, hub in enumerate(hubs):
				if distance_unit == "Layer Units":
					hub_distance = sqrt(pow(spoke[0].x() - hub[0].x(), 2.0) + \
						pow(spoke[0].y() - hub[0].y(), 2.0))
				else:
					hub_distance = mmqgis_distance(spoke[0], hub[0])

				if (closest_index < 0) or (hub_distance < closest_distance):
					closest_index = hub_index
					closest_distance = hub_distance

			# Append to line
			lines.append([spoke[0], hubs[closest_index][0], spoke[1],
				hubs[closest_index][1], closest_distance])



	# Write spokes to file
	for index, line in enumerate(lines):

		# Status message
		if status_callback and ((index % 50) == 0):
			if status_callback(90, "Writing feature " + str(index) + " of " + str(len(lines))):
				return "Canceled while writing features"

		# Convert distance to appropriate output unit
		if distance_unit == "Feet":
			hub_distance = line[4] * 3.2808399

		elif distance_unit == "Miles":
			hub_distance = line[4] / 1609.344

		elif distance_unit == "Nautical Miles":
			hub_distance = line[4] / 1852

		elif distance_unit == "Kilometers":
			hub_distance = line[4] / 1000

		else: # default meters = Euclidian distance in layer units?
			hub_distance = line[4]

		# Create feature
		attributes = line[2]
		attributes.append(line[3])
		attributes.append(hub_distance)

		outfeature = QgsFeature()
		outfeature.setAttributes(attributes)

		if geometry_type == QgsWkbTypes.Point:
			outfeature.setGeometry(QgsGeometry.fromPointXY(line[0]))

		else:
			outfeature.setGeometry(QgsGeometry.fromPolylineXY([line[0], line[1]]))

		outfile.addFeature(outfeature)

	del outfile

	if status_callback:
		status_callback(100, str(len(lines)) + " nodes created")

	return None



# ----------------------------------------------------------------------------------------
#    mmqgis_kml_export - Export attributes to KML file suitable for display in Google Maps
# ----------------------------------------------------------------------------------------

def mmqgis_kml_cdata(value):
	# Converts string to text appropriate for CDATA in KML
	# Chosen over XML entity conversion to avoid unexpected conversion isues
	value = str(value)
	value = value.replace('&', '&amp;')
	value = value.replace('[', '\\[')
	value = value.replace(']', '\\]')
	return value

def mmqgis_kml_export(input_layer, name_field, description, export_data, output_file_name, status_callback = None):

	# Error checks
	if (not input_layer) or (input_layer.type() != QgsMapLayer.VectorLayer):
		return "Invalid input layer"

	name_index = input_layer.dataProvider().fieldNameIndex(name_field)
	if name_index < 0:
		return "Invalid name field: " + name_field

	# Parse description string to find field names
	scan = 0
	descstrings = []
	descattributes = []
	while scan < len(description):
		start = description.find("{{", scan)
		if (start < 0):
			descstrings.append(description[scan:len(description)]);
			descattributes.append(-1)
			break;

		descstrings.append(description[scan:start])

		start = start + 2
		end = description.find("}}", scan)
		if (end < 0):
			return "Unclosed description field name"

		descindex = -1;
		fieldname = description[start:end]
		for index, field in enumerate(input_layer.fields()):
			if (field.name() == fieldname):
				descindex = index;
				break;

		# descindex = input_layer.dataProvider().fieldNameIndex(fieldname)
		if (descindex < 0):
			return "Invalid description attribute: " + fieldname

		descattributes.append(descindex)
		scan = end + 2


	# Create output file
	try:
		outfile = io.open(output_file_name, 'w', encoding="utf-8")
		# outfile = sys.stdout
	except:
		return "Failure opening " + output_file_name

	outfile.write(u'<?xml version="1.0" encoding="UTF-8"?>\n')
	outfile.write(u'<kml xmlns="http://earth.google.com/kml/2.2">\n')
	outfile.write(u'<Document>\n')

	# 6/4/2019 - a KML file must have a name or Google Maps will fail the import with no meaningful explanation
	if input_layer.name():
		outfile.write(u'<name>' + str(input_layer.name()) + u'</name>\n')
	else:
		outfile.write(u'<name>' + str(output_file_name) + u'</name>\n')
	#  <description><![CDATA[Test description]]></description>

	# 8/25/2014 startRender()/stopRender() kludge needed so symbolsForFeature() does not crash
	# http://osgeo-org.1560.x6.nabble.com/symbolForFeature-does-not-works-td5149509.html
	renderer = input_layer.renderer()
	render_context = QgsRenderContext()
	renderer.startRender(render_context, input_layer.fields())
	# print str(renderer.dump())


	# Build stylesheet
	stylecount = 0
	symbolcount = len(renderer.symbols(render_context))
	for index, symbol in enumerate(renderer.symbols(render_context)):
		# print u'<Style id="style' + str(index + 1) + u'">'

		outfile.write(u'<Style id="style' + str(index + 1) + u'">\n')

		if symbol.type() == QgsSymbol.Fill:
			outfile.write(u'\t<LineStyle>\n')
			outfile.write(u'\t\t<color>40000000</color>\n')
			outfile.write(u'\t\t<width>3</width>\n')
			outfile.write(u'\t</LineStyle>\n')

			# Opacity can be set in three ways:
			# 1) Symbol color alpha (in the color wheel dialogue) = 0 - 255
			# 2) Symbol opacity (top of the symbology dialogue) = 0 - 1.0
			# 3) Layer rendering opacity (bottom of the symbology dialogue) = 0 - 1.0

			alpha = int(round(symbol.color().alpha() * symbol.opacity() * input_layer.opacity()))

			# KML colors are AABBGGRR

			color = (alpha << 24) + (symbol.color().blue() << 16) + \
				(symbol.color().green() << 8) + symbol.color().red()

			#print("Color = " + str(symbol.color().alpha()) + "/" + str(input_layer.opacity()) + \
			#	"/" + str(symbol.opacity()) + " = " + str(alpha) + \
			#	", " + str(symbol.color().blue()) + ", " + str(symbol.color().green()) + \
			#	", " + str(symbol.color().red()) + " = " + str(format(color, '08x')))

			outfile.write(u'\t<PolyStyle>\n')
			outfile.write(u'\t\t<color>' + str(format(color, '08x')) + u'</color>\n')
			outfile.write(u'\t\t<fill>1</fill>\n')
			outfile.write(u'\t\t<outline>1</outline>\n')
			outfile.write(u'\t</PolyStyle>\n')

		elif symbol.type() == QgsSymbol.Line:
			# KML colors are AABBGGRR
			alpha = int(round(symbol.color().alpha() * input_layer.opacity()))

			color = (alpha << 24) + (symbol.color().blue() << 16) + \
				(symbol.color().green() << 8) + symbol.color().red()
			outfile.write(u'\t<LineStyle>\n')
			outfile.write(u'\t\t<color>' + str(format(color, '08x')) + u'</color>\n')
			outfile.write(u'\t\t<width>5</width>\n')
			outfile.write(u'\t</LineStyle>\n')

		else: # Marker
			# Placemarks in Google (tm) maps are images referenced with a URL
			# These are the standard placemark icons used in Google maps
			# red = (color & 0xff0000) >> 16
			# green = (color & 0xff00) >> 8
			# blue = (color & 0xff)

			red = symbol.color().red()
			green = symbol.color().green()
			blue = symbol.color().blue()
			threshold = (min(red, green, blue) + max(red, green, blue)) / 2
			composite = 0
			if red >= threshold:
				composite = composite + 4
			if green >= threshold:
				composite = composite + 2
			if blue >= threshold:
				composite = composite + 1

			# print "rgb(" + str(red) + "," + str(green) + "," + str(blue) + ") = " + str(composite)

			if composite == 0: # black
				icon = 'http://maps.gstatic.com/mapfiles/ms2/micons/blue-dot.png'
			elif composite == 1: # blue
				icon = 'http://maps.gstatic.com/mapfiles/ms2/micons/blue-dot.png'
			elif composite == 2: # green
				icon = 'http://maps.gstatic.com/mapfiles/ms2/micons/green-dot.png'
			elif composite == 3: # cyan
				icon = 'http://maps.gstatic.com/mapfiles/ms2/micons/ltblue-dot.png'
			elif composite == 4: # red
				icon = 'http://maps.gstatic.com/mapfiles/ms2/micons/red-dot.png'
			elif composite == 5: # magenta
				icon = 'http://maps.gstatic.com/mapfiles/ms2/micons/pink-dot.png'
			elif composite == 6: # yellow
				icon = 'http://maps.gstatic.com/mapfiles/ms2/micons/yellow-dot.png'
			else: # 7: white
				icon = 'http://maps.gstatic.com/mapfiles/ms2/micons/purple-dot.png'


			outfile.write(u'\t<IconStyle>\n')
			outfile.write(u'\t\t<Icon>\n')
			outfile.write(u'\t\t\t<href>' + str(icon) + u'</href>\n')
			outfile.write(u'\t\t</Icon>\n')
			outfile.write(u'\t</IconStyle>\n')

		# print str(index) + ") " + str(symbol.color().name())

		outfile.write(u'</Style>\n')


	# Transform projection to WGS84 long/lat
	wgs84 = QgsCoordinateReferenceSystem()
	wgs84.createFromProj4("+proj=longlat +datum=WGS84 +no_defs")
	transform = QgsCoordinateTransform(input_layer.crs(), wgs84, QgsProject.instance())

	# Write features to KML
	feature_count = 0
	for featureindex, feature in enumerate(input_layer.getFeatures()):

		# Must have a geometry
		if feature.geometry() == None:
			continue;

		# Find style for feature
		# Some renderers return multiple symbols when QgsFeatureRenderer::Capability == MoreSymbolsPerFeature
		# This uses only the first symbol. Is the second one a default of some kind?!
		style = []
		for symbolsindex, featuresymbol in enumerate(renderer.symbolsForFeature(feature, render_context)):
			# print("  Feature symbol " + str(symbolsindex) + ": " + str(featuresymbol.dump()))
			for renderindex, rendersymbol in enumerate(renderer.symbols(render_context)):
				# print("    Render symbol: " + str(rendersymbol.dump()))
				if featuresymbol.dump() == rendersymbol.dump():
					style = style + ['#style' + str(renderindex + 1)]
					# print("      Render: " + str(style))
					break

		if (len(style) <= 0):
			style = ['#style0']

		# print("Style for " + str(featureindex) + " = " + style[0]);

		# Build name strings for feature
		# name = str(feature.attributes()[name_index].toString())
		# name = str(feature.attributes()[name_index])

		# Name and description strings
		featurename = mmqgis_kml_cdata(feature.attributes()[name_index])

		featuredesc = ""
		for index in range(0, len(descstrings)):

			featuredesc = featuredesc + mmqgis_kml_cdata(descstrings[index])

			fieldindex = descattributes[index]
			if (fieldindex >= 0) and (fieldindex < len(feature.attributes())):
				featuredesc = featuredesc + mmqgis_kml_cdata(feature.attributes()[fieldindex])

		# Placemark header
		outfile.write(u'<Placemark>\n')
		outfile.write(u'<name>' + featurename + u'</name>\n')
		outfile.write(u'<description><![CDATA[' + featuredesc + u']]></description>\n')

		# Optional attribute data
		if export_data:
			outfile.write(u'<ExtendedData>\n')

			for index in range(0, len(feature.fields())):
				name = str(feature.fields().field(index).name())
				value = mmqgis_kml_cdata(feature.attributes()[index])
				
				outfile.write(u'\t<Data name="' + name + u'"><displayName>' + name + 
					u'</displayName><value><![CDATA[' + value + u']]></value></Data>\n')

			outfile.write(u'</ExtendedData>\n')


		# KML always in WGS 84 long/lat
		geometry = feature.geometry()
		geometry.transform(transform)

		# print str(geometry.wkbType()) + ": " + str(geometry.type()) + ": " + name

		# Write features
		if (geometry.wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D]):
			point = geometry.asPoint()
			outfile.write(u'<styleUrl>' + str(style[0]) + u'</styleUrl>\n')
			outfile.write(u'\t<Point>\n')
			outfile.write(u'\t\t<coordinates>' + str(point.x()) + u',' + \
				str(point.y()) + u',0.000</coordinates>\n')
			outfile.write(u'\t</Point>\n')
			feature_count = feature_count + 1

		elif (geometry.wkbType() in [QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPointZ, QgsWkbTypes.MultiPoint25D]):
			for point in geometry.asMultiPoint():
				outfile.write(u'<styleUrl>' + str(style[0]) + u'</styleUrl>\n')
				outfile.write(u'\t<Point>\n')
				outfile.write(u'\t\t<coordinates>' + str(point.x()) + u',' + \
					str(point.y()) + u',0.000</coordinates>\n')
				outfile.write(u'\t</Point>\n')
			feature_count = feature_count + 1

		elif (geometry.wkbType() in [QgsWkbTypes.LineString, QgsWkbTypes.LineStringZ, QgsWkbTypes.LineString25D]):
			line = geometry.asPolyline()
			outfile.write(u'<styleUrl>' + str(style[0]) + u'</styleUrl>\n')
			outfile.write(u'\t<LineString>\n')
			outfile.write(u'\t\t<tessellate>1</tessellate>\n')
			outfile.write(u'\t\t<coordinates>\n')
			for point in line:
				outfile.write(u'\t\t\t' + str(point.x()) + u',' + \
					str(point.y()) + u',0.000\n')
			outfile.write(u'\t\t</coordinates>\n')
			outfile.write(u'\t</LineString>\n')
			feature_count = feature_count + 1

		elif (geometry.wkbType() in \
			[QgsWkbTypes.MultiLineString, QgsWkbTypes.MultiLineStringZ, QgsWkbTypes.MultiLineString25D]):
			for line in geometry.asMultiPolyline():
				outfile.write(u'<styleUrl>' + str(style[0]) + u'</styleUrl>\n')
				outfile.write(u'\t<LineString>\n')
				outfile.write(u'\t\t<tessellate>1</tessellate>\n')
				outfile.write(u'\t\t<coordinates>\n')
				for point in line:
					outfile.write(u'\t\t\t' + str(point.x()) + u',' + \
						str(point.y()) + u',0.000\n')
				outfile.write(u'\t\t</coordinates>\n')
				outfile.write(u'\t</LineString>\n')
			feature_count = feature_count + 1

		elif (geometry.wkbType() in [QgsWkbTypes.Polygon, QgsWkbTypes.PolygonZ, QgsWkbTypes.Polygon25D]):
			outfile.write(u'<styleUrl>' + str(style[0]) + u'</styleUrl>\n')
			polygon = geometry.asPolygon()
			outfile.write(u'\t<Polygon>\n')

			for ringnum, ring in enumerate(polygon):
				if (ringnum == 0):
					outfile.write(u'\t\t<outerBoundaryIs>\n')
				else:
					outfile.write(u'\t\t<innerBoundaryIs>\n')

				outfile.write(u'\t\t\t<LinearRing>\n')
				outfile.write(u'\t\t\t\t<tessellate>1</tessellate>\n')
				outfile.write(u'\t\t\t\t<coordinates>\n')

				for point in ring:
					outfile.write(u'\t\t\t\t\t' + str(point.x()) + u',' + \
						str(point.y()) + u',0.000\n')

				outfile.write(u'\t\t\t\t</coordinates>\n')
				outfile.write(u'\t\t\t</LinearRing>\n')

				if (ringnum == 0):
					outfile.write(u'\t\t</outerBoundaryIs>\n')
				else:
					outfile.write(u'\t\t</innerBoundaryIs>\n')

			outfile.write(u'\t</Polygon>\n')
			feature_count = feature_count + 1

		elif (geometry.wkbType() in [QgsWkbTypes.MultiPolygon, QgsWkbTypes.MultiPolygonZ, QgsWkbTypes.MultiPolygon25D]):
			outfile.write(u'<styleUrl>' + str(style[0]) + u'</styleUrl>\n')
			outfile.write(u'<MultiGeometry>\n')
			for polygon in geometry.asMultiPolygon():
				outfile.write(u'\t<Polygon>\n')

				for ringnum, ring in enumerate(polygon):
					if (ringnum == 0):
						outfile.write(u'\t\t<outerBoundaryIs>\n')
					else:
						outfile.write(u'\t\t<innerBoundaryIs>\n')

					outfile.write(u'\t\t\t<LinearRing>\n')
					outfile.write(u'\t\t\t\t<tessellate>1</tessellate>\n')
					outfile.write(u'\t\t\t\t<coordinates>\n')

					for point in ring:
						outfile.write(u'\t\t\t\t\t' + str(point.x()) + \
							u',' + str(point.y()) + u',0.000\n')

					outfile.write(u'\t\t\t\t</coordinates>\n')
					outfile.write(u'\t\t\t</LinearRing>\n')

					if (ringnum == 0):
						outfile.write(u'\t\t</outerBoundaryIs>\n')
					else:
						outfile.write(u'\t\t</innerBoundaryIs>\n')

				outfile.write(u'\t</Polygon>\n')
			outfile.write(u'</MultiGeometry>\n')
			feature_count = feature_count + 1

		else:
			return "Unknown geometry type " + str(geometry.wkbType()) +\
				". Use the convert geometry tool to change to point, line, or polygon";

		outfile.write(u'</Placemark>\n\n')

	outfile.write(u'</Document>\n')
	outfile.write(u'</kml>')
	outfile.close()

	renderer.stopRender(render_context)

	if status_callback:
		status_callback(100, str(feature_count) + " KML features")

	return None


# --------------------------------------------------------
#    mmqgis_merge - Merge layers to single shapefile
# --------------------------------------------------------

def mmqgis_merge(input_layers, output_file_name, status_callback = None):
	field_list = []
	total_feature_count = 0

	if not input_layers:
		return "No layers given to merge"

	for layer_index, input_layer in enumerate(input_layers):
		if (not input_layer) or (input_layer.type() != QgsMapLayer.VectorLayer):
			return "Invalid input layer"

		# Verify that all layers are the same type (point, polygon, etc)
		if (layer_index > 0):
			if (input_layer.wkbType() != input_layers[0].wkbType()):
				return "Merged input_layers must all be same type of geometry (" + \
					QgsWkbTypes.displayString(input_layer.wkbType()) + " != " + \
					QgsWkbTypes.displayString(input_layers[0].wkbType()) + ")"

		total_feature_count += input_layer.featureCount()

		# Add any fields not in the composite field list
		for sindex, sfield in enumerate(input_layer.fields()):
			found = None
			for dindex, dfield in enumerate(field_list):
				if (dfield.name().upper() == sfield.name().upper()):
					found = dfield
					if (dfield.type() != sfield.type()):
						# print "Mismatch", dfield.typeName(), sfield.typeName(), input_layername
						field_list[dindex].setType(QVariant.String)
						field_list[dindex].setTypeName("String")
						field_list[dindex].setLength(254)
						field_list[dindex].setPrecision(0)
					break

			if not found:
				field_list.append(QgsField(sfield))

	# Convert field list to structure.
	# Have to do this as a list because fields in structure cannot be 
	# modified after appending, and conflicting types need to be converted to string

	fields = QgsFields()
	for field in field_list:
		fields.append(field)
			
	# Create the output shapefile
	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, fields, \
		input_layers[0].wkbType(), input_layers[0].crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())

	# Copy layer features to output file
	feature_count = 0
	for input_layer in input_layers:
		# print "Layer", str(feature_count)
		for feature in input_layer.getFeatures():
			sattributes = feature.attributes()
			dattributes = []
			for dindex, dfield in enumerate(fields):
				# dattribute = QVariant(dfield.type())
				# print str(dindex) + ": " + str(dfield.type())

				if (dfield.type() in [QVariant.Int, QVariant.UInt, QVariant.LongLong, QVariant.ULongLong]):
					dattribute = 0

				elif (dfield.type() == QVariant.Double):
					dattribute = 0.0

				else:
					dattribute = ""

				for sindex, sfield in enumerate(input_layer.fields()):
					if (sfield.name().upper() == dfield.name().upper()):
						if (sfield.type() == dfield.type()):
							dattribute = sattributes[sindex]

						elif (dfield.type() == QVariant.String):
							dattribute = str(sattributes[sindex])

						else:
							return "Attribute " + str(sfield.name()) + \
								" type mismatch " + sfield.typeName() + \
								" != " + dfield.typeName()
						break

				dattributes.append(dattribute)

			#for dindex, dfield in dattributes.items():
			#	print input_layer.name() + " (" + str(dindex) + ") " + str(dfield.toString())

			feature.setAttributes(dattributes)
			outfile.addFeature(feature)
			feature_count += 1
			if status_callback and ((feature_count % 50) == 0):
				if status_callback(100 * feature_count / total_feature_count,
						"Merging " + str(feature_count) + " of " + str(total_feature_count)):
					return "Canceled at feature " + str(feature_count)

	del outfile

	if status_callback:
		status_callback(100, str(feature_count) + " features merged")

	return None


# --------------------------------------------------------
#    mmqgis_sort - Sort layer by attribute
# --------------------------------------------------------

def mmqgis_sort(input_layer, sort_field, sort_direction, output_file_name, status_callback = None):

	if (not input_layer) or (input_layer.type() != QgsMapLayer.VectorLayer):
		return "Invalid input layer"

	sort_index = input_layer.dataProvider().fieldNameIndex(sort_field)
	if sort_index < 0:
		return "Invalid sort field name: " + sort_field
	
	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, input_layer.fields(), \
		input_layer.wkbType(), input_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())

	table = []
	for index, feature in enumerate(input_layer.getFeatures()):

		if status_callback and ((index % 100) == 0):
			if status_callback(25, "Reading " + str(feature.id())):
				return "Canceled at feature " + str(feature.id())

		table.append([ feature.id(), feature.attributes()[sort_index] ])

	if status_callback:
		status_callback(50, "Sorting")

	if (sort_direction.lower() == "descending"):
		table.sort(key = operator.itemgetter(1), reverse=True)
	else:
		table.sort(key = operator.itemgetter(1))

	writecount = 0
	for index, record in enumerate(table):
		feature = input_layer.getFeature(record[0])
		outfile.addFeature(feature)
		writecount += 1

		if status_callback and ((index % 100) == 0):
			if status_callback(100 * index / len(table), "Writing " + str(writecount) + " of " + str(len(table))):
				return "Canceled at feature " + str(index)

	del outfile

	if status_callback:
		status_callback(100, str(writecount) + " Features sorted")

	return None

# ----------------------------------------------------------
#    mmqgis_spatial_join - Spatial Join
# ----------------------------------------------------------

def mmqgis_spatial_join(target_layer, spatial_operation, join_layer, field_names, field_operation, \
	output_file_name, status_callback = None):

	# Error checks

	if (not target_layer) or (target_layer.type() != QgsMapLayer.VectorLayer):
		return "Invalid target layer"

	# Rasters don't have fields()
	if (not hasattr(target_layer, "fields")):
		return "Target layer has no fields (raster layer?)";

	if not spatial_operation in [ "Intersects", "Within", "Contains" ]:
		return "Invalid spatial operation"

	if (not join_layer) or (join_layer.type() != QgsMapLayer.VectorLayer):
		return "Invalid join layer"

	if (not hasattr(join_layer, "fields")):
		return "Join layer has no fields (raster layer?)";

	if len(field_names) != len(set(field_names)):
		return "Duplicate output field names from different layers"

	if not field_operation in ["First", "Sum", "Proportional Sum", "Average", "Weighted Average", "Largest Proportion"]:
		return "Invalid field operation"

	#wgs84 = QgsCoordinateReferenceSystem("PROJ4:+proj=longlat +datum=WGS84 +no_defs")
	#transform = QgsCoordinateTransform(wgs84, azimuthal_equidistant, QgsProject.instance())
	#geometry.transform(transform)

	transform = None

	#print(type(join_layer))
	#print(type(join_layer.crs()))
	if join_layer.crs() != target_layer.crs():
		transform = QgsCoordinateTransform(join_layer.crs(), target_layer.crs(), QgsProject.instance())


	# Build composite field list
	field_info = [] # [ layer, index, QgsField ]
	newfields = QgsFields()
	for index, field in enumerate(target_layer.fields()):
		if field.name() in field_names:
			newfields.append(field)
			field_info.append([target_layer, index, field])
			# print str(len(field_info) - 1) + " = " + field.name()

	# Add fields from join features
	for index, field in enumerate(join_layer.fields()):
		if field.name() in field_names:
			if target_layer.dataProvider().fieldNameIndex(field.name()) >= 0:
				return "Ambiguous field name in both target and join layers: " + field.name()
				
			# INT fields converted to DOUBLE to avoid overflow and rounding errors
			# 12/28/2016: LongLong types needed for 64-bit Windows shapefiles.
			# Precision kludge to avoid bogus OGR shapefile input precision zero,
			# which would result in conversion to int on write

			if (field.type() in [ QVariant.Int, QVariant.LongLong, \
					QVariant.UInt, QVariant.ULongLong, QVariant.Double ]):
				field = QgsField(field.name(), QVariant.Double, "Double", 12, 4)

			newfields.append(field)
			field_info.append([join_layer, index, field])
			# print str(len(field_info) - 1) + " = " + field.name() + " " + str(field.type())

	# Add field to count number of joined features
	count_field = QgsField("COUNT", QVariant.Int)
	newfields.append(count_field)
	field_info.append([None, 0, count_field])

	# Open file (delete any existing)

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, newfields, \
		target_layer.wkbType(), target_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())

	# Interate through target features
	total_joins = 0
	target_count = 0
	feature_count = target_layer.featureCount()
	for target_index, target_feature in enumerate(target_layer.getFeatures()):
		if status_callback and ((target_index % 10) == 0):
			status_callback(100 * target_index / target_layer.featureCount(),
				"Joining " + str(target_index) + " of " + str(target_layer.featureCount()))

		target_geometry = target_feature.geometry()

		# Copy all selected target attributes
		attributes = []
		for fieldlayer, fieldindex, field in field_info:
			if fieldlayer == target_layer:
				attributes.append(target_feature.attributes()[fieldindex])
			elif fieldlayer == join_layer:
				attributes.append(None)
			else:
				attributes.append(0) # count

		# Iterate through join features
		join_count = 0
		last_join_area = 0 # to keep track of feature with largest intersection area
		for join_index, join_feature in enumerate(join_layer.getFeatures()):

			# Get the geometry of the join feature
			join_geometry = join_feature.geometry()
			if transform:
				join_geometry.transform(transform)

			# print("\tTest: " + str(target_index) + " -> " + str(join_index))

			# Only analyze features that meet spatial join criteria
			if ((spatial_operation == 'Intersects') and (not target_geometry.intersects(join_geometry))) or \
			   ((spatial_operation == 'Within') and (not target_geometry.within(join_geometry))) or \
			   ((spatial_operation == 'Contains') and (not target_geometry.contains(join_geometry))):
				continue

			# print("\t\tMatch: " + str(target_index) + " -> " + str(join_index) + " = " + str(total_joins))

			# The count of joined features is added as an attribute, and used for averaging
			join_count = join_count + 1
			total_joins = total_joins + 1

			# If you only need the first matching feature, there is no need to test other features
			if (field_operation == "First"):
				for dest_index, field in enumerate(field_info):
					if field[0] == join_layer:
						attribute = join_feature.attributes()[field[1]]
						attributes[dest_index] = attribute
				break

			# Calculate areas
			join_area = join_geometry.area()
			target_area = target_geometry.area()
			intersect_area = target_geometry.intersection(join_geometry).area()

			# For each field
			for dest_index, field in enumerate(field_info):

				# Only process fields selected for joining
				if field[0] != join_layer:
					continue

				attribute = join_feature.attributes()[field[1]]

				# Join this field if the match is larger than any previous match
				if field_operation == "Largest Proportion":
					if last_join_area <= intersect_area:
						attributes[dest_index] = attribute
						last_join_area = intersect_area
					continue

				# Non-real fields can only be copied, not proportionately summed or averaged
				if (field[2].type() != QVariant.Double):
					if join_count == 1:
						attributes[dest_index] = attribute
					continue
					
				# Ratios for summing when doing proportional operations
				ratio = 1.0
				if (field_operation == "Proportional Sum"):
					if (join_area > 0):
						ratio = intersect_area / join_area

				elif (field_operation == "Weighted Average"):
					if (target_area > 0):
						ratio = intersect_area / target_area

				# Sum the values 
				try:
					if join_count <= 1:
						target_value = 0
					else:
						target_value = float(attributes[dest_index])

					join_value = float(join_feature.attributes()[field[1]])
					attributes[dest_index] = target_value + (ratio * join_value)
					# print "Join " + str(attributes[dest_index]) + " = " + \
					#	str(target_value) + " + (" + str(ratio) + \
					#	" * " + str(join_value) + ")"
				except:
					attributes[dest_index] = 0

				# print str(target_index) + ":" + str(join_index) + ") " + \
				#	str(target_value) + " + " + str(join_value) + " * " + \
				#	str(ratio)
						

		# Divide sums to get averages
		if (field_operation == "Average") and (join_count > 0):
			for dest_index, field in enumerate(field_info):
				if (field[0] == join_layer) and (field[2].type() == QVariant.Double):
					attributes[dest_index] = float(attributes[dest_index]) / float(join_count)

		# Counter
		attributes[len(field_info) - 1] = join_count
		# print "Join count(" + str(len(field_info) - 1) + "): " + str(join_count)

		# Add the feature
		# if join_count > 0:
		target_count = target_count + 1
		newfeature = QgsFeature()
		newfeature.setGeometry(target_feature.geometry())
		newfeature.setAttributes(attributes)
		# print str(target_count) + ") " + str(attributes[0].toString())
		if not outfile.addFeature(newfeature):
			return "Failure writing feature to output"

	del outfile

	if status_callback:
		status_callback(100, str(total_joins) + " features joined to " + str(target_count) + " output features")

	return None

# ---------------------------------------------------------
#    mmqgis_text_to_float - Change text fields to numbers
# ---------------------------------------------------------

def mmqgis_text_to_float(input_layer, field_names, output_file_name, status_callback = None):

	# Error checks
	if (not input_layer) or (input_layer.type() != QgsMapLayer.VectorLayer):
		return "Invalid input layer"

	# Build list of fields with selected fields changed to floating point
	changecount = 0
	destfields = QgsFields()
	field_changed = []
	for index, field in enumerate(input_layer.fields()):
		if (field.name() in field_names) and ((field.type() == QVariant.String) or (field.type() == QVariant.Int)):
			field_changed.append(True)
			# Arbitrary floating point length/precision 14.6 = nnnnnnnnnnnnnn.dddddd
			destfields.append(QgsField (field.name(), QVariant.Double, field.typeName(), \
				14, 6, field.comment()))
			changecount += 1
		else:
			field_changed.append(False)
			destfields.append(QgsField (field.name(), field.type(), field.typeName(), \
				field.length(), field.precision(), field.comment()))

	if (changecount <= 0):
		return "No string or integer fields selected for conversion to floating point"


	# Create the output file

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, destfields, \
		input_layer.wkbType(), input_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())


	# Write the features with modified field_names
	feature_count = input_layer.featureCount();
	for feature_index, feature in enumerate(input_layer.getFeatures()):
		if status_callback and ((feature_index % 50) == 0):
			status_callback(100 * feature_index / input_layer.featureCount(), \
				"Feature " + str(feature_index) + " of " + str(input_layer.featureCount()))

		new_values = []
		for field_index, field in enumerate(input_layer.fields()):
			if not field_changed[field_index]:
				new_values.append(feature.attribute(field_index))
				continue

			string = str(feature.attribute(field_index))

			multiplier = 1.0
			if string.find("%") >= 0:
				multiplier = 1 / 100.0
				string = string.replace("%", "")
			if string.find(",") >= 0:
				string = string.replace(",", "")

			string = string.replace(" ", "")

			start = 0
			while (start < len(string)) and (string[start] not in "0123456789."):
				start = start + 1
			end = start
			while (end < len(string)) and (string[end] in "0123456789."):
				end = end + 1

			if (start < len(string)) or (start < end):
				string = string[start:end]
			else:
				string = "0"

			try:	
				value = float(string) * multiplier
			except:
				value = 0
					
			new_values.append(value)

		feature.setAttributes(new_values)
		outfile.addFeature(feature)

	del outfile

	if status_callback:
		status_callback(100, str(len(field_names)) + " fields, " + str(input_layer.featureCount()) + " features")

	return None


# --------------------------------------------------------
#    mmqgis_voronoi - Voronoi diagram creation
# --------------------------------------------------------

class mmqgis_voronoi_line:
	def __init__(self, x, y):
		self.x = x
		self.y = y
		self.angle = 0
		self.distance = 0

	def list(self, title):
		print(title + ", " + str(self.x) + ", " + str(self.y) + \
			", angle " + str(self.angle * 180 / pi) + ", distance " + str(self.distance))

	def angleval(self):
		return self.angle


def mmqgis_voronoi_diagram(input_layer, output_file_name, status_callback = None):

	# Error checks
	if (not input_layer) or (input_layer.type() != QgsMapLayer.VectorLayer):
		return "Invalid input layer"

	if not output_file_name:
		return "No output file name given"

	file_formats = { ".shp":"ESRI Shapefile", ".geojson":"GeoJSON", ".kml":"KML", ".sqlite":"SQLite", ".gpkg":"GPKG" }

	if os.path.splitext(output_file_name)[1] not in file_formats:
		return "Unsupported output file format: " + str(output_file_name)

	output_file_format = file_formats[os.path.splitext(output_file_name)[1]]

	save_options = QgsVectorFileWriter.SaveVectorOptions()
	save_options.driverName = output_file_format
	save_options.fileEncoding = 'UTF-8'

	outfile = QgsVectorFileWriter.create(output_file_name, input_layer.fields(), \
		QgsWkbTypes.Polygon, input_layer.crs(), \
		transformContext=QgsProject.instance().transformContext(), \
		options=save_options)

	if (outfile.hasError() != QgsVectorFileWriter.NoError):
		return "Failure creating output file: " + str(outfile.errorMessage())

	points = []
	xmin = 0
	xmax = 0
	ymin = 0
	ymax = 0

	for feature in input_layer.getFeatures():
		# Re-read by feature ID because nextFeature() doesn't always seem to read attributes
		# input_layer.featureAtId(feature.id(), feature)
		geometry = feature.geometry()
		if status_callback:
			status_callback(0, "Feature " + str(feature.id()) + " of " + str(input_layer.featureCount()))

		# print str(feature.id()) + ": " + str(geometry.wkbType())
		if geometry.wkbType() == QgsWkbTypes.Point:
			points.append( (geometry.asPoint().x(), geometry.asPoint().y(), feature.attributes()) )
			if (len(points) <= 1) or (xmin > geometry.asPoint().x()):
				xmin = geometry.asPoint().x()
			if (len(points) <= 1) or (xmax < geometry.asPoint().x()):
				xmax = geometry.asPoint().x()
			if (len(points) <= 1) or (ymin > geometry.asPoint().y()):
				ymin = geometry.asPoint().y()
			if (len(points) <= 1) or (ymax < geometry.asPoint().y()):
				ymax = geometry.asPoint().y()

	if (len(points) < 3):
		return "Too few points to create diagram"

	for point_number, center in enumerate(points):
	# for center in [ points[17] ]:
		# print "\nCenter, " + str(center[0]) + ", " + str(center[1])
		if (point_number % 20) == 0:
			#status_callback("Processing point " + \
			#	str(center[0]) + ", " + str(center[1]))
			status_callback(100 * point_number / len(points),
				"Point " + str(point_number) + " of " + str(len(points)))

		# Borders are tangents to midpoints between all neighbors
		tangents = []
		for neighbor in points:
			border = mmqgis_voronoi_line((center[0] + neighbor[0]) / 2.0, (center[1] + neighbor[1]) / 2.0)
			if ((neighbor[0] != center[0]) or (neighbor[1] != center[1])):
				tangents.append(border)

		# Add edge intersections to clip to extent of points
		offset = (xmax - xmin) * 0.01
		tangents.append(mmqgis_voronoi_line(xmax + offset, center[1]))
		tangents.append(mmqgis_voronoi_line(center[0], ymax + offset))
		tangents.append(mmqgis_voronoi_line(xmin - offset, center[1]))
		tangents.append(mmqgis_voronoi_line(center[0], ymin - offset))
		#print "Extent x = " + str(xmax) + " -> " + str(xmin) + ", y = " + str(ymax) + " -> " + str(ymin)

		# Find vector distance and angle to border from center point
		for scan in range(0, len(tangents)):
			run = tangents[scan].x - center[0]
			rise = tangents[scan].y - center[1]
			tangents[scan].distance = sqrt((run * run) + (rise * rise))
			if (tangents[scan].distance <= 0):
				tangents[scan].angle = 0
			elif (tangents[scan].y >= center[1]):
				tangents[scan].angle = acos(run / tangents[scan].distance)
			elif (tangents[scan].y < center[1]):
				tangents[scan].angle = (2 * pi) - acos(run / tangents[scan].distance)
			elif (tangents[scan].x > center[0]):
				tangents[scan].angle = pi / 2.0
			else:
				tangents[scan].angle = 3 * pi / 4

			#print "  Tangent, " + str(tangents[scan].x) + ", " + str(tangents[scan].y) + \
			#	", angle " + str(tangents[scan].angle * 180 / pi) + ", distance " + \
			#	str(tangents[scan].distance)


		# Find the closest line - guaranteed to be a border
		closest = -1
		for scan in range(0, len(tangents)):
			if ((closest == -1) or (tangents[scan].distance < tangents[closest].distance)):
				closest = scan

		# Use closest as the first border
		border = mmqgis_voronoi_line(tangents[closest].x, tangents[closest].y)
		border.angle = tangents[closest].angle
		border.distance = tangents[closest].distance
		borders = [ border ]

		#print "  Border 0) " + str(closest) + " of " + str(len(tangents)) + ", " \
		#	+ str(border.x) + ", " + str(border.y) \
		#	+ ", (angle " + str(border.angle * 180 / pi) + ", distance " \
		#	+ str(border.distance) + ")"

		# Work around the tangents in a CCW circle
		circling = 1
		while circling:
			next = -1
			scan = 0
			while (scan < len(tangents)):
				anglebetween = tangents[scan].angle - borders[len(borders) - 1].angle
				if (anglebetween < 0):
					anglebetween += (2 * pi)
				elif (anglebetween > (2 * pi)):
					anglebetween -= (2 * pi)

				#print "    Scanning " + str(scan) + " of " + str(len(borders)) + \
				#	", " + str(tangents[scan].x) + ", " + str(tangents[scan].y) + \
				#	", angle " + str(tangents[scan].angle * 180 / pi) + \
				#	", anglebetween " + str(anglebetween * 180 / pi)

				# If border intersects to the left
				if (anglebetween < pi) and (anglebetween > 0):
					# A typo here with a reversed slash cost 8/13/2009 debugging
					tangents[scan].iangle = atan2( (tangents[scan].distance / 
						borders[len(borders) - 1].distance) \
						- cos(anglebetween), sin(anglebetween))
					tangents[scan].idistance = borders[len(borders) - 1].distance \
						/ cos(tangents[scan].iangle)

					tangents[scan].iangle += borders[len(borders) - 1].angle

					# If the rightmost intersection so far, it's a candidate for next border
					if (next < 0) or (tangents[scan].iangle < tangents[next].iangle):
						# print "      Take idistance " + str(tangents[scan].idistance)
						next = scan

				scan += 1

			# iangle/distance are for intersection of border with next border
			borders[len(borders) - 1].iangle = tangents[next].iangle
			borders[len(borders) - 1].idistance = tangents[next].idistance

			# Stop circling if back to the beginning
			if (borders[0].x == tangents[next].x) and (borders[0].y == tangents[next].y):
				circling = 0

			else:
				# Add the next border
				border = mmqgis_voronoi_line(tangents[next].x, tangents[next].y)
				border.angle = tangents[next].angle
				border.distance = tangents[next].distance
				border.iangle = tangents[next].iangle
				border.idistance = tangents[next].idistance
				borders.append(border)
				#print "  Border " + str(len(borders) - 1) + \
				#	") " + str(next) + ", " + str(border.x) + \
				#	", " + str(border.y) + ", angle " + str(border.angle * 180 / pi) +\
				#	", iangle " + str(border.iangle * 180 / pi) +\
				#	", idistance " + str(border.idistance) + "\n"

			# Remove the border from the list so not repeated
			tangents.pop(next)
			if (len(tangents) <= 0):
				circling = 0

		polygon = []
		if len(borders) >= 3:
			for border in borders:
				ix = center[0] + (border.idistance * cos(border.iangle))
				iy = center[1] + (border.idistance * sin(border.iangle))
				#print "  Node, " + str(ix) + ", " + str(iy) + \
				#	", angle " + str(border.angle * 180 / pi) + \
				#	", iangle " + str(border.iangle * 180 / pi) + \
				#	", idistance " + str(border.idistance) + ", from " \
				#	+ str(border.x) + ", " + str(border.y)
				polygon.append(QgsPointXY(ix, iy))

			#print "Polygon " + str(point_number)
			#for x in range(0, len(polygon)):
			#	print "  Point " + str(polygon[x].x()) + ", " + str(polygon[x].y())

			# Remove duplicate nodes
			# Compare as strings (str) to avoid odd precision discrepancies
			# that sometimes cause duplicate points to be unrecognized
			dup = 0
			while (dup < (len(polygon) - 1)):
				if (str(polygon[dup].x()) == str(polygon[dup + 1].x())) and \
				   (str(polygon[dup].y()) == str(polygon[dup + 1].y())):
					polygon.pop(dup)
					# print "  Removed duplicate node " + str(dup) + \
					#	" in polygon " + str(point_number)
				else:
					# print "  " + str(polygon[dup].x()) + ", " + \
					#	str(polygon[dup].y()) + " != " + \
					#	str(polygon[dup + 1].x()) + ", " + \
					#	str(polygon[dup + 1].y())
					dup = dup + 1

			# attributes = { 0:QVariant(center[0]), 1:QVariant(center[1]) }

		if len(polygon) >= 3:
			geometry = QgsGeometry.fromPolygonXY([ polygon ])
			feature = QgsFeature()
			feature.setGeometry(geometry)
			feature.setAttributes(center[2])
			outfile.addFeature(feature)
				
	del outfile

	if status_callback:
		status_callback(100, "Created " + str(len(points)) + " polygons")

	return None


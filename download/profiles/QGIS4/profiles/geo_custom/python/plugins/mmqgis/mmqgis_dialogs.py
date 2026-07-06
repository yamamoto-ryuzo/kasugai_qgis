# --------------------------------------------------------
#    mmqgis_dialogs - Dialog classes for mmqgis
#
#    begin		: 10 May 2010
#    copyright		: (c) 2010 - 2019 by Michael Minn
#    email		: See michaelminn.com
#
#   MMQGIS is free software and is offered without guarantee
#   or warranty. You can redistribute it and/or modify it 
#   under the terms of version 2 of the GNU General Public 
#   License (GPL v2) as published by the Free Software 
#   Foundation (www.gnu.org).
# --------------------------------------------------------

import csv
import math
import os.path
import operator

# https://gis.stackexchange.com/questions/234350/error-sip-setapiapi-1-in-pyqgis
from qgis.core import *

# from PyQt6 import QtCore, QtGui, QtWidgets
# from PyQt6.QtWidgets import *

from qgis.PyQt import QtCore, QtGui, QtWidgets
from qgis.PyQt.QtWidgets import *

try:
	from .mmqgis_library import *
except:
	from mmqgis_library import *

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/forms")

# ------------------------------------------------------------------------------
#    mmqgis_dialog - base class for MMQGIS dialogs containing utility functions
# ------------------------------------------------------------------------------

class mmqgis_dialog(QtWidgets.QDialog):
	def __init__(self, iface):
		QtWidgets.QDialog.__init__(self)
		self.iface = iface

	def mmqgis_fill_combo_box_with_print_layouts(self, combo_box):
		project = QgsProject.instance()
		layout_manager = project.layoutManager()

		# Add layouts not in layout manager
		for layout in layout_manager.printLayouts():
			if combo_box.findText(layout.name()) < 0:
				combo_box.addItem(layout.name())

		# Remove layouts not in layout manager
		removed = []
		for index in range(combo_box.count()):
			if not layout_manager.layoutByName(combo_box.itemText(index)):
				removed.append(index)

		removed.reverse()
		for index in removed:
			combo_box.removeItem(index)

	def mmqgis_fill_combo_box_with_vector_layers(self, combo_box):
		# Add layers not in the combo box
		for layer in self.iface.mapCanvas().layers():
			if layer.type() == QgsMapLayer.VectorLayer:
				if combo_box.findText(layer.name()) < 0:
					combo_box.addItem(layer.name())
					if layer in self.iface.layerTreeView().selectedLayers():
						combo_box.setCurrentIndex(combo_box.count() - 1)

		# Remove layers no longer on the map
		removed = []
		for index in range(combo_box.count()):
			found = False
			for layer in self.iface.mapCanvas().layers():
				if layer.name() == combo_box.itemText(index):
					found = True
					break
			if not found:
				removed.append(index)

		removed.reverse()
		for index in removed:
			combo_box.removeItem(index)
			
	def mmqgis_fill_combo_box_with_vector_layer_fields(self, combo_box, vector_layer_name):
		vector_layer = self.mmqgis_find_layer(vector_layer_name.currentText())
		if not vector_layer:
			return

		combo_box.clear()
		for field in vector_layer.fields():
			combo_box.addItem(field.name())

	def mmqgis_fill_combo_box_with_csv_fields(self, combo_box, input_csv_name):
		input_csv_name = str(self.input_csv_name.filePath())

		header = self.mmqgis_read_csv_header(input_csv_name)
		if type(header) == str:
			QMessageBox.critical(self.iface.mainWindow(), "Invalid CSV", header)
			return

		combo_box.clear()
		combo_box.addItems(header)

	#def mmqgis_fill_combo_box_with_output_file_formats(self, combo_box):
	# ogrinfo --format
	#	formats = ["ESRI Shapefile", "GeoJSON", "KML", "Spatialite", "GPKG"]
	#	combo_box.addItems(formats)
	#	combo_box.setCurrentIndex(0)

	def mmqgis_fill_list_widget_with_vector_layers(self, list_widget):
		# Add layers not in the list
		for layer in self.iface.mapCanvas().layers():
			if layer.type() == QgsMapLayer.VectorLayer:
				found = False
				for index in range(list_widget.count()):
					if list_widget.item(index).text() == layer.name():
						found = True
						break;
				if not found:
					list_widget.addItem(layer.name())

		# Remove layers no longer on the map
		removed = []
		for index in range(list_widget.count()):
			found = False
			for layer in self.iface.mapCanvas().layers():
				if layer.name() == list_widget.item(index).text():
					found = True
					break
			if not found:
				removed.append(index)

		removed.reverse()
		for index in removed:
			item = list_widget.takeItem(index)
			item = None
			# list_widget.removeItemWidget(list_widget.item(index))

	def mmqgis_find_layer(self, layer_name):
		if not layer_name:
			return None

		layers = QgsProject.instance().mapLayersByName(layer_name)
		if (len(layers) >= 1):
			return layers[0]

		return None

	def mmqgis_find_layer_by_data_source(self, file_name):
		if not file_name:
			return None

		# URI notation used by the API to distinguish layers within files that contain multiple layers
		# Simple formats like shapefile and GeoJSON still have these in the mapLayers() list
		if not file_name.find("|") >= 0:
			file_name = file_name + "|layerid=0"

		for layer_name, layer in QgsProject.instance().mapLayers().items():
			if layer.dataProvider() and (file_name == layer.dataProvider().dataSourceUri()):
				return layer

		return None

	def mmqgis_find_print_layout(self, layout_name):
		layout_manager = QgsProject.instance().layoutManager()

		for layout in layout_manager.printLayouts():
			if layout_name == layout.name():
				return layout

		return None

	def mmqgis_initialize_spatial_output_file_widget(self, file_widget, suffix = ".shp"):
		initial_file_name = self.mmqgis_temp_file_name(suffix)
		file_widget.setFilePath(initial_file_name)
		file_widget.setStorageMode(QgsFileWidget.SaveFile)

		file_widget.setFilter("ESRI Shapefile (*.shp);;GeoJSON (*.geojson);;KML (*.kml);;" + \
			"Spatialite (*.sqlite);;GPKG (*.gpkg);;All Files (*.*)")
		
	def mmqgis_initialize_tabular_output_file_widget(self, file_widget, suffix = ".csv"):
		initial_file_name = self.mmqgis_temp_file_name(suffix)
		file_widget.setFilePath(initial_file_name)
		file_widget.setStorageMode(QgsFileWidget.SaveFile)
		file_widget.setFilter("CSV (*.csv);;Text (*.txt);;All Files (*.*)")


	def mmqgis_read_csv_header(self, input_csv_name):
		# This may take awhile with large CSV files
		input_csv = QgsVectorLayer(input_csv_name)

		field_names = []

		if (not input_csv) or (input_csv.featureCount() <= 0) or (len(input_csv.fields()) <= 0):
			return field_names

		for field in input_csv.fields():
			field_names.append(field.name())

		return field_names

	def mmqgis_direct_read_csv_header(self, filename):
		try:
			infile = open(filename, 'r', encoding='utf-8')
		except Exception as e:
			return	"Failure opening " + filename + ": " + str(e)

		try:
			dialect = csv.Sniffer().sniff(infile.read(8192))
		except Exception as e:
			return "Bad CSV file " + filename + ": " + str(e) + "(verify that your delimiters are consistent)"

		infile.seek(0)
		reader = csv.reader(infile, dialect)
		header = next(reader)
			
		del reader
		infile.close()
		del infile

		if len(header) <= 0:
			return filename + " does not appear to be a CSV file"

		return header

	def mmqgis_set_status_bar(self, status_bar):
		status_bar.setMinimum(0)
		status_bar.setMaximum(100)
		status_bar.setValue(0)
		status_bar.setFormat("Ready")
		self.status_bar = status_bar

	def mmqgis_status_callback(self, percent_complete, message):
		try:
			if not message:
				message = str(int(percent_complete)) + "%"

			self.status_bar.setFormat(message)

			if percent_complete < 0:
				self.status_bar.setValue(0)
			elif percent_complete > 100:
				self.status_bar.setValue(100)
			else:
				self.status_bar.setValue(percent_complete)

			self.iface.statusBarIface().showMessage(message)

			# print("status_callback(" + message + ")")
		except:
			print(message)

		# add handling of "Close" button
		return 0
		
	def mmqgis_temp_file_name(self, suffix):
		project = QgsProject.instance()

		home_path = project.homePath()
		if not home_path:
			home_path = os.getcwd()

		for x in range(1, 10):
			name = home_path + "/temp" + str(x) + suffix
			if not os.path.isfile(name):
				return name

		return home_path + "/temp" + suffix

	def mmqgis_frame_directory(self, suffix = "/frames"):
		project = QgsProject.instance()
		home_path = project.homePath()

		if not home_path:
			home_path = project.absolutePath()

		if not home_path:
			home_path = os.getcwd()

		return home_path + suffix

	#def mmqgis_update_file_extension_from_file_format(self, file_widget, file_format_combo_box):
	#	path, old_extension = os.path.splitext(file_widget.filePath())
	#	if not old_extension:
	#		return

	#	extensions = { "ESRI Shapefile": ".shp",
	#		"SQLite": ".sqlite",
	#		"GeoJSON": ".geojson",
	#		"KML": ".kml",
	#		"GPKG": ".gpkg" }

	#	file_format = file_format_combo_box.currentText()

	#	if not file_format in extensions:
	#		return

	#	new_extension = extensions[file_format]
	#	new_path = file_widget.filePath()[0:(len(file_widget.filePath()) - len(old_extension))]
	#	file_widget.setFilePath(new_path + new_extension)



# ------------------------------------------------------------------------------------
#    mmqgis_animate_lines - Create animations by interpolating offsets from attributes
# ------------------------------------------------------------------------------------

from mmqgis_animate_lines_form import *

class mmqgis_animate_lines_dialog(mmqgis_dialog, Ui_mmqgis_animate_lines_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_print_layouts(self.print_layout)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

		self.frame_count.setText("20")

		self.frame_directory.setStorageMode(QgsFileWidget.GetDirectory)
		self.frame_directory.setFilePath(self.mmqgis_frame_directory())

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_print_layouts(self.print_layout)
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def run(self):
		print_layout = self.mmqgis_find_print_layout(self.print_layout.currentText())
		input_layer = self.mmqgis_find_layer(self.input_layer_name.currentText())
		fixed_speed = str(self.timing.currentText()) == "One Line Speed Determined By Longest Line"
		frame_count = int(self.frame_count.displayText())
		frame_directory = str(self.frame_directory.filePath())

		message = mmqgis_animate_lines(print_layout, input_layer, fixed_speed,
			frame_count, frame_directory, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Animate Columns", message)

# ---------------------------------------------------------------------------------------
#    mmqgis_animate_location - Create animations by interpolating offsets from attributes
# ---------------------------------------------------------------------------------------

from mmqgis_animate_location_form import *

class mmqgis_animate_location_dialog(mmqgis_dialog, Ui_mmqgis_animate_location_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)
		# self.setModal(False)

		self.mmqgis_fill_combo_box_with_print_layouts(self.print_layout)

		self.mmqgis_fill_combo_box_with_vector_layers(self.source_layer_name)
		self.mmqgis_fill_combo_box_with_vector_layer_fields(self.source_key_field, self.source_layer_name)
		self.source_layer_name.currentIndexChanged.connect(lambda:
			self.mmqgis_fill_combo_box_with_vector_layer_fields(self.source_key_field, self.source_layer_name))

		self.mmqgis_fill_combo_box_with_vector_layers(self.destination_layer_name)
		self.mmqgis_fill_combo_box_with_vector_layer_fields(self.destination_key_field, self.destination_layer_name)
		self.destination_layer_name.currentIndexChanged.connect(lambda:
			self.mmqgis_fill_combo_box_with_vector_layer_fields(
			self.destination_key_field, self.destination_layer_name))

		self.frame_count.setText("20")

		self.frame_directory.setStorageMode(QgsFileWidget.GetDirectory)
		self.frame_directory.setFilePath(self.mmqgis_frame_directory())

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_print_layouts(self.print_layout)
		self.mmqgis_fill_combo_box_with_vector_layers(self.source_layer_name)
		self.mmqgis_fill_combo_box_with_vector_layers(self.destination_layer_name)

	def run(self):
		print_layout = self.mmqgis_find_print_layout(self.print_layout.currentText())

		source_layer = self.mmqgis_find_layer(self.source_layer_name.currentText())
		source_key_field = self.source_key_field.currentText()

		destination_layer = self.mmqgis_find_layer(self.destination_layer_name.currentText())
		destination_key_field = self.destination_key_field.currentText()

		frame_count = int(self.frame_count.displayText())
		frame_directory = str(self.frame_directory.filePath())

		message = mmqgis_animate_location(print_layout, source_layer, source_key_field, \
			destination_layer, destination_key_field, frame_count, \
			frame_directory, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Animate Migration", message)

# ------------------------------------------------------------------------
#    mmqgis_animate_sequence - Create animations by displaying successive rows
# ------------------------------------------------------------------------

from mmqgis_animate_sequence_form import *

class mmqgis_animate_sequence_dialog(mmqgis_dialog, Ui_mmqgis_animate_sequence_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_print_layouts(self.print_layout)
		self.mmqgis_fill_list_widget_with_vector_layers(self.input_layer_names)

		self.frame_directory.setStorageMode(QgsFileWidget.GetDirectory)
		self.frame_directory.setFilePath(self.mmqgis_frame_directory())

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_print_layouts(self.print_layout)
		self.mmqgis_fill_list_widget_with_vector_layers(self.input_layer_names)

	def run(self):
		print_layout = self.mmqgis_find_print_layout(self.print_layout.currentText())

		layers = []
		for item in self.input_layer_names.selectedItems():
			layer = self.mmqgis_find_layer(item.text())
			if layer == None:
				QMessageBox.critical(self.iface.mainWindow(), "Animate Rows", 
					"Invalid layer name: " + str(item.text()))
				return
			layers.append(layer)
			
		if len(layers) <= 0:
			QMessageBox.critical(self.iface.mainWindow(), "Animate Rows", "No layers given to animate")
			return 

		cumulative = self.cumulative.isChecked()
		frame_directory = str(self.frame_directory.filePath())

		message = mmqgis_animate_sequence(print_layout, layers, cumulative, \
			frame_directory, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Animate Rows", message)


# ------------------------------------------------------------------------
#    mmqgis_animate_zoom - Animate map zoom and pan
# ------------------------------------------------------------------------

from mmqgis_animate_zoom_form import *

class mmqgis_animate_zoom_dialog(mmqgis_dialog, Ui_mmqgis_animate_zoom_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_print_layouts(self.print_layout)

		self.start_zoom.addItems([str(x) for x in range(1,21)])
		self.start_zoom.setCurrentIndex(14)

		self.end_zoom.addItems([str(x) for x in range(1,21)])
		self.end_zoom.setCurrentIndex(14)

		canvas = iface.mapCanvas()
		if canvas:
			wgs84 = QgsCoordinateReferenceSystem("PROJ4:+proj=longlat +datum=WGS84 +no_defs")
			transform = QgsCoordinateTransform(QgsProject.instance().crs(), wgs84, QgsProject.instance())
			center = transform.transform(canvas.center())
			self.start_long.setText(str(center.x()))
			self.start_lat.setText(str(center.y()))
			self.end_long.setText(str(center.x()))
			self.end_lat.setText(str(center.y()))
		
		self.frame_count.setText("20")

		self.frame_directory.setStorageMode(QgsFileWidget.GetDirectory)
		self.frame_directory.setFilePath(self.mmqgis_frame_directory())

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_print_layouts(self.print_layout)

	def run(self):
		print_layout = self.mmqgis_find_print_layout(self.print_layout.currentText())
		try:
			start_lat = float(self.start_lat.displayText())
			start_long = float(self.start_long.displayText())
		except: 
			QMessageBox.critical(self.iface.mainWindow(), "Animate Zoom", "Invalid start lat/long")
			return

		try:
			end_lat = float(self.end_lat.displayText())
			end_long = float(self.end_long.displayText())
		except: 
			QMessageBox.critical(self.iface.mainWindow(), "Animate Zoom", "Invalid end lat/long")
			return

		start_zoom = int(self.start_zoom.currentText())
		end_zoom = int(self.end_zoom.currentText())

		try: 
			frame_count = int(self.frame_count.displayText())
		except:
			QMessageBox.critical(self.iface.mainWindow(), "Animate Zoom", "Invalid frame count")
			return

		frame_directory = str(self.frame_directory.filePath())
			
		message = mmqgis_animate_zoom(print_layout, start_lat, \
			start_long, start_zoom, end_lat, end_long, end_zoom, \
			frame_count, frame_directory, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "Animate Zoom", message)


# ----------------------------------------------------------
#    mmqgis_attribute_export - Export attributes to CSV file
# ----------------------------------------------------------

from mmqgis_attribute_export_form import *

class mmqgis_attribute_export_dialog(mmqgis_dialog, Ui_mmqgis_attribute_export_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

		self.field_delimiter.addItems(["(comma)", "(semicolon)", "(space)"])
		self.line_terminator.addItems(["CR-LF", "LF"])
		self.decimal_mark.addItems(["(period)", "(comma)"])

		self.input_layer_name.currentIndexChanged.connect(self.set_attributes)
		self.set_attributes()

		self.mmqgis_initialize_tabular_output_file_widget(self.output_csv_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def set_attributes(self):
		self.attributes.clear()
		layer = self.mmqgis_find_layer(self.input_layer_name.currentText())
		if (layer == None):
			return

		for field in layer.fields():
			self.attributes.addItem(field.name())

		# Decimal mark is dependent on locale (comma instead of decimal point in Europe)
		# This doesn't use local override in settings (although it should)
		# Idiot check to make sure it's either a period or comma

		# QGIS configured country codes (locale/userLocale) are not
		# usable with python locale, so just use QLocale from user interface

		if (self.locale().decimalPoint() == '.'):
			self.decimal_mark.setCurrentIndex(self.decimal_mark.findText("(period)"))
			self.field_delimiter.setCurrentIndex(self.field_delimiter.findText("(comma)"))

		else:
			self.decimal_mark.setCurrentIndex(self.decimal_mark.findText("(comma)"))
			self.field_delimiter.setCurrentIndex(self.field_delimiter.findText("(semicolon)"))

	def run(self):
		input_layer = self.mmqgis_find_layer(self.input_layer_name.currentText())

		attribute_names = []
		for x in self.attributes.selectedItems():
			attribute_names.append(str(x.text()))

		if str(self.field_delimiter.currentText()) == "(space)":
			field_delimiter = " "
		elif str(self.field_delimiter.currentText()) == "(semicolon)":
			field_delimiter = ";"
		else:
			field_delimiter = ","

		if str(self.line_terminator.currentText()) == "LF":
			line_terminator = "\n"
		else:
			line_terminator = "\r\n"

		if str(self.decimal_mark.currentText()) == "(comma)":
			decimal_mark = ','
		else:
			decimal_mark = '.'

		output_csv_name = str(self.output_csv_name.filePath())

		message = mmqgis_attribute_export(input_layer, attribute_names, output_csv_name, 
			field_delimiter, line_terminator, decimal_mark, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Attribute Export", message)

# --------------------------------------------------------------------------
#    mmqgis_attribute_join - Join attributes from a CSV file to a shapefile
# --------------------------------------------------------------------------

from mmqgis_attribute_join_form import *

class mmqgis_attribute_join_dialog(mmqgis_dialog, Ui_mmqgis_attribute_join_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)
		self.mmqgis_fill_combo_box_with_vector_layer_fields(self.input_layer_attribute, self.input_layer_name)

		self.input_layer_name.currentIndexChanged.connect(lambda: \
			self.mmqgis_fill_combo_box_with_vector_layer_fields( \
			self.input_layer_attribute, self.input_layer_name))

		self.input_csv_name.fileChanged.connect(lambda: \
			self.mmqgis_fill_combo_box_with_csv_fields( \
			self.input_csv_attribute, self.input_csv_name))

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def run(self):
		input_layer = self.mmqgis_find_layer(self.input_layer_name.currentText())
		input_layer_attribute = str(self.input_layer_attribute.currentText())
		input_csv_name = str(self.input_csv_name.filePath())
		input_csv_attribute = str(self.input_csv_attribute.currentText())
		output_file_name = str(self.output_file_name.filePath())
		# not_found_name = str(self.not_found_name.filePath())

		message = mmqgis_attribute_join(input_layer, input_layer_attribute, \
			input_csv_name, input_csv_attribute, \
			output_file_name, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Attribute Join", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")

# ---------------------------------------------------------
#    mmqgis_buffers - Create buffer polygons
# ---------------------------------------------------------

from mmqgis_buffers_form import *

class mmqgis_buffers_dialog(mmqgis_dialog, Ui_mmqgis_buffers_form):
	def __init__(self, iface):

		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)
		self.input_layer_name.currentIndexChanged.connect(self.layer_changed)

		self.radius_attribute.currentIndexChanged.connect(self.radius_attribute_changed)
		self.radius.setText(str(0.5))
		self.radius_unit.addItems(["Kilometers", "Feet", "Miles", "Nautical Miles", "Meters"])
		self.radius_unit.setCurrentIndex(2) # miles

		self.edges_attribute.currentIndexChanged.connect(self.edges_attribute_changed)
		self.edge_count.addItems(["3 (Triangle)", "4 (Square)", "5 (Pentagon)", \
				"6 (Hexagon)", "32 (Rough Circle)", "64 (Smooth Circle)", "128 (Fine Circle)"])
		self.edge_count.setCurrentIndex(4) # rough circle

		self.rotation_attribute.currentIndexChanged.connect(self.rotation_attribute_changed)
		self.rotation_degrees.setText(str(0))

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

		self.layer_changed()

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def edges_attribute_changed(self):
		self.edge_count.setEnabled(self.edges_attribute.currentText() == "(fixed)")

	def radius_attribute_changed(self):
		self.radius.setEnabled(self.radius_attribute.currentText() == "(fixed)")

	def rotation_attribute_changed(self):
		self.rotation_degrees.setEnabled(self.rotation_attribute.currentText() == "(fixed)")

	def layer_changed(self):
		self.edges_attribute.clear()
		self.radius_attribute.clear()
		self.rotation_attribute.clear()

		self.radius_attribute.addItem("(fixed)")
		self.rotation_attribute.addItem("(fixed)")

		self.radius_attribute.setCurrentIndex(0)
		self.rotation_attribute.setCurrentIndex(0)

		self.radius.setEnabled(True)

		layer = self.mmqgis_find_layer(str(self.input_layer_name.currentText()))
		if (layer == None):
			return

		for field in layer.fields().toList():
			if (field.type() in [QVariant.Double, QVariant.Int, QVariant.UInt, \
					QVariant.LongLong, QVariant.ULongLong]):
				self.radius_attribute.addItem(field.name())
				self.rotation_attribute.addItem(field.name())


		if (layer.wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.Point25D, \
				QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPoint25D]):
			self.edge_count.setEnabled(True)
			self.rotation_degrees.setEnabled(True)
			self.rotation_attribute.setEnabled(True)

			self.edges_attribute.addItem("(fixed)")

			for field in layer.fields().toList():
				if (field.type() in [QVariant.Double, QVariant.Int, QVariant.UInt, \
						QVariant.LongLong, QVariant.ULongLong]):
					self.edges_attribute.addItem(field.name())


		elif (layer.wkbType() in [QgsWkbTypes.LineString, QgsWkbTypes.LineString25D, \
		      QgsWkbTypes.MultiLineString, QgsWkbTypes.MultiLineString25D]):

			self.edge_count.setEnabled(False)
			self.rotation_degrees.setEnabled(False)
			self.rotation_attribute.setEnabled(False)

			self.edges_attribute.addItems(["Rounded", "Flat End", "North Side", \
				"East Side", "South Side", "West Side"])

		else:
			self.edge_count.setEnabled(False)
			self.rotation_degrees.setEnabled(False)
			self.rotation_attribute.setEnabled(False)

			self.edges_attribute.addItems(["Rounded"])

		self.edges_attribute.setCurrentIndex(0)


	def run(self):
		input_layer = self.mmqgis_find_layer(str(self.input_layer_name.currentText()))

		selected_only = self.selected_only.isChecked()

		# Radius
		radius_attribute = self.radius_attribute.currentText()
		if (radius_attribute == "(fixed)"):
			radius_attribute = None

		try:
			radius = float(self.radius.displayText())
		except:
			QMessageBox.critical(self.iface.mainWindow(), "Create Buffers", 
				"Invalid radius number format: " + str(self.radius.displayText()))
			return None

		radius_unit = self.radius_unit.currentIndex()
		radius_unit = str(self.radius_unit.currentText())

		# Shape / Edges
		edges_attribute = self.edges_attribute.currentText()
		if (edges_attribute == "(fixed)"):
			edges_attribute = None

		edge_count = int(re.match("([1-9]{1,3})",self.edge_count.currentText())[0])
		# edge_count = int(self.edge_count.currentText()[0:2])

		# Rotation
		rotation_attribute = self.rotation_attribute.currentText()
		if (rotation_attribute == "(fixed)"):
			rotation_attribute = None

		try:
			rotation_degrees = float(self.rotation_degrees.displayText())
		except:
			QMessageBox.critical(self.iface.mainWindow(), "Create Buffers", 
				"Invalid rotation number format: " + str(self.rotation_degrees.displayText()))
			return None

		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_buffers(input_layer, selected_only, radius_attribute, radius, radius_unit, \
			edges_attribute, edge_count, rotation_attribute, rotation_degrees, \
			output_file_name, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "Create Buffers", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")


# ------------------------------------------------------------------------------------------
#    mmqgis_change_projection_geometries - Save to shaperile while removing duplicate shapes
# ------------------------------------------------------------------------------------------

from mmqgis_change_projection_form import *

class mmqgis_change_projection_dialog(mmqgis_dialog, Ui_mmqgis_change_projection_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

		self.input_layer_name.currentIndexChanged.connect(self.refresh_proj4)
		self.new_crs.crsChanged.connect(self.refresh_proj4)

		self.old_proj4.setReadOnly(True)
		self.new_proj4.setReadOnly(True)
		self.refresh_proj4()

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def refresh_proj4(self):
		input_layer = self.mmqgis_find_layer(str(self.input_layer_name.currentText()))
		if input_layer:
			self.old_proj4.setText(str(input_layer.crs().toProj4()))
		
		new_crs = self.new_crs.crs()
		if new_crs:
			self.new_proj4.setText(str(new_crs.toProj4()))
		
	def run(self):
		input_layer = self.mmqgis_find_layer(str(self.input_layer_name.currentText()))
		new_crs = self.new_crs.crs()
		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_change_projection(input_layer, new_crs, 
			output_file_name, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Change projection", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")

# ------------------------------------------------------------------------------------------
#    mmqgis_delete_duplicate_geometries - Save to shaperile while removing duplicate shapes
# ------------------------------------------------------------------------------------------

from mmqgis_delete_duplicate_form import *

class mmqgis_delete_duplicate_dialog(mmqgis_dialog, Ui_mmqgis_delete_duplicate_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def run(self):
		input_layer = self.mmqgis_find_layer(str(self.input_layer_name.currentText()))
		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_delete_duplicate_geometries(input_layer, \
			output_file_name, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Delete Duplicate Geometries", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")

# ---------------------------------------------------------
#    mmqgis_float_to_text - Change text fields to numbers
# ---------------------------------------------------------

from mmqgis_float_to_text_form import *

class mmqgis_float_to_text_dialog(mmqgis_dialog, Ui_mmqgis_float_to_text_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)
		self.input_layer_name.currentIndexChanged.connect(self.set_attributes)
		self.set_attributes()

		self.separator.clear()
		self.separator.addItems(["None", "Comma", "Space"])

		self.decimals.clear()
		for x in range(12):
			self.decimals.addItem(str(x))

		self.multiplier.setText("1")

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def set_attributes(self):
		self.attributes.clear()
		layer = self.mmqgis_find_layer(self.input_layer_name.currentText())
		if (layer == None):
			return

		# Needed so joined fields are visible?
		layer.updateFields()

		for field in layer.fields().toList():
			if (field.type() in [QVariant.Double, QVariant.Int, QVariant.UInt, \
						QVariant.LongLong, QVariant.ULongLong]):
				self.attributes.addItem(field.name())
				self.attributes.item(self.attributes.count() - 1).setSelected(1)

	def run(self):
		input_layer = self.mmqgis_find_layer(str(self.input_layer_name.currentText()))

		attributes = []
		for x in range(0, self.attributes.count()):
			if self.attributes.item(x).isSelected():
				attributes.append(self.attributes.item(x).text())

		if str(self.separator.currentText()) == "Comma":
			separator = ','
		elif str(self.separator.currentText()) == "Space":
			separator = ' '
		else:
			separator = None

		decimals = self.decimals.currentIndex()

		try:
			multiplier = float(self.multiplier.displayText())
		except:
			multiplier = 1

		prefix = str(self.prefix.text())
		suffix = str(self.suffix.text())

		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_float_to_text(input_layer, attributes, 
			separator, decimals, multiplier, prefix, suffix, \
			output_file_name, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Float to Text", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")


# ---------------------------------------------------------------------
#    mmqgis_geocode_reverse - Reverse geocode locations to addresses
# ---------------------------------------------------------------------

from mmqgis_geocode_reverse_form import *

class mmqgis_geocode_reverse_dialog(mmqgis_dialog, Ui_mmqgis_geocode_reverse_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)
		self.web_service.addItems(["OpenStreetMap / Nominatim", "Google"])
		self.web_service.currentIndexChanged.connect(self.web_service_changed)
		self.api_key.setEnabled(False)

		self.duplicate_handling.addItems(["Use Only First Result", "Multiple Features for Multiple Results"])

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def web_service_changed(self):
		self.api_key.setEnabled(str(self.web_service.currentText()) == "Google")

	def run(self):
		input_layer = self.mmqgis_find_layer(str(self.input_layer_name.currentText()))
		web_service = str(self.web_service.currentText())
		api_key = str(self.api_key.displayText())
		use_first = str(self.duplicate_handling.currentText()) == "Use Only First Result"
		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_geocode_reverse(input_layer, web_service, api_key, use_first, \
			output_file_name, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Reverse Geocode", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")

# ---------------------------------------------------------------------------------------
#    mmqgis_geocode_street_layer - Geocode addresses from street address finder layer
# ---------------------------------------------------------------------------------------

from mmqgis_geocode_street_layer_form import *

class mmqgis_geocode_street_layer_dialog(mmqgis_dialog, Ui_mmqgis_geocode_street_layer_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.input_csv_name.fileChanged.connect(self.set_csv_attributes)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)
		self.input_layer_name.currentIndexChanged.connect(self.set_layer_attributes)
		self.set_layer_attributes(0)

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

		self.mmqgis_initialize_tabular_output_file_widget(self.not_found_file_name, "-notfound.csv")

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def set_csv_attributes(self):
		header = self.mmqgis_read_csv_header(self.input_csv_name.filePath())
		if not header:
			return

		# Add attributes to street and number
		self.street_name_column.clear()
		self.number_column.clear()
		self.zip_column.clear()

		self.zip_column.addItem("(none)")
		for field in header:
			self.street_name_column.addItem(field)
			self.number_column.addItem(field)
			self.zip_column.addItem(field)

		self.zip_column.setCurrentIndex(0)
		for x, field in enumerate(header):
			if field.strip().lower().find("street") >= 0:
				self.street_name_column.setCurrentIndex(x)

			elif field.strip().lower().find("number") >= 0:
				self.number_column.setCurrentIndex(x)

			# Leave this up to user choice because ZIP codes can be flaky

			# elif field.strip().lower().find("zip") >= 0:
			#	self.zip_column.setCurrentIndex(x + 1)

	def set_layer_attributes(self, index):
		# index parameter required for currentIndexChanged() signal and is not used
		layer_name = str(self.input_layer_name.currentText())
		layer = self.mmqgis_find_layer(layer_name)

		if not layer:
			# print "Layer not found " + layer_name
			return

		self.street_name_attr.clear()

		self.left_from_attr.clear()
		self.left_to_attr.clear()
		self.right_from_attr.clear()
		self.right_to_attr.clear()
		self.left_zip_attr.clear()
		self.right_zip_attr.clear()

		self.from_x_attr.clear()
		self.from_y_attr.clear()
		self.to_x_attr.clear()
		self.to_y_attr.clear()
		self.setback.setText("0")


		# From/To options to use line geometries for X/Y coordinates
		# Assumes order of line vertices in shapefile is consistent

		self.from_x_attr.addItem("(street line order)")
		self.from_y_attr.addItem("(street line order)")
		self.to_x_attr.addItem("(street line order)")
		self.to_y_attr.addItem("(street line order)")
		self.left_zip_attr.addItem("(none)")
		self.right_zip_attr.addItem("(none)")

		self.from_x_attr.setCurrentIndex(0)
		self.from_y_attr.setCurrentIndex(0)
		self.to_x_attr.setCurrentIndex(0)
		self.to_y_attr.setCurrentIndex(0)
		self.left_zip_attr.setCurrentIndex(0)
		self.right_zip_attr.setCurrentIndex(0)

		# Add all attributes to lists

		for field in layer.fields().toList():
			self.street_name_attr.addItem(str(field.name()))
			self.from_x_attr.addItem(str(field.name()))
			self.from_y_attr.addItem(str(field.name()))
			self.to_x_attr.addItem(str(field.name()))
			self.to_y_attr.addItem(str(field.name()))
			self.left_from_attr.addItem(str(field.name()))
			self.left_to_attr.addItem(str(field.name()))
			self.right_from_attr.addItem(str(field.name()))
			self.right_to_attr.addItem(str(field.name()))
			self.left_zip_attr.addItem(str(field.name()))
			self.right_zip_attr.addItem(str(field.name()))


		# Select different parameters based on guesses from attribute names

		for index, field in enumerate(layer.fields()):
			if str(field.name()).lower().find("name") >= 0:
				self.street_name_attr.setCurrentIndex(index)

			elif (str(field.name().lower()).find("street") >= 0):
				self.street_name_attr.setCurrentIndex(index)

			elif (str(field.name().lower()).find("calle") >= 0):
				self.street_name_attr.setCurrentIndex(index)

			elif str(field.name()).lower() == "xfrom":
				self.from_x_attr.setCurrentIndex(index + 2)

			elif str(field.name()).lower() == "yfrom":
				self.from_y_attr.setCurrentIndex(index + 2)

			elif str(field.name()).lower() == "xto":
				self.to_x_attr.setCurrentIndex(index + 2)

			elif str(field.name()).lower() == "yto":
				self.to_y_attr.setCurrentIndex(index + 2)

			elif str(field.name()).lower() == "lfromadd":
				self.left_from_attr.setCurrentIndex(index)

			elif str(field.name()).lower() == "lfromhn":
				self.left_from_attr.setCurrentIndex(index)

			elif str(field.name()).lower() == "ltoadd":
				self.left_to_attr.setCurrentIndex(index)

			elif str(field.name()).lower() == "ltohn":
				self.left_to_attr.setCurrentIndex(index)

			elif str(field.name()).lower() == "rfromadd":
				self.right_from_attr.setCurrentIndex(index)

			elif str(field.name()).lower() == "rfromhn":
				self.right_from_attr.setCurrentIndex(index)

			elif str(field.name()).lower() == "rtoadd":
				self.right_to_attr.setCurrentIndex(index)

			elif str(field.name()).lower() == "rtohn":
				self.right_to_attr.setCurrentIndex(index)

			elif (str(field.name().lower()).find("right") >= 0):
				if (str(field.name().lower()).find("from") >= 0):
					self.right_from_attr.setCurrentIndex(index)

				elif (str(field.name().lower()).find("to") >= 0):
					self.right_to_attr.setCurrentIndex(index)

			elif (str(field.name().lower()).find("left") >= 0):
				if (str(field.name().lower()).find("from") >= 0):
					self.left_from_attr.setCurrentIndex(index)

				elif (str(field.name().lower()).find("to") >= 0):
					self.left_to_attr.setCurrentIndex(index)

			# ZIP Codes can be flaky, so make the default to not use the field

			# elif str(field.name()).lower() == "zipl":
			#	self.left_zip_attr.setCurrentIndex(index + 1)

			# elif str(field.name()).lower() == "zipr":
			#	self.right_zip_attr.setCurrentIndex(index + 1)

	


	def run(self):
		input_csv_name = str(self.input_csv_name.filePath()).strip()
		street_name_column = str(self.street_name_column.currentText()).strip()
		number_column = str(self.number_column.currentText()).strip()
		zip_column = str(self.zip_column.currentText()).strip()
		if zip_column == "(none)":
			zip_column = None

		input_layer_name = str(self.input_layer_name.currentText())
		input_layer = self.mmqgis_find_layer(input_layer_name)
		street_name_attr = str(self.street_name_attr.currentText())

		left_from_attr = str(self.left_from_attr.currentText())
		left_to_attr = str(self.left_to_attr.currentText())
		left_zip_attr = str(self.left_zip_attr.currentText())
		if left_zip_attr == "(none)":
			left_zip_attr = None

		right_from_attr = str(self.right_from_attr.currentText())
		right_to_attr = str(self.right_to_attr.currentText())
		right_zip_attr = str(self.right_zip_attr.currentText())
		if right_zip_attr == "(none)":
			right_zip_attr = None

		from_x_attr = str(self.from_x_attr.currentText())
		if from_x_attr == "(street line order)":
			from_x_attr = None
		from_y_attr = str(self.from_y_attr.currentText())
		if from_y_attr == "(street line order)":
			from_y_attr = None

		to_x_attr = str(self.to_x_attr.currentText())
		if to_x_attr == "(street line order)":
			to_x_attr = None
		to_y_attr = str(self.to_y_attr.currentText())
		if to_y_attr == "(street line order)":
			to_y_attr = None

		try:
			setback = float(self.setback.displayText())
		except: 
			QMessageBox.critical(self.iface.mainWindow(), "Geocode Street Layer", "Invalid setback")
			return

		output_file_name = str(self.output_file_name.filePath())
		not_found_file = self.not_found_file_name.filePath()

		message = mmqgis_geocode_street_layer(input_csv_name, number_column, street_name_column, zip_column, \
			input_layer, street_name_attr, left_from_attr, left_to_attr, left_zip_attr, \
			right_from_attr, right_to_attr, right_zip_attr, \
			from_x_attr, from_y_attr, to_x_attr, to_y_attr, setback, \
			output_file_name, not_found_file, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "Geocode Street Layer", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")

# -------------------------------------------------------------------------------------
#    mmqgis_geocode_web_service - Geocode using a web service (Google, Nominatim, etc.)
# -------------------------------------------------------------------------------------

from mmqgis_geocode_web_service_form import *

#pyqt4-dev-tools
#designer

class mmqgis_geocode_web_service_dialog(mmqgis_dialog, Ui_mmqgis_geocode_web_service_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.input_csv_name.fileChanged.connect(self.set_csv_attributes)

		web_services = ["OpenStreetMap / Nominatim", "Google", "US Census Bureau", "ESRI Server", "NetToolKit"]
		self.web_service.clear()
		self.web_service.addItems(web_services)
		self.web_service.setCurrentIndex(0)
		self.api_key.setEnabled(False)
		self.web_service.currentIndexChanged.connect(self.service_changed)

		self.duplicate_handling.addItems(["Use Only First Result", "Multiple Features for Multiple Results"])

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

		self.mmqgis_initialize_tabular_output_file_widget(self.not_found_file_name)


	def service_changed(self):
		if str(self.web_service.currentText()).strip() == "ESRI Server":
			self.api_key_label.setText("ESRI Server URL")

			self.api_key.setEnabled(True)
		else:
			self.api_key_label.setText("API Key")

			self.api_key.setEnabled(str(self.web_service.currentText()).strip() \
				in ["Google", "NetToolKit"])

		self.parameter_attribute_4.setEnabled(str(self.web_service.currentText()).strip() != "US Census Bureau")

	def set_csv_attributes(self):
		combolist = [ self.parameter_attribute_1, self.parameter_attribute_2, \
			self.parameter_attribute_3, self.parameter_attribute_4 ]

		for box in combolist:
			box.clear()
			box.addItem("(none)")
			box.setCurrentIndex(0)

		input_csv = QgsVectorLayer(str(self.input_csv_name.filePath()))

		if len(input_csv.fields()) <= 0:
			return

		for index, field in enumerate(input_csv.fields()):
			field_name = field.name()

			for box in combolist:
				box.addItem(field_name)

			if field_name.lower().find("addr") >= 0:
				self.parameter_attribute_1.setCurrentIndex(index + 1)
			if field_name.lower().find("street") >= 0:
				self.parameter_attribute_2.setCurrentIndex(index + 1)

			if field_name.lower().find("city") >= 0:
				self.parameter_attribute_2.setCurrentIndex(index + 1)

			if field_name.lower().find("state") >= 0:
				self.parameter_attribute_3.setCurrentIndex(index + 1)
			if field_name.lower() == "st":
				self.parameter_attribute_3.setCurrentIndex(index + 1)
			if field_name.lower().find("province") >= 0:
				self.parameter_attribute_3.setCurrentIndex(index + 1)

			if field_name.lower().find("country") >= 0:
				self.parameter_attribute_4.setCurrentIndex(index + 1)


	def run(self):
		input_csv_name = str(self.input_csv_name.filePath()).strip()

		parameters = []
		if self.parameter_attribute_1.currentText() and (self.parameter_attribute_1.currentText() != "(none)"):
			parameters.append((str(self.parameter_name_1.text()).strip(), 
				str(self.parameter_attribute_1.currentText()).strip()))

		if self.parameter_attribute_2.currentText() and (self.parameter_attribute_2.currentText() != "(none)"):
			parameters.append((str(self.parameter_name_2.text()).strip(), 
				str(self.parameter_attribute_2.currentText()).strip()))

		if self.parameter_attribute_3.currentText() and (self.parameter_attribute_3.currentText() != "(none)"):
			parameters.append((str(self.parameter_name_3.text()).strip(), 
				str(self.parameter_attribute_3.currentText()).strip()))

		if self.parameter_attribute_4.currentText() and (self.parameter_attribute_4.currentText() != "(none)"):
			parameters.append((str(self.parameter_name_4.text()).strip(), 
				str(self.parameter_attribute_4.currentText()).strip()))

		web_service = str(self.web_service.currentText()).strip()

		api_key = str(self.api_key.displayText()).strip()

		if (api_key == "(none)") or (api_key == ""):
			api_key = None

		use_first = str(self.duplicate_handling.currentText()) == "Use Only First Result"

		output_file_name = str(self.output_file_name.filePath())
		not_found_file_name = self.not_found_file_name.filePath()

		message = mmqgis_geocode_web_service(input_csv_name, parameters, web_service, api_key, use_first,
			output_file_name, not_found_file_name, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Web Service Geocode", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")
		

		
# -----------------------------------------------------------------
#    mmqgis_geometry_convert - Convert geometries to simpler types
# -----------------------------------------------------------------

from mmqgis_geometry_convert_form import *

class mmqgis_geometry_convert_dialog(mmqgis_dialog, Ui_mmqgis_geometry_convert_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

		self.attribute_handling.addItems(["First", "Sum"])

		self.input_layer_name.currentIndexChanged.connect(self.set_geometry_types)
		self.new_geometry.currentIndexChanged.connect(self.set_merge_fields)

		self.set_geometry_types()

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def set_geometry_types(self):
		newtypes = []
		layer_name = self.input_layer_name.currentText()
		# for name, layer in QgsMapLayerStore.mapLayers().items():
		for name, layer in QgsProject.instance().mapLayers().items():
			# print layer_name + " =? " + layer.name() + ": " + str(layer.dataProvider().geometryType())

			if layer.name() == layer_name:
				if layer.wkbType() == QgsWkbTypes.Point:
					self.old_geometry.setText("Type: Point")
					newtypes = ["Multipoints"]

				elif layer.wkbType() == QgsWkbTypes.Point25D:
					self.old_geometry.setText("Type: Point 2.5D")
					newtypes = ["Points", "Multipoints"]

				elif layer.wkbType() == QgsWkbTypes.LineString:
					self.old_geometry.setText("Type: Lines")
					# Multi-linestring layers have a geometry type of WKBLineString,
					# so a linestring option must be provided and no
					# multilinestring option is possible
					newtypes = ["Line Centers", "Centroids", "Nodes", "Lines", "Multilines"]

				elif layer.wkbType() == QgsWkbTypes.LineString25D:
					self.old_geometry.setText("Type: Linestring 2.5D")
					newtypes = ["Line Centers", "Centroids", "Nodes", "Lines", "Multilines"]

				elif layer.wkbType() == QgsWkbTypes.Polygon:
					self.old_geometry.setText("Type: Polygon")
					newtypes = ["Centroids", "Nodes", "Lines", "Multilines", \
						"Polygons", "Multipolygons"] 

				elif layer.wkbType() == QgsWkbTypes.Polygon25D:
					self.old_geometry.setText("Type: Polygon 2.5D")
					newtypes = ["Centroids", "Nodes", "Lines", "Multilines", \
						"Polygons", "Multipolygons"]

				elif layer.wkbType() == QgsWkbTypes.MultiPoint:
					self.old_geometry.setText("Type: Multipoint")
					newtypes = ["Points", "Centroids", "Multipoints"]

				elif layer.wkbType() == QgsWkbTypes.MultiPoint25D:
					self.old_geometry.setText("Type: Multipoint 2.5D")
					newtypes = ["Points", "Centroids", "Multipoints"]

				elif layer.wkbType() == QgsWkbTypes.MultiLineString:
					self.old_geometry.setText("Type: Multilines")
					newtypes = ["Line Centers", "Centroids", "Nodes", "Lines", "Multilines"]

				elif layer.wkbType() == QgsWkbTypes.MultiLineString25D:
					self.old_geometry.setText("Type: Multilines 2.5D")
					newtypes = ["Line Centers", "Centroids", "Nodes", "Lines", "Multilines"]

				elif layer.wkbType() == QgsWkbTypes.MultiPolygon:
					self.old_geometry.setText("Type: Multipolygons")
					newtypes = ["Centroids", "Nodes", "Lines", "Multilines", "Polygons", "Multipolygons"] 

				elif layer.wkbType() == QgsWkbTypes.MultiPolygon25D:
					self.old_geometry.setText("Type: Multipolygons 2.5D")
					newtypes = ["Centroids", "Nodes", "Lines", "Multilines", "Polygons", "Multipolygons"]

		self.new_geometry.clear()
		self.new_geometry.addItems(newtypes)
		self.set_merge_fields()

	def set_merge_fields(self):
		self.merge_field.clear()
		layer = self.mmqgis_find_layer(self.input_layer_name.currentText())
		if (layer == None):
			return

		old_geometry = layer.wkbType()
		new_geometry = self.new_geometry.currentText()

		#if ((old_geometry == QgsWkbTypes.Point) and (new_geometry == "Multipoints")) or \
		#   ((old_geometry == QgsWkbTypes.Point25D) and (new_geometry == "Multipoints")) or \
		#   ((old_geometry == QgsWkbTypes.LineString) and (new_geometry == "Multilines")) or \
		#   ((old_geometry == QgsWkbTypes.LineString25D) and (new_geometry == "Multilines")) or \
		#   ((old_geometry == QgsWkbTypes.Polygon) and (new_geometry == "Multipolygons")) or \
		#   ((old_geometry == QgsWkbTypes.Polygon25D) and (new_geometry == "Multipolygons")):
		if new_geometry in ["Multipoints", "Multilines", "Multipolygons"]:
			self.merge_field.clear()
			for field in layer.fields().toList():
				self.merge_field.addItem(field.name())
			self.merge_field.setEnabled(True)
			self.attribute_handling.setEnabled(True)

		else:
			self.merge_field.clear()
			self.merge_field.setEnabled(False)
			self.attribute_handling.setEnabled(False)
		
	def run(self):
		input_layer = self.mmqgis_find_layer(str(self.input_layer_name.currentText()))
		new_geometry = str(self.new_geometry.currentText())
		output_file_name = str(self.output_file_name.filePath()).strip()

		if self.merge_field.isEnabled():
			merge_field = str(self.merge_field.currentText())
			attribute_handling = str(self.attribute_handling.currentText())
			message = mmqgis_geometry_to_multipart(input_layer, merge_field, attribute_handling, \
				output_file_name, self.mmqgis_status_callback)

		else:
			message = mmqgis_geometry_convert(input_layer, new_geometry,
				output_file_name, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Label", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")


# --------------------------------------------------------------------------
#    mmqgis_geometry_export - Export geometries and attributes to CSV files
# --------------------------------------------------------------------------

from mmqgis_geometry_export_form import *

class mmqgis_geometry_export_dialog(mmqgis_dialog, Ui_mmqgis_geometry_export_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.input_layer_name.currentIndexChanged.connect(self.check_layer_type)

		self.field_delimiter.addItems(["(comma)", "(semicolon)", "(space)"])
		self.line_terminator.addItems(["CR-LF", "LF"])

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

		self.mmqgis_initialize_tabular_output_file_widget(self.node_file_name, "-nodes.csv")

		self.mmqgis_initialize_tabular_output_file_widget(self.attribute_file_name, "-attributes.csv")

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def check_layer_type(self):
		layer = self.mmqgis_find_layer(self.input_layer_name.currentText())
		if not layer or (layer.type() != QgsMapLayer.VectorLayer):
			return

		self.attribute_file_name.setEnabled(not layer.wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.Point25D])

	def run(self):
		if str(self.field_delimiter.currentText()) == "(semicolon)":
			field_delimiter = ";"
		elif str(self.field_delimiter.currentText()) == "(space)":
			field_delimiter = " "
		else:
			field_delimiter = ","

		if str(self.line_terminator.currentText()) == "LF":
			line_terminator = "\n"
		else:
			line_terminator = "\r\n"

		input_layer_name = self.input_layer_name.currentText()
		input_layer = self.mmqgis_find_layer(input_layer_name)
		node_file_name = self.node_file_name.filePath()
		attribute_file_name = self.attribute_file_name.filePath()

		message = mmqgis_geometry_export_to_csv(input_layer, node_file_name, 
			attribute_file_name, field_delimiter, line_terminator, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Geometry Export", message)


# ---------------------------------------------------------------------------------------
#    mmqgis_geometry_import - Import geometries from a CSV files of nodes and attributes
# ---------------------------------------------------------------------------------------

from mmqgis_geometry_import_form import *

class mmqgis_geometry_import_dialog(mmqgis_dialog, Ui_mmqgis_geometry_import_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.geometry_type.addItems(["Point", "LineString", "Polygon", \
			"MultiPoint", "MultiLineString", "MultiPolygon"])

		self.input_csv_name.fileChanged.connect(self.set_field_names)
		self.geometry_type.currentIndexChanged.connect(self.set_field_names)

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def set_field_names(self):
		header = self.mmqgis_read_csv_header(self.input_csv_name.filePath())
		if not header:
			return

		self.shape_id_field.clear()
		self.part_id_field.clear()
		self.longitude_field.clear()
		self.latitude_field.clear()
		
		self.shape_id_field.addItems(header)
		self.part_id_field.addItems(header)
		self.longitude_field.addItems(header)
		self.latitude_field.addItems(header)

		for index, field in enumerate(header):
			if (field.lower() == "shapeid") or (field.lower() == 'shape_id'):
				self.shape_id_field.setCurrentIndex(index)

			elif (field.lower() == "partid") or (field.lower() == 'part_id'):
				self.part_id_field.setCurrentIndex(index)

			elif (field.lower().find("x") >= 0):
				self.longitude_field.setCurrentIndex(index)

			elif (field.lower().find("y") >= 0):
				self.latitude_field.setCurrentIndex(index)

			elif (field.lower().find('lon') >= 0):
				self.longitude_field.setCurrentIndex(index)

			elif (field.lower().find('lat') >= 0):
				self.latitude_field.setCurrentIndex(index)

		self.part_id_field.setEnabled(self.geometry_type.currentText() in
			["MultiPoint", "MultiLineString", "MultiPolygon"])

		shapename = self.input_csv_name.filePath()
		shapename = shapename.replace(".csv", ".shp")
		shapename = shapename.replace(".CSV", ".shp")
		shapename = shapename.replace(".txt", ".shp")
		shapename = shapename.replace(".TXT", ".shp")
		if shapename == self.input_csv_name.filePath():
			shapename = str(shapename) + ".shp"
		self.output_file_name.setFilePath(shapename)

	def run(self):
		input_csv_name = str(self.input_csv_name.filePath())
		shape_id_field = str(self.shape_id_field.currentText())
		part_id_field = str(self.part_id_field.currentText())
		geometry_type = str(self.geometry_type.currentText())
		longitude_field = str(self.longitude_field.currentText())
		latitude_field = str(self.latitude_field.currentText())
		output_file_name = str(self.output_file_name.filePath())

		message = mmqgis_geometry_import_from_csv(input_csv_name, shape_id_field, part_id_field, \
			geometry_type, latitude_field, longitude_field, \
			output_file_name, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "Geometry Import", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")
		




# --------------------------------------------------------
#    mmqgis_grid - Grid creation plugin
# --------------------------------------------------------

from mmqgis_grid_form import *

class mmqgis_grid_dialog(mmqgis_dialog, Ui_mmqgis_grid_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.wgs84 = QgsCoordinateReferenceSystem("PROJ4:+proj=longlat +datum=WGS84 +no_defs")
		self.current_crs = self.wgs84

		self.geometry_type.addItems(["Lines", "Rectangles", "Points", "Random Points", "Diamonds", "Hexagons"])
		self.geometry_type.setCurrentIndex(0);
		self.geometry_type.currentIndexChanged.connect(self.geometry_type_changed)

		self.x_spacing.textEdited.connect(self.x_spacing_changed)
		self.y_spacing.textEdited.connect(self.y_spacing_changed)
		self.units.addItems(["Degrees", "Layer Units", "Project Units"])
		self.units.setCurrentIndex(0);
		self.units.currentIndexChanged.connect(self.units_changed)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)
		self.input_layer_name.currentIndexChanged.connect(self.layer_changed)

		self.extent_type.addItems(["Current Window", "Layer Extent", "Whole World", "Custom Area"])
		self.extent_type.setCurrentIndex(0);
		self.extent_type.currentTextChanged.connect(self.extent_type_changed)
		self.extent_type_changed("Current Window")

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def set_extent(self, extent, enable):
		self.y_top.setText(str(extent.yMaximum()))
		self.x_left.setText(str(extent.xMinimum()))
		self.x_right.setText(str(extent.xMaximum()))
		self.y_bottom.setText(str(extent.yMinimum()))

		self.y_top.setEnabled(enable)
		self.x_left.setEnabled(enable)
		self.x_right.setEnabled(enable)
		self.y_bottom.setEnabled(enable)

		self.set_default_spacing()

	def set_default_spacing(self):
		try:
			width = float(self.x_right.displayText()) - float(self.x_left.displayText())
			height = float(self.y_top.displayText()) - float(self.y_bottom.displayText())
		except:
			width = 1
			height = 1

		if (width <= 0):
			width = 1
		if (height <= 0):
			height = 1

		x = 10 ** (math.floor(math.log(width, 10)) - 1)
		y = 10 ** (math.floor(math.log(height, 10)) - 1)

		if self.geometry_type.currentText() == "Hexagons":
			y = x / 0.866025

		self.x_spacing.setText(str(x))
		self.y_spacing.setText(str(y))


	def layer_changed(self, text):
		if (self.extent_type.currentText() == "Layer Extent"):
			self.extent_type_changed(self.extent_type.currentText())
		else:
			self.units_changed(self.units.currentText())


	def extent_type_changed(self, text):
		if (text == "Current Window"):

			self.units.setCurrentIndex(2)
			self.current_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
			self.set_extent(self.iface.mapCanvas().mapSettings().extent(), False)
			self.input_layer_name.setEnabled(False)
			
		elif (text == "Layer Extent"):

			layer = self.mmqgis_find_layer(self.input_layer_name.currentText())
			if layer == None:
				return

			self.units.setCurrentIndex(1)
			self.current_crs = layer.crs()
			self.set_extent(layer.extent(), False)
			self.input_layer_name.setEnabled(True)

		elif (text == "Custom Area"):
			# print("Enabling: ")

			self.y_top.setEnabled(True)
			self.x_left.setEnabled(True)
			self.x_right.setEnabled(True)
			self.y_bottom.setEnabled(True)

			if (self.units.currentText() != "Layer Units"):
				self.input_layer_name.setEnabled(False)

		else: # "Whole World"
			# print("Disabling: " + str(text))

			self.units.setCurrentIndex(0)
			self.current_crs = self.wgs84
			self.set_extent(QgsRectangle(-180, -90, 180, 90), False)

			if (self.units.currentText() != "Layer Units"):
				self.input_layer_name.setEnabled(False)


	def geometry_type_changed(self, text):
		if str(self.geometry_type.currentText()) == "Hexagons":
			try:
				y_spacing = float(self.y_spacing.displayText())
				self.x_spacing.setText(str(y_spacing * 0.866025403784439))
			except:
				self.set_default_spacing()

	def y_spacing_changed(self, text):
		# Hexagonal grid must maintain fixed aspect ratio to make sense
		if str(self.geometry_type.currentText()) == "Hexagons":
			try:
				y_spacing = float(text)
			except:
				y_spacing = 1
			self.x_spacing.setText(str(y_spacing * 0.866025403784439))

	def x_spacing_changed(self, text):
		if str(self.geometry_type.currentText()) == "Hexagons":
			try:
				x_spacing = float(text)
			except:
				x_spacing = 1
			self.y_spacing.setText(str(x_spacing / 0.866025))

	def units_changed(self, text):

		# Choose the appropriate CRS for the new units

		past_crs = self.current_crs

		if (text == "Layer Units"):
			layer = self.mmqgis_find_layer(str(self.input_layer_name.currentText()))
			if (layer == None):
				self.current_crs = self.wgs84
			else:
				self.current_crs = layer.crs()

			self.input_layer_name.setEnabled(True)
				
		elif (text == "Project Units"):
			self.current_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
			self.input_layer_name.setEnabled(self.extent_type.currentText() == "Layer Extent")

		else:
			self.current_crs = self.wgs84
			self.input_layer_name.setEnabled(self.extent_type.currentText() == "Layer Extent")


		# Initialization = no conversion necessary
		if not past_crs:
			return

		# Convert the extent to the new units

		try:
			extent = QgsGeometry.fromRect(QgsRectangle( \
				float(self.x_left.displayText()), float(self.y_bottom.displayText()), \
				float(self.x_right.displayText()), float(self.y_top.displayText())))
		except:
			extent = QgsGeometry.fromRect(QgsRectangle(-180, -90, 180, 90))

		extent.transform(QgsCoordinateTransform(past_crs, self.current_crs, QgsProject.instance()))

		# Set the extent text boxes and base a new spacing on that

		self.set_extent(extent.boundingBox(), (self.extent_type.currentText() == "Custom Area"))

		self.set_default_spacing()


	def run(self):
		try:
			x_spacing = float(self.x_spacing.displayText())
			y_spacing = float(self.y_spacing.displayText())
			
			y_top = float(self.y_top.displayText())
			x_left = float(self.x_left.displayText())
			x_right = float(self.x_right.displayText())
			y_bottom = float(self.y_bottom.displayText())
		except:
			QMessageBox.critical(self.iface.mainWindow(), "Grid", "Invalid dimension parameter")
			return

		if (x_spacing <= 0) or (y_spacing <= 0):
			QMessageBox.critical(self.iface.mainWindow(), "Grid", "X and Y spacing must be greater than zero")
			return

		units = self.units.currentText()
		geometry_type = self.geometry_type.currentText()
		extent_type = self.extent_type.currentText()

		# Hexagons must have a fixed aspect ratio to align
		if (geometry_type == "Hexagons"):
			y_spacing = x_spacing / 0.866025

		# Align extent on even spacing boundaries so numbers look better
		if (extent_type in ["Current Window", "Layer Extent"]):
			x_left = x_spacing * floor(x_left / x_spacing)
			x_right = x_spacing * ceil(x_right / x_spacing)
			y_bottom = y_spacing * floor(y_bottom / y_spacing)
			y_top = y_spacing * ceil(y_top / y_spacing)
			

		input_layer_name = str(self.input_layer_name.currentText())
		layer = self.mmqgis_find_layer(input_layer_name)

		if (units == "Project Units"):
			crs = self.iface.mapCanvas().mapSettings().destinationCrs()

		elif (units == "Layer Units"):
			if (layer == None):
				QMessageBox.critical(self.iface.mainWindow(), "Grid", "No Layer Selected")
				return
			crs = layer.crs()

		else:
			crs = self.wgs84

		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_grid(geometry_type, crs, x_spacing, y_spacing, x_left, y_bottom, x_right, y_top, \
				output_file_name, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "Grid", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")



# --------------------------------------------------------
#    mmqgis_gridify - Snap shape verticies to grid
# --------------------------------------------------------

from mmqgis_gridify_form import *

class mmqgis_gridify_dialog(mmqgis_dialog, Ui_mmqgis_gridify_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)
		self.layer_changed()

		self.input_layer_name.currentIndexChanged.connect(self.layer_changed)
		
		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def layer_changed(self):
		layer = self.mmqgis_find_layer(str(self.input_layer_name.currentText()))

		extent = QgsRectangle (-180.0, -90.0, 180.0, 90.0)
		if layer:
			extent = layer.extent()

		self.horizontal_spacing.setText(str(round(extent.width() / 200, 4)))
		self.vertical_spacing.setText(str(round(extent.height() / 200, 4)))

	def run(self):
		input_layer = self.mmqgis_find_layer(str(self.input_layer_name.currentText()).strip())

		try:
			horizontal_spacing = float(self.horizontal_spacing.displayText())
			vertical_spacing = float(self.vertical_spacing.displayText())
		except Exception as e:
			QMessageBox.critical(self.iface.mainWindow(), "Gridify", "Invalid spacing parameter (" + str(e) + ")")
			return

		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_gridify_layer(input_layer, horizontal_spacing, vertical_spacing, \
			output_file_name, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "Gridify", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")


# ---------------------------------------------------------------------------------
#    mmqgis_hub_lines - Create layer of lines from spokes to matching/closest hubs
# ---------------------------------------------------------------------------------

from mmqgis_hub_lines_form import *

class mmqgis_hub_lines_dialog(mmqgis_dialog, Ui_mmqgis_hub_lines_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.hub_layer_name)
		self.mmqgis_fill_combo_box_with_vector_layer_fields(self.hub_name_field, self.hub_layer_name)
		self.hub_layer_name.currentIndexChanged.connect(lambda:
			self.mmqgis_fill_combo_box_with_vector_layer_fields(self.hub_name_field, self.hub_layer_name))

		self.mmqgis_fill_combo_box_with_vector_layers(self.spoke_layer_name)
		self.mmqgis_fill_combo_box_with_vector_layer_fields(self.spoke_hub_name_field, self.spoke_layer_name)
		self.spoke_layer_name.currentIndexChanged.connect(lambda:
			self.mmqgis_fill_combo_box_with_vector_layer_fields(self.spoke_hub_name_field, self.spoke_layer_name))

		self.allocation_criteria.addItems([ "Nearest Hub", "Hub Name in Spoke Layer", "Evenly Distribute" ])
		self.allocation_criteria.currentIndexChanged.connect(self.allocation_criteria_changed)
		self.allocation_criteria_changed()

		self.output_geometry.addItems(["Lines to Hubs", "Points"])

		self.distance_unit.addItems(["Layer Units", "Meters", "Feet", "Miles", "Kilometers"])
	
		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.hub_layer_name)
		self.mmqgis_fill_combo_box_with_vector_layers(self.spoke_layer_name)

	def allocation_criteria_changed(self):
		self.spoke_hub_name_field.setEnabled(self.allocation_criteria.currentText() == "Hub Name in Spoke Layer")

	def run(self):
		hub_layer_name = str(self.hub_layer_name.currentText())
		hub_layer = self.mmqgis_find_layer(hub_layer_name)
		hub_name_field = str(self.hub_name_field.currentText())

		spoke_layer_name = str(self.spoke_layer_name.currentText())
		spoke_layer = self.mmqgis_find_layer(spoke_layer_name)
		spoke_hub_name_field = str(self.spoke_hub_name_field.currentText())

		allocation_criteria = str(self.allocation_criteria.currentText())
		output_geometry = str(self.output_geometry.currentText())
		distance_unit = str(self.distance_unit.currentText())

		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_hub_lines(hub_layer, hub_name_field, spoke_layer, spoke_hub_name_field, \
			allocation_criteria, distance_unit, output_geometry, \
			output_file_name, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "Hub Lines", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")



# from mmqgis_hub_lines_form import *
# 
# class mmqgis_hub_lines_dialog(mmqgis_dialog, Ui_mmqgis_hub_lines_form):
# 	def __init__(self, iface):
# 		mmqgis_dialog.__init__(self, iface)
# 		self.setupUi(self)
# 		self.mmqgis_set_status_bar(self.status)
# 		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)
# 
# 		self.mmqgis_fill_combo_box_with_vector_layers(self.hub_layer_name)
# 		self.mmqgis_fill_combo_box_with_vector_layers(self.spoke_layer_name)
# 
# 		self.hub_layer_name.currentIndexChanged.connect(lambda:
# 			self.mmqgis_fill_combo_box_with_vector_layer_fields(self.hub_field, self.hub_layer_name))
# 
# 		self.mmqgis_fill_combo_box_with_vector_layer_fields(self.hub_field, self.hub_layer_name)
# 
# 		self.spoke_layer_name.currentIndexChanged.connect(lambda:
# 			self.mmqgis_fill_combo_box_with_vector_layer_fields(self.spoke_field, self.spoke_layer_name))
# 
# 		self.mmqgis_fill_combo_box_with_vector_layer_fields(self.spoke_field, self.spoke_layer_name)
# 
# 		self.output_file_name.setFilePath(self.mmqgis_temp_file_name(".shp"))
# 
# 		self.mmqgis_fill_combo_box_with_output_file_formats(self.output_file_format)
# 
# 		self.output_file_format.currentIndexChanged.connect(lambda: 
# 			self.mmqgis_update_file_extension_from_file_format(self.output_file_name, self.output_file_format))
# 
# 	def run(self):
# 		hub_layer_name = str(self.hub_layer_name.currentText())
# 		hub_layer = self.mmqgis_find_layer(hub_layer_name)
# 		hub_field = str(self.hubid.currentText())
# 		spoke_layer_name = str(self.spoke_layer_name.currentText())
# 		spoke_layer = self.mmqgis_find_layer(spoke_layer_name)
# 		spoke_field = str(self.spoke_field.currentText())
# 		output_file_name = str(self.output_file_name.filePath()).strip()
# 		output_file_format = str(self.output_file_format.currentText()).strip()
# 			
# 		message = mmqgis_hub_lines(hub_layer, hub_field, spoke_layer, spoke_field, \
# 			output_file_name, output_file_format, status_callback)
# 
# 		if message:
# 			QMessageBox.critical(self.iface.mainWindow(), "Hub Lines", message)
# 		else:
# 			self.iface.addVectorLayer(output_file_name, os.path.basename(output_file_name), "ogr")


# -----------------------------------------------------------------------------------------
#    mmqgis_kml_export - Export attributes to KML file suitable for display in Google Maps
# -----------------------------------------------------------------------------------------

from mmqgis_kml_export_form import *

class mmqgis_kml_export_dialog(mmqgis_dialog, Ui_mmqgis_kml_export_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)
		self.input_layer_name.currentIndexChanged.connect(self.change_layer)
		self.change_layer()

		self.separator.addItems([ 'Field Names', 'Paragraphs', 'Commas', 'Custom HTML'])
		self.separator.currentIndexChanged.connect(self.change_description)

		self.export_data.setChecked(True)

		self.output_file_name.setStorageMode(QgsFileWidget.SaveFile)
		self.output_file_name.setFilter("KML (*.kml);;All Files (*.*)")
		self.output_file_name.setFilePath(self.mmqgis_temp_file_name(".kml"))

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def change_layer(self):
		self.mmqgis_fill_combo_box_with_vector_layer_fields(self.name_field, self.input_layer_name)
		self.separator.setCurrentIndex(0)
		self.change_description()

	def change_description(self):
		layer = self.mmqgis_find_layer(self.input_layer_name.currentText())
		if layer == None:
			return

		if (self.separator.currentText() == 'Custom HTML'):
			self.description.setEnabled(True)
			return

		description = ""
		self.description.setEnabled(False)
		for index, field in enumerate(layer.fields()):
			if (self.separator.currentText() == 'Commas'):

				if (index == 0):
					description = "<p>"
				else:
					description = description + ', '

				description = description + '{{' + field.name() + '}}'

				if (index == (len(layer.fields()) - 1)):
					description = description + "</p>"


			elif (self.separator.currentText() == 'Paragraphs'):

				description = description + '<p>{{' + field.name() + '}}</p>\n'

			else: # Field Names

				if (index == 0):
					description = "<p>"
				else:
					description = description + '\n<br/>'

				description = description + field.name() + ': {{' + field.name() + '}}'

				if (index == (len(layer.fields()) - 1)):
					description = description + "</p>"

		self.description.setPlainText(description)


	def run(self):
		input_layer_name = str(self.input_layer_name.currentText())
		input_layer = self.mmqgis_find_layer(input_layer_name)
		name_field = str(self.name_field.currentText())
		description = str(self.description.toPlainText())
		export_data = self.export_data.isChecked()
		output_file_name = str(self.output_file_name.filePath())

		message = mmqgis_kml_export(input_layer, name_field, description, export_data, \
			output_file_name, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "KML Export", message)

# --------------------------------------------------------
#    mmqgis_merge - Merge layers to single shapefile
# --------------------------------------------------------

from mmqgis_merge_form import *

class mmqgis_merge_dialog(mmqgis_dialog, Ui_mmqgis_merge_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_list_widget_with_vector_layers(self.input_layer_names)

		# Suggested by Daniel Vaz
		self.input_layer_names.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_list_widget_with_vector_layers(self.input_layer_names)

	def run(self):
		input_layers = []
		for x in range(0, self.input_layer_names.count()):
			if self.input_layer_names.item(x).isSelected():
				input_layers.append(self.mmqgis_find_layer(str(self.input_layer_names.item(x).text())))

		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_merge(input_layers, output_file_name, self.mmqgis_status_callback)

		if message != None:
			QMessageBox.critical(self.iface.mainWindow(), "Merge", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")


# ----------------------------------------------------------
#    mmqgis_search - Interactive search
# ----------------------------------------------------------

from mmqgis_search_widget import *

class mmqgis_search_widget(QtWidgets.QDockWidget, Ui_mmqgis_search_widget):

	def __init__(self, iface):
		QtWidgets.QDockWidget.__init__(self)

		iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self)

		self.iface = iface
		self.setupUi(self)

		self.refresh_layers()

		self.input_layer_names.currentIndexChanged.connect(self.set_search_attributes)

		self.results.itemSelectionChanged.connect(self.pan_to_selected_features)

		self.comparison.addItems(['contains', 'begins with', '=', '<>', '>', '>=', '<', '<='])

		self.set_search_attributes()

		self.search.clicked.connect(self.perform_search)

	def refresh_layers(self):
		self.input_layer_names.clear()
		self.input_layer_names.addItem("[Open Street Map]")
		self.input_layer_names.addItem("[All Layers]")

		for layer in self.iface.mapCanvas().layers():
			if layer.type() == QgsMapLayer.VectorLayer:
				self.input_layer_names.addItem(layer.name())

	def set_search_attributes(self):
		self.results.clear()
		self.attributes.clear()

		if (self.input_layer_names.currentText() == "[Open Street Map]"):
			self.attributes.addItem("Address")
			self.comparison.setCurrentIndex(self.comparison.findText("="))
			self.comparison.setEnabled(False)

		elif (self.input_layer_names.currentText() == "[All Layers]"):
			self.attributes.addItem("[All]")
			self.comparison.setCurrentIndex(self.comparison.findText("contains"))
			self.comparison.setEnabled(False)

		else:
			self.attributes.clear()
			for layer in self.iface.mapCanvas().layers():
				if layer.name() == self.input_layer_names.currentText():
					for field in layer.fields():
						self.attributes.addItem(field.name())

			self.attributes.addItem('[All]')
			self.comparison.setEnabled(True)

	def perform_search(self):
		self.found = []
		self.results.clear()
		max_items = 5000

		if (self.input_layer_names.currentText() == "[Open Street Map]"):
			return self.perform_nominatim_search()

		if not str(self.value.displayText()):
			return

		try:
			float(str(self.value.displayText()))
			value_is_numeric = True
		except:
			value_is_numeric = False

		for layer_name, layer in QgsProject.instance().mapLayers().items():

			# Only search selected vector layers
			if (layer.type() != QgsMapLayer.VectorLayer) or \
			   ((self.input_layer_names.currentText() != "[All Layers]") and \
			    (layer.name() != str(self.input_layer_names.currentText()))):
				continue

			expression = ""
			value = self.value.displayText().strip().replace("'", "")
			comparison = self.comparison.currentText().lower()

			# Build query expression from fields
			for field in layer.fields():
				print("  Field: " + field.name() + " " + comparison + " " + self.attributes.currentText())
				if (self.attributes.currentText() != "[All]") and \
				   (field.name() != self.attributes.currentText()):
					continue
				
				if expression != "":
					expression = expression + " OR "

				if comparison == "contains":
					expression = expression + "to_string(\"" + field.name() \
						+ "\") ILIKE \'%" + value + "%\'"

				elif comparison == "begins with":
					expression = expression + "LOWER(LEFT(to_string(\"" + field.name() \
						+ "\", " + str(len(value)) + "))) = \'" + value.lower() + "\'"

				elif value_is_numeric:
					expression = expression + "\"" + field.name() + "\" " + \
						comparison + " \'" + value.lower() + "\'"

				else:
					expression = expression + "LOWER(to_string(\"" + field.name() + "\")) " + \
						comparison + " \'" + value.lower() + "\'"

			print("Search " + layer_name + ": " + expression)
		
			# Select in this layer
			# layer.selectByExpression(expression)


			# Add to the list
			transform = QgsCoordinateTransform(layer.crs(), \
				self.iface.mapCanvas().mapSettings().destinationCrs(), QgsProject.instance())

			for feature in layer.getFeatures(expression):
				if len(self.found) >= max_items:
					break

				name = str(feature.id())
				if self.attributes.currentText() != "[All]":
					name = str(feature.attribute(self.attributes.currentText()))

				center = transform.transform(feature.geometry().boundingBox().center())
				self.found.append([layer_name, feature.id(), center])
				self.results.addItem(name)


	def perform_nominatim_search(self):
		self.found = []
		self.results.clear()

		address = str(self.value.displayText()).strip()
		address = address.replace("  ", " ")
		address = address.replace(" ", "+")

		url = "http://nominatim.openstreetmap.org/search?format=geojson&q=" + address
		try:
			user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3)"
			request = urllib.request.Request(url, headers={'User-Agent': user_agent})
			json_string = urllib.request.urlopen(request).read()
			json_array = json.loads(json_string.decode("utf-8"))

		except Exception as e:
			self.found.append([None, [0, 0]])
			self.results.addItem(str(e))
			return


		if (not "features" in json_array) or (len(json_array["features"]) <= 0):
			self.found.append([None, None, QgsPointXY(0, 0)])
			self.results.addItem("No results found")
			return

		transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem("PROJ4:+proj=longlat +datum=WGS84 +no_defs"),\
				self.iface.mapCanvas().mapSettings().destinationCrs(), QgsProject.instance())

		for result in json_array["features"]:
			try:
				name = str(result["properties"]["display_name"])
				latitude = float(result["geometry"]["coordinates"][1])
				longitude = float(result["geometry"]["coordinates"][0])
				
				self.found.append([None, None, transform.transform(QgsPointXY(longitude, latitude))])
				self.results.addItem(name)
			except:
				continue

	def pan_to_selected_features(self):

		# Remove any existing selections
		# for layer_name, layer in QgsProject.instance().mapLayers().items():
		#	if layer.type() == QgsMapLayer.VectorLayer:
		#		layer.removeSelection()

		# Build lists of features

		layer_selections = {}
		selected_points = []
	
		for x in range(self.results.count()):
			item = self.results.item(x)

			if (not item) or (not item.isSelected()):
				continue

			if self.found[x][0] in layer_selections:
				layer_selections[self.found[x][0]].append(self.found[x][1])
			else:
				layer_selections[self.found[x][0]] = [ self.found[x][1] ]
				
			selected_points.append(self.found[x][2])

		# Select features in each layer
		for selected_layer, selected_features in layer_selections.items():
			for layer_name, layer in QgsProject.instance().mapLayers().items():
				if layer_name == selected_layer:
					layer.selectByIds(selected_features)
				
		if not selected_points:
			return

		# Zoom to the center of the area containing all selected features
		center = QgsGeometry.fromMultiPointXY(selected_points).boundingBox().center()

		extent = self.iface.mapCanvas().extent()
		extent.set(center.x() - (extent.width() / 2.0), center.y() - (extent.height() / 2.0),
			center.x() + (extent.width() / 2.0), center.y() + (extent.height() / 2.0))
		self.iface.mapCanvas().setExtent(extent)

		self.iface.mapCanvas().refresh()



# --------------------------------------------------------
#    mmqgis_sort - Sort layer by attribute
# --------------------------------------------------------

from mmqgis_sort_form import *

class mmqgis_sort_dialog(mmqgis_dialog, Ui_mmqgis_sort_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

		self.input_layer_name.currentIndexChanged.connect(lambda:
			self.mmqgis_fill_combo_box_with_vector_layer_fields(self.sort_fields, self.input_layer_name))

		self.mmqgis_fill_combo_box_with_vector_layer_fields(self.sort_fields, self.input_layer_name)

		self.sort_direction.addItems(["Ascending", "Descending"])

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def run(self):
		input_layer_name = str(self.input_layer_name.currentText())
		input_layer = self.mmqgis_find_layer(input_layer_name)
		sort_field = self.sort_fields.currentText()
		sort_direction = str(self.sort_direction.currentText())
		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_sort(input_layer, sort_field, sort_direction, \
			output_file_name, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "Sort", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")



# ----------------------------------------------------------
#    mmqgis_spatial_join - Spatial Join
# ----------------------------------------------------------

from mmqgis_spatial_join_form import *

class mmqgis_spatial_join_dialog(mmqgis_dialog, Ui_mmqgis_spatial_join_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.target_layer_name)
		self.target_layer_name.currentIndexChanged.connect(self.set_join_layer)

		self.mmqgis_fill_combo_box_with_vector_layers(self.join_layer_name)

		self.field_operation.addItems(["First", "Sum", "Proportional Sum", "Average", \
			"Weighted Average", "Largest Proportion"])
		self.join_layer_name.currentIndexChanged.connect(self.set_spatial_operations)
		self.set_join_layer()

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.join_layer_name)
		self.mmqgis_fill_combo_box_with_vector_layers(self.target_layer_name)

	def set_join_layer(self):
		self.join_layer_name.clear()
		target_layer = self.mmqgis_find_layer(self.target_layer_name.currentText())
		if (target_layer == None):
			return

		self.mmqgis_fill_combo_box_with_vector_layers(self.join_layer_name)

		# Remove target layer so no accidental join to itself
		index = 0
		while (index < self.join_layer_name.count()):
			if (self.join_layer_name.itemText(index) == target_layer.name()):
				self.join_layer_name.removeItem(index)
			else:
				index = index + 1

		self.join_layer_name.setCurrentIndex(0)
		self.set_spatial_operations()

	def set_spatial_operations(self):
		target = self.mmqgis_find_layer(self.target_layer_name.currentText())
		if (target == None):
			return

		join = self.mmqgis_find_layer(self.join_layer_name.currentText())
		if (join == None):
			return

		self.spatial_operation.clear()

		if not join:
			return

		# Rasters don't have fields()
		if (not hasattr(target, "fields")) or (not hasattr(join, "fields")):
			return

		self.field_names.clear()
		for field in target.fields().toList():
			self.field_names.addItem(field.name())
			self.field_names.item(self.field_names.count() - 1).setSelected(1)

		for field in join.fields().toList():
			self.field_names.addItem(field.name())
			self.field_names.item(self.field_names.count() - 1).setSelected(1)

		if (target.wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.Point25D]):
			if (join.wkbType() in [QgsWkbTypes.Polygon, QgsWkbTypes.Polygon25D, 
			    QgsWkbTypes.MultiPolygon, QgsWkbTypes.MultiPolygon25D]):
				self.spatial_operation.addItems(["Within"])

		elif (target.wkbType() in [QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPoint25D, \
		      QgsWkbTypes.LineString, QgsWkbTypes.LineString25D, QgsWkbTypes.MultiLineString, \
		      QgsWkbTypes.MultiLineString25D]):
			if (join.wkbType() in [QgsWkbTypes.Polygon, QgsWkbTypes.Polygon25D,
			    QgsWkbTypes.MultiPolygon, QgsWkbTypes.MultiPolygon25D]):
				self.spatial_operation.addItems(["Intersects", "Within"])

		else: # Polygon
			if (join.wkbType() in [QgsWkbTypes.Point, QgsWkbTypes.Point25D]):
				self.spatial_operation.addItems(["Contains"])

			elif (join.wkbType() in [QgsWkbTypes.MultiPoint, QgsWkbTypes.MultiPoint25D,
			      QgsWkbTypes.LineString, QgsWkbTypes.LineString25D, QgsWkbTypes.MultiLineString]):
				self.spatial_operation.addItems(["Intersects", "Contains"])

			else: # Polygon
				self.spatial_operation.addItems(["Intersects", "Within", "Contains"])


	def run(self):
		target_layer_name = str(self.target_layer_name.currentText())
		target_layer = self.mmqgis_find_layer(target_layer_name)
		spatial_operation = str(self.spatial_operation.currentText())
		join_layer_name = str(self.join_layer_name.currentText())
		join_layer = self.mmqgis_find_layer(join_layer_name)
		field_operation = str(self.field_operation.currentText())
		output_file_name = str(self.output_file_name.filePath())

		field_names = []
		for x in range(0, self.field_names.count()):
			if self.field_names.item(x).isSelected():
				field_names.append(self.field_names.item(x).text())

		#start_message = "Running spatial join..."
		#self.status_bar.setFormat(start_message)
		#self.iface.statusBarIface().showMessage(start_message)

		message = mmqgis_spatial_join(target_layer, spatial_operation, join_layer, field_names, field_operation, \
			output_file_name, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "Spatial Join", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")

# ---------------------------------------------------------
#    mmqgis_text_to_float - Change text fields to numbers
# ---------------------------------------------------------

from mmqgis_text_to_float_form import *

class mmqgis_text_to_float_dialog(mmqgis_dialog, Ui_mmqgis_text_to_float_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

		self.input_layer_name.currentIndexChanged.connect(self.set_field_names)

		self.set_field_names()

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def set_field_names(self):
		self.field_names.clear()
		layer = self.mmqgis_find_layer(self.input_layer_name.currentText())
		if (layer == None):
			return

		for index, field in enumerate(layer.fields()):
			self.field_names.addItem(field.name())

			if (field.type() == QVariant.String):
				self.field_names.item(index).setSelected(1)

	def run(self):
		input_layer_name = str(self.input_layer_name.currentText())
		input_layer = self.mmqgis_find_layer(input_layer_name)

		field_names = []
		for x in range(0, self.field_names.count()):
			if self.field_names.item(x).isSelected():
				field_names.append(self.field_names.item(x).text())

		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_text_to_float(input_layer, field_names, \
			output_file_name, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "Text to Float", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")


# --------------------------------------------------------
#    mmqgis_voronoi - Voronoi diagram creation
# --------------------------------------------------------

from mmqgis_voronoi_form import *

class mmqgis_voronoi_dialog(mmqgis_dialog, Ui_mmqgis_voronoi_form):
	def __init__(self, iface):
		mmqgis_dialog.__init__(self, iface)
		self.setupUi(self)
		self.mmqgis_set_status_bar(self.status)
		self.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self.run)

		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

		self.mmqgis_initialize_spatial_output_file_widget(self.output_file_name)

	def refresh_layers(self):
		self.mmqgis_fill_combo_box_with_vector_layers(self.input_layer_name)

	def run(self):
		input_layer_name = str(self.input_layer_name.currentText())
		input_layer = self.mmqgis_find_layer(input_layer_name)
		output_file_name = str(self.output_file_name.filePath()).strip()

		message = mmqgis_voronoi_diagram(input_layer, output_file_name, self.mmqgis_status_callback)

		if message:
			QMessageBox.critical(self.iface.mainWindow(), "Voronoi", message)

		elif self.mmqgis_find_layer_by_data_source(output_file_name):
			self.iface.mapCanvas().refreshAllLayers()

		else:
			self.iface.addVectorLayer(output_file_name, "", "ogr")

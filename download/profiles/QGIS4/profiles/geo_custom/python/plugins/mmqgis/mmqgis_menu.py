# --------------------------------------------------------
#    mmqgis_menu - QGIS plugins menu class
#
#    begin                : August 5, 2009
#    copyright            : (c) 2009 - 2019 by Michael Minn
#    email                : See michaelminn.com
#
#   MMQGIS is free software and is offered without guarantee
#   or warranty. You can redistribute it and/or modify it 
#   under the terms of version 2 of the GNU General Public 
#   License (GPL v2) as published by the Free Software 
#   Foundation (www.gnu.org).
# --------------------------------------------------------

from qgis.PyQt.QtCore import *
from qgis.PyQt.QtGui import *
from qgis.core import *

from .mmqgis_dialogs import *

# ---------------------------------------------

class mmqgis_menu:
	def __init__(self, iface):
		self.iface = iface
		self.mmqgis_menu = None

	def mmqgis_add_submenu(self, submenu):
		if self.mmqgis_menu != None:
			self.mmqgis_menu.addMenu(submenu)
		else:
			self.iface.addPluginToMenu("&mmqgis", submenu.menuAction())

	def initGui(self):
		# Uncomment the following two lines to have MMQGIS accessible from a top-level menu
		self.mmqgis_menu = QtWidgets.QMenu(QCoreApplication.translate("mmqgis", "MMQGIS"))
		self.iface.mainWindow().menuBar().insertMenu(self.iface.firstRightStandardMenu().menuAction(), self.mmqgis_menu)

		# Animate Submenu
		self.animate_menu = QtWidgets.QMenu(QCoreApplication.translate("mmqgis", "&Animate"))
		self.mmqgis_add_submenu(self.animate_menu)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_animate_lines.png")
		self.animate_lines_action = QtGui.QAction(icon, "Animate Lines", self.iface.mainWindow())
		self.animate_lines_action.triggered.connect(self.animate_lines)
		self.animate_menu.addAction(self.animate_lines_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_animate_location.png")
		self.animate_location_action = QtGui.QAction(icon, "Animate Location", self.iface.mainWindow())
		self.animate_location_action.triggered.connect(self.animate_location)
		self.animate_menu.addAction(self.animate_location_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_animate_sequence.png")
		self.animate_sequence_action = QtGui.QAction(icon, "Animate Sequence", self.iface.mainWindow())
		self.animate_sequence_action.triggered.connect(self.animate_sequence)
		self.animate_menu.addAction(self.animate_sequence_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_animate_zoom.png")
		self.animate_zoom_action = QtGui.QAction(icon, "Animate Zoom and Pan", self.iface.mainWindow())
		self.animate_zoom_action.triggered.connect(self.animate_zoom)
		self.animate_menu.addAction(self.animate_zoom_action)


		# Combine Submenu
		self.combine_menu = QtWidgets.QMenu(QCoreApplication.translate("mmqgis", "&Combine"))
		self.mmqgis_add_submenu(self.combine_menu)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_attribute_join.png")
		self.attribute_join_action = QtGui.QAction(icon, "Attributes Join from CSV File", self.iface.mainWindow())
		self.attribute_join_action.triggered.connect(self.attribute_join)
		self.combine_menu.addAction(self.attribute_join_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_merge.png")
		self.merge_action = QtGui.QAction(icon, "Merge Layers", self.iface.mainWindow())
		self.merge_action.triggered.connect(self.merge)
		self.combine_menu.addAction(self.merge_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_spatial_join.png")
		self.spatial_join_action = QtGui.QAction(icon, "Spatial Join", self.iface.mainWindow())
		self.spatial_join_action.triggered.connect(self.spatial_join)
		self.combine_menu.addAction(self.spatial_join_action)


		# Create Submenu
		self.create_menu = QtWidgets.QMenu(QCoreApplication.translate("mmqgis", "&Create"))
		self.mmqgis_add_submenu(self.create_menu)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_buffers.png")
		self.buffers_action = QtGui.QAction(icon, "Create Buffers", self.iface.mainWindow())
		self.buffers_action.triggered.connect(self.buffers)
		self.create_menu.addAction(self.buffers_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_grid.png")
		self.grid_action = QtGui.QAction(icon, "Create Grid Layer", self.iface.mainWindow())
		self.grid_action.triggered.connect(self.grid)
		self.create_menu.addAction(self.grid_action)

		#icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_hub_distance.png")
		#self.hub_distance_action = QtGui.QAction(icon, "Hub Distance", self.iface.mainWindow())
		#self.hub_distance_action.triggered.connect(self.hub_distance)
		#self.create_menu.addAction(self.hub_distance_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_hub_distance.png")
		self.hub_lines_action = QtGui.QAction(icon, "Hub Lines / Distance", self.iface.mainWindow())
		self.hub_lines_action.triggered.connect(self.hub_lines)
		self.create_menu.addAction(self.hub_lines_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_voronoi.png")
		self.voronoi_action = QtGui.QAction(icon, "Voronoi Diagram", self.iface.mainWindow())
		self.voronoi_action.triggered.connect(self.voronoi)
		self.create_menu.addAction(self.voronoi_action)


		# Geocode submenu
		self.geocode_menu = QtWidgets.QMenu(QCoreApplication.translate("mmqgis", "&Geocode"))
		self.mmqgis_add_submenu(self.geocode_menu)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_geocode_web_service.png")
		self.geocode_web_service_action = QtGui.QAction(icon, "Geocode CSV with Web Service", 
			self.iface.mainWindow())
		self.geocode_web_service_action.triggered.connect(self.geocode_web_service)
		self.geocode_menu.addAction(self.geocode_web_service_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_geocode_street_layer.png")
		self.geocode_street_layer_action = QtGui.QAction(icon, "Geocode from Street Layer", self.iface.mainWindow())
		self.geocode_street_layer_action.triggered.connect(self.geocode_street_layer)
		self.geocode_menu.addAction(self.geocode_street_layer_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_geocode_reverse.png")
		self.geocode_reverse_action = QtGui.QAction(icon, "Reverse Geocode", self.iface.mainWindow())
		self.geocode_reverse_action.triggered.connect(self.geocode_reverse)
		self.geocode_menu.addAction(self.geocode_reverse_action)


		# Import / Export Submenu
		self.import_export_menu = QtWidgets.QMenu(QCoreApplication.translate("mmqgis", "&Import / Export"))
		self.mmqgis_add_submenu(self.import_export_menu)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_attribute_export.png")
		self.attribute_export_action = QtGui.QAction(icon, "Attributes Export to CSV File", self.iface.mainWindow())
		self.attribute_export_action.triggered.connect(self.attribute_export)
		self.import_export_menu.addAction(self.attribute_export_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_attribute_export.png")
		self.geometry_export_action = QtGui.QAction(icon, "Geometry Export to CSV File", self.iface.mainWindow())
		self.geometry_export_action.triggered.connect(self.geometry_export)
		self.import_export_menu.addAction(self.geometry_export_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_attribute_join.png")
		self.geometry_import_action = QtGui.QAction(icon, "Geometry Import from CSV File", self.iface.mainWindow())
		self.geometry_import_action.triggered.connect(self.geometry_import)
		self.import_export_menu.addAction(self.geometry_import_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_geocode_web_service.png")
		self.kml_export_action = QtGui.QAction(icon, "Google Maps KML Export", self.iface.mainWindow())
		self.kml_export_action.triggered.connect(self.kml_export)
		self.import_export_menu.addAction(self.kml_export_action)

		# Modify Submenu
		self.modify_menu = QtWidgets.QMenu(QCoreApplication.translate("mmqgis", "&Modify"))
		self.mmqgis_add_submenu(self.modify_menu)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_animate_location.png")
		self.change_projection_action = QtGui.QAction(icon, "Change Projection", self.iface.mainWindow())
		self.change_projection_action.triggered.connect(self.change_projection)
		self.modify_menu.addAction(self.change_projection_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_attribute_export.png")
		self.geometry_convert_action = QtGui.QAction(icon, "Convert Geometry Type", self.iface.mainWindow())
		self.geometry_convert_action.triggered.connect(self.geometry_convert)
		self.modify_menu.addAction(self.geometry_convert_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_attribute_join.png")
		self.delete_duplicate_action = QtGui.QAction(icon, "Delete Duplicate Geometries", self.iface.mainWindow())
		self.delete_duplicate_action.triggered.connect(self.delete_duplicate_geometries)
		self.modify_menu.addAction(self.delete_duplicate_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_float_to_text.png")
		self.float_to_text_action = QtGui.QAction(icon, "Float to Text", self.iface.mainWindow())
		self.float_to_text_action.triggered.connect(self.float_to_text)
		self.modify_menu.addAction(self.float_to_text_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_gridify.png")
		self.gridify_action = QtGui.QAction(icon, "Gridify", self.iface.mainWindow())
		self.gridify_action.triggered.connect(self.gridify)
		self.modify_menu.addAction(self.gridify_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_sort.png")
		self.sort_action = QtGui.QAction(icon, "Sort", self.iface.mainWindow())
		self.sort_action.triggered.connect(self.sort)
		self.modify_menu.addAction(self.sort_action)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_text_to_float.png")
		self.text_to_float_action = QtGui.QAction(icon, "Text to Float", self.iface.mainWindow())
		self.text_to_float_action.triggered.connect(self.text_to_float)
		self.modify_menu.addAction(self.text_to_float_action)

		# Search / Select Submenu
		self.search_select_menu = QtWidgets.QMenu(QCoreApplication.translate("mmqgis", "&Search / Select"))
		self.mmqgis_add_submenu(self.search_select_menu)

		icon = QIcon(os.path.dirname(__file__) + "/icons/mmqgis_search.png")
		self.search_action = QtGui.QAction(icon, "Search / Select", self.iface.mainWindow())
		self.search_action.triggered.connect(self.search)
		self.search_select_menu.addAction(self.search_action)







	def unload(self):
		if self.mmqgis_menu != None:
			self.iface.mainWindow().menuBar().removeAction(self.mmqgis_menu.menuAction())
		else:
			self.iface.removePluginMenu("&mmqgis", self.animate_menu.menuAction())
			self.iface.removePluginMenu("&mmqgis", self.combine_menu.menuAction())
			self.iface.removePluginMenu("&mmqgis", self.create_menu.menuAction())
			self.iface.removePluginMenu("&mmqgis", self.geocode_menu.menuAction())
			self.iface.removePluginMenu("&mmqgis", self.import_export_menu.menuAction())
			self.iface.removePluginMenu("&mmqgis", self.modify_menu.menuAction())

		# This one button in the plugins toolbar is for the South Derbyshire District Council (7/14/2013)
		# self.iface.removeToolBarIcon(self.search_action)

	def animate_lines(self):
		try:
			self.animate_lines_dialog.refresh_layers()
		except: 
			self.animate_lines_dialog = mmqgis_animate_lines_dialog(self.iface)

		self.animate_lines_dialog.exec()

	def animate_location(self):
		try:
			self.animate_location_dialog.refresh_layers()
		except: 
			self.animate_location_dialog = mmqgis_animate_location_dialog(self.iface)

		self.animate_location_dialog.exec()

	def animate_sequence(self):
		try:
			self.animate_sequence_dialog.refresh_layers()
		except: 
			self.animate_sequence_dialog = mmqgis_animate_sequence_dialog(self.iface)

		self.animate_sequence_dialog.exec()

	def animate_zoom(self):
		try:
			self.animate_zoom_dialog.refresh_layers()
		except: 
			self.animate_zoom_dialog = mmqgis_animate_zoom_dialog(self.iface)

		self.animate_zoom_dialog.exec()

	def attribute_export(self):
		try:
			self.attribute_export_dialog.refresh_layers()
		except: 
			self.attribute_export_dialog = mmqgis_attribute_export_dialog(self.iface)

		self.attribute_export_dialog.exec()

	def attribute_join(self):
		try:
			self.attribute_join_dialog.refresh_layers()
		except: 
			self.attribute_join_dialog = mmqgis_attribute_join_dialog(self.iface)

		self.attribute_join_dialog.exec()

	def buffers(self):
		try:
			self.buffers_dialog.refresh_layers()
		except: 
			self.buffers_dialog = mmqgis_buffers_dialog(self.iface)

		self.buffers_dialog.exec()

	def change_projection(self):
		try:
			self.change_projection_dialog.refresh_layers()
		except: 
			self.change_projection_dialog = mmqgis_change_projection_dialog(self.iface)

		self.change_projection_dialog.exec()

	def delete_duplicate_geometries(self):
		try:
			self.delete_duplicate_dialog.refresh_layers()
		except: 
			self.delete_duplicate_dialog = mmqgis_delete_duplicate_dialog(self.iface)

		self.delete_duplicate_dialog.exec()

	def float_to_text(self):
		try:
			self.float_to_text_dialog.refresh_layers()
		except: 
			self.float_to_text_dialog = mmqgis_float_to_text_dialog(self.iface)

		self.float_to_text_dialog.exec()

	def geocode_reverse(self):
		try:
			self.geocode_reverse_dialog.refresh_layers()
		except: 
			self.geocode_reverse_dialog = mmqgis_geocode_reverse_dialog(self.iface)

		self.geocode_reverse_dialog.exec()

	def geocode_street_layer(self):
		try:
			self.geocode_street_layer_dialog.refresh_layers()
		except: 
			self.geocode_street_layer_dialog = mmqgis_geocode_street_layer_dialog(self.iface)

		self.geocode_street_layer_dialog.exec()

	def geocode_web_service(self):
		try:
			self.geocode_web_service_dialog
		except: 
			self.geocode_web_service_dialog = mmqgis_geocode_web_service_dialog(self.iface)

		self.geocode_web_service_dialog.exec()
		# self.geocode_web_service_dialog.show()

	def geometry_convert(self):
		try:
			self.geometry_convert_dialog.refresh_layers()
		except: 
			self.geometry_convert_dialog = mmqgis_geometry_convert_dialog(self.iface)

		self.geometry_convert_dialog.exec()

	def geometry_export(self):
		try:
			self.geometry_export_dialog.refresh_layers()
		except: 
			self.geometry_export_dialog = mmqgis_geometry_export_dialog(self.iface)

		self.geometry_export_dialog.exec()

	def geometry_import(self):
		try:
			self.geometry_import_dialog
		except: 
			self.geometry_import_dialog = mmqgis_geometry_import_dialog(self.iface)

		self.geometry_import_dialog.exec()

	def grid(self):
		try:
			self.grid_dialog.refresh_layers()
		except: 
			self.grid_dialog = mmqgis_grid_dialog(self.iface)

		self.grid_dialog.exec()

	def gridify(self):
		try:
			self.gridify_dialog.refresh_layers()
		except: 
			self.gridify_dialog = mmqgis_gridify_dialog(self.iface)

		self.gridify_dialog.exec()

	def hub_lines(self):
		try:
			self.hub_lines_dialog.refresh_layers()
		except: 
			self.hub_lines_dialog = mmqgis_hub_lines_dialog(self.iface)

		self.hub_lines_dialog.exec()

	def kml_export(self):
		try:
			self.kml_export_dialog.refresh_layers()
		except: 
			self.kml_export_dialog = mmqgis_kml_export_dialog(self.iface)

		self.kml_export_dialog.exec()

	def merge(self):
		try:
			self.merge_dialog.refresh_layers()
		except: 
			self.merge_dialog = mmqgis_merge_dialog(self.iface)

		self.merge_dialog.exec()

	def search(self):
		# Modeless interactive widget
		# Must be saved in self, otherwise garbage collector destroys dialog
		self.search_widget = mmqgis_search_widget(self.iface)
		# self.search_widget.setWindowModality(Qt.NonModal) 
		self.search_widget.show()
		# self.search_dialog.activateWindow()

	def sort(self):
		try:
			self.sort_dialog.refresh_layers()
		except: 
			self.sort_dialog = mmqgis_sort_dialog(self.iface)

		self.sort_dialog.exec()

	def spatial_join(self):
		try:
			self.spatial_join_dialog.refresh_layers()
		except: 
			self.spatial_join_dialog = mmqgis_spatial_join_dialog(self.iface)

		self.spatial_join_dialog.exec()

	def text_to_float(self):
		try:
			self.text_to_float_dialog.refresh_layers()
		except: 
			self.text_to_float_dialog = mmqgis_text_to_float_dialog(self.iface)

		self.text_to_float_dialog.exec()

	def voronoi(self):
		try:
			self.voronoi_dialog.refresh_layers()
		except: 
			self.voronoi_dialog = mmqgis_voronoi_dialog(self.iface)

		self.voronoi_dialog.exec()

# coding=utf-8
#
# Copyright 2014 Leo Moll
#
# Authors: Leo Moll and Contributors (see CREDITS)
#
# Thanks to Mark Johnson for btsyncindicator.py which gave me the
# last nudge needed to learn python and write my first linux gui
# application. Thank you!
#
# This file is part of btsync-gui. btsync-gui is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>
#

import os
import md5
import requests
import datetime

from gi.repository import Gtk, Gdk, GObject

from btsyncapi import BtSyncApi
from prefsadvanced import BtSyncPrefsAdvanced
from btsyncutils import BtInputHelper,BtMessageHelper,BtValueDescriptor
from dialogs import BtSyncFolderAdd,BtSyncFolderRemove,BtSyncFolderScanQR,BtSyncFolderPrefs

class BtSyncApp(BtInputHelper,BtMessageHelper):

	def __init__(self,btsyncapi):
		self.btsyncapi = btsyncapi
		self.builder = Gtk.Builder()
		self.builder.add_from_file(os.path.dirname(__file__) + "/btsyncapp.glade")
		self.builder.connect_signals (self)

		self.window = self.builder.get_object('btsyncapp')
		self.window.connect('delete-event',self.onDelete);
		self.window.show()

		self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
		self.refresh_folders_id = None

		self.prefs = self.btsyncapi.get_prefs()

		self.init_folders_controls()
		self.init_devices_controls()
		self.init_transfers_controls()
		self.init_history_controls()
		self.init_preferences_controls()
		self.init_folders_values()
		self.init_preferences_values()

	def close(self):
		if self.refresh_folders_id is not None:
			GObject.source_remove(self.refresh_folders_id)
			self.refresh_folders_id = None

	def connect_close_signal(self,handler):
		return self.window.connect('delete-event', handler)

	def init_folders_controls(self):
		self.folders = self.builder.get_object('folders_list')
		self.folders_menu = self.builder.get_object('folders_menu')
		self.folders_menu_openarchive = self.builder.get_object('folder_menu_openarchive')
		self.folders_selection = self.builder.get_object('folders_selection')
		self.folders_treeview = self.builder.get_object('folders_tree_view')
		self.folders_add = self.builder.get_object('folders_add')
		self.folders_remove = self.builder.get_object('folders_remove')
		self.folders_remove.set_sensitive(False)

	def init_folders_values(self):
		try:
			self.lock()
			folders = self.btsyncapi.get_folders()
			if folders is not None:
				for index, value in enumerate(folders):
					# see in update_folder_values the insane explanation why
					# also an md5 digest has to be saved
					digest = md5.new(value['dir'].encode('latin-1')).hexdigest()
					self.folders.append ([
						self.btsyncapi.fix_decode(value['dir']),	# 0:Folder
						self.get_folder_info_string(value),			# 1:Content
						value['secret'],							# 2:Secret
						digest										# 3:FolderTag
					])
					self.add_device_infos(value,digest)
			self.unlock()
			self.refresh_folders_id = GObject.timeout_add(1000, self.refresh_app_status)
		except requests.exceptions.ConnectionError:
			self.unlock()
			self.onConnectionError()
		except requests.exceptions.HTTPError:
			self.unlock()
			self.onCommunicationError()

	def init_devices_controls(self):
		self.devices = self.builder.get_object('devices_list')
		self.devices_treeview = self.builder.get_object('devices_tree_view')

	def init_transfers_controls(self):
		self.transfers = self.builder.get_object('transfers_list')
		self.transfers_treeview = self.builder.get_object('transfers_tree_view')
		self.transfers_status = self.builder.get_object('transfers_status')
		# TODO: remove placeholder as soon as the suitable API call permits
		#       a working implementation...
		self.transfers.append ([
			'Cannot implement due to missing API',
			'BitTorrent Inc.',
			'',
			''
		])

	def init_history_controls(self):
		self.history = self.builder.get_object('history_list')
		self.history_treeview = self.builder.get_object('history_tree_view')
		# TODO: remove placeholder as soon as the suitable API call permits
		#       a working implementation...
		self.history.append ([
			'Now',
			'Cannot implement due to missing API'
		])

	def refresh_app_status(self):
		try:
			self.lock()
			folders = self.btsyncapi.get_folders()
			# forward scan updates existing folders and adds new ones
			for index, value in enumerate(folders):
				# see in update_folder_values the insane explanation why
				# also an md5 digest has to be saved
				digest = md5.new(value['dir'].encode('latin-1')).hexdigest()
				if not self.update_folder_values(value):
					# it must be new (probably added via web interface) - let's add it
					self.folders.append ([
						self.btsyncapi.fix_decode(value['dir']),	# 0:Folder
						self.get_folder_info_string(value),			# 1:Content
						value['secret'],							# 2:Secret
						digest										# 3:FolderTag
					])
				self.update_device_infos(value,digest)
			# reverse scan deletes disappeared folders...
			for row in self.folders:
				if not self.folder_exists(folders,row):
					self.folders.remove(row.iter)
					self.remove_device_infos(row[2],row[3])
			# update transfer status
			speed = self.btsyncapi.get_speed()
			self.transfers_status.set_label('{0:.1f} kB/s up, {1:.1f} kB/s down'.format(speed['upload'] / 1000, speed['download'] / 1000))
			# TODO: fill file list...
			#       but there is still no suitable API call...
			self.unlock()

			return True
		except requests.exceptions.ConnectionError:
			self.unlock()
			self.refresh_folders_id = None
			return self.onConnectionError()
		except requests.exceptions.HTTPError:
			self.unlock()
			self.refresh_folders_id = None
			return self.onCommunicationError()

	def update_folder_values(self,value):
		for row in self.folders:
			if value['secret'] == row[2]:
				# found - update information
				row[1] = self.get_folder_info_string(value)
				return True
			elif md5.new(value['dir'].encode('latin-1')).hexdigest() == row[3]:
				# comparing the md5 digests avoids casting errors due to the
				# insane encoding fix tecnique
				# found - secret was changed
				row[1] = self.get_folder_info_string(value)
				row[2] = value['secret']
				return True
		# not found
		return False

	def folder_exists(self,folders,row):
		if folders is not None:
			for index, value in enumerate(folders):
				if value['secret'] == row[2]:
					return True
				elif md5.new(value['dir'].encode('latin-1')).hexdigest() == row[3]:
					# comparing the md5 digests avoids casting errors due to the
					# insane encoding fix tecnique
					return True
		return False

	def add_device_infos(self,folder,digest):
		foldername = self.btsyncapi.fix_decode(folder['dir'])
		peers = self.btsyncapi.get_folder_peers(folder['secret'])
		for index, value in enumerate(peers):
			self.devices.append ([
				self.btsyncapi.fix_decode(value['name']),	# 0:Device
				foldername,									# 1:Folder
				self.get_device_info_string(value),			# 2:Status
				folder['secret'],							# 3:Secret
				digest,										# 4:FolderTag
				value['id']									# 5:DeviceTag
			])

	def update_device_infos(self,folder,digest):
		foldername = self.btsyncapi.fix_decode(folder['dir'])
		peers = self.btsyncapi.get_folder_peers(folder['secret'])
		# forward scan updates existing and adds new
		for index, value in enumerate(peers):
			if not self.update_device_values(folder,value,digest):
				# it must be new - let's add it
					self.devices.append ([
					self.btsyncapi.fix_decode(value['name']),	# 0:Device
					foldername,									# 1:Folder
					self.get_device_info_string(value),			# 2:Status
					folder['secret'],							# 3:Secret
					digest,										# 4:FolderTag
					value['id']									# 5:DeviceTag
				])
		# reverse scan deletes disappeared folders...
		for row in self.devices:
			if row[3] == folder['secret'] or row[4] == digest:
				# it's our folder
				if not self.device_exists(peers,row):
					self.devices.remove(row.iter)

	def update_device_values(self,folder,peer,digest):
		for row in self.devices:
			if peer['id'] == row[5] and folder['secret'] == row[3]:
				# found - update information
				row[0] = self.btsyncapi.fix_decode(peer['name'])
				row[2] = self.get_device_info_string(peer)
				return True
			elif peer['id'] == row[5] and digest == row[4]:
				# found - secret probably changed...
				row[0] = self.btsyncapi.fix_decode(peer['name'])
				row[2] = self.get_device_info_string(peer)
				row[3] = folder['secret']
				return True
		# not found
		return False

	def remove_device_infos(self,secret,digest=None):
		for row in self.devices:
			if secret == row[3]:
				self.devices.remove(row.iter)
			elif digest is not None and digest == row[4]:
				self.devices.remove(row.iter)

	def device_exists(self,peers,row):
		for index, value in enumerate(peers):
			if value['id'] == row[5]:
				return True
		return False

	def get_folder_info_string(self,folder):
		if folder['error'] == 0:
			if folder['indexing'] == 0:
				return '{0} in {1} files'.format(self.sizeof_fmt(folder['size']), str(folder['files']))
			else:
				return '{0} in {1} files (indexing...)'.format(self.sizeof_fmt(folder['size']), str(folder['files']))
		else:
			return self.btsyncapi.get_error_message(folder)

	def get_device_info_string(self,peer):
		connection = {
			'direct' : ' (Direct Connection)',
			'relay'  : ' (Relayed Connection)'
		}.get(peer['connection'], '')
		if peer['synced'] != 0:
			dt = datetime.datetime.fromtimestamp(peer['synced'])
			return 'Synched on {0}'.format(dt.strftime("%x %X")) + connection
		elif peer['download'] == 0 and peer['upload'] != 0:
			return '⇧ {0}'.format(self.sizeof_fmt(peer['upload'])) + connection
		elif peer['download'] != 0 and peer['upload'] == 0:
			return '⇩ {0}'.format(self.sizeof_fmt(peer['download'])) + connection
		elif peer['download'] != 0 and peer['upload'] != 0:
			return '⇧ {0} - ⇩ {1}'.format(self.sizeof_fmt(peer['upload']), self.sizeof_fmt(peer['download'])) + connection
		else:
			return 'Idle...' + connection

	def init_preferences_controls(self):
		self.devname = self.builder.get_object('devname')
		self.autostart = self.builder.get_object('autostart')
		self.listeningport = self.builder.get_object('listeningport')
		self.upnp = self.builder.get_object('upnp')
		self.limitdn = self.builder.get_object('limitdn')
		self.limitdnrate = self.builder.get_object('limitdnrate')
		self.limitup = self.builder.get_object('limitup')
		self.limituprate = self.builder.get_object('limituprate')

	def init_preferences_values(self):
		self.lock()
		self.attach(self.devname,BtValueDescriptor.new_from('device_name',self.prefs['device_name']))
		# self.autostart.set_active(self.prefs[""]);
		self.autostart.set_sensitive(False)
		self.attach(self.listeningport,BtValueDescriptor.new_from('listening_port',self.prefs['listening_port']))
		self.attach(self.upnp,BtValueDescriptor.new_from('use_upnp',self.prefs['use_upnp']))
		self.attach(self.limitdnrate,BtValueDescriptor.new_from('download_limit',self.prefs['download_limit']))
		self.attach(self.limituprate,BtValueDescriptor.new_from('upload_limit',self.prefs['upload_limit']))

		self.limitdn.set_active(self.prefs['download_limit'] > 0)
		self.limitup.set_active(self.prefs['upload_limit'] > 0)
		self.unlock()

	def onDelete(self, *args):
		self.close()

	def onSaveEntry(self,widget,valDesc,newValue):
		try:
			self.btsyncapi.set_prefs({valDesc.Name : newValue})
			self.prefs[valDesc.Name] = newValue
		except requests.exceptions.ConnectionError:
			return self.onConnectionError()
		except requests.exceptions.HTTPError:
			return self.onCommunicationError()
		return True

	def onFoldersSelectionChanged(self,selection):
		model, tree_iter = selection.get_selected()
		self.folders_remove.set_sensitive(selection.count_selected_rows() > 0)

	def onFoldersAdd(self,widget):
		dlg = BtSyncFolderAdd(self.btsyncapi)
		try:
			dlg.create()
			result = dlg.run()
			if result == Gtk.ResponseType.OK:
				# all checks have already been done. let's go!
				result = self.btsyncapi.add_folder(dlg.folder,dlg.secret)
				if self.btsyncapi.get_error_code(result) > 0:
					self.show_warning(self.window,self.btsyncapi.get_error_message(result))
		except requests.exceptions.ConnectionError:
			pass
		except requests.exceptions.HTTPError:
			pass
		finally:
			dlg.destroy()

	def onFoldersRemove(self,widget):
		dlg = BtSyncFolderRemove()
		dlg.create()
		result = dlg.run()
		dlg.destroy()
		if result == Gtk.ResponseType.OK:
			model, tree_iter = self.folders_selection.get_selected()
			if tree_iter is not None:
				# ok - let's delete it!
				secret = model[tree_iter][2]
				try:
					result = self.btsyncapi.remove_folder(secret)
					if self.btsyncapi.get_error_code(result) == 0:
						self.folders.remove(tree_iter)
						self.remove_device_infos(secret)
					else:
						logging.error('Failed to remove folder ' + str(secret))
				except requests.exceptions.ConnectionError:
					pass
				except requests.exceptions.HTTPError:
					pass

	def onFoldersMouseClick(self,widget,event):
		x = int(event.x)
		y = int(event.y)
		time = event.time
		pathinfo = widget.get_path_at_pos(x,y)
		if pathinfo is not None:
			if event.button == 1:
				if event.type == Gdk.EventType._2BUTTON_PRESS or event.type == Gdk.EventType._3BUTTON_PRESS:
					path, column, cellx, celly = pathinfo
					widget.grab_focus()
					widget.set_cursor(path,column,0)
					model, tree_iter = self.folders_selection.get_selected()
					if tree_iter is not None:
						if os.path.isdir(model[tree_iter][0]):
							os.system('xdg-open '+model[tree_iter][0])
							return True
			elif event.button == 3:
				path, column, cellx, celly = pathinfo
				widget.grab_focus()
				widget.set_cursor(path,column,0)
				model, tree_iter = self.folders_selection.get_selected()
				if tree_iter is not None:
					self.folders_menu_openarchive.set_sensitive(
						os.path.isdir(model[tree_iter][0] + '/.SyncArchive')
					)
				else:
					self.folders_menu_openarchive.set_sensitive(False)

				self.folders_menu.popup(None,None,None,None,event.button,time)
				return True

	def onFoldersCopySecret(self,widget):
		model, tree_iter = self.folders_selection.get_selected()
		if tree_iter is not None:
			self.clipboard.set_text(model[tree_iter][2], -1)

	def onFoldersConnectMobile(self,widget):
		model, tree_iter = self.folders_selection.get_selected()
		if tree_iter is not None:
			result = self.btsyncapi.get_secrets(model[tree_iter][2], False)
			if self.btsyncapi.get_error_code(result) == 0:
				dlg = BtSyncFolderScanQR(
					result['read_write'] if result.has_key('read_write') else None,
					result['read_only'],
					os.path.basename(model[tree_iter][0])
				)
				dlg.create()
				result = dlg.run()
				dlg.destroy()

	def onFoldersOpenArchive(self,widget):
		model, tree_iter = self.folders_selection.get_selected()
		if tree_iter is not None:
			syncarchive = model[tree_iter][0] + '/.SyncArchive'
			if os.path.isdir(syncarchive):
				os.system('xdg-open '+syncarchive)

	def onFoldersPreferences(self,widget):
		model, tree_iter = self.folders_selection.get_selected()
		if tree_iter is not None:
			dlg = BtSyncFolderPrefs(self.btsyncapi)
			try:
				dlg.create(model[tree_iter][0],model[tree_iter][2])
				dlg.run()
			except requests.exceptions.ConnectionError:
				pass
			except requests.exceptions.HTTPError:
				pass
			finally:
				dlg.destroy()

	def onPreferencesToggledLimitDn(self,widget):
		self.limitdnrate.set_sensitive(widget.get_active())
		if not self.is_locked():
			rate = int(self.limitdnrate.get_text()) if widget.get_active() else 0
			try:
				self.btsyncapi.set_prefs({"download_limit" : rate})
				self.prefs['download_limit'] = rate
			except requests.exceptions.ConnectionError:
				return self.onConnectionError()
			except requests.exceptions.HTTPError:
				return self.onCommunicationError()


	def onPreferencesToggledLimitUp(self,widget):
		self.limituprate.set_sensitive(widget.get_active())
		if not self.is_locked():
			rate = int(self.limituprate.get_text()) if widget.get_active() else 0
			try:
				self.btsyncapi.set_prefs({"upload_limit" : rate})
				self.prefs['upload_limit'] = rate
			except requests.exceptions.ConnectionError:
				return self.onConnectionError()
			except requests.exceptions.HTTPError:
				return self.onCommunicationError()

	def onPreferencesClickedAdvanced(self,widget):
		try:
			dlgPrefsAdvanced = BtSyncPrefsAdvanced(self.btsyncapi)
			dlgPrefsAdvanced.run()
			dlgPrefsAdvanced.destroy()
		except requests.exceptions.ConnectionError:
			return self.onConnectionError()
		except requests.exceptions.HTTPError:
			return self.onCommunicationError()

	def onConnectionError(self):
		logger.error('BtSync API Connection Error')
		self.window.destroy()
		return False

	def onCommunicationError(self):
		logging.error('BtSync API HTTP error: {0}'.format(self.btsyncapi.get_status_code()))
		self.window.destroy()
		return False


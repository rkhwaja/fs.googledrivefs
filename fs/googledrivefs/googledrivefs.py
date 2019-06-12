from __future__ import absolute_import

from datetime import datetime
from io import BytesIO, SEEK_END
from logging import debug, info
from os import close, remove
from os.path import splitext
from tempfile import mkstemp

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from fs.base import FS
from fs.enums import ResourceType
from fs.errors import DestinationExists, DirectoryExists, DirectoryExpected, DirectoryNotEmpty, FileExists, FileExpected, InvalidCharsInPath, NoURL, ResourceNotFound, OperationFailed, RemoveRootError
from fs.info import Info
from fs.iotools import RawWrapper
from fs.mode import Mode
from fs.path import basename, dirname, iteratepath
from fs.subfs import SubFS
from fs.time import datetime_to_epoch

_fileMimeType = "application/vnd.google-apps.file"
_folderMimeType = "application/vnd.google-apps.folder"
_sharingUrl = "https://drive.google.com/open?id="
_INVALID_PATH_CHARS = ":\0"

def _Escape(name):
	name = name.replace("\\", "\\\\")
	name = name.replace("'", r"\'")
	return name


def _CheckPath(path):
	for char in _INVALID_PATH_CHARS:
		if char in path:
			raise InvalidCharsInPath(path)


# TODO - switch to MediaIoBaseUpload and use BytesIO
class _UploadOnClose(RawWrapper):
	def __init__(self, fs, path, thisMetadata, parentMetadata, parsedMode): # pylint: disable=too-many-arguments
		self.fs = fs
		self.path = path
		self.parentMetadata = parentMetadata
		# None here means we'll have to create a new file later
		self.thisMetadata = thisMetadata
		# keeping a parsed mode separate from the base class's mode member
		self.parsedMode = parsedMode
		fileHandle, self.localPath = mkstemp(prefix="pyfilesystem-googledrive-", suffix=splitext(self.path)[1],
											 text=False)
		close(fileHandle)
		debug(f"self.localPath: {self.localPath}")

		if (self.parsedMode.reading or self.parsedMode.appending) and not self.parsedMode.truncate:
			if self.thisMetadata is not None:
				initialData = self.fs.drive.files().get_media(fileId=self.thisMetadata["id"]).execute()
				debug(f"Read initial data: {initialData}")
				with open(self.localPath, "wb") as f:
					f.write(initialData)
		platformMode = self.parsedMode.to_platform()
		platformMode += ("b" if "b" not in platformMode else "")
		platformMode = platformMode.replace("x", "a")
		super().__init__(f=open(self.localPath, mode=platformMode))
		if self.parsedMode.appending:
			# seek to the end
			self.seek(0, SEEK_END)

	def close(self):
		super().close()  # close the file so that it's readable for upload
		if self.parsedMode.writing:
			# google doesn't accept the fractional second part
			now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
			onlineMetadata = {"modifiedTime": now}

			with open(self.localPath, "rb") as f:
				dataToWrite = f.read()
			debug(f"About to upload data: {dataToWrite}")

			if len(dataToWrite) > 0:
				upload = MediaFileUpload(self.localPath, resumable=True)
				if self.thisMetadata is None:
					debug("Creating new file")
					onlineMetadata.update(
						{"name": basename(self.path), "parents": [self.parentMetadata["id"]], "createdTime": now})
					request = self.fs.drive.files().create(body=onlineMetadata, media_body=upload)
				else:
					debug("Updating existing file")
					request = self.fs.drive.files().update(fileId=self.thisMetadata["id"], body={}, media_body=upload)

				response = None
				while response is None:
					status, response = request.next_chunk()
					debug(f"{status}: {response}")
				# MediaFileUpload doesn't close it's file handle, so we have to workaround it (https://github.com/googleapis/google-api-python-client/issues/575)
				upload._fd.close()  # pylint: disable=protected-access
			else:
				fh = BytesIO(b"")
				media = MediaIoBaseUpload(fh, mimetype="application/octet-stream", chunksize=-1, resumable=False)
				if self.thisMetadata is None:
					onlineMetadata.update(
						{"name": basename(self.path), "parents": [self.parentMetadata["id"]], "createdTime": now})
					createdFile = self.fs.drive.files().create(
						body=onlineMetadata,
						media_body=media).execute()
					debug(f"Created empty file: {createdFile}")
				else:
					updatedFile = self.fs.drive.files().update(
						fileId=self.thisMetadata["id"],
						body={},
						media_body=media).execute()
					debug(f"Updated file to empty: {updatedFile}")
		remove(self.localPath)


class GoogleDriveFS(FS):
	def __init__(self, credentials):
		super().__init__()

		self.drive = build("drive", "v3", credentials=credentials, cache_discovery=False)

		_meta = self._meta = {
			"case_insensitive": True,
		# it will even let you have 2 identical filenames in the same directory! But the search is case-insensitive
			"invalid_path_chars": _INVALID_PATH_CHARS,  # not sure what else
			"max_path_length": None,  # don't know what the limit is
			"max_sys_path_length": None,  # there's no syspath
			"network": True,
			"read_only": False,
			"supports_rename": False  # since we don't have a syspath...
		}

	def __repr__(self):
		return "<GoogleDriveFS>"

	def _fileQuery(self, query):
		allFields = "nextPageToken,files(id,mimeType,kind,name,createdTime,modifiedTime,size,permissions)"
		response = self.drive.files().list(q=query, fields=allFields).execute()
		result = response["files"]
		while "nextPageToken" in response:
			response = self.drive.files().list(q=query, fields=allFields, pageToken=response["nextPageToken"]).execute()
			result.extend(response["files"])
		return result

	def _childByName(self, parentId, childName):
		# this "name=" clause seems to be case-insensitive, which means it's easier to model this
		# as a case-insensitive filesystem
		if not parentId:
			parentId = 'root'
			# Google drive seems to somehow distinguish it's real root folder from folder named "root" in root folder.
		query = f"trashed=False and name='{_Escape(childName)}' and '{parentId}' in parents"
		result = self._fileQuery(query)
		if len(result) not in [0, 1]:
			# Google drive doesn't follow the model of a filesystem, really
			# but since most people will set it up to follow the model, we'll carry on regardless
			# and just throw an error when it becomes a problem
			raise RuntimeError(f"Folder with id {parentId} has more than 1 child with name {childName}")
		return result[0] if len(result) == 1 else None

	def _childrenById(self, parentId):
		if not parentId:
			parentId = 'root'
			# Google drive seems to somehow distinguish it's real root folder from folder named "root" in root folder.
		query = f"trashed=False and '{parentId}' in parents"
		return self._fileQuery(query)

	def _itemsFromPath(self, path):
		pathIdMap = {}
		ipath = iteratepath(path)
		if not ipath:
			return {"/": self._childrenById(None)} # querying root folder. will return a list, not dict

		pathSoFar = ""
		parentId = None
		for childName in ipath:
			pathSoFar = f"{pathSoFar}/{childName}"
			metadata = self._childByName(parentId, childName)
			if metadata is None:
				break
			pathIdMap[pathSoFar] = metadata
			parentId = metadata["id"] # pylint: disable=unsubscriptable-object
		return pathIdMap

	def _itemFromPath(self, path):
		metadata = None
		ipath = iteratepath(path)
		if ipath:
			for child_name in ipath:
				parent_id = metadata["id"] if metadata else None # pylint: disable=unsubscriptable-object
				metadata = self._childByName(parent_id, child_name)
		else:
			metadata = self._childrenById(None) # querying root folder. will return a list, not dict
		return metadata

	def _infoFromMetadata(self, metadata):  # pylint: disable=no-self-use
		isRoot = isinstance(metadata, list)
		isFolder = isRoot or (metadata["mimeType"] == _folderMimeType)
		rfc3339 = "%Y-%m-%dT%H:%M:%S.%fZ"
		rawInfo = {
			"basic": {
				"name": "" if isRoot else metadata["name"],
				"is_dir": isFolder
			},
			"details": {
				"accessed": None,  # not supported by Google Drive API
				"created": None if isRoot else datetime_to_epoch(datetime.strptime(metadata["createdTime"], rfc3339)),
				"metadata_changed": None,  # not supported by Google Drive API
				"modified": None if isRoot else datetime_to_epoch(datetime.strptime(metadata["modifiedTime"], rfc3339)),
				"size": int(metadata["size"]) if "size" in metadata else None, # folders, native google documents etc have no size
				"type": ResourceType.directory if isFolder else ResourceType.file
			},
			"sharing": {
				"id": None if isRoot else metadata["id"],
				"permissions": None if isRoot else metadata["permissions"],
				"is_shared": None if isRoot else len(metadata["permissions"]) > 1
			}
		}
		# there is also file-type-specific metadata like imageMediaMetadata
		return Info(rawInfo)

	def getinfo(self, path, namespaces=None):  # pylint: disable=unused-argument
		_CheckPath(path)
		with self._lock:
			metadata = self._itemFromPath(path)
			if metadata is None or isinstance(metadata, list):
				raise ResourceNotFound(path=path)
			return self._infoFromMetadata(metadata)

	def setinfo(self, path, info):  # pylint: disable=redefined-outer-name,too-many-branches,unused-argument
		_CheckPath(path)
		with self._lock:
			metadata = self._itemFromPath(path)
			if metadata is None or isinstance(metadata, list):
				raise ResourceNotFound(path=path)

	def share(self, path, email=None, role='reader'):
		"""
		Shares item.
		:param path: item path
		:param email: email of gmail-user to share item. If None, will share with anybody.
		:param role: google drive sharing role
		:return: URL
		"""
		_CheckPath(path)
		with self._lock:
			metadata = self._itemFromPath(path)
			if metadata is None or isinstance(metadata, list):
				raise ResourceNotFound(path=path)
			if role not in ('reader', 'writer', 'commenter', 'fileOrganizer', 'organizer', 'owner'):
				raise OperationFailed(path=path, msg=f'unknown sharing role: {role}')
			if email:
				permissions = {'role': role, 'type': 'user', 'emailAddress': email}
			else:
				permissions = {'role': role, 'type': 'anyone'}
			self.drive.permissions().create(fileId=metadata['id'], body=permissions).execute()
			return self.geturl(path)

	def hasurl(self, path, purpose="download"):
		_CheckPath(path)
		if purpose != "download":
			raise NoURL(path, purpose, "No such purpose")
		with self._lock:
			try:
				return self.getinfo(path).get("sharing", "is_shared")
			except ResourceNotFound:
				return False

	def geturl(self, path, purpose="download"): # pylint: disable=unused-argument
		_CheckPath(path)
		if purpose != "download":
			raise NoURL(path, purpose, "No such purpose")
		with self._lock:
			fileInfo = self.getinfo(path)
			if fileInfo.get("sharing", "is_shared") is False:
				raise NoURL(path, purpose, f"{path} is not shared")
			return _sharingUrl + fileInfo.get("sharing", "id")

	def listdir(self, path):
		_CheckPath(path)
		with self._lock:
			return [x.name for x in self.scandir(path)]

	def _create_subdirectory(self, name, path, parents):
		newMetadata = {"name": basename(name), "parents": parents, "mimeType": _folderMimeType}
		self.drive.files().create(body=newMetadata, fields="id").execute()
		return SubFS(self, path)

	def makedir(self, path, permissions=None, recreate=False):
		_CheckPath(path)
		with self._lock:
			info(f"makedir: {path}, {permissions}, {recreate}")
			parentMetadata = self._itemFromPath(dirname(path))

			if isinstance(parentMetadata, list): # adding new folder to root folder
				if not self._childByName(None, path):
					return self._create_subdirectory(path, path, None)
				raise DirectoryExists(path=path)

			if parentMetadata is None:
				raise ResourceNotFound(path=path)

			childMetadata = self._childByName(parentMetadata["id"], basename(path))
			if childMetadata is not None:
				if recreate is False:
					raise DirectoryExists(path=path)
				return SubFS(self, path)

			return self._create_subdirectory(basename(path), path, [parentMetadata["id"]])

	def openbin(self, path, mode="r", buffering=-1, **options):  # pylint: disable=unused-argument
		_CheckPath(path)
		with self._lock:
			info(f"openbin: {path}, {mode}, {buffering}")
			parsedMode = Mode(mode)
			pathIdMap = self._itemsFromPath(path)
			item = pathIdMap.get(path, None)
			if parsedMode.exclusive and item is not None:
				raise FileExists(path)
			if parsedMode.reading and not parsedMode.create and item is None:
				raise ResourceNotFound(path)
			if item is not None and item["mimeType"] == _folderMimeType:
				raise FileExpected(path)
			parentDir = dirname(path)
			parentDirItem = pathIdMap.get(parentDir, None)
			# make sure that the parent directory exists if we're writing
			if parsedMode.writing and parentDirItem is None:
				raise ResourceNotFound(parentDir)
			return _UploadOnClose(fs=self, path=path, thisMetadata=item, parentMetadata=parentDirItem, parsedMode=parsedMode)

	def remove(self, path):
		if path == '/':
			raise RemoveRootError()
		_CheckPath(path)
		with self._lock:
			info(f"remove: {path}")
			metadata = self._itemFromPath(path)
			if metadata is None:
				raise ResourceNotFound(path=path)
			if metadata["mimeType"] == _folderMimeType:
				raise FileExpected(path=path)
			self.drive.files().delete(fileId=metadata["id"]).execute()

	def removedir(self, path):
		if path == '/':
			raise RemoveRootError()
		_CheckPath(path)
		with self._lock:
			info(f"removedir: {path}")
			metadata = self._itemFromPath(path)
			if metadata is None:
				raise ResourceNotFound(path=path)
			if metadata["mimeType"] != _folderMimeType:
				raise DirectoryExpected(path=path)
			children = self._childrenById(metadata["id"])
			if len(children) > 0:
				raise DirectoryNotEmpty(path=path)
			self.drive.files().delete(fileId=metadata["id"]).execute()

	def _generate_children(self, children, page):
		if page:
			return (self._infoFromMetadata(x) for x in children[page[0]:page[1]])
		return (self._infoFromMetadata(x) for x in children)

	# Non-essential method - for speeding up walk
	# Takes advantage of the fact that you get the full metadata for all children in one call
	def scandir(self, path, namespaces=None, page=None):
		_CheckPath(path)
		with self._lock:
			info(f"scandir: {path}, {namespaces}, {page}")
			metadata = self._itemFromPath(path)
			if metadata is None:
				raise ResourceNotFound(path=path)
			if isinstance(metadata, list): # root folder
				children = self._childrenById(None)
				return self._generate_children(children, page)
			if metadata["mimeType"] != _folderMimeType:
				raise DirectoryExpected(path=path)
			children = self._childrenById(metadata["id"])
			return self._generate_children(children, page)

	# Non-essential - takes advantage of the file contents are already being on the server
	def copy(self, src_path, dst_path, overwrite=False):
		info(f"copy: {src_path} -> {dst_path}, {overwrite}")
		_CheckPath(src_path)
		_CheckPath(dst_path)
		with self._lock:
			parentDir = dirname(dst_path)
			parentDirItem = self._itemFromPath(parentDir)

			if parentDirItem is None:
				raise ResourceNotFound(parentDir)

			dstItem = self._itemFromPath(dst_path)
			if overwrite is False and dstItem is not None:
				raise DestinationExists(dst_path)

			srcItem = self._itemFromPath(src_path)
			if srcItem is None:
				raise ResourceNotFound(src_path)

			if srcItem["mimeType"] == _folderMimeType:
				raise FileExpected(src_path)

			# TODO - we should really replace the contents of the existing file with the new contents, so that the history is correct
			if dstItem is not None:
				self.drive.files().delete(fileId=dstItem["id"]).execute()

			newMetadata = {"parents": [parentDirItem["id"]], "name": basename(dst_path)}
			self.drive.files().copy(fileId=srcItem["id"], body=newMetadata).execute()

	# Non-essential - takes advantage of the file contents already being on the server
	def move(self, src_path, dst_path, overwrite=False):
		info(f"move: {src_path} -> {dst_path}, {overwrite}")
		_CheckPath(src_path)
		_CheckPath(dst_path)
		with self._lock:
			dstItem = self._itemFromPath(dst_path)
			if overwrite is False and dstItem is not None:
				raise DestinationExists(dst_path)

			srcParentItem = self._itemFromPath(dirname(src_path))
			if srcParentItem is None:
				raise ResourceNotFound(src_path)

			# TODO - it would be more efficient to go directly from srcParentItem to it's child here
			srcItem = self._itemFromPath(src_path)
			if srcItem is None:
				raise ResourceNotFound(src_path)

			if srcItem["mimeType"] == _folderMimeType:
				raise FileExpected(src_path)

			dstParentDir = dirname(dst_path)
			dstParentDirItem = self._itemFromPath(dstParentDir)

			if dstParentDirItem is None:
				raise ResourceNotFound(dstParentDir)

			if dstItem is not None:
				assert overwrite is True
				self.drive.files().delete(fileId=dstItem["id"]).execute()

			self.drive.files().update(
				fileId=srcItem["id"],
				addParents=dstParentDirItem["id"],
				removeParents=srcParentItem["id"],
				body={"name": basename(dst_path)}).execute()
